import asyncio
from types import SimpleNamespace

import pytest
import httpx
from sqlalchemy import select


@pytest.mark.asyncio
async def test_byte_heavy_messages_and_bulk_tombstones_pass_real_relay(tmp_path):
    from test_network import serve_app
    from remote_control.config import ServerConfig
    from remote_control.server import create_app
    from remote_control.bridge_sync import SourceSync
    from remote_control.bridge_state import BridgeState
    from remote_control.relay_link import RelayLink
    from remote_control import db
    app=create_app(ServerConfig(development=True,database_url='sqlite:///'+str(tmp_path/'relay.db'),oidc={'issuer':'http://localhost','client_id':'test'}))
    store=app.state.store;_,_,uid=store.login('issuer','owner','Owner')
    source={'backend_id':'pc','profile':'default','engine':'hermes'}
    p=store.create_pairing('pc',[source]);store.approve_pairing(uid,p['pairing_id'],p['user_code'],[source]);credential=store.exchange(p['pairing_id'],p['device_code'])
    with serve_app(app) as url:
        config=SimpleNamespace(relay_url=url);link=RelayLink(config,credential);await link.connect()
        bridge=SimpleNamespace(state=BridgeState(tmp_path/'bridge.db'),link=link)
        sync=SourceSync(bridge,SimpleNamespace(**source),SimpleNamespace(capabilities=lambda:{}))
        row={'native_session_id':'original'}
        records=[{'id':str(i),'revision':1,'ordinal':i,'content':'文'*230000} for i in range(4)]
        records.append({'id':'large','revision':1,'ordinal':5,'content':'token'*500000})
        try:
            async with httpx.AsyncClient(base_url=url) as client:
                response=await client.post('/api/remote/bridge/snapshot',headers={'Authorization':'Bearer '+credential['device_token'],'X-Remote-Bridge-Lease':'stale'},json={'type':'snapshot','source':source,'session':row,'messages':[]})
                assert response.status_code==403
            sid=await sync.publish(row,records,sync={'complete':True})
            with store.engine.connect() as c:
                saved=c.execute(select(db.messages).where(db.messages.c.session_id==sid)).mappings().all()
            assert {r['id']:r['data']['content'] for r in saved}=={r['id']:r['content'] for r in records}
            tombstones=[{'id':str(i),'revision':2,'deleted':True} for i in range(1201)]
            # Simulate a pre-fix persisted outbox. Recovery must repartition it too.
            bridge.state.write('outbox:'+sync.key,{'type':'snapshot','request_id':'old','source':source,'session':row,
                                                  'messages':tombstones,'sync':{'complete':True}})
            await sync.recover()
            with store.engine.connect() as c:
                deleted=c.execute(select(db.messages).where(db.messages.c.session_id==sid,db.messages.c.deleted==True)).mappings().all()
            assert len(deleted)==1201
            assert bridge.state.read('outbox:'+sync.key) is None
        finally:
            await link.close()


@pytest.mark.asyncio
async def test_oversized_record_reports_incomplete_without_blocking_other_rows(tmp_path,monkeypatch):
    from remote_control.bridge_state import BridgeState
    from remote_control import bridge_sync
    monkeypatch.setattr(bridge_sync,'MAX_MESSAGE_BYTES',500)
    frames=[]
    class Link:
        async def request(self,frame,expected):
            frames.append(frame)
            return {'session_id':'public'}
    backend=SimpleNamespace(backend_id='pc',profile='default',engine='hermes')
    state=BridgeState(tmp_path/'journal.db')
    sync=bridge_sync.SourceSync(SimpleNamespace(state=state,link=Link()),backend,SimpleNamespace(capabilities=lambda:{}))
    row={'native_session_id':'original'}
    await sync.publish(row,[{'id':'large','revision':1,'content':'x'*600},{'id':'small','revision':1,'content':'ok'}],sync={'complete':True})
    assert [m['id'] for f in frames for m in f['messages']]==['small']
    assert not frames[-1]['sync']['complete'] and frames[-1]['sync']['unavailable_message_ids']==['large']
    assert state.read('outbox:'+sync.key) is None
    await sync.publish(row,[{'id':'large','revision':2,'deleted':True}],sync={'complete':True})
    assert frames[-1]['sync']['complete']
    assert state.read('oversized:'+sync.local_key('original'))=={}


