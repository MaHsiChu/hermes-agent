import asyncio
import json
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException
from sqlalchemy import select, update, func

from . import db
from .config import source_key
from .security import require, redact, token


class Connections:
    def __init__(self, store):
        self.store=store
        self.devices={}
        self.browser={}
        self.status={}
        self.upload_leases={}

    def source_online(self,row):
        key=(row['device_id'],source_key(row))
        return row['device_id'] in self.devices and self.status.get(key,False)

    async def revoke(self,did):
        device=self.store.one(db.devices,db.devices.c.id==did)
        peer=self.devices.pop(did,None)
        self.upload_leases.pop(did,None)
        self.store.disconnected(did)
        if peer:
            await peer.close(code=4403)
        # Subscribed browsers must discard formerly authorized in-memory state immediately.
        for ws,identity in list(self.browser.items()):
            if device and identity['user_id']==device['user_id']:
                await ws.close(code=4403)

    async def logout(self,login_hash):
        for ws,identity in list(self.browser.items()):
            if identity['hash']==login_hash:
                await ws.close(code=4401)

    async def dispatch(self,session,command):
        with self.store.transaction() as c:
            c.execute(update(db.commands).where(db.commands.c.request_id==command['request_id']).values(state='dispatched'))
        ws=self.devices.get(session['device_id'])
        if not ws:
            self.store.disconnected(session['device_id'])
            return
        frame={'type':'command','request_id':command['request_id'],'digest':command['digest'],
            'operation':command['operation'],'payload':command['payload'],'expires_at':command['expires_at'],
            'device_id':session['device_id'],'session_id':session['id'],
            'native_session_id':session['native_session_id'],
            'source':{k:session[k] for k in ('backend_id','profile','engine')}}
        try:
            await asyncio.wait_for(ws.send_json(frame),5)
        except (TimeoutError,RuntimeError,WebSocketDisconnect):
            self.store.disconnected(session['device_id'])


