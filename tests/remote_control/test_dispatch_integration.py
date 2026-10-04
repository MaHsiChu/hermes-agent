"""Bridge fault handling through real HTTP/WS/SQL; the execution endpoint is a test actor."""
import asyncio
import json
import time
from pathlib import Path

import pytest
from fastapi import FastAPI,HTTPException


@pytest.mark.asyncio
async def test_executed_command_with_lost_backend_ack_is_never_sent_twice(tmp_path):
    from test_network import serve_app
    from remote_control.server import create_app
    from remote_control.config import ServerConfig,BridgeConfig,source_key
    from remote_control.bridge import Bridge,write_credential
    from remote_control.bridge_sync import SourceSync
    from remote_control.adapters.hub import HubAdapter
    from remote_control.relay_link import RelayLink
    from remote_control import db
    from remote_control.security import digest
    effect=tmp_path/'execution.log'
    backend=FastAPI()
    @backend.post('/rpc/health')
    async def health():return {'ok':True}
    @backend.post('/rpc/app_dispatch')
    async def act(body:dict):
        with effect.open('a') as f:f.write(body['request_key']+'\n')
        raise HTTPException(500,'Injected ACK loss after side effect')
    relay=create_app(ServerConfig(development=True,database_url='sqlite:///'+str(tmp_path/'relay.db'),oidc={'issuer':'http://localhost','client_id':'test'}))
    store=relay.state.store;_,_,uid=store.login('issuer','owner','Owner')
    source={'backend_id':'hub','profile':'personal','engine':'codex'}
    p=store.create_pairing('pc',[source]);store.approve_pairing(uid,p['pairing_id'],p['user_code'],[source]);credential=store.exchange(p['pairing_id'],p['device_code'])
    with serve_app(backend) as backend_url,serve_app(relay) as relay_url:
        credential['relay_url']=relay_url
        secret=tmp_path/'backend.token';secret.write_text('test');secret.chmod(0o600)
        credential_path=tmp_path/'credential.json';write_credential(credential_path,credential)
        config=BridgeConfig(relay_url=relay_url,development=True,device_name='pc',credential_file=str(credential_path),state_file=str(tmp_path/'bridge.db'),
            backends=[dict(source,url=backend_url,token={'file':str(secret)})])
        bridge=Bridge(config);bridge.link=RelayLink(config,credential);await bridge.link.connect()
        adapter=HubAdapter(config.backends[0]);await adapter.connect()
        sync=SourceSync(bridge,config.backends[0],adapter);bridge.sources[source_key(source)]=sync
        row={'native_session_id':'original','title':'Original'};sync.rows={'original':row}
        sid=await sync.publish(row)
        session=store.own_session(uid,sid)
        command,_=store.accept(uid,session,'persistent-request','send',{'text':'one'})
        frame=dict(command,type='command',native_session_id='original',source=source)
        try:
            await bridge.execute(frame)
            assert store.one(db.commands,db.commands.c.request_id=='persistent-request')['state']=='delivery_uncertain'
            await bridge.execute(frame)
            assert effect.read_text().splitlines()==['persistent-request']
            restarted=Bridge(config)
            assert restarted.state.get('persistent-request')['state']=='delivery_uncertain'
            expired,_=store.accept(uid,session,'expired-request','send',{'text':'two'})
            expired=dict(expired,type='command',native_session_id='original',source=source,expires_at=time.time()-1)
            await bridge.execute(expired)
            assert store.one(db.commands,db.commands.c.request_id=='expired-request')['state']=='failed'
            assert effect.read_text().splitlines()==['persistent-request']
            foreign=dict(frame,request_id='foreign-request',source={**source,'profile':'other'})
            await bridge.execute(foreign)
            assert bridge.state.get('foreign-request') is None
        finally:
            await bridge.link.close();await adapter.close()
