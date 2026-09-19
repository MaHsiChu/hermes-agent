"""Read-only native session adapters. Never write foreign history or state DBs."""
from __future__ import annotations
import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return {}


def canonical_native_path(value):
    # Windows extended-length names and ordinary drive/UNC names identify the
    # same store. Normalize both before the resolved containment check; never
    # relax the check or follow a rollout outside the configured Codex home.
    text = str(value)
    if os.name == 'nt':
        if text.startswith('\\\\?\\UNC\\'):
            text = '\\\\' + text[8:]
        elif text.startswith('\\\\?\\'):
            text = text[4:]
    return Path(text).resolve()


@contextmanager
def readonly(path):
    conn = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=2)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA query_only=ON')
    try: yield conn
    finally: conn.close()


def lines(path, tail_bytes=2_000_000):
    """A bounded tail; discard a partial first row and tolerate a live partial last row."""
    try:
        with Path(path).open('rb') as f:
            f.seek(0, 2)
            size = f.tell()
            start = max(0, size-tail_bytes)
            f.seek(start)
            if start:
                f.readline()
            for line in f:
                try:
                    obj = json.loads(line)
                    if isinstance(obj, dict):
                        yield obj
                except (ValueError, UnicodeDecodeError):
                    continue
    except OSError:
        return


def text_blocks(content):
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ''
    return '\n'.join(b.get('text', '') for b in content if isinstance(b, dict) and b.get('type') in ('text','input_text','output_text'))


