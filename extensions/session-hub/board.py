"""Task projections over native sessions. Read receipts never modify foreign history."""
import json
import sqlite3
import threading
import time
from urllib.parse import quote

LOCK = threading.RLock()


def initialize(db):
    with db() as c:
        c.execute('CREATE TABLE IF NOT EXISTS task_reads(key TEXT PRIMARY KEY, revision TEXT NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS task_titles(key TEXT PRIMARY KEY, title TEXT NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS task_closures(key TEXT PRIMARY KEY, closed INTEGER NOT NULL, updated REAL NOT NULL)')


def reference(key, title='Session task'):
    label = title.replace('\\', '\\\\').replace('[', '\\[').replace(']', '\\]').replace('\n', ' ')
    return f'[{label}](#task/session-hub/{quote(key, safe="")})'


def state_of(native, live_status, job):
    raw = live_status.get('type', '') if isinstance(live_status, dict) else str(live_status or '')
    compact = raw.replace('_', '').replace('-', '').lower()
    flags = live_status.get('activeFlags', []) if isinstance(live_status, dict) else []
    if any(str(flag).lower() in ('waitingonapproval', 'waitingonuserinput', 'waitingforapproval', 'waitingforinput') for flag in flags):
        return 'attention'
    if compact in ('needsinput', 'needsattention', 'waitingforapproval', 'waitingforinput'):
        return 'attention'
    if compact in ('active', 'running', 'inprogress', 'working', 'busy'):
        return 'running'
    if job and job['state'] in ('queued', 'sending', 'delivered', 'waiting_handoff', 'checking'):
        return 'queued'
    if job and job['state'] in ('needs_attention', 'delivery_uncertain', 'failed'):
        return 'attention'
    status = native.get('status', 'unknown')
    if status == 'running': return 'unknown' if compact in ('notloaded', 'idle') else 'running'
    if status == 'interrupted': return 'interrupted'
    if status == 'completed' or compact == 'completed': return 'completed'
    if job and job['state'] == 'completed': return 'completed'
    if job and job['state'] == 'cancelled': return 'interrupted'
    if job and job['state'] == 'running': return 'running'
    # An idle App is not evidence that its last task succeeded.
    return 'unknown'


