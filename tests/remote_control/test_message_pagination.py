from fastapi.testclient import TestClient

from test_relay import app_at, login, pair, SOURCE


def test_latest_history_pages_are_chronological_and_cursor_is_direction_bound(tmp_path):
    app=app_at(tmp_path)
    with TestClient(app) as client:
        login(app,client,'owner');_,device=pair(client)
        with client.websocket_connect('/api/remote/bridge',headers={'Authorization':'Bearer '+device['device_token'],'Origin':''}) as ws:
            ws.receive_json()
            ws.send_json({'type':'snapshot','source':SOURCE,'session':{'native_session_id':'original','revision':1},
                          'messages':[{'id':str(i),'ordinal':i,'revision':1,'content':str(i)} for i in range(7)]})
            sid=ws.receive_json()['session_id']
            path=f'/api/remote/sessions/{sid}/messages'
            newest=client.get(path,params={'order':'latest','limit':3}).json()
            assert [m['id'] for m in newest['messages']]==['4','5','6']
            # Concurrent new messages must not shift a backwards cursor.
            ws.send_json({'type':'snapshot','source':SOURCE,'session':{'native_session_id':'original','revision':2},
                          'messages':[{'id':'7','ordinal':7,'revision':1,'content':'new'}]})
            ws.receive_json()
            older=client.get(path,params={'order':'latest','limit':3,'cursor':newest['next_cursor']}).json()
            assert [m['id'] for m in older['messages']]==['1','2','3']
            last=client.get(path,params={'order':'latest','limit':3,'cursor':older['next_cursor']}).json()
            assert [m['id'] for m in last['messages']]==['0'] and last['next_cursor'] is None
            assert client.get(path,params={'order':'oldest','cursor':newest['next_cursor']}).status_code==400
            assert [m['id'] for m in client.get(path,params={'limit':2}).json()['messages']]==['0','1']
            assert client.get(path,params={'order':'sideways'}).status_code==400