def router():
    r=APIRouter()

    @r.websocket('/api/remote/bridge')
    async def bridge(ws:WebSocket):
        store=ws.app.state.store; connections=ws.app.state.connections
        auth=ws.headers.get('authorization','')
        device=store.device(auth.removeprefix('Bearer ')) if auth.startswith('Bearer ') else None
        if not ws.app.state.config.oidc or not device or ws.headers.get('origin'):
            await ws.close(code=4401); return
        did=device['id']
        if did in connections.devices:
            await ws.close(code=4409); return
        # Reserve before accept yields; concurrent handshakes cannot both become writers.
        connections.devices[did]=ws
        connections.upload_leases[did]=token()
        for source in device['sources']:
            connections.status[(did,source_key(source))]=False
        try:
            await ws.accept()
        except BaseException:
            connections.devices.pop(did,None)
            connections.upload_leases.pop(did,None)
            raise
        try:
            await ws.send_json({'type':'welcome','device_id':did,'allowed_sources':device['sources'],'protocol':1,
                                'upload_lease':connections.upload_leases[did]})
            while True:
                frame=await asyncio.wait_for(ws.receive_json(),45)
                device=store.device(auth.removeprefix('Bearer '))
                if not device:
                    await ws.close(code=4403); return
                require(len(json.dumps(frame,ensure_ascii=False,separators=(',',':')).encode())<=2*1024*1024,413,'Frame too large')
                with store.transaction() as c:
                    c.execute(update(db.devices).where(db.devices.c.id==did).values(last_seen=time.time()))
                try:
                    kind=frame.get('type')
                    if kind=='snapshot':
                        require(len(frame.get('messages',[]))<=500,400,'Snapshot page too large')
                        sid=store.snapshot(device,frame)
                        connections.status[(did,source_key(frame['source']))]=True
                        await ws.send_json({'type':'snapshot.ack','session_id':sid,'native_session_id':frame['session']['native_session_id'],
                                            'request_id':frame.get('request_id')})
                    elif kind=='receipt':
                        store.receipt(did,frame)
                        await ws.send_json({'type':'receipt.ack','request_id':frame['request_id']})
                    elif kind=='receipt.query':
                        row=store.one(db.commands,db.commands.c.request_id==frame['request_id'],db.commands.c.device_id==did)
                        await ws.send_json({'type':'receipt.status','request_id':frame['request_id'],
                            'state':row['state'] if row else 'unknown','digest':row['digest'] if row else None})
                    elif kind=='event':
                        row=store.one(db.sessions,db.sessions.c.id==frame['session_id'],db.sessions.c.device_id==did)
                        require(row)
                        store.event(row['id'],'gateway.event',frame['event'])
                    elif kind=='heartbeat':
                        for status in frame.get('sources',[]):
                            require(source_key(status['source']) in {source_key(s) for s in device['sources']},403,'Foreign source')
                            connections.status[(did,source_key(status['source']))]=bool(status['online'])
                        await ws.send_json({'type':'heartbeat.ack'})
                    else:
                        raise HTTPException(400,'Unknown Bridge frame')
                except (HTTPException,ValueError,KeyError) as e:
                    await ws.send_json({'type':'error','request_id':frame.get('request_id'),'error':str(getattr(e,'detail','Invalid Bridge frame'))})
        except (WebSocketDisconnect,TimeoutError,RuntimeError):
            pass
        finally:
            if connections.devices.get(did) is ws:
                connections.devices.pop(did,None)
                connections.upload_leases.pop(did,None)
                store.disconnected(did)

    @r.websocket('/api/remote/events')
    async def events(ws:WebSocket):
        store=ws.app.state.store; connections=ws.app.state.connections
        raw=ws.cookies.get('remote_session'); user=store.web_user(raw)
        if not ws.app.state.config.oidc or not user or ws.headers.get('origin')!=ws.app.state.config.public_url:
            await ws.close(code=4401); return
        await ws.accept(); connections.browser[ws]={'hash':user['hash'],'user_id':user['user_id']}
        subscribed=[]; cursor=0
        try:
            with store.engine.connect() as c:
                barrier=c.scalar(select(func.max(db.events.c.seq)).select_from(db.events)
                    .join(db.sessions,db.sessions.c.id==db.events.c.session_id)
                    .join(db.devices,db.devices.c.id==db.sessions.c.device_id)
                    .where(db.devices.c.user_id==user['user_id'],db.devices.c.revoked==False,db.sessions.c.deleted==False)) or 0
            await ws.send_json({'type':'hello','protocol':1,'cursor':barrier})
            while True:
                if not store.web_user(raw):
                    await ws.close(code=4401); return
                try:
                    frame=await asyncio.wait_for(ws.receive_json(),.25)
                    require(frame.get('type')=='subscribe',400,'Expected subscribe')
                    ids=frame.get('session_ids',[])
                    require(isinstance(ids,list) and len(ids)<=32,400,'Subscription limit')
                    for sid in ids:
                        store.own_session(user['user_id'],sid)
                    subscribed=ids; cursor=max(0,int(frame.get('cursor') or 0))
                    await ws.send_json({'type':'subscribed','session_ids':ids,'cursor':cursor})
                except TimeoutError:
                    pass
                if not subscribed:
                    continue
                for sid in subscribed:
                    store.own_session(user['user_id'],sid)
                with store.engine.connect() as c:
                    rows=c.execute(select(db.events).where(db.events.c.session_id.in_(subscribed),db.events.c.seq>cursor)
                                   .order_by(db.events.c.seq).limit(201)).mappings().all()
                if len(rows)>200:
                    cursor=rows[-1]['seq']
                    await ws.send_json({'type':'gap','cursor':cursor,'session_ids':subscribed,'reason':'Snapshot repair required'})
                else:
                    for row in rows:
                        cursor=row['seq']
                        await asyncio.wait_for(ws.send_json({'type':'event','cursor':cursor,'session_id':row['session_id'],
                                                           'event':{'type':row['type'],'payload':row['data']}}),5)
        except (WebSocketDisconnect,RuntimeError,TimeoutError):
            pass
        except (HTTPException,ValueError,KeyError):
            await ws.close(code=4403)
        finally:
            connections.browser.pop(ws,None)

    return r