@pytest.mark.asyncio
@pytest.mark.parametrize('live',[False,True])
async def test_native_large_completion_repairs_through_relay_and_keeps_control_live(tmp_path,live):
    import json
    from test_network import serve_app
    from websockets.asyncio.server import serve
    from remote_control.config import ServerConfig
    from remote_control.server import create_app
    from remote_control.bridge_sync import SourceSync
    from remote_control.bridge_state import BridgeState
    from remote_control.relay_link import RelayLink
    from remote_control.rpc import RpcClient
    from remote_control import db
    content='文\n"'*400000
    event={'session_id':'runtime','seq':1,'type':'message.complete','payload':{'text':content}}
    async def native(ws):
        emitted=False
        async for raw in ws:
            request=json.loads(raw)
            await ws.send(json.dumps({'id':request['id'],'result':{'epoch':'native-process','latest_seq':1,'truncated':False,'events':[event] if request['params']['last_seen']==0 else [],'open_requests':[]}}))
            if live and not emitted:
                emitted=True
                await ws.send(json.dumps({'method':'event','params':event}))
    app=create_app(ServerConfig(development=True,database_url='sqlite:///'+str(tmp_path/'relay.db'),oidc={'issuer':'http://localhost','client_id':'test'}))
    store=app.state.store;_,_,uid=store.login('issuer','owner','Owner')
    source={'backend_id':'pc','profile':'default','engine':'hermes'}
    pairing=store.create_pairing('pc',[source]);store.approve_pairing(uid,pairing['pairing_id'],pairing['user_code'],[source]);credential=store.exchange(pairing['pairing_id'],pairing['device_code'])
    with serve_app(app) as url:
        link=RelayLink(SimpleNamespace(relay_url=url),credential);await link.connect()
        async with serve(native,'127.0.0.1',0,max_size=8*1024*1024) as server:
            rpc=RpcClient(f'ws://127.0.0.1:{server.sockets[0].getsockname()[1]}','test');await rpc.connect()
            async def replay(native,last_seen=0):return await rpc.call('session.events.since',{'last_seen':last_seen})
            class Adapter:
                catalog_complete=True
                runtime={'original':'runtime'}
                def capabilities(self):return {}
                async def catalog(self):yield {'native_session_id':'original','updated_at':1,'is_active':False}
                async def attach(self,*args):return {'status':'idle','open_requests':[]}
                async def history(self,*args,**kwargs):return [{'id':'1','ordinal':1,'content':content}],None,{}
            adapter=Adapter();adapter.rpc=rpc;adapter.replay=replay
            sync=SourceSync(SimpleNamespace(state=BridgeState(tmp_path/'bridge.db'),link=link),SimpleNamespace(**source),adapter)
            row={'native_session_id':'original'};sync.rows={'original':row}
            task=None
            try:
                sid=await sync.publish(row)
                if live:
                    sync.epochs['original']='native-process'
                    sync.generations['original']='bridge-generation'
                    sync.bridge.state.write('event:'+sync.local_key('original'),{'seq':0,'epoch':'native-process','runtime_id':'runtime','generation':'bridge-generation'})
                    task=asyncio.create_task(sync.events())
                    # Read the actual native WS frame without forwarding its replay copy first.
                    await replay('original')
                    for _ in range(100):
                        if sync.bridge.state.read('repair:'+sync.local_key('original')):break
                        await asyncio.sleep(.02)
                    assert sync.bridge.state.read('repair:'+sync.local_key('original'))
                    task.cancel();await asyncio.gather(task,return_exceptions=True);task=None
                else:
                    await sync.replay(row)
                assert await link.request({'type':'receipt.query','request_id':'probe'},'receipt.status')=={'type':'receipt.status','request_id':'probe','state':'unknown','digest':None}
                await sync.cycle()
                with store.engine.connect() as c:
                    saved=c.execute(select(db.messages).where(db.messages.c.session_id==sid)).mappings().all()
                    events=c.execute(select(db.events).where(db.events.c.session_id==sid,db.events.c.type=='gateway.event')).mappings().all()
                assert saved[0]['data']['content']==content
                assert any(e['data']['type']=='history.repair' for e in events)
                assert all(len(json.dumps(e['data']).encode())<2*1024*1024 for e in events)
                assert (await link.request({'type':'receipt.query','request_id':'after-repair'},'receipt.status'))['state']=='unknown'
            finally:
                if task:task.cancel();await asyncio.gather(task,return_exceptions=True)
                await rpc.close();await link.close()
