"""PC-owned journal. A dispatch intent is committed before touching an execution API."""
import json
import sqlite3
import time
from contextlib import contextmanager

from .security import digest


class BridgeState:
    def __init__(self,path):
        self.path=str(path)
        with self.db() as c:
            c.executescript('''
                CREATE TABLE IF NOT EXISTS receipts(id TEXT PRIMARY KEY,digest TEXT,state TEXT,data TEXT);
                CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY,value TEXT);
                CREATE TABLE IF NOT EXISTS revisions(session TEXT,id TEXT,digest TEXT,revision INTEGER,data TEXT,seen TEXT,
                                                      PRIMARY KEY(session,id));
            ''')
            c.execute("UPDATE receipts SET state='delivery_uncertain' WHERE state='dispatching'")

    @contextmanager
    def db(self):
        c=sqlite3.connect(self.path,timeout=30); c.row_factory=sqlite3.Row
        try:
            c.execute('PRAGMA journal_mode=DELETE')
            with c:
                yield c
        finally:
            c.close()

    def get(self,rid):
        with self.db() as c:
            row=c.execute('SELECT * FROM receipts WHERE id=?',(rid,)).fetchone()
            return dict(json.loads(row['data']),request_id=rid,digest=row['digest'],state=row['state']) if row else None

    def begin(self,command):
        with self.db() as c:
            row=c.execute('SELECT * FROM receipts WHERE id=?',(command['request_id'],)).fetchone()
            if row:
                if row['digest']!=command['digest']:
                    raise ValueError('Request id payload differs')
            else:
                c.execute('INSERT INTO receipts VALUES(?,?,?,?)',(command['request_id'],command['digest'],'received','{}'))
        return self.get(command['request_id'])

    def mark(self,rid,state,**data):
        with self.db() as c:
            c.execute('UPDATE receipts SET state=?,data=? WHERE id=?',(state,json.dumps(data),rid))
        return self.get(rid)

    def receipts(self):
        with self.db() as c:
            ids=[r[0] for r in c.execute('SELECT id FROM receipts')]
        return [self.get(rid) for rid in ids]

    def read(self,key,default=None):
        with self.db() as c:
            row=c.execute('SELECT value FROM state WHERE key=?',(key,)).fetchone()
            return json.loads(row[0]) if row else default

    def write(self,key,value):
        with self.db() as c:
            c.execute('INSERT INTO state VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,json.dumps(value)))

    def next_revision(self):
        with self.db() as c:
            c.execute("INSERT INTO state VALUES('counter','0') ON CONFLICT(key) DO NOTHING")
            c.execute("UPDATE state SET value=CAST(CAST(value AS INTEGER)+1 AS TEXT) WHERE key='counter'")
            return int(c.execute("SELECT value FROM state WHERE key='counter'").fetchone()[0])

    def request_repair(self,local,reason):
        from .security import opaque
        self.write('repair:'+local,{'id':opaque(),'reason':reason})
        self.write('scan:'+local,None)

    def revise(self,session,rows,complete=False,scan=None):
        scan=scan or str(time.time_ns())
        changed=[]
        with self.db() as c:
            for data in rows:
                data=dict(data); mid=str(data['id']); hashed=digest(data)
                old=c.execute('SELECT * FROM revisions WHERE session=? AND id=?',(session,mid)).fetchone()
                revision=(old['revision']+1 if old else 1)
                if not old or old['digest']!=hashed:
                    changed.append(dict(data,id=mid,revision=revision))
                    c.execute('INSERT INTO revisions VALUES(?,?,?,?,?,?) ON CONFLICT(session,id) DO UPDATE SET digest=excluded.digest,revision=excluded.revision,data=excluded.data,seen=excluded.seen',
                              (session,mid,hashed,revision,json.dumps(data),scan))
                else:
                    c.execute('UPDATE revisions SET seen=? WHERE session=? AND id=?',(scan,session,mid))
            if complete:
                unseen=c.execute('SELECT * FROM revisions WHERE session=? AND seen!=?',(session,scan)).fetchall()
                for old in unseen:
                    previous=json.loads(old['data'])
                    if previous.get('deleted'):
                        continue
                    data={'id':old['id'],'ordinal':previous.get('ordinal',0),'deleted':True}
                    revision=old['revision']+1
                    changed.append(dict(data,revision=revision))
                    c.execute('UPDATE revisions SET digest=?,revision=?,data=? WHERE session=? AND id=?',
                              (digest(data),revision,json.dumps(data),session,old['id']))
        return changed

    def message_rows(self,session):
        with self.db() as c:
            return [dict(json.loads(r['data']),revision=r['revision']) for r in c.execute('SELECT * FROM revisions WHERE session=?',(session,))]
