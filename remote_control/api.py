import base64
import io
import json
import time
import secrets
import math
import binascii

from fastapi import APIRouter, Request, Query, UploadFile, File, HTTPException
from starlette.responses import Response
from sqlalchemy import select, update, and_, or_
from PIL import Image

from . import db
from .auth import current, mutation, configured
from .protocol import Command, validate_payload, receipt_public
from .security import require, opaque, digest
from .attachments import save_image


def page_cursor(cursor):
    if not cursor:
        return 0
    try:
        value = int(base64.urlsafe_b64decode(cursor.encode()).decode())
        require(value >= 0, 400, 'Invalid cursor')
        return value
    except (ValueError, UnicodeError):
        raise HTTPException(400, 'Invalid cursor') from None


def next_cursor(offset):
    return base64.urlsafe_b64encode(str(offset).encode()).decode()


def view_session(row):
    result = dict(row.get('data') or {})
    result.update({k:row[k] for k in ('id','device_id','backend_id','profile','engine','native_session_id','title','archived','updated_at','revision')})
    return result


def router():
    r = APIRouter(prefix='/api/remote')

    @r.post('/pairings')
    async def pair(request: Request, body: dict):
        configured(request)
        name = body.get('name','')
        require(isinstance(name,str) and 0 < len(name) <=100, 400, 'Device name required')
        return request.app.state.store.create_pairing(name, body.get('sources',[]))

    @r.get('/pairings/{pid}')
    async def pairing_detail(pid: str, request: Request):
        current(request)
        p = request.app.state.store.pairing(pid)
        return {'pairing_id':pid,'name':p['name'],'sources':p['sources'],'expires_at':p['expires_at']}

    @r.post('/pairings/{pid}/approve')
    async def approve(pid: str, request: Request, body: dict):
        user = mutation(request)
        request.app.state.store.approve_pairing(user['user_id'],pid,body.get('user_code',''),body.get('allowed_sources',[]))
        return {'approved':True}

    @r.post('/pairings/{pid}/exchange')
    async def exchange(pid: str, request: Request, body: dict):
        configured(request)
        return request.app.state.store.exchange(pid,body.get('device_code',''))

    @r.get('/devices')
    async def devices(request: Request):
        uid = current(request)['user_id']
        with request.app.state.store.engine.connect() as c:
            rows = c.execute(select(db.devices).where(db.devices.c.user_id==uid,db.devices.c.revoked==False)).mappings()
            return {'devices':[{'id':d['id'],'name':d['name'],'last_seen':d['last_seen'],
                                'online':d['id'] in request.app.state.connections.devices,'backends':d['sources']} for d in rows]}

    @r.delete('/devices/{did}')
    async def revoke(did: str, request: Request):
        uid = mutation(request)['user_id']
        store = request.app.state.store
        store.own_device(uid,did)
        with store.transaction() as c:
            c.execute(update(db.devices).where(db.devices.c.id==did).values(revoked=True))
        await request.app.state.connections.revoke(did)
        return {'revoked':True}

    @r.get('/sessions')
    async def sessions(request: Request, device_id: str|None=None, engine: str|None=None,
        profile: str|None=None,q: str='', status: str|None=None, archived: str='exclude', cursor: str|None=None,limit:int=Query(50,ge=1,le=100)):
        uid = current(request)['user_id']
        require(archived in {'exclude','only','include'},400,'Invalid archived filter')
        require(status is None or status in {'idle','starting','waiting','working','streaming','resuming','unknown','completed','failed','interrupted'},400,'Invalid status filter')
        statement = select(db.sessions).join(db.devices).where(db.devices.c.user_id==uid,
            db.devices.c.revoked==False,db.sessions.c.deleted==False)
        for col,value in ((db.sessions.c.device_id,device_id),(db.sessions.c.engine,engine),(db.sessions.c.profile,profile)):
            if value:
                statement=statement.where(col==value)
        if q:
            statement=statement.where(db.sessions.c.title.ilike('%'+q.replace('%','\\%').replace('_','\\_')+'%',escape='\\'))
        if archived!='include':
            statement=statement.where(db.sessions.c.archived==(archived=='only'))
        if status:
            from sqlalchemy import func
            statement=statement.where(func.coalesce(db.sessions.c.data['status'].as_string(),'unknown')==status)
        offset=page_cursor(cursor)
        with request.app.state.store.engine.connect() as c:
            rows=c.execute(statement.order_by(db.sessions.c.updated_at.desc(),db.sessions.c.id).offset(offset).limit(limit+1)).mappings().all()
        return {'sessions':[dict(view_session(x),online=x['device_id'] in request.app.state.connections.devices) for x in rows[:limit]],
                'next_cursor':next_cursor(offset+limit) if len(rows)>limit else None}

    @r.get('/sessions/{sid}')
    async def session(sid: str,request: Request):
        row=request.app.state.store.own_session(current(request)['user_id'],sid)
        online=request.app.state.connections.source_online(row)
        caps=row['capabilities'] or {}
        if not online:
            caps={k:({'status':'unavailable','reason':'Execution backend offline'} if k!='history' else v) for k,v in caps.items()}
        return {'session':view_session(row),'online':online,'capabilities':caps,'sync':row['sync'],
                'pending_requests':row['pending_requests'] if online else []}

    @r.get('/sessions/{sid}/messages')
    async def messages(sid: str,request: Request,cursor:str|None=None,order:str='oldest',limit:int=Query(100,ge=1,le=500)):
        store=request.app.state.store
        row=store.own_session(current(request)['user_id'],sid)
        require(order in {'oldest','latest'},400,'Invalid history order')
        statement=select(db.messages).where(db.messages.c.session_id==sid)
        if cursor:
            try:
                position=json.loads(base64.urlsafe_b64decode(cursor.encode()))
                require(position['order']==order and position['session']==sid,400,'Cursor scope mismatch')
                ordinal=float(position['ordinal']);mid=position['id']
                require(math.isfinite(ordinal) and isinstance(mid,str),400,'Invalid cursor')
            except (ValueError,TypeError,KeyError,binascii.Error):
                raise HTTPException(400,'Invalid cursor') from None
            if order=='latest':
                statement=statement.where(or_(db.messages.c.ordinal<ordinal,and_(db.messages.c.ordinal==ordinal,db.messages.c.id<mid)))
            else:
                statement=statement.where(or_(db.messages.c.ordinal>ordinal,and_(db.messages.c.ordinal==ordinal,db.messages.c.id>mid)))
        columns=(db.messages.c.ordinal,db.messages.c.id)
        sorting=[col.desc() if order=='latest' else col.asc() for col in columns]
        with store.engine.connect() as c:
            rows=c.execute(statement.order_by(*sorting).limit(limit+1)).mappings().all()
        page=rows[:limit];following=None
        if len(rows)>limit:
            last=page[-1]
            following=base64.urlsafe_b64encode(json.dumps({'order':order,'session':sid,'ordinal':last['ordinal'],'id':last['id']}).encode()).decode()
        if order=='latest':page.reverse()
        return {'messages':[dict(x['data'],revision=x['revision'],deleted=x['deleted']) for x in page],
                'next_cursor':following,'sync':row['sync']}

    @r.post('/sessions/{sid}/commands',status_code=202)
    async def command(sid:str,request:Request,body:Command):
        uid=mutation(request)['user_id']; store=request.app.state.store
        row=store.own_session(uid,sid)
        validate_payload(body.operation,body.payload)
        old=store.one(db.commands,db.commands.c.request_id==body.request_id)
        if old:
            require(old['user_id']==uid,404)
            require(old['digest']==digest([sid,body.operation,body.payload]),409,'Request id has different payload')
            return receipt_public(old)
        require(request.app.state.connections.source_online(row),409,'Execution backend offline; draft remains local')
        cap=(row['capabilities'] or {}).get(body.operation,{})
        require(cap.get('status')=='supported',409,cap.get('reason','Operation unavailable'))
        for aid in body.payload.get('attachment_ids',[]):
            require(store.one(db.attachments,db.attachments.c.id==aid,db.attachments.c.session_id==sid),404)
        accepted,created=store.accept(uid,row,body.request_id,body.operation,body.payload)
        if created:
            await request.app.state.connections.dispatch(row,accepted)
        return receipt_public(store.one(db.commands,db.commands.c.request_id==body.request_id))

    @r.get('/commands/{rid}')
    async def receipt(rid:str,request:Request):
        uid=current(request)['user_id']; store=request.app.state.store
        row=store.one(db.commands,db.commands.c.request_id==rid,db.commands.c.user_id==uid)
        require(row)
        store.own_device(uid,row['device_id'])
        return receipt_public(row)

    @r.post('/sessions/{sid}/attachments')
    async def upload(sid:str,request:Request,file:UploadFile=File(...)):
        store=request.app.state.store; row=store.own_session(mutation(request)['user_id'],sid)
        require(row['capabilities'].get('attachments',{}).get('status')=='supported',409,'Attachment upload unavailable')
        content=await file.read(request.app.state.config.attachment_limit+1)
        return save_image(store,sid,file.filename,content)

    @r.get('/sessions/{sid}/attachments/{aid}')
    async def download(sid:str,aid:str,request:Request):
        store=request.app.state.store; store.own_session(current(request)['user_id'],sid)
        a=store.one(db.attachments,db.attachments.c.id==aid,db.attachments.c.session_id==sid)
        require(a)
        return Response(a['data'],media_type=a['mime'],headers={'Content-Disposition':'inline','X-Content-Type-Options':'nosniff'})

    @r.get('/bridge/attachments/{sid}/{aid}')
    async def bridge_attachment(sid:str,aid:str,request:Request):
        configured(request)
        auth=request.headers.get('authorization','')
        device=request.app.state.store.device(auth.removeprefix('Bearer ')) if auth.startswith('Bearer ') else None
        require(device,401,'Device authentication required')
        row=request.app.state.store.own_session(device['user_id'],sid)
        require(row['device_id']==device['id'],404)
        a=request.app.state.store.one(db.attachments,db.attachments.c.id==aid,db.attachments.c.session_id==sid)
        require(a)
        return Response(a['data'],media_type=a['mime'])

    @r.post('/bridge/attachments/{sid}')
    async def source_upload(sid:str,request:Request,file:UploadFile=File(...)):
        configured(request)
        auth=request.headers.get('authorization','')
        device=request.app.state.store.device(auth.removeprefix('Bearer ')) if auth.startswith('Bearer ') else None
        require(device,401,'Device authentication required')
        row=request.app.state.store.own_session(device['user_id'],sid)
        require(row['device_id']==device['id'],404)
        content=await file.read(request.app.state.config.attachment_limit+1)
        return save_image(request.app.state.store,sid,file.filename,content)

    @r.post('/bridge/snapshot')
    async def large_snapshot(request:Request,body:dict):
        configured(request)
        auth=request.headers.get('authorization','')
        device=request.app.state.store.device(auth.removeprefix('Bearer ')) if auth.startswith('Bearer ') else None
        require(device,401,'Device authentication required')
        connections=request.app.state.connections
        expected=connections.upload_leases.get(device['id'])
        require(expected and secrets.compare_digest(expected,request.headers.get('x-remote-bridge-lease','')),403,'Active Bridge upload lease required')
        require(body.get('type')=='snapshot' and len(body.get('messages',[]))<=500,400,'Invalid snapshot page')
        sid=request.app.state.store.snapshot(device,body)
        return {'type':'snapshot.ack','request_id':body.get('request_id'),'session_id':sid,
                'native_session_id':body['session']['native_session_id']}

    return r
