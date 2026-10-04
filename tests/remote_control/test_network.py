"""Real localhost HTTP/WebSocket boundaries; synthetic IdP, real signed OIDC tokens."""
import asyncio
import base64
import hashlib
import json
import socket
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient
from websockets.asyncio.client import connect


@contextmanager
def serve_app(app):
    sock=socket.socket(); sock.bind(('127.0.0.1',0)); sock.listen(128)
    port=sock.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(app,log_level='error',access_log=False))
    thread=threading.Thread(target=lambda:server.run(sockets=[sock]),daemon=True); thread.start()
    deadline=time.monotonic()+10
    while not server.started and thread.is_alive() and time.monotonic()<deadline:
        time.sleep(.01)
    assert server.started
    try:
        yield f'http://127.0.0.1:{port}'
    finally:
        server.should_exit=True; thread.join(10); sock.close()
        assert not thread.is_alive()


@contextmanager
def identity_provider():
    from authlib.jose import JsonWebKey,jwt
    key=JsonWebKey.generate_key('RSA',2048,is_private=True,options={'kid':'test-key'})
    state={'authorization':{},'wrong_nonce':False,'pkce_verified':False}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):
            pass
        def send(self,value):
            data=json.dumps(value).encode(); self.send_response(200)
            self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)))
            self.end_headers();self.wfile.write(data)
        def do_GET(self):
            if self.path=='/.well-known/openid-configuration':
                self.send({'issuer':state['issuer'],'authorization_endpoint':state['issuer']+'/authorize',
                    'token_endpoint':state['issuer']+'/token','jwks_uri':state['issuer']+'/jwks',
                    'response_types_supported':['code'],'subject_types_supported':['public'],
                    'id_token_signing_alg_values_supported':['RS256']})
            elif self.path=='/jwks':
                self.send({'keys':[key.as_dict(is_private=False)]})
            else:
                self.send_error(404)
        def do_POST(self):
            form=parse_qs(self.rfile.read(int(self.headers['Content-Length'])).decode())
            verifier=form['code_verifier'][0]
            actual=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
            assert actual==state['authorization']['code_challenge'][0]
            assert form['grant_type']==['authorization_code']
            state['pkce_verified']=True
            claims={'iss':state['issuer'],'sub':'account-a','aud':'remote-test','iat':int(time.time()),
                'exp':int(time.time())+300,'nonce':'invalid' if state['wrong_nonce'] else state['authorization']['nonce'][0],
                'name':'Test account'}
            self.send({'access_token':'provider-secret-token','token_type':'Bearer',
                       'id_token':jwt.encode({'alg':'RS256','kid':'test-key'},claims,key).decode()})
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    state['issuer']=f'http://127.0.0.1:{server.server_port}'
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        yield state
    finally:
        server.shutdown();server.server_close();thread.join(5)


@pytest.mark.parametrize('wrong_nonce',[False,True])
def test_real_oidc_code_pkce_nonce_and_server_side_session(tmp_path,wrong_nonce):
    from remote_control.config import ServerConfig
    from remote_control.server import create_app
    with identity_provider() as provider:
        app=create_app(ServerConfig(development=True,public_url='http://testserver',database_url='sqlite:///'+str(tmp_path/'oidc.db'),
                                  oidc={'issuer':provider['issuer'],'client_id':'remote-test'}))
        with TestClient(app) as client:
            response=client.get('/auth/login',follow_redirects=False)
            assert response.status_code==302
            query=parse_qs(urlsplit(response.headers['location']).query)
            provider['authorization']=query; provider['wrong_nonce']=wrong_nonce
            assert query['code_challenge_method']==['S256']
            assert query['response_type']==['code']
            callback='/auth/callback?code=authorized&state='+query['state'][0]
            response=client.get(callback,follow_redirects=False)
            assert provider['pkce_verified']
            if wrong_nonce:
                assert response.status_code==400
                assert client.get('/api/remote/me').json()['user'] is None
            else:
                assert response.status_code==307
                assert 'HttpOnly' in response.headers['set-cookie']
                assert 'provider-secret-token' not in str(client.cookies)
                assert client.get('/api/remote/me').json()['user']['name']=='Test account'
                assert client.get(callback,follow_redirects=False).status_code==400


@pytest.mark.asyncio
async def test_simultaneous_bridge_connections_have_one_writer(tmp_path):
    from remote_control.config import ServerConfig
    from remote_control.server import create_app
    app=create_app(ServerConfig(development=True,database_url='sqlite:///'+str(tmp_path/'concurrent.db'),
                               oidc={'issuer':'http://localhost','client_id':'test'}))
    store=app.state.store; _,_,uid=store.login('http://localhost','owner','Owner')
    source={'backend_id':'pc','profile':'default','engine':'hermes'}
    p=store.create_pairing('PC',[source]); store.approve_pairing(uid,p['pairing_id'],p['user_code'],[source])
    device=store.exchange(p['pairing_id'],p['device_code'])
    with serve_app(app) as url:
        gate=asyncio.Event()
        async def attempt():
            await gate.wait()
            try:
                ws=await connect(url.replace('http:','ws:')+'/api/remote/bridge',additional_headers={'Authorization':'Bearer '+device['device_token']})
                await ws.recv()
                return ws
            except Exception:
                return None
        tasks=[asyncio.create_task(attempt()) for _ in range(2)];gate.set()
        results=await asyncio.gather(*tasks)
        winners=[ws for ws in results if ws is not None]
        try:
            assert len(winners)==1
        finally:
            await asyncio.gather(*(ws.close() for ws in winners))
