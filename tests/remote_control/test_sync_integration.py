"""Real native DB/REST → Bridge normalizer → relay WebSocket/SQL, with a lost ACK."""
import asyncio
import json
import time
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select,func


@pytest.mark.asyncio
async def test_real_native_idle_sync_and_scoped_operator_repair_old_record(tmp_path,monkeypatch):
    from test_network import serve_app
    from hermes_state import SessionDB
    from hermes_cli.web_routers.sessions import manage_router,list_router
    from remote_control.adapters.hermes import HermesAdapter
    from remote_control.config import Backend,ServerConfig,BridgeConfig
    from remote_control.server import create_app
    from remote_control.bridge_sync import SourceSync
    from remote_control.bridge_state import BridgeState
    from remote_control.relay_link import RelayLink
    from remote_control.bridge import repair_history
    from remote_control import db
    monkeypatch.setattr(Path,'home',lambda:tmp_path)
    home=tmp_path/'home';home.mkdir();monkeypatch.setenv('HERMES_HOME',str(home))
    monkeypatch.setattr('hermes_state.DEFAULT_DB_PATH',home/'state.db')
    with SessionDB(db_path=home/'state.db') as native:
        native.create_session(session_id='original',source='desktop')
        native.append_messages_batch('original',[{'role':'assistant','content':f'row-{n}'} for n in range(211)])
        native.end_session('original','fixture')
    secret=tmp_path/'token';secret.write_text('test');secret.chmod(0o600)
    backend=Backend(backend_id='pc',profile='default',engine='hermes',url='http://localhost',token={'file':str(secret)})
    adapter=HermesAdapter(backend);await adapter.http.aclose()
    native_app=FastAPI();native_app.include_router(list_router);native_app.include_router(manage_router)
    adapter.http=httpx.AsyncClient(base_url='http://localhost',transport=httpx.ASGITransport(app=native_app))
    reads=[];history=adapter.history
    async def counted(*args,**kwargs):reads.append((args,kwargs));return await history(*args,**kwargs)
    adapter.history=counted
    source={k:getattr(backend,k) for k in ('backend_id','profile','engine')}
    app=create_app(ServerConfig(development=True,database_url='sqlite:///'+str(tmp_path/'relay.db'),oidc={'issuer':'http://localhost','client_id':'test'}))
    store=app.state.store;_,_,uid=store.login('issuer','owner','Owner')
    pairing=store.create_pairing('pc',[source]);store.approve_pairing(uid,pairing['pairing_id'],pairing['user_code'],[source]);credential=store.exchange(pairing['pairing_id'],pairing['device_code'])
    with serve_app(app) as url:
        credential['relay_url']=url;credential_file=tmp_path/'credential';credential_file.write_text(json.dumps(credential))
        config=BridgeConfig(relay_url=url,development=True,device_name='pc',credential_file=str(credential_file),state_file=str(tmp_path/'bridge.db'),backends=[backend])
        link=RelayLink(config,credential);await link.connect()
        sync=SourceSync(SimpleNamespace(state=BridgeState(config.state_file),link=link),backend,adapter)
        try:
            await sync.cycle();sid=sync.public['original'];local=sync.local_key('original')
            before=store.one(db.sessions,db.sessions.c.id==sid)['updated_at'];reads.clear()
            # A very old completed scan must still be idle, without the former five-minute audit.
            checkpoint=sync.bridge.state.read('scan:'+local);checkpoint['finished']=1;sync.bridge.state.write('scan:'+local,checkpoint)
            for _ in range(3):await sync.cycle()
            assert reads==[] and store.one(db.sessions,db.sessions.c.id==sid)['updated_at']==before
            await sync.recover()
            assert reads==[] and store.one(db.sessions,db.sessions.c.id==sid)['sync']['complete']
            with sqlite3.connect(home/'state.db') as c:
                c.execute("UPDATE messages SET content='old record edited in place' WHERE id=(SELECT min(id) FROM messages WHERE session_id='original')")
            await sync.cycle();assert reads==[]
            with pytest.raises(ValueError,match='configured|paired'):
                repair_history(config,{**source,'profile':'foreign'},'original')
            repair_history(config,source,'original')
            await sync.cycle()
            with store.engine.connect() as c:
                saved=c.execute(select(db.messages).where(db.messages.c.session_id==sid)).mappings().all()
            assert len(saved)==211 and min(saved,key=lambda r:r['ordinal'])['data']['content']=='old record edited in place'
            assert sync.bridge.state.read('scan:'+local)['finished']
        finally:await link.close();await adapter.close()


