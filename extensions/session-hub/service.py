"""Session Hub sidecar: durable jobs, native session access and completion inbox."""
from __future__ import annotations
from contextlib import asynccontextmanager, contextmanager
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
import threading
import time
import uuid
import psutil

from fastapi import FastAPI, HTTPException, Request
import uvicorn
from readers import SessionReaders
from transcript import TranscriptStore
import live
from board import TaskBoard, initialize as initialize_board

ROOT=Path(__file__).resolve().parent
SETTINGS=json.loads((ROOT/'settings.json').read_text(encoding='utf-8'))
DATA=ROOT/'data'
DATA.mkdir(exist_ok=True)
TOKEN_FILE=DATA/'token'
try:
    with TOKEN_FILE.open('x',encoding='ascii') as f: f.write(secrets.token_urlsafe(32))
except FileExistsError: pass
TOKEN=TOKEN_FILE.read_text(encoding='ascii')
READERS=SessionReaders(SETTINGS)
TRANSCRIPTS=TranscriptStore(READERS,DATA/'transcripts.sqlite')
STOP=threading.Event()
READ_LOCK=threading.RLock()


@contextmanager
def db():
    c=sqlite3.connect(DATA/'hub.sqlite',timeout=10)
    c.row_factory=sqlite3.Row
    try:
        with c: yield c
    finally: c.close()