class SessionReaders:
    def __init__(self, settings):
        self.settings = settings
        self.codex = Path(settings['codex_home'])
        self.claude = Path(settings['claude_home'])
        self.desktop = Path(settings['claude_desktop_home'])
        self._cache = []
        self._at = 0

    def sessions(self, engine='', query='', limit=50, refresh=False):
        if refresh or time.monotonic()-self._at > 10:
            items = []
            errors = []
            for source in (self.codex_sessions, self.claude_sessions):
                try:
                    items.extend(source())
                except (OSError, sqlite3.Error, ValueError) as exc:
                    errors.append(f'{source.__name__}: {exc}')
            self._cache = sorted(items, key=lambda s:s['updated_at'], reverse=True)
            self._errors = errors
            self._at = time.monotonic()
        matching = [s for s in self._cache if (not engine or s['engine']==engine) and (not query or query.lower() in (s['title']+' '+s['cwd']+' '+s['session_id']).lower())]
        return {'sessions': matching[:max(1,min(limit,200))], 'total':len(matching), 'errors':self._errors}

    def codex_sessions(self, exact_id=None):
        with readonly(self.codex/'state_5.sqlite') as db:
            query='SELECT id,rollout_path,cwd,title,name,updated_at,archived,source,history_mode FROM threads WHERE '
            rows = db.execute(query+('id=?' if exact_id else 'archived=0 ORDER BY updated_at DESC'),(exact_id,) if exact_id else ()).fetchall()
        result = []
        for r in rows:
            path=canonical_native_path(r['rollout_path'])
            # Never follow a foreign DB path outside its own store.
            if not path.is_relative_to(canonical_native_path(self.codex)):
                continue
            result.append({'engine':'codex','session_id':r['id'],'title':r['name'] or r['title'] or r['id'],'cwd':r['cwd'],'updated_at':r['updated_at'],'path':str(path),'origin':r['source'],'app_session_id':r['id'],'history_mode':r['history_mode']})
        return result

    def claude_sessions(self):
        desktop={}
        for path in self.desktop.rglob('local_*.json') if self.desktop.exists() else []:
            obj=read_json(path)
            if obj.get('cliSessionId'):
                desktop[obj['cliSessionId']]=obj
        result=[]
        root=self.claude/'projects'
        for path in root.glob('*/*.jsonl'):
            if not path.resolve().is_relative_to(root.resolve()):
                continue
            sid=path.stem
            meta=desktop.get(sid,{})
            cwd=meta.get('cwd','')
            title=meta.get('title','')
            # Read a bounded head for project/session title; full transcript stays on demand.
            with path.open('r',encoding='utf-8',errors='replace') as f:
                for _ in range(35):
                    line=f.readline(120000)
                    if not line: break
                    try: row=json.loads(line)
                    except ValueError: continue
                    cwd=cwd or row.get('cwd','')
                    if not title and row.get('type')=='user':
                        title=text_blocks(row.get('message',{}).get('content',''))[:180]
                    if cwd and title: break
            result.append({'engine':'claude','session_id':sid,'title':title or sid,'cwd':cwd,'updated_at':path.stat().st_mtime,'path':str(path),'origin':'claude-desktop' if meta else 'claude-code','app_session_id':meta.get('sessionId')})
        return result

    def resolve(self, engine, session_id, refresh_missing=True):
        if engine not in ('codex','claude'):
            raise ValueError('engine must be codex or claude')
        self.sessions()
        found=next((s for s in self._cache if s['engine']==engine and session_id in (s['session_id'],s.get('app_session_id'))),None)
        if not found and refresh_missing:
            self.sessions(refresh=True)
            found=next((s for s in self._cache if s['engine']==engine and session_id in (s['session_id'],s.get('app_session_id'))),None)
        if not found and engine=='codex' and refresh_missing:
            exact=self.codex_sessions(session_id)
            if exact:found=exact[0]
        if not found: raise ValueError('Session not found in the local store; cloud-only sessions are not supported')
        return dict(found)

    def codex_owned(self, sid):
        path=self.codex/'thread-writer-locks'/f'{sid}.lock'
        if not path.exists(): return False
        try:
            with path.open('rb') as f:
                f.read(1)
            return False
        except PermissionError:
            return True
        except OSError:
            return None

    def read(self, engine, session_id, limit=20, refresh_missing=True):
        s=self.resolve(engine,session_id,refresh_missing=refresh_missing)
        messages=[]; activity=[]; status='unknown'; completion=None
        limit=max(1,min(limit,100))
        # Rollouts retain live event markers even with normalized history.
        for row in lines(s['path']):
            typ=row.get('type'); p=row.get('payload') or {}
            if engine=='codex':
                if typ=='event_msg':
                    event=p.get('type')
                    if event in ('task_started','turn_started'): status='running'; completion=None
                    elif event in ('task_complete','task_completed','turn_complete'):
                        status='completed'; completion=str(row.get('timestamp',''))+str(p.get('turn_id',''))
                    elif event in ('turn_aborted','task_aborted'): status='interrupted'; completion=None
                if typ=='response_item' and p.get('type')=='message' and p.get('role') in ('user','assistant'):
                    text=text_blocks(p.get('content'))
                    if text: messages.append({'role':p['role'],'text':text[:18000]})
                elif typ=='response_item' and p.get('type') in ('function_call','custom_tool_call'):
                    activity.append({'tool':p.get('name','tool'),'at':row.get('timestamp')})
            else:
                if typ in ('user','assistant'):
                    msg=row.get('message',{})
                    text=text_blocks(msg.get('content'))
                    if text: messages.append({'role':typ,'text':text[:18000]})
                    if typ=='user': status='running'; completion=None
                    else:
                        blocks=msg.get('content',[])
                        if isinstance(blocks,list):
                            activity.extend({'tool':b.get('name'),'at':row.get('timestamp')} for b in blocks if isinstance(b,dict) and b.get('type')=='tool_use')
                        if msg.get('stop_reason') in ('end_turn','stop_sequence'):
                            status='completed'; completion=row.get('uuid') or row.get('timestamp')
                if typ=='system' and row.get('subtype')=='turn_duration':
                    status='completed'; completion=row.get('uuid') or row.get('timestamp')
        if engine=='codex' and s.get('history_mode')!='legacy':
            try:
                with readonly(self.codex/'thread_history_1.sqlite') as db:
                    turn=db.execute('SELECT status,turn_id,completed_at FROM thread_turns WHERE thread_id=? ORDER BY rollout_ordinal DESC LIMIT 1',(s['session_id'],)).fetchone()
                    if turn and status=='unknown':
                        status={'inProgress':'running','completed':'completed','interrupted':'interrupted','failed':'failed'}.get(turn['status'],'unknown')
                        if status=='completed': completion=f'{turn["turn_id"]}:{turn["completed_at"]}'
                    rows=db.execute('SELECT item_json FROM thread_items WHERE thread_id=? AND item_type IN (?,?) ORDER BY rollout_ordinal DESC LIMIT ?', (s['session_id'],'userMessage','agentMessage',limit)).fetchall()
                    normalized=[]
                    for row in reversed(rows):
                        item=json.loads(row[0]); role='user' if item.get('type')=='userMessage' else 'assistant'
                        text=item.get('text') or text_blocks(item.get('content',[]))
                        if text: normalized.append({'role':role,'text':text[:18000]})
                    if normalized: messages=normalized
            except (sqlite3.Error,ValueError): pass
        # Exclude injected system wrapper text from human-work summaries.
        visible=[m for m in messages if not m['text'].lstrip().startswith(('<environment_context>','<permissions','<user_instructions>'))]
        return {**s,'status':status,'status_basis':'native transcript/turn markers; unknown is not idle','writer_owned':self.codex_owned(s['session_id']) if engine=='codex' else None,'completion_marker':completion,'messages':visible[-limit:],'recent_tools':activity[-8:],'last_request':next((m['text'][:2000] for m in reversed(visible) if m['role']=='user'),''),'last_answer':next((m['text'][:8000] for m in reversed(visible) if m['role']=='assistant'),'')}