@pytest.mark.asyncio
async def test_long_history_and_catalog_recover_after_lost_snapshot_ack(tmp_path,monkeypatch):
    from test_network import serve_app
    from hermes_state import SessionDB
    from hermes_cli.web_routers.sessions import manage_router,list_router
    from remote_control.adapters.hermes import HermesAdapter
    from remote_control.config import Backend,ServerConfig
    from remote_control.server import create_app
    from remote_control.bridge_sync import SourceSync
    from remote_control.bridge_state import BridgeState
    from remote_control.relay_link import RelayLink
    from remote_control import db
    monkeypatch.setattr(Path,'home',lambda:tmp_path)
    home=tmp_path/'.hermes';home.mkdir();monkeypatch.setenv('HERMES_HOME',str(home))
    monkeypatch.setattr('hermes_state.DEFAULT_DB_PATH',home/'state.db')
    with SessionDB(db_path=home/'state.db') as native:
        for n in range(1000):
            sid=f'catalog-{n:04}'
            native.create_session(session_id=sid,source='desktop')
            native.end_session(sid,'test-fixture')
        native.append_messages_batch('catalog-0000',[{'role':'user' if n%2==0 else 'assistant','content':f'generated-{n}'} for n in range(10000)])
        native.set_session_archived('catalog-0000',True)
    native_app=FastAPI();native_app.include_router(list_router);native_app.include_router(manage_router)
    secret=tmp_path/'backend-token';secret.write_text('test-only');secret.chmod(0o600)
    backend=Backend(backend_id='pc',profile='default',engine='hermes',url='http://localhost',token={'file':str(secret)})
    adapter=HermesAdapter(backend);await adapter.http.aclose()
    adapter.http=httpx.AsyncClient(base_url='http://localhost',transport=httpx.ASGITransport(app=native_app))
    source={k:getattr(backend,k) for k in ('backend_id','profile','engine')}
    app=create_app(ServerConfig(development=True,database_url='sqlite:///'+str(tmp_path/'relay.db'),oidc={'issuer':'http://localhost','client_id':'test'}))
    _,_,uid=app.state.store.login('issuer','owner','Owner')
    p=app.state.store.create_pairing('pc',[source]);app.state.store.approve_pairing(uid,p['pairing_id'],p['user_code'],[source])
    credential=app.state.store.exchange(p['pairing_id'],p['device_code'])
    started=time.monotonic()
    with serve_app(app) as url:
        config=SimpleNamespace(relay_url=url,poll_seconds=5)
        link=RelayLink(config,credential);await link.connect()
        state=BridgeState(tmp_path/'bridge.db')
        class LoseOneAck:
            def __init__(self): self.lost=False
            async def request(self,frame,expected):
                result=await link.request(frame,expected)
                if not self.lost and frame.get('messages'):
                    self.lost=True
                    raise ConnectionError('Injected lost ACK after real relay commit')
                return result
            async def send(self,frame):
                await link.send(frame)
        bridge=SimpleNamespace(state=state,config=config,credential=credential,link=LoseOneAck())
        first=SourceSync(bridge,backend,adapter)
        with pytest.raises(ConnectionError):
            await first.cycle()
        bridge.link=link;bridge.state=BridgeState(tmp_path/'bridge.db')
        restored=SourceSync(bridge,backend,adapter)
        try:
            await restored.recover()
            await restored.cycle()
            with app.state.store.engine.connect() as c:
                assert c.execute(select(func.count()).select_from(db.sessions)).scalar()==1000
                sid=c.execute(select(db.sessions.c.id).where(db.sessions.c.native_session_id=='catalog-0000')).scalar()
                rows=c.execute(select(db.messages).where(db.messages.c.session_id==sid).order_by(db.messages.c.ordinal)).mappings().all()
                assert len(rows)==10000
                assert len({row['id'] for row in rows})==10000
                assert rows[0]['data']['content']=='generated-0'
                assert rows[-1]['data']['content']=='generated-9999'
                assert app.state.store.one(db.sessions,db.sessions.c.id==sid)['sync']['complete']
            print(json.dumps({'catalog_sessions':1000,'long_session_messages':10000,'seconds':round(time.monotonic()-started,2),'fault':'lost snapshot ACK after commit'}))
        finally:
            await link.close();await adapter.close()