def initialize():
    initialize_board(db)
    with db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, request_key TEXT UNIQUE, engine TEXT, session_id TEXT, cwd TEXT, prompt TEXT, mode TEXT, state TEXT, detail TEXT, answer TEXT, created REAL, updated REAL, pid INTEGER, request_hash TEXT);
        CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT, event_key TEXT UNIQUE, kind TEXT, engine TEXT, session_id TEXT, job_id TEXT, text TEXT, created REAL);
        CREATE TABLE IF NOT EXISTS watches(engine TEXT, session_id TEXT, marker TEXT, enabled INTEGER, PRIMARY KEY(engine,session_id));
        ''')
        # Never re-run a possibly completed process after a crash.
        c.execute("UPDATE jobs SET state='needs_attention',detail='Hub restarted during execution; inspect the native session before resubmitting',updated=? WHERE state IN ('running','checking')",(time.time(),))


def event(key,kind,engine,sid,text,job_id=None):
    with db() as c:
        c.execute('INSERT OR IGNORE INTO events(event_key,kind,engine,session_id,job_id,text,created) VALUES(?,?,?,?,?,?,?)',(key,kind,engine,sid,job_id,text[:16000],time.time()))


def update_job(jid, **values):
    values['updated']=time.time()
    with db() as c:
        c.execute('UPDATE jobs SET '+','.join(k+'=?' for k in values)+' WHERE id=?',[*values.values(),jid])


def native_busy(engine,sid):
    if not sid: return ''
    with READ_LOCK: state=READERS.read(engine,sid,1)
    if engine=='codex' and state['writer_owned'] is not False:
        return 'Codex App/another process owns this session. Close/unload it there to hand it off; history is not copied.'
    if state['status'] not in ('completed','interrupted'):
        return 'Native session is running or has no reliable end marker; waiting for a confirmed handoff.'
    if engine=='claude':
        try:
            p=subprocess.run([SETTINGS['claude_binary'],'agents','--json'],capture_output=True,text=True,encoding='utf-8',timeout=10,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            if p.returncode: return 'Claude live-session inventory unavailable; waiting for handoff.'
            agents=json.loads(p.stdout)
            if any(sid in json.dumps(a) for a in agents):
                return 'Claude still owns the session; close it before CLI handoff. Live SendMessage is a separate capability.'
        except (ValueError,subprocess.TimeoutExpired,OSError):
            return 'Unable to verify Claude session ownership; waiting for handoff.'
        # Some Desktop SDK sessions are absent from `agents --json`. A live
        # CLI process using this ID is still an owner. Unknown SDK ownership
        # is conservatively held instead of trusting filesystem inactivity.
        for process in psutil.process_iter(['pid','exe','cmdline']):
            try:
                exe=(process.info['exe'] or '').lower()
                if not exe.endswith('claude.exe') or 'anthropicclaude' in exe: continue
                argv=process.info['cmdline'] or []
                if sid in argv: return 'A live Claude Code process owns this session; close it before handoff.'
                if '--sdk-url' in argv and not any(a in argv for a in ('--resume','--session-id')):
                    return 'A Claude Desktop SDK process has unidentified session ownership; automatic handoff is held.'
            except (psutil.NoSuchProcess,psutil.AccessDenied): continue
    return ''


def command(job):
    if job['engine']=='codex':
        cmd=[SETTINGS['codex_binary'],'exec','--sandbox',job['mode'],'-c','windows.sandbox="unelevated"']
        if job['session_id']: cmd+=['resume',job['session_id']]
        cmd+=['--ignore-user-config','--skip-git-repo-check','--json','-c','approval_policy="never"']
        if not job['session_id']: cmd+=['-m','gpt-5.5','-c','model_reasoning_effort="low"']
        cmd+=['-']
    else:
        cmd=[SETTINGS['claude_binary'],'-p','--output-format','stream-json','--verbose','--permission-mode','plan' if job['mode']=='read-only' else 'acceptEdits','--permission-prompts','none','--strict-mcp-config','--setting-sources','']
        if job['session_id']: cmd+=['--resume',job['session_id']]
        else: cmd+=['--name',f'Hermes Hub {job["id"][:8]}']
    return cmd


def run_job(job):
    with db() as c:
        claim=c.execute("UPDATE jobs SET state='checking',updated=? WHERE id=? AND state IN ('queued','waiting_handoff')",(time.time(),job['id']))
    if claim.rowcount!=1: return
    reason=native_busy(job['engine'],job['session_id'])
    if reason:
        update_job(job['id'],state='waiting_handoff',detail=reason)
        return
    update_job(job['id'],state='running',detail='Native CLI is executing; completion will be delivered to the inbox')
    log=DATA/f'{job["id"]}.jsonl'
    err=DATA/f'{job["id"]}.stderr.log'
    env=dict(os.environ,PYTHONUTF8='1',PYTHONIOENCODING='utf-8')
    env.pop('CLAUDECODE',None)
    sid=job['session_id']; answers=[]; completed=False; failed=False; denial=False
    # Dedicated pipes stream session IDs and progress before task completion.
    with err.open('w',encoding='utf-8') as errors, log.open('w',encoding='utf-8') as transcript:
        p=subprocess.Popen(command(job),cwd=job['cwd'],env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=errors,text=True,encoding='utf-8',errors='replace',creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        update_job(job['id'],pid=p.pid)
        timed_out=threading.Event()
        def timeout():
            timed_out.set()
            if p.poll() is None:
                subprocess.run(['taskkill','/PID',str(p.pid),'/T','/F'],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW) if os.name=='nt' else p.kill()
        timer=threading.Timer(SETTINGS['job_timeout_seconds'],timeout); timer.daemon=True; timer.start()
        try:
            p.stdin.write(job['prompt']); p.stdin.close()
            for line in p.stdout:
                transcript.write(line); transcript.flush()
                try: row=json.loads(line)
                except ValueError: continue
                if row.get('session_id'): sid=row['session_id']
                if row.get('type')=='thread.started': sid=row['thread_id']
                if sid and sid!=job['session_id']:
                    update_job(job['id'],session_id=sid)
                    job['session_id']=sid
                if row.get('type')=='item.completed' and row.get('item',{}).get('type')=='agent_message': answers.append(row['item'].get('text',''))
                if row.get('type')=='turn.completed': completed=True
                if row.get('type') in ('turn.failed','error'): failed=True
                if row.get('type')=='item.completed' and row.get('item',{}).get('type')=='file_change' and row['item'].get('status')=='failed': denial=True
                if row.get('type')=='result':
                    completed=not row.get('is_error',False); failed=bool(row.get('is_error'))
                    denial=denial or bool(row.get('permission_denials'))
                    answers=[row.get('result','')]
            rc=p.wait(timeout=10)
        finally: timer.cancel()
    answer='\n'.join(answers)
    outcome='completed' if completed and not failed and rc==0 else 'failed'
    if denial: outcome='needs_attention'
    detail='Turn completed; task correctness is described in the result, not inferred from exit code.' if outcome=='completed' else ('Tool permission needs attention' if denial else err.read_text(encoding='utf-8',errors='replace')[-2500:])
    if timed_out.is_set(): outcome='timed_out'; detail='Job exceeded its configured time limit and was stopped.'
    update_job(job['id'],state=outcome,detail=detail,answer=answer,pid=None)
    with READ_LOCK: READERS.sessions(refresh=True)
    event(f'job:{job["id"]}',outcome,job['engine'],sid,answer or detail,job['id'])


def worker():
    while not STOP.is_set():
        with db() as c:
            jobs=[dict(r) for r in c.execute("SELECT * FROM jobs WHERE state IN ('queued','waiting_handoff') ORDER BY created")]
        for job in jobs:
            if STOP.is_set(): break
            try: run_job(job)
            except Exception as exc:
                update_job(job['id'],state='failed',detail=str(exc),pid=None)
                event(f'job:{job["id"]}','failed',job['engine'],job['session_id'],str(exc),job['id'])
        STOP.wait(SETTINGS['poll_seconds'])


def monitor():
    while not STOP.wait(SETTINGS['poll_seconds']):
        with db() as c: watches=[dict(r) for r in c.execute('SELECT * FROM watches WHERE enabled=1')]
        for w in watches:
            try:
                with READ_LOCK: s=READERS.read(w['engine'],w['session_id'],3)
                marker=s['completion_marker']
                if s['status']=='completed' and marker and marker!=w['marker']:
                    event(f'watch:{w["engine"]}:{w["session_id"]}:{marker}','external_turn_completed',w['engine'],w['session_id'],s['last_answer'] or 'Native session finished a turn.')
                    with db() as c: c.execute('UPDATE watches SET marker=? WHERE engine=? AND session_id=?',(marker,w['engine'],w['session_id']))
            except (OSError,ValueError,sqlite3.Error): continue


def dispatch(body):
    engine=body.get('engine'); sid=body.get('session_id') or None
    if engine not in ('claude','codex'): raise ValueError('Unknown engine')
    mode=body.get('mode','read-only')
    if mode not in ('read-only','workspace-write'): raise ValueError('Unknown mode')
    prompt=body.get('prompt','')
    if not isinstance(prompt,str) or not prompt.strip() or len(prompt)>60000: raise ValueError('Prompt must contain 1-60000 characters')
    if sid:
        with READ_LOCK: s=READERS.resolve(engine,sid)
        sid=s['session_id']; cwd=s['cwd']
    else: cwd=body.get('cwd') or SETTINGS['default_workspace']
    path=Path(cwd)
    if not path.is_absolute() or not path.is_dir(): raise ValueError('Workspace must be an existing absolute local directory')
    jid=str(uuid.uuid4()); now=time.time()
    request_key=body.get('request_key') or jid
    if not isinstance(request_key,str) or len(request_key)>128: raise ValueError('Invalid request key')
    digest=hashlib.sha256(json.dumps([engine,sid,str(path.resolve()),prompt,mode]).encode()).hexdigest()
    with db() as c:
        old=c.execute('SELECT * FROM jobs WHERE request_key=?',(request_key,)).fetchone()
        if old:
            if old['request_hash']!=digest: raise ValueError('Idempotency key already used with different arguments')
            return dict(old)
        c.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(jid,request_key,engine,sid,str(path.resolve()),prompt,mode,'queued','Awaiting worker','',now,now,None,digest))
    return {'id':jid,'state':'queued','engine':engine,'session_id':sid,'cwd':str(path.resolve()),'mode':mode}


BOARD=TaskBoard(READERS,live,db,READ_LOCK)


def rpc(op,body):
    if op=='board': return BOARD.snapshot(background=True)
    if op=='task': return BOARD.get(body['key'])
    if op=='task_read': return BOARD.mark_read(body['key'],body['revision'])
    if op=='task_closed': return BOARD.set_closed(body['key'],body['closed'])
    if op=='task_create': return BOARD.create(body,dispatch)
    if op.startswith('app_'):return live.rpc(op,body)
    if op=='health': return {'ok':True,'version':'0.4.4','pid':os.getpid(),'transports':['native-cli-handoff','codex-app-tools-mcp','claude-official-peer-messaging','native-transcript-pages','task-board','task-closures','local-image-attachments','claude-desktop-session-composer']}
    if op=='transcript':
        with READ_LOCK:
            return live.enrich_transcript(TRANSCRIPTS.page(body['engine'],body['session_id'],body.get('cursor',''),body.get('limit',40),body.get('since'),body.get('generation')))
    if op=='transcript_document':
        with READ_LOCK:
            return TRANSCRIPTS.document(body['engine'],body['session_id'],body['item_id'],body['href'])
    if op=='transcript_asset':
        with READ_LOCK:
            return TRANSCRIPTS.asset(body['engine'],body['session_id'],body['item_id'],body['asset_path'])
    if op=='sessions':
        with READ_LOCK: return READERS.sessions(body.get('engine',''),body.get('query',''),int(body.get('limit',50)),body.get('refresh',False))
    if op=='read':
        with READ_LOCK: return READERS.read(body['engine'],body['session_id'],int(body.get('limit',20)))
    if op=='dispatch': return dispatch(body)
    if op=='jobs':
        with db() as c:
            rows=c.execute('SELECT * FROM jobs WHERE id=?',(body['job_id'],)).fetchall() if body.get('job_id') else c.execute('SELECT * FROM jobs ORDER BY created DESC LIMIT 50').fetchall()
        return {'jobs':[dict(r) for r in rows]}
    if op=='cancel':
        with db() as c:
            cur=c.execute("UPDATE jobs SET state='cancelled',updated=? WHERE id=? AND state IN ('queued','waiting_handoff')",(time.time(),body['job_id']))
        return {'cancelled':cur.rowcount==1,'note':'Only queued jobs can be cancelled here; no unrelated native process is interrupted.'}
    if op=='watch':
        with READ_LOCK: s=READERS.read(body['engine'],body['session_id'],1)
        with db() as c: c.execute('INSERT OR REPLACE INTO watches VALUES(?,?,?,?)',(s['engine'],s['session_id'],s['completion_marker'],int(body.get('enabled',True))))
        return {'watching':body.get('enabled',True),'session_id':s['session_id'],'baseline':s['completion_marker']}
    if op=='events':
        with db() as c:
            if body.get('recent'):
                rows=list(reversed([dict(r) for r in c.execute('SELECT * FROM events ORDER BY seq DESC LIMIT 100')]))
            else:
                rows=[dict(r) for r in c.execute('SELECT * FROM events WHERE seq>? ORDER BY seq LIMIT 100',(int(body.get('after',0)),))]
            total=c.execute('SELECT coalesce(max(seq),0) FROM events').fetchone()[0]
        return {'events':rows,'cursor':rows[-1]['seq'] if rows else int(body.get('after',0)),'latest':total}
    raise ValueError('Unknown operation')


@asynccontextmanager
async def lifespan(app):
    initialize()
    live.initialize()
    threading.Thread(target=live.worker,args=(STOP,event),daemon=True).start()
    for target in (worker,monitor): threading.Thread(target=target,daemon=True).start()
    yield
    STOP.set()


app=FastAPI(lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)


@app.post('/rpc/{op}')
def endpoint(op:str,body:dict,request:Request):
    if not secrets.compare_digest(request.headers.get('authorization',''),'Bearer '+TOKEN): raise HTTPException(401,'Local authorization required')
    try: return rpc(op,body)
    except (ValueError,KeyError) as exc: raise HTTPException(400,str(exc))


if __name__=='__main__':
    uvicorn.run(app,host='127.0.0.1',port=SETTINGS['port'],log_level='warning',access_log=False)
