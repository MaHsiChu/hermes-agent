from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI


@pytest.mark.asyncio
async def test_real_hermes_profile_history_a_b_a_and_compacted_pages(tmp_path,monkeypatch):
    from hermes_state import SessionDB
    from hermes_cli.web_routers.sessions import manage_router,list_router
    from remote_control.adapters.hermes import HermesAdapter
    from remote_control.config import Backend
    monkeypatch.setattr(Path,'home',lambda:tmp_path)
    home=tmp_path/'.hermes'; other=home/'profiles'/'work'
    home.mkdir();other.mkdir(parents=True)
    monkeypatch.setenv('HERMES_HOME',str(home))
    monkeypatch.setattr('hermes_state.DEFAULT_DB_PATH',home/'state.db')
    for path,label in ((home,'A'),(other,'B')):
        with SessionDB(db_path=path/'state.db') as store:
            store.create_session(session_id='same-id',source='desktop')
            store.append_messages_batch('same-id',[{'role':'user' if n%2==0 else 'assistant','content':f'{label}-{n}'} for n in range(211)])
            store.archive_and_compact('same-id',[{'role':'assistant','content':f'{label}-summary'}])
            store.set_session_archived('same-id',True)
    token=tmp_path/'token';token.write_text('local-test');token.chmod(0o600)
    app=FastAPI();app.include_router(list_router);app.include_router(manage_router)
    seen=[]
    for profile in ('default','work','default'):
        adapter=HermesAdapter(Backend(backend_id='desktop',profile=profile,engine='hermes',url='http://localhost',token={'file':str(token)}))
        await adapter.http.aclose()
        adapter.http=httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://localhost')
        try:
            catalog=[row async for row in adapter.catalog()]
            assert len(catalog)==1 and catalog[0]['archived']
            rows=[];offset=0
            while offset is not None:
                page,offset,_=await adapter.history('same-id',offset)
                rows.extend(page)
            assert len(rows)==212 and len({r['id'] for r in rows})==212
            assert rows[-1]['content'].endswith('-summary')
            seen.append(rows[0]['content'])
        finally:
            await adapter.close()
    assert seen==['A-0','B-0','A-0']


@pytest.mark.asyncio
async def test_catalog_native_windows_pins_and_source_activity_are_stable(tmp_path,monkeypatch):
    from hermes_state import SessionDB
    from hermes_cli.web_routers.sessions import list_router
    from remote_control.adapters.hermes import HermesAdapter
    from remote_control.config import Backend
    monkeypatch.setattr(Path,'home',lambda:tmp_path)
    home=tmp_path/'.hermes';home.mkdir();monkeypatch.setenv('HERMES_HOME',str(home))
    monkeypatch.setattr('hermes_state.DEFAULT_DB_PATH',home/'state.db')
    with SessionDB(db_path=home/'state.db') as store:
        for n in range(211):
            store.create_session(session_id=f's{n}',source='desktop')
            store.end_session(f's{n}','fixture')
        store.set_session_pinned('s0',True);store.set_session_pinned('s1',True)
        store.append_messages_batch('s0',[{'role':'user','content':'recent activity','timestamp':2000000000}])
    token=tmp_path/'token';token.write_text('local-test');token.chmod(0o600)
    app=FastAPI();app.include_router(list_router)
    adapter=HermesAdapter(Backend(backend_id='pc',profile='default',engine='hermes',url='http://localhost',token={'file':str(token)}))
    await adapter.http.aclose()
    adapter.http=httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://localhost')
    try:
        first=[r async for r in adapter.catalog()];second=[r async for r in adapter.catalog()]
        assert len(first)==211 and {r['native_session_id'] for r in first}=={f's{n}' for n in range(211)}
        assert {r['id']:r['updated_at'] for r in first}=={r['id']:r['updated_at'] for r in second}
        assert max(first,key=lambda r:r['updated_at'])['id']=='s0'
        from fastapi.testclient import TestClient
        from test_relay import app_at,login,pair,SOURCE
        relay=app_at(tmp_path)
        with TestClient(relay) as client:
            login(relay,client,'owner');_,credential=pair(client)
            device=relay.state.store.device(credential['device_token'])
            chosen=[r for r in first if r['id'] in {'s0','s210'}]
            for revision in (1,2):
                for row in chosen:
                    relay.state.store.snapshot(device,{'source':SOURCE,'session':dict(row,revision=revision)})
                page=client.get('/api/remote/sessions').json()['sessions']
                assert [r['native_session_id'] for r in page]==['s0','s210']
                assert {r['native_session_id']:r['updated_at'] for r in page}=={r['id']:r['updated_at'] for r in chosen}
    finally:
        await adapter.close()
