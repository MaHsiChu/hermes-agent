from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from PIL import Image
from sqlalchemy import select,func


@pytest.mark.asyncio
async def test_native_persisted_image_markers_export_only_authorized_images(tmp_path,monkeypatch):
    from test_network import serve_app
    from hermes_state import SessionDB
    from hermes_cli.web_routers.sessions import manage_router
    from tui_gateway import session_history
    from tui_gateway.method_ctx import rebind
    from remote_control.adapters.hermes import HermesAdapter
    from remote_control.bridge_attachments import rewrite_images
    from remote_control.bridge_state import BridgeState
    from remote_control.config import Backend,ServerConfig
    from remote_control.server import create_app
    from remote_control import db
    home=tmp_path/'home';home.mkdir();allowed=home/'images';allowed.mkdir()
    monkeypatch.setattr(Path,'home',lambda:tmp_path);monkeypatch.setenv('HERMES_HOME',str(home))
    monkeypatch.setattr('hermes_state.DEFAULT_DB_PATH',home/'state.db')
    inside=allowed/'photo %2F with spaces.png';outside=tmp_path/'private.png'
    Image.new('RGB',(2,2),'red').save(inside);Image.new('RGB',(2,2),'blue').save(outside)
    invalid=allowed/'invalid.png';invalid.write_bytes(b'not an image')
    persisted=rebind(session_history._build_persist_message_with_image_refs,{**vars(session_history),'Path':Path})
    contents=[persisted('caption',[str(inside)])+'\n[screenshot]',
              '@image:'+str(allowed/'missing.png'),persisted('private',[str(outside)]),
              '@image:https://example.invalid/never-fetch.png',persisted('',[str(invalid)]),'plain\n[screenshot]']
    with SessionDB(db_path=home/'state.db') as native:
        native.create_session(session_id='original',source='desktop')
        native.append_messages_batch('original',[{'role':'user','content':content} for content in contents])
    secret=tmp_path/'token';secret.write_text('test');secret.chmod(0o600)
    backend=Backend(backend_id='pc',profile='default',engine='hermes',url='http://localhost',token={'file':str(secret)},attachment_roots=[str(allowed)])
    adapter=HermesAdapter(backend);await adapter.http.aclose()
    native_app=FastAPI();native_app.include_router(manage_router)
    adapter.http=httpx.AsyncClient(transport=httpx.ASGITransport(app=native_app),base_url='http://localhost')
    try:
        rows,_,_=await adapter.history('original')
    finally:
        await adapter.close()
    assert '@image:' in rows[0]['content'] and str(inside) in rows[0]['content']
    app=create_app(ServerConfig(development=True,database_url='sqlite:///'+str(tmp_path/'relay.db'),oidc={'issuer':'http://localhost','client_id':'test'}))
    store=app.state.store;_,_,uid=store.login('issuer','owner','Owner')
    source={'backend_id':'pc','profile':'default','engine':'hermes'}
    p=store.create_pairing('pc',[source]);store.approve_pairing(uid,p['pairing_id'],p['user_code'],[source]);credential=store.exchange(p['pairing_id'],p['device_code'])
    sid=store.snapshot(store.device(credential['device_token']),{'source':source,'session':{'native_session_id':'original','revision':1}})
    with serve_app(app) as url:
        bridge=SimpleNamespace(config=SimpleNamespace(relay_url=url),credential=credential,state=BridgeState(tmp_path/'bridge.db'))
        sync=SimpleNamespace(bridge=bridge,backend=backend,current_native='original',public={'original':sid})
        rewritten=await rewrite_images(sync,rows)
        content=rewritten[0]['content']
        assert isinstance(content,list)
        image=next(part for part in content if part['type']=='attachment')
        assert image['status']=='available' and image['name']==inside.name
        assert str(inside) not in str(content) and '[screenshot]' not in str(content)
        assert any(part.get('text','').startswith('caption') for part in content)
        for row in rewritten[1:5]:
            unavailable=next(part for part in row['content'] if part['type']=='attachment')
            assert unavailable['status']=='unavailable' and unavailable['reason']
            assert '@image:' not in str(row['content'])
        assert rewritten[5]['content']==contents[5]
        assert rows[0]['content']==contents[0]
        assert await rewrite_images(sync,rows)==rewritten
        with store.engine.connect() as conn:
            assert conn.scalar(select(func.count()).select_from(db.attachments))==1
        async with httpx.AsyncClient(base_url=url,headers={'Authorization':'Bearer '+credential['device_token']}) as client:
            response=await client.get(f'/api/remote/bridge/attachments/{sid}/{image["id"]}')
            assert response.content==inside.read_bytes()
            assert (await client.get(f'/api/remote/bridge/attachments/foreign/{image["id"]}')).status_code==404
