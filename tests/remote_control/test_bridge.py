import asyncio
import json
import time
from pathlib import Path

import pytest
from websockets.asyncio.server import serve


@pytest.mark.asyncio
async def test_hub_real_normalizer_iso_and_normalized_codex_milliseconds_become_seconds(tmp_path,monkeypatch):
    import sqlite3
    from types import SimpleNamespace
    from remote_control.adapters.hub import HubAdapter
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2]/'extensions'/'session-hub'))
    from transcript import TranscriptStore
    codex=tmp_path/'codex';codex.mkdir();claude=tmp_path/'claude.jsonl';rollout=codex/'rollout.jsonl';rollout.write_text('')
    claude.write_text(json.dumps({'type':'assistant','uuid':'claude-item','timestamp':'2026-10-04T00:00:00Z','message':{'content':'hello'}})+'\n')
    with sqlite3.connect(codex/'thread_history_1.sqlite') as c:
        c.execute('CREATE TABLE thread_items(thread_id TEXT,item_id TEXT,item_json TEXT,turn_id TEXT,created_at_ms INTEGER,rollout_ordinal INTEGER,updated_at_ordinal INTEGER)')
        c.execute('INSERT INTO thread_items VALUES(?,?,?,?,?,?,?)',('codex','codex-item',json.dumps({'type':'agentMessage','text':'hello'}),'turn',1791072000000,0,1))
    class Readers:
        def resolve(self,engine,sid):return {'path':str(claude if engine=='claude' else rollout),'session_id':sid,'history_mode':'normalized','title':sid,'cwd':str(tmp_path)}
    readers=Readers();readers.codex=codex
    native=TranscriptStore(readers,tmp_path/'index.db')
    token=SimpleNamespace(read=lambda:'test')
    for engine in ('claude','codex'):
        adapter=HubAdapter(SimpleNamespace(url='http://localhost',token=token,engine=engine))
        async def rpc(op,body):return native.page(engine,engine,limit=body.get('limit',100),since=body.get('since'),generation=body.get('generation'))
        adapter.rpc=rpc
        try:
            rows,_,info=await adapter.history(engine)
            assert rows[0]['timestamp']==1791072000
            assert not await adapter.changed(engine,info)
            if engine=='codex':
                with sqlite3.connect(codex/'thread_history_1.sqlite') as c:
                    c.execute('UPDATE thread_items SET item_json=?,updated_at_ordinal=2',(json.dumps({'type':'agentMessage','text':'edited old item'}),))
                assert await adapter.changed(engine,info)
        finally:await adapter.close()


def test_receipts_recover_dispatch_as_uncertain_and_bind_payload(tmp_path):
    from remote_control.bridge_state import BridgeState
    state=BridgeState(tmp_path/'state.sqlite')
    command={'request_id':'id-123456','digest':'hash','session_id':'s','operation':'send'}
    assert state.begin(command)['state']=='received'
    state.mark('id-123456','dispatching')
    restored=BridgeState(tmp_path/'state.sqlite')
    assert restored.begin(command)['state']=='delivery_uncertain'
    with pytest.raises(ValueError,match='payload'):
        restored.begin({**command,'digest':'different'})
    assert restored.get('id-123456')['state']=='delivery_uncertain'


@pytest.mark.asyncio
async def test_rpc_reader_does_not_deadlock_on_server_request_and_handles_batches():
    from remote_control.rpc import RpcClient
    async def handler(ws):
        frame=json.loads(await ws.recv())
        await ws.send(json.dumps({'jsonrpc':'2.0','id':'srq-1','method':'clarify','params':{'session_id':'runtime','question':'Continue?'}})+'\n'+
                      json.dumps({'jsonrpc':'2.0','id':frame['id'],'result':{'status':'ok'}}))
        await ws.wait_closed()
    async with serve(handler,'127.0.0.1',0) as server:
        port=server.sockets[0].getsockname()[1]
        rpc=RpcClient(f'ws://127.0.0.1:{port}', 'credential')
        await rpc.connect()
        try:
            result=await rpc.call('probe',{})
            assert result=={'status':'ok'}
            event=await asyncio.wait_for(rpc.events.get(),2)
            assert event['method']=='clarify'
        finally:
            await rpc.close()


