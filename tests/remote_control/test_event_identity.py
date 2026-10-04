import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from test_relay import app_at,login,pair,SOURCE


def test_browser_hello_barrier_is_account_scoped_and_covers_repair_race(tmp_path):
    app=app_at(tmp_path);store=app.state.store
    def session(client,name):
        login(app,client,name);_,paired=pair(client)
        return store.snapshot(store.device(paired['device_token']),{'source':SOURCE,'session':{'native_session_id':name,'revision':1}})
    with TestClient(app) as alice,TestClient(app) as bob,TestClient(app) as empty:
        sid=session(alice,'alice');own_cursor=store.event(sid,'gateway.event',{'type':'message.complete','seq':5})
        foreign=session(bob,'bob');assert store.event(foreign,'gateway.event',{'type':'message.complete'})>own_cursor
        login(app,empty,'empty')
        with empty.websocket_connect('/api/remote/events') as ws:
            assert ws.receive_json()['cursor']==0
        with alice.websocket_connect('/api/remote/events') as ws:
            hello=ws.receive_json()
            assert hello['cursor']==own_cursor
            # Snapshot repair happens after hello; an event during repair must survive.
            cursor=store.event(sid,'gateway.event',{'type':'message.delta','seq':6,'epoch':'native'})
            ws.send_json({'type':'subscribe','session_ids':[sid],'cursor':hello['cursor']})
            assert ws.receive_json()['type']=='subscribed'
            assert ws.receive_json()['cursor']==cursor


@pytest.mark.asyncio
@pytest.mark.parametrize('live_first',[False,True])
@pytest.mark.parametrize('old_epoch,old_runtime',[('old-native-process','runtime'),('new-native-process','previous-runtime')])
async def test_replay_and_live_use_actual_epoch_and_reset_stale_restart_sequence(tmp_path,live_first,old_epoch,old_runtime):
    from remote_control.bridge_state import BridgeState
    from remote_control.bridge_sync import SourceSync
    from remote_control.rpc import RpcClient
    from websockets.asyncio.server import serve
    import json
    sent=[];delivered=asyncio.Event();calls=[]
    async def backend(ws):
        await ws.send(json.dumps({'method':'event','params':{'session_id':'runtime','seq':2,'type':'message.delta','data':{'text':'live'}}}))
        async for raw in ws:
            frame=json.loads(raw);calls.append(frame['params']['last_seen'])
            events=[event for event in [{'session_id':'runtime','seq':1,'type':'message.delta','data':{'text':'replayed'}},
                                       {'session_id':'runtime','seq':2,'type':'message.delta','data':{'text':'live'}}] if event['seq']>frame['params']['last_seen']]
            await ws.send(json.dumps({'id':frame['id'],'result':{'epoch':'new-native-process','latest_seq':2,'truncated':False,'events':events,'open_requests':[]}}))
    class Link:
        async def send(self,frame):
            sent.append(frame)
            if frame['event'].get('seq')==2:delivered.set()
    async with serve(backend,'127.0.0.1',0) as server:
        rpc=RpcClient(f'ws://127.0.0.1:{server.sockets[0].getsockname()[1]}','test');await rpc.connect()
        async def replay(native,last_seen=0):
            return await rpc.call('session.events.since',{'last_seen':last_seen})
        adapter=SimpleNamespace(rpc=rpc,runtime={'original':'runtime'},replay=replay)
        state=BridgeState(tmp_path/'bridge.db')
        sync=SourceSync(SimpleNamespace(state=state,link=Link()),SimpleNamespace(**SOURCE),adapter)
        row={'native_session_id':'original'};sync.rows={'original':row};sync.public={'original':'public'}
        state.write('event:'+sync.local_key('original'),{'seq':900,'epoch':old_epoch,'runtime_id':old_runtime})
        task=None
        try:
            if not live_first:
                await sync.replay(row)
            task=asyncio.create_task(sync.events())
            await asyncio.wait_for(delivered.wait(),5)
            assert calls[:2]==[900,0]
            assert [(frame['event']['seq'],frame['event']['epoch']) for frame in sent if frame['event']['type']!='history.repair']==[(1,'new-native-process'),(2,'new-native-process')]
        finally:
            if task:
                task.cancel();await asyncio.gather(task,return_exceptions=True)
            await rpc.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('live_first',[False,True])
@pytest.mark.parametrize('buffered',[1,120])
async def test_native_ring_eviction_repairs_same_runtime_sequence_generation(tmp_path,live_first,buffered):
    from tui_gateway import event_replay as native
    from remote_control.bridge_state import BridgeState
    from remote_control.bridge_sync import SourceSync
    sent=[]
    class Link:
        async def send(self,frame):sent.append(frame)
    async def replay(sid,last_seen=0):
        from tui_gateway import server
        return server._methods['session.events.since']('replay',{'session_id':'original-runtime','last_seen':last_seen})['result']
    def emit(sid,text):
        native._stamp_event({'method':'event','params':{'session_id':sid,'type':'message.delta','payload':{'text':text}}})
    native.reset_replay_state()
    try:
        for n in range(100):emit('original-runtime',str(n))
        late=native.events_since('original-runtime',0)[-1]
        state=BridgeState(tmp_path/'bridge.db')
        adapter=SimpleNamespace(runtime={'original':'original-runtime'},replay=replay,rpc=SimpleNamespace(gap=False))
        sync=SourceSync(SimpleNamespace(state=state,link=Link()),SimpleNamespace(**SOURCE),adapter)
        row={'native_session_id':'original'};sync.public['original']='public';sync.rows['original']=row
        await sync.replay(row);sent.clear()
        old=state.read('event:'+sync.local_key('original'))
        for n in range(65):emit(f'other-{n}','other')
        for n in range(buffered):emit('original-runtime',f'resumed-{n}')
        if live_first:
            # Catch-up live seq101 is exactly old watermark+1: only real generation detects reset.
            await sync.live_event('original',native.events_since('original-runtime',100 if buffered>100 else 0)[0])
        else:
            await sync.replay(row)
        resumed=[f['event'] for f in sent if f['event'].get('type')=='message.delta']
        assert [event['seq'] for event in resumed]==list(range(1,buffered+1))
        assert [event['payload']['text'] for event in resumed]==[f'resumed-{n}' for n in range(buffered)]
        assert resumed[0]['bridge_generation']!=old['generation']
        assert any(f['event'].get('type')=='history.repair' for f in sent)
        assert state.read('scan:'+sync.local_key('original')) is None
        # A delayed event from the retired ring must not receive the new Bridge generation.
        await sync.live_event('original',late)
        emit('original-runtime','new second event')
        await sync.live_event('original',native.events_since('original-runtime',buffered)[0])
        assert [f['event']['payload']['text'] for f in sent if f['event'].get('type')=='message.delta']==[f'resumed-{n}' for n in range(buffered)]+['new second event']
    finally:
        native.reset_replay_state()
