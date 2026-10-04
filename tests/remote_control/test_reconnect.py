import asyncio
import json
from types import SimpleNamespace

import pytest
from websockets.asyncio.server import serve


@pytest.mark.asyncio
async def test_failed_readers_do_not_escape_cleanup_and_prevent_reconnect():
    from remote_control.rpc import RpcClient
    from remote_control.relay_link import RelayLink
    async def native(ws):
        await ws.close(code=1011,reason='injected backend restart')
    async with serve(native,'127.0.0.1',0) as server:
        rpc=RpcClient(f'ws://127.0.0.1:{server.sockets[0].getsockname()[1]}','token')
        await rpc.connect()
        await asyncio.wait_for(asyncio.gather(rpc.reader,return_exceptions=True),3)
        await rpc.close()
        await rpc.connect()
        await asyncio.wait_for(asyncio.gather(rpc.reader,return_exceptions=True),3)
        await rpc.close()
    async def relay(ws):
        await ws.send(json.dumps({'type':'welcome','device_id':'pc','allowed_sources':[]}))
        await ws.close(code=1011,reason='injected relay restart')
    async with serve(relay,'127.0.0.1',0) as server:
        link=RelayLink(SimpleNamespace(relay_url=f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}'),{'device_id':'pc','device_token':'token'})
        await link.connect()
        await asyncio.wait_for(asyncio.gather(link.reader,return_exceptions=True),3)
        await link.close()
        await link.connect()
        await asyncio.wait_for(asyncio.gather(link.reader,return_exceptions=True),3)
        await link.close()


def test_shared_lock_preserves_windows_only_dependency_marker():
    from pathlib import Path
    from packaging.requirements import Requirement
    lock=Path(__file__).resolve().parents[2]/'remote_control'/'requirements.lock'
    requirement=Requirement(next(line.rstrip(' \\') for line in lock.read_text().splitlines() if line.startswith('pywin32==')))
    assert requirement.marker is not None
    assert requirement.marker.evaluate({'sys_platform':'win32'})
    assert not requirement.marker.evaluate({'sys_platform':'linux'})
    assert not requirement.marker.evaluate({'sys_platform':'darwin'})


@pytest.mark.asyncio
async def test_bulk_tombstones_are_replayable_bounded_snapshot_pages(tmp_path):
    from remote_control.bridge_state import BridgeState
    from remote_control.bridge_sync import SourceSync
    frames=[]
    class Link:
        async def request(self,frame,expected):
            frames.append(frame)
            if len(frame['messages'])>500:raise ValueError('Relay snapshot page limit')
            return {'session_id':'public'}
    adapter=SimpleNamespace(capabilities=lambda:{})
    backend=SimpleNamespace(backend_id='pc',profile='default',engine='hermes')
    bridge=SimpleNamespace(state=BridgeState(tmp_path/'state.db'),link=Link())
    sync=SourceSync(bridge,backend,adapter)
    messages=[{'id':str(i),'revision':2,'deleted':True} for i in range(1201)]
    await sync.publish({'native_session_id':'original'},messages,sync={'complete':True})
    assert sum(len(f['messages']) for f in frames)==1201
    assert max(len(f['messages']) for f in frames)<=500
    assert frames[-1]['sync']['complete']
    assert all(not f['sync']['complete'] for f in frames[:-1])


@pytest.mark.asyncio
async def test_hub_generation_change_restarts_incomplete_history_cursor(tmp_path):
    from remote_control.bridge_state import BridgeState
    from remote_control.bridge_sync import SourceSync
    class Link:
        async def request(self,frame,expected):return {'session_id':'public'}
    class Adapter:
        catalog_complete=True
        def capabilities(self):return {}
        async def catalog(self):yield {'native_session_id':'original'}
        async def history(self,native,offset='',recent=False):
            if not recent:assert offset=='', 'Old generation cursor reused'
            return [],None,{'generation':'new','total':0}
    backend=SimpleNamespace(backend_id='hub',profile='personal',engine='codex')
    bridge=SimpleNamespace(state=BridgeState(tmp_path/'state.db'),link=Link())
    sync=SourceSync(bridge,backend,Adapter());local=sync.local_key('original')
    bridge.state.write('scan:'+local,{'scan':'old','generation':'old','offset':'old-cursor','finished':0})
    await sync.cycle()
    assert bridge.state.read('scan:'+local)['generation']=='new'


@pytest.mark.asyncio
async def test_completed_idle_catalog_does_not_read_history_and_explicit_repair_finds_old_edit(tmp_path):
    from remote_control.bridge_state import BridgeState
    from remote_control.bridge_sync import SourceSync
    reads=[];frames=[]
    class Link:
        async def request(self,frame,expected):frames.append(frame);return {'session_id':'public'}
    class Adapter:
        catalog_complete=True
        content='old'
        def capabilities(self):return {}
        async def catalog(self):yield {'native_session_id':'original','updated_at':1,'message_count':211}
        async def history(self,native,offset='',recent=False):
            reads.append((offset,recent))
            return [{'id':'old-row','ordinal':1,'content':self.content}],None,{'generation':'stable','total':1}
    adapter=Adapter();backend=SimpleNamespace(backend_id='hub',profile='personal',engine='codex')
    bridge=SimpleNamespace(state=BridgeState(tmp_path/'state.db'),link=Link())
    sync=SourceSync(bridge,backend,adapter);await sync.cycle();reads.clear();frames.clear()
    for _ in range(3):await sync.cycle()
    assert reads==[] and frames==[]
    adapter.content='edited old row'
    sync.request_repair('original','operator audit')
    await sync.cycle()
    assert any(m.get('content')=='edited old row' for f in frames for m in f['messages'])
