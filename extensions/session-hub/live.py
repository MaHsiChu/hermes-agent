"""Durable App messaging jobs. Never fall back to a different CLI session."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import threading
import time
import uuid
from urllib.parse import urlencode
import codex_app
import claude_live
import attachments
from readers import SessionReaders,lines,text_blocks

ROOT=Path(__file__).resolve().parent
SETTINGS=json.loads((ROOT/'settings.json').read_text(encoding='utf-8'))
DATA=ROOT/'data'
READERS=SessionReaders(SETTINGS)
LOCK=threading.RLock()


@contextmanager
def db():
    conn=sqlite3.connect(DATA/'live.sqlite',timeout=10);conn.row_factory=sqlite3.Row
    try:
        with conn:yield conn
    finally:conn.close()


def initialize():
    with db() as c:
        c.execute('CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, request_key TEXT UNIQUE, digest TEXT, engine TEXT, session_id TEXT, spec TEXT, state TEXT, detail TEXT, receipt TEXT, baseline TEXT, answer TEXT, created REAL, updated REAL)')
        c.execute("UPDATE jobs SET state='delivery_uncertain',detail='Hub restarted while sending. Inspect the App before submitting again.' WHERE state='sending'")


def update(jid,**fields):
    fields['updated']=time.time()
    with db() as c:c.execute('UPDATE jobs SET '+','.join(k+'=?' for k in fields)+' WHERE id=?',[*fields.values(),jid])


def jobs():
    with db() as c:return [dict(r) for r in c.execute('SELECT * FROM jobs ORDER BY created DESC LIMIT 100')]


def app_sessions(engine=''):
    rows=[];errors=[]
    if engine in ('','codex'):
        try:
            result=codex_app.call('list_threads',{'limit':50})
            rows.extend({'engine':'codex','session_id':r['id'],'title':r['title'],'cwd':r.get('cwd',''),'host_id':r.get('hostId'),'status':r.get('status'),'origin':'codex-app','project_id':r.get('projectId')} for r in result.get('pinnedThreads',[])+result.get('threads',[]) if r.get('kind')=='codex')
            # App's recency catalog can omit newly created tasks until its
            # sidebar refreshes. Resolve our exact known IDs through App read.
            seen={r['session_id'] for r in rows}
            resolved=0
            for job in jobs():
                sid=job['session_id']
                if job['engine']!='codex' or not sid or sid in seen:continue
                if resolved>=10:break
                resolved+=1
                seen.add(sid)
                try:
                    t=codex_app.call('read_thread',{'threadId':sid,'turnLimit':1,'maxOutputCharsPerItem':0})['thread']
                    rows.insert(0,{'engine':'codex','session_id':sid,'title':t['title'],'cwd':t.get('cwd',''),'host_id':t.get('hostId','local'),'status':t.get('status',{}).get('type','unknown'),'origin':'codex-app'})
                except Exception:pass
        except Exception as e:errors.append('Codex App unavailable: '+short_error(e))
    if engine in ('','claude'):rows.extend(claude_live.sessions())
    return {'sessions':rows,'errors':errors}


def short_error(error):
    while isinstance(error,BaseExceptionGroup) and error.exceptions:error=error.exceptions[0]
    return str(error)[:1200]


def snapshot(sid,host='local',cursor=None):
    target={'threadId':sid,'hostId':host}
    if cursor:target['afterCursor']=cursor
    result=codex_app.call('wait_threads',{'targets':[target],'timeoutMs':0})
    if result.get('errors'):raise RuntimeError(str(result['errors']))
    if not result.get('polls'):raise RuntimeError('App returned no task snapshot')
    return result['polls'][0]


def submit(body):
    engine=body.get('engine');sid=body.get('session_id') or ''
    if engine not in ('codex','claude'):raise ValueError('Unknown App engine')
    message=body.get('prompt','')
    images=attachments.prepare(body)
    if not isinstance(message,str) or (not message.strip() and not images) or len(message)>20000:raise ValueError('App message must contain text or an image (text limit 20000 characters)')
    key=body.get('request_key')
    if not isinstance(key,str) or not key or len(key)>128:raise ValueError('A stable request_key is required')
    if engine=='claude' and not sid:raise ValueError('Open a Claude Desktop Code session first; GUI creation is not implemented by this transport.')
    if engine=='codex' and sid:
        binding=json.loads(codex_app.BINDING.read_text(encoding='utf-8'))
        if sid==binding['caller_thread_id']:raise ValueError('Sending into the control task itself is disabled; choose another App task.')
    target=body.get('target') or {'type':'projectless'}
    if not isinstance(target,dict):raise ValueError('App target must be an object')
    # Whitelist the payload. Model/permission overrides are deliberately absent.
    spec={'engine':engine,'session_id':sid,'prompt':message,'target':target,'host_id':body.get('host_id') or 'local'}
    if images:spec['attachments']=images;spec['delivery_prompt']=attachments.delivery_prompt(message,images)
    if body.get('title'): spec['title']=str(body['title']).strip()[:180]
    digest=hashlib.sha256(json.dumps(spec,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    with db() as c:
        old=c.execute('SELECT * FROM jobs WHERE request_key=?',(key,)).fetchone()
        if old:
            if old['digest']!=digest:raise ValueError('request_key already belongs to different App work')
            return dict(old)
        if engine=='claude':
            # Validate after the idempotency lookup: an accepted request still
            # resolves even after its original App process exits.
            claude_live.target(sid)
        jid=str(uuid.uuid4());now=time.time()
        c.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(jid,key,digest,engine,sid,json.dumps(spec,ensure_ascii=False),'queued','Awaiting App delivery','','','',now,now))
    return {'id':jid,'state':'queued','engine':engine,'session_id':sid,'transport':'app-live'}


def project_target(target):
    if target.get('type')=='projectless':return {'type':'projectless'}
    if target.get('type')!='project':raise ValueError('Only local saved-project or projectless App tasks are supported')
    result=codex_app.call('list_projects')
    # Keep the official project identity and environment rules.
    candidates=[]
    def visit(value):
        if isinstance(value,dict):
            if value.get('projectId')==target.get('projectId') or value.get('id')==target.get('projectId'):candidates.append(value)
            for child in value.values():visit(child)
        elif isinstance(value,list):
            for child in value:visit(child)
    visit(result)
    if len(candidates)!=1:raise ValueError('Select an exact saved project from hub_app_projects')
    project=candidates[0]
    environment=target.get('environment') or {'type':'worktree' if project.get('isGitRepository') else 'local'}
    if environment not in ({'type':'local'},{'type':'worktree'}):raise ValueError('Unsupported App environment request')
    return {'type':'project','projectId':target['projectId'],'environment':environment}


def deliver(job):
    with db() as c:claimed=c.execute("UPDATE jobs SET state='sending' WHERE id=? AND state='queued'",(job['id'],)).rowcount
    if not claimed:return
    spec=json.loads(job['spec']);sid=spec['session_id'];host=spec['host_id']
    try:
        if job['engine']=='codex':
            before={}
            if sid:
                before=snapshot(sid,host)
                update(job['id'],baseline=json.dumps(before))
                receipt=codex_app.call('send_message_to_thread',{'threadId':sid,'hostId':host,'prompt':spec.get('delivery_prompt',spec['prompt'])})
            else:
                target=project_target(spec['target'])
                receipt=codex_app.call('create_thread',{'target':target,'prompt':spec['prompt'],**({'title':spec['title']} if spec.get('title') else {})})
                sid=receipt.get('threadId','')
                host=receipt.get('hostId','local');spec['host_id']=host
                if not sid:
                    update(job['id'],state='needs_attention',detail='App is setting up the task. Receipt contains clientThreadId; do not use it as threadId.',receipt=json.dumps(receipt))
                    return
            # Snapshot after acceptance binds completion to the actual turn.
            accepted=snapshot(sid,host)
            baseline={'accepted_turn':(accepted.get('latestTurn') or {}).get('id'),'cursor':accepted.get('cursor'),'before_turn':(before.get('latestTurn') or {}).get('id'),'before_active':(before.get('latestTurn') or {}).get('status')=='inProgress'}
            update(job['id'],session_id=sid,state='delivered',detail='Accepted by Codex App; monitoring its original task.',receipt=json.dumps(receipt),baseline=json.dumps(baseline),spec=json.dumps(spec))
        else:
            try:peer=claude_live.target(sid)
            except ValueError as e:
                update(job['id'],state='needs_attention',detail=str(e));return
            sid=peer['session_id']
            with LOCK:before=READERS.read('claude',sid,1)
            baseline={'marker':before['completion_marker'],'offset':Path(before['path']).stat().st_size}
            update(job['id'],session_id=sid,baseline=json.dumps(baseline))
            receipt=claude_live.send(sid,spec.get('delivery_prompt',spec['prompt']),job['id'])
            receipts=receipt.get('receipts',[])
            if not receipt.get('guard_claimed') or not receipt.get('message_id') or not receipts or any(r.get('is_error') for r in receipts):
                update(job['id'],state='needs_attention',detail='Claude did not confirm a permitted send. Inspect delivery receipt.',receipt=json.dumps(receipt,ensure_ascii=False));return
            baseline['message_id']=receipt['message_id']
            update(job['id'],state='delivered',baseline=json.dumps(baseline),detail='Claude queued this message ID. Awaiting confirmed receipt and completion in the target transcript.',receipt=json.dumps(receipt,ensure_ascii=False))
    except Exception as e:
        # A timeout may follow a successful send. Never blindly retry.
        update(job['id'],state='delivery_uncertain',detail=short_error(e))


def claude_progress(path,message_id,checkpoint=None,complete_lines=True):
    """Incremental receipt correlation, independent of history tail size."""
    state=dict(checkpoint or {});state.setdefault('offset',0)
    if not message_id:return state
    with Path(path).open('rb') as stream:
        if Path(path).stat().st_size<state['offset']:
            state={'offset':0}  # Never reuse receipt state after truncation.
        stream.seek(state['offset']);start=stream.tell()
        while stream.tell()-start<8_000_000:
            line=stream.readline()
            if not line or (complete_lines and not line.endswith(b'\n')):break
            state['offset']=stream.tell()
            try:row=json.loads(line)
            except (ValueError,UnicodeDecodeError):continue
            if not isinstance(row,dict):continue
            if (row.get('origin') or {}).get('msg_id')==message_id:state['received']=True
            if not state.get('received'):continue
            if row.get('type')=='assistant':
                message=row.get('message') or {}
                answer=text_blocks(message.get('content'))
                if answer:state['answer']=answer
                if message.get('stop_reason') in ('end_turn','stop_sequence'):state['completed']=True
            if row.get('type')=='system' and row.get('subtype')=='turn_duration':state['completed']=True
            if state.get('completed'):break
    return state


def claude_completion(path,message_id):
    state=claude_progress(path,message_id,complete_lines=False)
    return bool(state.get('completed')),state.get('answer','') if state.get('completed') else ''


def poll(job,emit):
    if time.time()-job['created']>SETTINGS['job_timeout_seconds']:
        update(job['id'],state='needs_attention',detail='No verified completion within monitoring window. App work is not interrupted; inspect it before resending.');return
    spec=json.loads(job['spec']);baseline=json.loads(job['baseline'] or '{}')
    if job['engine']=='codex':
        state=snapshot(job['session_id'],spec['host_id'])
        turn=state.get('latestTurn') or {};status=turn.get('status')
        if status=='inProgress':update(job['id'],state='running',detail='Codex App is working on the original task.');return
        if status not in ('completed','interrupted','failed'):return
        if turn.get('id')==baseline.get('before_turn') and not baseline.get('before_active'):return
        # A matching accepted turn or a later turn can satisfy a live delivery.
        if not turn.get('id'):return
        message=state.get('latestAssistantMessage') or {}
        answer=message.get('text','') if message.get('turnId')==turn['id'] else ''
        outcome='completed' if status=='completed' else 'needs_attention'
    else:
        with LOCK:state=READERS.resolve('claude',job['session_id'])
        progress=claude_progress(state['path'],baseline.get('message_id'),baseline)
        update(job['id'],baseline=json.dumps(progress),**({'state':'running','detail':'Claude consumed the message in the original session; awaiting completion.'} if progress.get('received') else {}))
        if not progress.get('completed'):return
        answer=progress.get('answer','')
        outcome='completed'
    update(job['id'],state=outcome,answer=answer,detail='App finished a turn after delivery; inspect its answer for task correctness.')
    emit('app:'+job['id'],'app_'+outcome,job['engine'],job['session_id'],answer or outcome,job['id'])


def worker(stop,emit):
    # Recover a crash between saving the terminal job and writing the inbox
    # (the inbox deduplicates this same event key).
    with db() as c:finished=[dict(r) for r in c.execute("SELECT * FROM jobs WHERE state='completed'")]
    for job in finished:emit('app:'+job['id'],'app_completed',job['engine'],job['session_id'],job['answer'] or 'completed',job['id'])
    while not stop.is_set():
        with db() as c:pending=[dict(r) for r in c.execute("SELECT * FROM jobs WHERE state IN ('queued','delivered','running') ORDER BY created")]
        for job in pending:
            if stop.is_set():return
            if job['state']=='queued':deliver(job)
            elif job['state'] in ('delivered','running'):
                try:poll(job,emit)
                except Exception as e:update(job['id'],detail='Monitoring temporarily unavailable: '+short_error(e))
        stop.wait(5)


def enrich_transcript(page):
    """Restore upload thumbnails only for an exact recorded delivery we own."""
    with db() as c:
        specs=[json.loads(r[0]) for r in c.execute('SELECT spec FROM jobs WHERE engine=? AND session_id=?', (page['engine'],page['session_id']))]
    sent={s.get('delivery_prompt',s['prompt']).strip():s for s in specs if s.get('delivery_prompt',s['prompt']).strip()}
    for item in page['items']:
        if item['role'] not in ('user','peer'):continue
        text='\n'.join(b.get('text','') for b in item['blocks'] if b['type']=='text').strip()
        spec=sent.get(text)
        if not spec:continue
        item['local_input']=True
        item['blocks']=([{'type':'text','text':spec['prompt']}] if spec['prompt'] else [])+[
            {'type':'attachment','kind':'image','data':{'attachment_id':a['id'],'name':a['name'],'thumbnail':a['thumbnail']}} for a in spec.get('attachments',[])]
    return page

def rpc(op,body):
    if op=='app_upload_image':return attachments.upload(body)
    if op=='app_attachment':return attachments.read(body)
    if op=='app_sessions':return app_sessions(body.get('engine',''))
    if op=='app_projects':return codex_app.call('list_projects')
    if op=='app_dispatch':return submit(body)
    if op=='app_jobs':return {'jobs':jobs()}
    if op=='app_open':
        if body.get('engine')=='claude':
            with LOCK:session=READERS.resolve('claude',body['session_id'])
            app_id=session.get('app_session_id')
            if not app_id or not app_id.startswith('local_'):
                raise ValueError('This Claude history has no Desktop session; open/import it in Claude first.')
            app_id='local_'+str(uuid.UUID(app_id[6:]))
            if os.name!='nt':raise ValueError('Claude App opening is currently available on Windows.')
            os.startfile('claude://code/continue?'+urlencode({'session':app_id}))
            # The OS acknowledges the link, not the App's final navigation.
            return {'requested':True,'navigated':False,'engine':'claude','session_id':session['session_id'],'app_session_id':app_id}
        # Only a validated task identity can reach the fixed native protocol;
        # callers cannot supply arbitrary URLs or shell commands here.
        sid=str(uuid.UUID(body['session_id']))
        result=codex_app.call('navigate_to_codex_page',{'threadId':sid})
        if result.get('navigated') is not True: raise ValueError('Codex did not confirm navigation')
        activated=False
        if os.name=='nt':
            try:
                os.startfile('codex://threads/'+sid)
                activated=True
            except OSError:
                pass  # Task is selected; UI asks the user to switch windows.
        return {**result,'activated':activated}
    if op=='app_prepare_claude':
        prompt=body.get('prompt','')
        if not isinstance(prompt,str) or not prompt.strip() or len(prompt.encode('utf-16-le'))//2>12000:
            raise ValueError('Claude draft must contain 1–12000 characters.')
        if os.name!='nt':raise ValueError('Claude draft opening is currently available on Windows.')
        # Official deep link only prefills. No fabricated task or completion.
        url='claude://code/new?'+urlencode({'q':prompt})
        if len(url)>28000:raise ValueError('Claude draft is too long for the Windows link; shorten it before opening.')
        os.startfile(url)
        return {'requested':True,'state':'draft','requires_send':True}
    if op=='app_read':
        if body['engine']=='codex':return codex_app.call('read_thread',{'threadId':body['session_id'],'hostId':body.get('host_id') or 'local','turnLimit':3,'includeOutputs':False})
        with LOCK:return READERS.read('claude',body['session_id'],20)
    raise ValueError('Unknown App operation')