class TaskBoard:
    def __init__(self, readers, live, db, read_lock):
        self.readers, self.live, self.db, self.read_lock = readers, live, db, read_lock
        self.cached = None
        self.cached_at = 0
        self.app_inventory = {'sessions': [], 'errors': []}
        self.app_inventory_at = 0
        self.app_refreshing = False

    def _app_inventory(self, background):
        if not background: return self.live.app_sessions()
        if not self.app_refreshing and time.monotonic() - self.app_inventory_at > 10:
            self.app_refreshing = True
            def load():
                try:
                    result = self.live.app_sessions()
                    for row in result['sessions']:
                        if row['engine']=='codex' and row.get('status')=='active':
                            try:
                                detail = self.live.rpc('app_read',row)
                                row['status'] = detail.get('thread',{}).get('status') or row['status']
                            except Exception as exc:
                                result['errors'].append(str(exc))
                except Exception as exc:
                    result = {'sessions': [], 'errors': [str(exc)]}
                with LOCK:
                    self.app_inventory = result
                    self.app_inventory_at = time.monotonic()
                    self.app_refreshing = False
                    self.cached_at = 0
            threading.Thread(target=load, daemon=True).start()
        return self.app_inventory

    def snapshot(self, force=False, background=False):
        with LOCK:
            if not force and self.cached and time.monotonic() - self.cached_at < 4:
                return self._receipts(self.cached)
            inventory = self._app_inventory(background)
            with self.read_lock:
                history = self.readers.sessions(limit=200)
            with self.db() as c:
                cli_jobs = [dict(r, transport='cli') for r in c.execute('SELECT * FROM jobs ORDER BY created DESC')]
            jobs = [dict(j, transport='app') for j in self.live.jobs()] + cli_jobs
            latest = {}
            for job in sorted(jobs, key=lambda j: j['created']):
                if job['session_id']: latest[job['engine'] + ':' + job['session_id']] = job
            rows = {s['engine'] + ':' + s['session_id']: dict(s, live=False) for s in history['sessions']}
            for s in inventory['sessions']:
                key = s['engine'] + ':' + s['session_id']
                rows[key] = {**rows.get(key, {}), **s, 'live': s.get('status') != 'notLoaded'}
            for key, job in latest.items():
                if key not in rows:
                    rows[key] = {'engine': job['engine'], 'session_id': job['session_id'], 'title': job['session_id'], 'live': False}
            tasks = []
            for key, row in rows.items():
                native = {}
                try:
                    with self.read_lock: native = self.readers.read(row['engine'], row['session_id'], 1, refresh_missing=False)
                except (ValueError, OSError, sqlite3.Error): pass
                job = latest.get(key)
                # A prior Hub delivery must not override newer work started directly in the App.
                status_job = job if not job or job['updated'] >= native.get('updated_at', 0) else None
                state = state_of(native, row.get('status'), status_job)
                if state == 'running' and not row.get('live') and not (status_job and status_job['state']=='running') and native.get('writer_owned') is not True:
                    # A start marker without a live owner may be an old crash, not current work.
                    state = 'unknown'
                revision = str(native.get('completion_marker') or (job and job['state'] == 'completed' and job['id']) or '')
                tasks.append({**row, 'key': key, 'state': state, 'revision': revision,
                    'managed': bool(job), 'updated_at': row.get('updated_at') or (job or {}).get('updated', 0),
                    'cwd': row.get('cwd') or native.get('cwd', ''),
                    'summary': (job or {}).get('detail', ''), 'job_id': (job or {}).get('id'),
                    'transport': (job or {}).get('transport', 'app'),
                    'reference': reference(key, row.get('title', 'Session task'))})
            for job in jobs:
                if job['session_id']: continue
                spec = json.loads(job.get('spec') or '{}')
                key = 'job:' + job['id']
                tasks.append({'key': key, 'engine': job['engine'], 'session_id': '', 'title': spec.get('prompt', job.get('prompt', ''))[:120],
                    'state': state_of({}, '', job), 'revision': '', 'live': False, 'managed': True,
                    'updated_at': job['updated'], 'cwd': job.get('cwd', ''), 'summary': job['detail'],
                    'job_id': job['id'], 'transport': job['transport'], 'reference': reference(key)})
            self.cached = {'tasks': tasks, 'errors': inventory.get('errors', []) + history.get('errors', []),
                'history_total': history['total'], 'history_loaded': len(history['sessions']), 'synced_at': time.time()}
            self.cached_at = time.monotonic()
            return self._receipts(self.cached)

    def _receipts(self, snapshot):
        with self.db() as c:
            seen = dict(c.execute('SELECT key,revision FROM task_reads'))
            titles = dict(c.execute('SELECT key,title FROM task_titles'))
            closures = {r['key']: bool(r['closed']) for r in c.execute('SELECT key,closed FROM task_closures')}
            # A queued job gains a native session ID later. Carry the user's
            # explicit flag to that durable identity once; newer edits win.
            for row in snapshot['tasks']:
                alias = 'job:' + str(row.get('job_id'))
                if row['key'] not in closures and alias in closures:
                    c.execute('INSERT OR IGNORE INTO task_closures VALUES(?,?,?)', (row['key'], int(closures[alias]), time.time()))
                    closures[row['key']] = closures[alias]
        tasks = []
        for row in snapshot['tasks']:
            title = titles.get(row['key']) or titles.get('job:' + str(row.get('job_id'))) or row['title']
            state = row['state']
            if state == 'completed' and row['revision'] and seen.get(row['key']) != row['revision']: state = 'unread'
            tasks.append({**row, 'title': title, 'state': state, 'closed': closures.get(row['key'], False), 'reference': reference(row['key'], title)})
        return {**snapshot, 'tasks': tasks, 'closures': closures}

    def set_closed(self, key, closed):
        if not isinstance(key, str) or len(key) > 1000 or ':' not in key or not key.split(':', 1)[1] or key.split(':', 1)[0] not in ('codex', 'claude', 'hermes', 'job'):
            raise ValueError('Invalid task key')
        if type(closed) is not bool: raise ValueError('closed must be a boolean')
        keys = {key}
        if key.startswith('job:'):
            for database in (self.db, self.live.db):
                with database() as c:
                    job = c.execute('SELECT engine,session_id FROM jobs WHERE id=?', (key[4:],)).fetchone()
                if job and job['session_id']: keys.add(job['engine'] + ':' + job['session_id'])
        # Metadata only. This never cancels, archives or writes to native apps.
        with self.db() as c:
            for identity in keys:
                c.execute('INSERT OR REPLACE INTO task_closures VALUES(?,?,?)', (identity, int(closed), time.time()))
        return {'closures': {identity: closed for identity in keys}}

    def get(self, key):
        if key.startswith('job:'):
            job_id = key[4:]
            with self.live.db() as c:
                job = c.execute('SELECT engine,session_id FROM jobs WHERE id=?', (job_id,)).fetchone()
            if not job:
                with self.db() as c:
                    job = c.execute('SELECT engine,session_id FROM jobs WHERE id=?', (job_id,)).fetchone()
            if job and job['session_id']:
                return self.get(job['engine'] + ':' + job['session_id'])
        rows = self.snapshot()['tasks']
        row = next((r for r in rows if r['key'] == key or 'job:' + str(r.get('job_id')) == key), None)
        if row: return row
        # A durable reference still resolves after the session falls out of recency.
        engine, _, sid = key.partition(':')
        if engine not in ('codex', 'claude') or not sid: raise ValueError('Task not found')
        with self.read_lock: native = self.readers.read(engine, sid, 1)
        row = {**native, 'key': key, 'state': state_of(native, '', None), 'revision': str(native.get('completion_marker') or ''),
            'reference': reference(key, native['title'])}
        return self._receipts({'tasks': [row]})['tasks'][0]

    def mark_read(self, key, revision):
        # Store the displayed completion, not the newest one: a finish racing an open stays unread.
        if not isinstance(revision, str) or len(revision) > 1000: raise ValueError('Invalid revision')
        with self.db() as c:
            c.execute('INSERT OR REPLACE INTO task_reads VALUES(?,?)', (key, revision))
        return {'ok': True}

    def create(self, body, dispatch):
        transport = body.get('transport', 'app')
        if transport not in ('app', 'cli'): raise ValueError('transport must be app or cli')
        if body.get('session_id'): raise ValueError('Task creation requires an empty session_id')
        title = str(body.get('title', '')).strip()[:180]
        result = self.live.submit(body) if transport == 'app' else dispatch(body)
        key = 'job:' + result['id']
        with self.db() as c:
            if title: c.execute('INSERT OR IGNORE INTO task_titles VALUES(?,?)', (key, title))
        self.cached_at = 0
        return {**result, 'task_key': key, 'reference': reference(key, title or 'Session task'),
            'display_hint': 'Include reference verbatim as a Markdown link in your reply. It renders a live task card in Hermes.'}