def test_pending_answers_validate_original_choices_and_locked_questions():
    from remote_control.adapters.hermes import validate_answer
    request={'id':'srq-1','method':'approval','params':{'choices':['once','deny'],'request_id':'native'}}
    assert validate_answer(request,{'choice':'once'})=={'choice':'once'}
    with pytest.raises(ValueError):
        validate_answer(request,{'choice':'always'})
    clarify={'id':'srq-2','method':'clarify','params':{'questions':[{'qid':'a','question':'A?','choices':['yes','no']}],'answers':{'a':'yes'}}}
    with pytest.raises(ValueError):
        validate_answer(clarify,{'answers':{'a':'no'}})


def test_revision_tombstones_cannot_be_resurrected_by_old_history(tmp_path):
    from remote_control.bridge_state import BridgeState
    state=BridgeState(tmp_path/'state.sqlite')
    first=state.revise('s',[{'id':'1','content':'old'}],complete=True)
    assert len(first)==1
    assert state.revise('s',[{'id':'1','content':'old'}],complete=True)==[]
    tombstone=state.revise('s',[],complete=True)[0]
    assert tombstone['deleted'] and tombstone['revision']>first[0]['revision']
    restored=BridgeState(tmp_path/'state.sqlite')
    assert restored.revise('s',[],complete=True)==[]


def test_source_key_is_unambiguous_and_full_history_checkpoint_resumes(tmp_path):
    from remote_control.config import source_key
    assert source_key({'backend_id':'a|b','profile':'c','engine':'hermes'}) != source_key({'backend_id':'a','profile':'b|c','engine':'hermes'})


@pytest.mark.asyncio
async def test_hermes_images_reject_before_touching_native_pending_queue(tmp_path):
    from remote_control.adapters.hermes import HermesAdapter
    from remote_control.config import Backend
    secret=tmp_path/'token';secret.write_text('test-token');secret.chmod(0o600)
    adapter=HermesAdapter(Backend(backend_id='pc',profile='default',engine='hermes',url='http://localhost',token={'file':str(secret)}))
    try:
        assert adapter.capabilities()['attachments']['status']=='unavailable'
        with pytest.raises(ValueError,match='atomic'):
            await adapter.execute({'native_session_id':'native','operation':'send','payload':{'text':'see','attachment_ids':['image']}},[('image',b'png')])
    finally:
        await adapter.close()

@pytest.mark.asyncio
async def test_hermes_negotiates_atomic_submit_and_refreshes_credentials(tmp_path):
    from remote_control.adapters.hermes import HermesAdapter
    from remote_control.config import Backend
    from remote_control.rpc import RpcError
    secret=tmp_path/'token'; secret.write_text('first-token'); secret.chmod(0o600)
    adapter=HermesAdapter(Backend(backend_id='pc',profile='default',engine='hermes',url='http://localhost',token={'file':str(secret)}))
    class Peer:
        def __init__(self):
            self.calls=[]; self.caps={}; self.url=''; self.token=''
        async def connect(self): pass
        async def close(self): pass
        async def call(self,method,params):
            self.calls.append((method,params))
            if method=='gateway.capabilities': return self.caps
            if method=='session.resume': return {'session_id':'runtime','running':False}
            return {'status':'streaming'}
    peer=Peer(); adapter.rpc=peer
    try:
        await adapter.connect()
        assert adapter.capabilities()['send']['status']=='unavailable'
        command={'native_session_id':'native','operation':'send','payload':{'text':'text'}}
        with pytest.raises(ValueError,match='atomic'):
            await adapter.execute(command,[])
        peer.caps={'request_owned_prompt_images':True,'prompt_reject_if_busy':True,
                   'prompt_image_uploads':True,'prompt_image_max_count':5,
                   'prompt_image_max_total_bytes':25*1024*1024,'prompt_image_max_request_bytes':36*1024*1024}
        secret.write_text('rotated-token')
        await adapter.connect()
        assert peer.token=='rotated-token' and 'rotated-token' in peer.url
        assert adapter.http.headers['Authorization']=='Bearer rotated-token'
        assert adapter.capabilities()['attachments']['status']=='supported'
        await adapter.execute(command,[])
        assert peer.calls[-1]==('prompt.submit',{'session_id':'runtime','profile':'default','text':'text',
                                              'queued':True,'image_inputs':[],'reject_if_busy':True})
        queue={'native_session_id':'native','operation':'queue','payload':{'text':'picture','attachment_ids':['image']}}
        await adapter.execute(queue,[('image',b'bytes')])
        params=peer.calls[-1][1]
        assert params['image_inputs']==[{'filename':'image','content_base64':'Ynl0ZXM='}]
        assert params['reject_if_busy'] is False
        assert all(method!='image.attach_bytes' for method,_ in peer.calls)
    finally:
        await adapter.close()
