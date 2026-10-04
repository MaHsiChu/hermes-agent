"""Disposable loopback-only browser fixture, never imported by production.

Uses the real relay, signed OIDC/PKCE, cookies, SQL store and Bridge WebSocket.
The PC execution authority is synthetic; no user's native sessions are read.
"""
import base64
import hashlib
import json
import secrets
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
import uvicorn
from authlib.jose import JsonWebKey, jwt
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from websockets.sync.client import connect
from remote_control.config import ServerConfig
from remote_control.server import create_app

PUBLIC = 'http://127.0.0.1:8791'
ISSUER = 'http://127.0.0.1:8792'
temp = tempfile.TemporaryDirectory(prefix='hermes-mobile-test-')
key = JsonWebKey.generate_key('RSA', 2048, is_private=True, options={'kid': 'browser-test'})
flows = {}
control = {'user': 'alice', 'online': True, 'revision': 1, 'expired': False, 'deleted': False, 'commands': []}
provider = FastAPI()

@provider.get('/.well-known/openid-configuration')
def discovery():
    return dict(issuer=ISSUER, authorization_endpoint=ISSUER+'/authorize', token_endpoint=ISSUER+'/token', jwks_uri=ISSUER+'/jwks', response_types_supported=['code'], subject_types_supported=['public'], id_token_signing_alg_values_supported=['RS256'])

@provider.get('/jwks')
def jwks():
    return {'keys': [key.as_dict(is_private=False)]}

@provider.get('/authorize')
def authorize(request: Request):
    params = dict(request.query_params)
    if params.get('redirect_uri') != PUBLIC+'/auth/callback' or params.get('client_id') != 'mobile-browser-test' or params.get('code_challenge_method') != 'S256':
        raise HTTPException(400, 'Invalid fixture client')
    code = secrets.token_urlsafe(24)
    flows[code] = dict(params, sub=control['user'], expires=time.time()+60)
    return RedirectResponse(params['redirect_uri']+'?'+urlencode({'code': code, 'state': params['state']}))

@provider.post('/token')
async def token(request: Request):
    params = await request.form()
    flow = flows.pop(params.get('code'), None)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(params.get('code_verifier', '').encode()).digest()).rstrip(b'=').decode()
    if not flow or flow['expires'] < time.time() or challenge != flow['code_challenge']:
        raise HTTPException(400, 'Invalid fixture code')
    claims = dict(iss=ISSUER, sub=flow['sub'], aud='mobile-browser-test', iat=int(time.time()), exp=int(time.time())+300, nonce=flow['nonce'], name=flow['sub'])
    return dict(access_token=secrets.token_urlsafe(24), token_type='Bearer', id_token=jwt.encode({'alg': 'RS256', 'kid': 'browser-test'}, claims, key).decode())

@provider.post('/fixture/control')
async def configure(request: Request):
    values = await request.json()
    for name in ('user', 'online', 'expired', 'deleted'):
        if name in values:
            control[name] = values[name]
    control['revision'] += 1
    return {'updated': True}

@provider.get('/fixture/state')
def state():
    return {'commands': control['commands'], 'revision': control['revision']}

config = ServerConfig(development=True, public_url=PUBLIC,
    database_url='sqlite:///'+str(Path(temp.name)/'relay.sqlite3'),
    static_dir=str(ROOT/'apps/mobile/dist'), oidc={'issuer': ISSUER, 'client_id': 'mobile-browser-test'})
app = create_app(config)
store = app.state.store
source = {'backend_id': 'browser-test', 'profile': 'test', 'engine': 'hermes'}
caps = {name: {'status': 'supported'} for name in ['history', 'send', 'queue', 'steer', 'interrupt', 'approval', 'clarify']}
caps['attachments'] = {'status': 'unsupported', 'reason': 'Synthetic PC has no image execution'}
credentials = {}
for user in ('alice', 'bob'):
    _, _, uid = store.login(ISSUER, user, user)
    pairing = store.create_pairing(user+' test computer', [source])
    store.approve_pairing(uid, pairing['pairing_id'], pairing['user_code'], [source])
    credentials[user] = store.exchange(pairing['pairing_id'], pairing['device_code'])['device_token']

def snapshot(user):
    revision = control['revision']
    rows = [{'id': str(index), 'ordinal': index, 'revision': revision, 'role': 'assistant', 'content': f'{user} history {index}'} for index in range(1, 251)]
    rows[-2]['content'] = '```python\n'+'print("full output")\n'*400+'# END OF LONG OUTPUT\n```'
    rows[-1]['content'] = f'{user} newest message'
    if control['deleted']:
        rows[-1] = {'id': '250', 'ordinal': 250, 'revision': revision, 'deleted': True}
    return {'type': 'snapshot', 'request_id': f'fixture-{revision}', 'source': source,
        'session': {'native_session_id': 'synthetic-'+user, 'title': user+' long conversation', 'revision': revision, 'updated_at': time.time(), 'status': 'waiting', 'capabilities': caps},
        'messages': rows, 'sync': {'complete': True, 'last_synced': time.time(), 'total': 250},
        'pending_requests': [{'id': 'approval-'+user, 'method': 'approval', 'params': {'command': 'synthetic harmless check', 'choices': ['once', 'deny'], 'expires_at': time.time()-1 if control['expired'] else time.time()+600}}]}

def bridge(user, credential):
    while True:
        if not control['online']:
            time.sleep(.1)
            continue
        try:
            with connect(PUBLIC.replace('http:', 'ws:')+'/api/remote/bridge', additional_headers={'Authorization': 'Bearer '+credential}) as ws:
                ws.recv(timeout=5)
                sent = 0
                heartbeat = 0
                while control['online']:
                    if sent != control['revision']:
                        ws.send(json.dumps(snapshot(user)))
                        sent = control['revision']
                    if time.time()-heartbeat > 5:
                        ws.send(json.dumps({'type': 'heartbeat', 'sources': [{'source': source, 'online': True}]}))
                        heartbeat = time.time()
                    try:
                        frame = json.loads(ws.recv(timeout=.1))
                    except TimeoutError:
                        continue
                    if frame['type'] == 'command':
                        control['commands'].append({'user': user, 'request_id': frame['request_id'], 'operation': frame['operation'], 'payload': frame['payload']})
                        ws.send(json.dumps({'type': 'receipt', 'request_id': frame['request_id'], 'digest': frame['digest'], 'state': 'acknowledged', 'result': {'status': 'accepted'}}))
        except (OSError, TimeoutError, ConnectionError):
            time.sleep(.2)
        except Exception as error:
            # A revoked test device or startup race is expected; never log credentials.
            print('Fixture Bridge reconnect:', type(error).__name__, flush=True)
            time.sleep(.5)

if __name__ == '__main__':
    threading.Thread(target=lambda: uvicorn.run(provider, host='127.0.0.1', port=8792, log_level='error', access_log=False), daemon=True).start()
    for user, credential in credentials.items():
        threading.Thread(target=bridge, args=(user, credential), daemon=True).start()
    uvicorn.run(app, host='127.0.0.1', port=8791, log_level='error', access_log=False)
