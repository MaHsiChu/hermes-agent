import time

import pytest
from fastapi.testclient import TestClient

SOURCE = {"backend_id": "desktop", "profile": "default", "engine": "hermes"}


def app_at(tmp_path):
    from remote_control.config import ServerConfig
    from remote_control.server import create_app
    return create_app(ServerConfig(public_url="http://testserver", development=True,
        database_url="sqlite:///" + str(tmp_path / "relay.db"),
        oidc={"issuer": "http://localhost:8788/realms/test", "client_id": "test"}))


def login(app, client, subject):
    token, csrf, _ = app.state.store.login("http://localhost:8788/realms/test", subject, subject)
    client.cookies.set("remote_session", token)
    client.headers.update({"Origin": "http://testserver", "X-CSRF-Token": csrf})


def pair(client):
    p = client.post("/api/remote/pairings", json={"name": "PC", "sources": [SOURCE]}).json()
    approved = client.post(f"/api/remote/pairings/{p['pairing_id']}/approve",
        json={"user_code": p['user_code'], "allowed_sources": [SOURCE]})
    assert approved.status_code == 200, approved.text
    r = client.post(f"/api/remote/pairings/{p['pairing_id']}/exchange", json={"device_code": p['device_code']})
    assert r.status_code == 200, r.text
    return p, r.json()


def snapshot(ws, native="same-id", profile="default"):
    ws.send_json({"type": "snapshot", "source": {**SOURCE, "profile": profile},
        "session": {"native_session_id": native, "title": "Work", "revision": 1,
                    "capabilities": {"send": {"status": "supported"}}},
        "messages": [{"id": "m1", "revision": 1, "ordinal": 1, "role": "user", "content": "hello"}],
        "sync": {"complete": True}})
    return ws.receive_json()


def test_tenant_source_revocation_and_opaque_attachment_isolation(tmp_path):
    app = app_at(tmp_path)
    with TestClient(app) as a, TestClient(app) as b:
        login(app, a, "a"); login(app, b, "b")
        _, device = pair(a)
        with a.websocket_connect("/api/remote/bridge", headers={"Authorization": "Bearer " + device['device_token'], "Origin": ""}) as ws:
            assert ws.receive_json()['type'] == 'welcome'
            owned = snapshot(ws)['session_id']
            assert snapshot(ws, profile="foreign")['type'] == 'error'
            assert a.get(f"/api/remote/sessions/{owned}").status_code == 200
            assert b.get(f"/api/remote/sessions/{owned}").status_code == 404
            assert b.get("/api/remote/sessions").json()['sessions'] == []
            assert b.delete(f"/api/remote/devices/{device['device_id']}").status_code == 404
            assert a.delete(f"/api/remote/devices/{device['device_id']}").status_code == 200
            from starlette.websockets import WebSocketDisconnect
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()
        assert a.get(f"/api/remote/sessions/{owned}").status_code == 404


def test_pairing_claim_is_one_time_expiring_and_csrf_protected(tmp_path):
    app = app_at(tmp_path)
    with TestClient(app) as client:
        login(app, client, "a")
        p, device = pair(client)
        path = f"/api/remote/pairings/{p['pairing_id']}/exchange"
        assert client.post(path, json={"device_code": p['device_code']}).status_code == 409
        client.headers['X-CSRF-Token'] = 'wrong'
        assert client.delete(f"/api/remote/devices/{device['device_id']}").status_code == 403
        from remote_control.db import pairings
        with app.state.store.engine.begin() as c:
            c.execute(pairings.update().values(expires_at=time.time()-1))
        assert client.post(path, json={"device_code": p['device_code']}).status_code == 410


def test_command_idempotency_and_restart_never_redispatches(tmp_path):
    app = app_at(tmp_path)
    with TestClient(app) as client:
        login(app, client, "a")
        _, device = pair(client)
        with client.websocket_connect("/api/remote/bridge", headers={"Authorization": "Bearer " + device['device_token'], "Origin": ""}) as ws:
            ws.receive_json(); sid = snapshot(ws)['session_id']
            path = f"/api/remote/sessions/{sid}/commands"
            body = {"request_id": "persistent-request", "operation": "send", "payload": {"text": "hello"}}
            assert client.post(path, json=body).status_code == 202
            frame = ws.receive_json()
            assert frame['type'] == 'command'
            assert client.post(path, json=body).json()['request_id'] == body['request_id']
            assert client.post(path, json={**body, "payload": {"text": "changed"}}).status_code == 409
        assert client.get('/api/remote/commands/persistent-request').json()['state'] == 'delivery_uncertain'
        assert client.post(path, json={**body, "request_id": "offline-request"}).status_code == 409
    restored = app_at(tmp_path)
    with TestClient(restored) as client:
        login(restored, client, 'a')
        assert client.get('/api/remote/commands/persistent-request').json()['state'] == 'delivery_uncertain'


