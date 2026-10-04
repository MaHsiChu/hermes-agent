from __future__ import annotations

import secrets
import threading
import time
from contextlib import contextmanager

from sqlalchemy import select, update, delete

from . import db
from .config import Source, source_key
from .security import digest, opaque, token, redact, require


class Store:
    def __init__(self, config):
        self.config = config
        self.engine = db.open_database(config.database_secret.read() if config.database_secret else config.database_url)
        db.migrate(self.engine)
        # One relay worker owns websocket routing; serialize SQLite read/modify/write too.
        self.lock = threading.RLock()
        with self.transaction() as c:
            c.execute(update(db.commands).where(db.commands.c.state.in_(["accepted", "dispatched", "received"])).values(state="delivery_uncertain", error="Relay restarted; reconcile PC receipt"))

    @contextmanager
    def transaction(self):
        with self.lock, self.engine.begin() as c:
            yield c

    def one(self, table, *conditions, conn=None):
        statement = select(table).where(*conditions)
        if conn is not None:
            return conn.execute(statement).mappings().first()
        with self.engine.connect() as c:
            return c.execute(statement).mappings().first()

    def login(self, issuer, subject, name):
        with self.transaction() as c:
            user = self.one(db.users, db.users.c.issuer == issuer, db.users.c.subject == subject, conn=c)
            uid = user['id'] if user else opaque()
            if not user:
                c.execute(db.users.insert().values(id=uid, issuer=issuer, subject=subject, name=name))
            raw, csrf = token(), token()
            c.execute(db.logins.insert().values(hash=digest(raw), user_id=uid, csrf=csrf,
                expires_at=time.time()+self.config.session_seconds))
        return raw, csrf, uid

    def web_user(self, raw):
        if not raw:
            return None
        with self.engine.connect() as c:
            return c.execute(select(db.logins, db.users.c.name).join(db.users).where(
                db.logins.c.hash == digest(raw), db.logins.c.expires_at > time.time())).mappings().first()

    def device(self, raw):
        return self.one(db.devices, db.devices.c.token_hash == digest(raw), db.devices.c.revoked == False)

    def own_device(self, uid, did):
        row = self.one(db.devices, db.devices.c.id == did, db.devices.c.user_id == uid, db.devices.c.revoked == False)
        require(row)
        return dict(row)

    def own_session(self, uid, sid):
        row = self.one(db.sessions, db.sessions.c.id == sid, db.sessions.c.deleted == False)
        require(row)
        self.own_device(uid, row['device_id'])
        return dict(row)

    def create_pairing(self, name, sources):
        sources = [Source.model_validate(s).model_dump() for s in sources]
        require(0 < len(sources) <= 32, 400, "Choose explicit sources")
        require(len({source_key(s) for s in sources}) == len(sources), 400, "Duplicate source")
        pid, raw = opaque(), token()
        code = secrets.token_hex(4).upper()
        with self.transaction() as c:
            c.execute(delete(db.pairings).where(db.pairings.c.expires_at<time.time()-86400))
            c.execute(db.pairings.insert().values(id=pid, device_hash=digest(raw), user_code=code,
                name=name, sources=sources, expires_at=time.time()+self.config.pairing_seconds))
        return {"pairing_id": pid, "device_code": raw, "user_code": code,
                "verification_uri": self.config.public_url + "/pair?pairing_id=" + pid,
                "expires_in": self.config.pairing_seconds}

    def pairing(self, pid, conn=None):
        row = self.one(db.pairings, db.pairings.c.id == pid, conn=conn)
        require(row)
        require(row['expires_at'] > time.time(), 410, "Pairing expired")
        return row

    def approve_pairing(self, uid, pid, code, allowed):
        with self.transaction() as c:
            p = self.pairing(pid, c)
            require(not p['claimed'] and not p['user_id'], 409, "Pairing already approved or claimed")
            require(secrets.compare_digest(p['user_code'], code), 403, "Incorrect user code")
            proposed = {source_key(s) for s in p['sources']}
            allowed = [Source.model_validate(s).model_dump() for s in allowed]
            require(allowed and {source_key(s) for s in allowed} <= proposed, 400, "Source was not proposed by PC")
            c.execute(update(db.pairings).where(db.pairings.c.id == pid).values(user_id=uid, approved_sources=allowed))

    def exchange(self, pid, raw):
        with self.transaction() as c:
            p = self.pairing(pid, c)
            require(secrets.compare_digest(p['device_hash'], digest(raw)), 403, "Invalid device code")
            require(not p['claimed'], 409, "Device code already claimed")
            if not p['user_id']:
                return {"status": "pending"}
            did, credential = opaque(), token()
            c.execute(db.devices.insert().values(id=did, user_id=p['user_id'], name=p['name'],
                token_hash=digest(credential), sources=p['approved_sources'], revoked=False, last_seen=0))
            c.execute(update(db.pairings).where(db.pairings.c.id == pid).values(claimed=True))
            return {"status": "approved", "device_id": did, "device_token": credential, "allowed_sources": p['approved_sources']}

    def snapshot(self, device, frame):
        source = Source.model_validate(frame['source']).model_dump()
        require(source_key(source) in {source_key(s) for s in device['sources']}, 403, "Source not paired")
        value = redact(frame['session'])
        native = str(value['native_session_id'])
        require(0 < len(native) <= 255, 400, "Invalid native identity")
        revision = int(value['revision'])
        sid = digest([device['id'], *[source[k] for k in ('backend_id','profile','engine')], native])
        with self.transaction() as c:
            old = self.one(db.sessions, db.sessions.c.id == sid, conn=c)
            fields = dict(device_id=device['id'], **source, native_session_id=native,
                title=value.get('title', native), archived=bool(value.get('archived')), deleted=bool(value.get('deleted')),
                revision=revision, updated_at=float(value['updated_at'] if value.get('updated_at') is not None else old['updated_at'] if old else 0), data=value,
                capabilities=value.get('capabilities', {}), sync=redact(frame.get('sync', {})),
                pending_requests=redact(frame.get('pending_requests', [])))
            if old and old['revision'] < revision:
                c.execute(update(db.sessions).where(db.sessions.c.id == sid).values(**fields))
            elif not old:
                c.execute(db.sessions.insert().values(id=sid, **fields))
            messages_changed = False
            for message in frame.get('messages', []):
                mid = str(message['id'])
                require(len(mid) <= 255, 400, "Message id too long")
                current = self.one(db.messages, db.messages.c.session_id == sid, db.messages.c.id == mid, conn=c)
                rev = int(message.get('revision', revision))
                if current and current['revision'] >= rev:
                    continue
                data = redact(message)
                values = dict(revision=rev, ordinal=float(message.get('ordinal', 0)), deleted=bool(message.get('deleted')), data=data)
                if current:
                    c.execute(update(db.messages).where(db.messages.c.session_id == sid, db.messages.c.id == mid).values(**values))
                else:
                    c.execute(db.messages.insert().values(session_id=sid, id=mid, **values))
                messages_changed = True
            self.event(sid, "session.updated", {"revision": revision, "messages_changed": messages_changed}, c)
        return sid

    def event(self, sid, kind, data, conn=None):
        if conn is None:
            with self.transaction() as c:
                return self.event(sid, kind, data, c)
        result = conn.execute(db.events.insert().values(session_id=sid, type=kind, data=redact(data), created_at=time.time()))
        return result.inserted_primary_key[0]

    def accept(self, uid, session, request_id, operation, payload):
        hashed = digest([session['id'], operation, payload])
        with self.transaction() as c:
            old = self.one(db.commands, db.commands.c.request_id == request_id, conn=c)
            if old:
                require(old['user_id'] == uid, 404)
                require(old['digest'] == hashed, 409, "Request id has different payload")
                return dict(old), False
            values = dict(request_id=request_id, user_id=uid, session_id=session['id'], device_id=session['device_id'],
                digest=hashed, operation=operation, payload=payload, state="accepted", created_at=time.time(),
                expires_at=time.time()+self.config.command_seconds)
            c.execute(db.commands.insert().values(**values))
            return values, True

    def receipt(self, device_id, frame):
        with self.transaction() as c:
            command = self.one(db.commands, db.commands.c.request_id == frame['request_id'], db.commands.c.device_id == device_id, conn=c)
            require(command, 404)
            require(command['digest'] == frame['digest'], 409, "Receipt payload mismatch")
            state = frame['state']
            allowed = {"received", "acknowledged", "completed", "failed", "delivery_uncertain", "response_submitted"}
            require(state in allowed, 400, "Invalid receipt state")
            terminal = {"completed", "failed"}
            if command['state'] in terminal:
                return
            if command['state'] in {'acknowledged','response_submitted'} and state not in terminal:
                return
            c.execute(update(db.commands).where(db.commands.c.request_id == frame['request_id']).values(
                state=state, result=redact(frame.get('result')), error=redact(frame.get('error'))))
            self.event(command['session_id'], "command.updated", {"request_id": command['request_id'], "state": state}, c)

    def disconnected(self, did):
        with self.transaction() as c:
            c.execute(update(db.commands).where(db.commands.c.device_id == did,
                db.commands.c.state.in_(["accepted", "dispatched", "received"])).values(
                    state="delivery_uncertain", error="Connection lost; execution must be reconciled"))