def test_unconfigured_auth_fails_closed(tmp_path):
    from remote_control.config import ServerConfig
    from remote_control.server import create_app
    app = create_app(ServerConfig(development=True, database_url='sqlite:///' + str(tmp_path/'closed.db')))
    with TestClient(app) as c:
        assert c.get('/health').status_code == 200
        assert c.get('/api/remote/me').json()['user'] is None
        assert c.post('/api/remote/pairings', json={'name':'PC','sources':[SOURCE]}).status_code == 503


def test_disabling_oidc_revokes_existing_cookie_and_device_access(tmp_path):
    app=app_at(tmp_path)
    with TestClient(app) as c:
        login(app,c,'owner'); _,device=pair(c); cookie=c.cookies.get('remote_session')
    from remote_control.server import create_app
    closed=create_app(app.state.config.model_copy(update={'oidc':None}))
    with TestClient(closed) as c:
        c.cookies.set('remote_session',cookie)
        assert c.get('/api/remote/me').json()['user'] is None
        assert c.get('/api/remote/devices').status_code==503
        from starlette.websockets import WebSocketDisconnect
        with pytest.raises(WebSocketDisconnect):
            with c.websocket_connect('/api/remote/bridge',headers={'Authorization':'Bearer '+device['device_token']}):
                pass


def test_receipt_completion_advances_ack_but_never_regresses(tmp_path):
    app=app_at(tmp_path)
    with TestClient(app) as c:
        login(app,c,'owner'); _,device=pair(c)
        with c.websocket_connect('/api/remote/bridge',headers={'Authorization':'Bearer '+device['device_token'],'Origin':''}) as ws:
            ws.receive_json(); sid=snapshot(ws)['session_id']
            c.post(f'/api/remote/sessions/{sid}/commands',json={'request_id':'receipt-final','operation':'send','payload':{'text':'hello'}})
            command=ws.receive_json()
            for state in ('acknowledged','completed','received'):
                ws.send_json({'type':'receipt','request_id':command['request_id'],'digest':command['digest'],'state':state})
                ws.receive_json()
            assert c.get('/api/remote/commands/receipt-final').json()['state']=='completed'


def test_revoke_does_not_disconnect_another_tenants_browser(tmp_path):
    app=app_at(tmp_path)
    with TestClient(app) as a,TestClient(app) as b:
        login(app,a,'a'); login(app,b,'b'); _,device=pair(a)
        with b.websocket_connect('/api/remote/events') as socket:
            assert socket.receive_json()['type']=='hello'
            assert a.delete('/api/remote/devices/'+device['device_id']).status_code==200
            socket.send_json({'type':'subscribe','session_ids':[],'cursor':0})
            assert socket.receive_json()['type']=='subscribed'


def test_attachments_validate_bytes_and_require_exact_session_ownership(tmp_path):
    import io
    from PIL import Image
    app=app_at(tmp_path)
    with TestClient(app) as a,TestClient(app) as b:
        login(app,a,'a');login(app,b,'b');_,device=pair(a)
        with a.websocket_connect('/api/remote/bridge',headers={'Authorization':'Bearer '+device['device_token'],'Origin':''}) as ws:
            ws.receive_json();sid=snapshot(ws)['session_id'];other=snapshot(ws,native='other')['session_id']
            from remote_control.db import sessions
            with app.state.store.transaction() as c:
                c.execute(sessions.update().values(capabilities={'attachments':{'status':'supported'}}))
            content=io.BytesIO();Image.new('RGB',(2,2),'red').save(content,format='PNG')
            path=f'/api/remote/sessions/{sid}/attachments'
            uploaded=a.post(path,files={'file':('../unsafe.png',content.getvalue(),'image/png')})
            assert uploaded.status_code==200,uploaded.text
            aid=uploaded.json()['id']
            assert uploaded.json()['name']=='unsafe.png'
            assert a.get(path+'/'+aid).content==content.getvalue()
            assert b.get(path+'/'+aid).status_code==404
            assert a.get(f'/api/remote/sessions/{other}/attachments/{aid}').status_code==404
            assert a.post(path,files={'file':('fake.png',b'not an image','image/png')}).status_code==415


def test_colliding_source_names_do_not_grant_scope_and_equal_revision_cannot_resurrect(tmp_path):
    app=app_at(tmp_path);store=app.state.store
    _,_,uid=store.login('issuer','owner','Owner')
    allowed={'backend_id':'a|b','profile':'c','engine':'hermes'}
    foreign={'backend_id':'a','profile':'b|c','engine':'hermes'}
    p=store.create_pairing('pc',[allowed]);store.approve_pairing(uid,p['pairing_id'],p['user_code'],[allowed]);d=store.exchange(p['pairing_id'],p['device_code'])
    device=store.device(d['device_token'])
    from fastapi import HTTPException
    frame={'source':foreign,'session':{'native_session_id':'native','revision':1}}
    with pytest.raises(HTTPException):
        store.snapshot(device,frame)
    frame['source']=allowed;frame['session']['deleted']=True
    sid=store.snapshot(device,frame)
    frame['session']['deleted']=False
    store.snapshot(device,frame)
    with pytest.raises(HTTPException):
        store.own_session(uid,sid)


def test_equal_session_revision_still_accepts_new_independent_message_revision(tmp_path):
    app=app_at(tmp_path);store=app.state.store
    _,_,uid=store.login('issuer','owner','Owner')
    p=store.create_pairing('pc',[SOURCE]);store.approve_pairing(uid,p['pairing_id'],p['user_code'],[SOURCE]);d=store.exchange(p['pairing_id'],p['device_code'])
    device=store.device(d['device_token'])
    frame={'source':SOURCE,'session':{'native_session_id':'native','revision':1},
           'messages':[{'id':'m','revision':1,'content':'old'}]}
    sid=store.snapshot(device,frame)
    frame['messages']=[{'id':'m','revision':2,'content':'edited'}]
    store.snapshot(device,frame)
    from remote_control.db import messages
    assert store.one(messages,messages.c.session_id==sid)['data']['content']=='edited'


def test_status_filter_applies_before_pagination(tmp_path):
    app=app_at(tmp_path)
    with TestClient(app) as client:
        login(app,client,'owner');_,paired=pair(client);device=app.state.store.device(paired['device_token'])
        for n,status in enumerate(('working','idle','working')):
            app.state.store.snapshot(device,{'source':SOURCE,'session':{'native_session_id':f'session-{n}',
                'title':f'Session {n}','status':status,'updated_at':n+1,'revision':1},'messages':[]})
        result=client.get('/api/remote/sessions?status=idle&limit=1').json()
        assert len(result['sessions'])==1 and result['sessions'][0]['status']=='idle'
        assert result['next_cursor'] is None
        assert client.get('/api/remote/sessions?status=made-up').status_code==400


def test_session_event_marks_only_committed_message_revision_changes(tmp_path):
    from sqlalchemy import select
    from remote_control import db
    app=app_at(tmp_path);store=app.state.store
    with TestClient(app) as client:
        login(app,client,'owner');_,paired=pair(client);device=store.device(paired['device_token'])
        frame={'source':SOURCE,'session':{'native_session_id':'original','revision':7}}
        batches=[
            ([{'id':'m','revision':2,'content':'original'}],True),
            ([],False),
            ([{'id':'m','revision':1,'content':'stale'}],False),
            ([{'id':'m','revision':2,'content':'conflicting replay'}],False),
            ([{'id':'m','revision':3,'content':'edited'}],True),
            ([{'id':'m','revision':4,'deleted':True}],True),
            ([{'id':'m','revision':4,'deleted':True}],False),
            ([{'id':'already-deleted','revision':1,'deleted':True}],True),
        ]
        for messages,expected in batches:
            frame['messages']=messages
            sid=store.snapshot(device,frame)
            with store.engine.connect() as conn:
                event=conn.execute(select(db.events).where(db.events.c.session_id==sid).order_by(db.events.c.seq.desc()).limit(1)).mappings().one()
            assert event['type']=='session.updated'
            assert event['data']=={'revision':7,'messages_changed':expected}
        assert store.one(db.messages,db.messages.c.session_id==sid,db.messages.c.id=='m')['revision']==4
