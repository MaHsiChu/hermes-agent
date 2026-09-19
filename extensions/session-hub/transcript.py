"""Paginated native timeline. Foreign stores are read-only; this index is disposable.

Includes persisted conversation/tool/artifact records, not private App UI state.
The JSONL offset advances only over complete lines. Stable identities de-duplicate
Codex rollout/normalized records and update streamed records in place.
"""
from __future__ import annotations
import base64
from contextlib import contextmanager
import hashlib
import json
import re
from pathlib import Path
import sqlite3
import threading
import uuid
from readers import readonly
import documents


def dump(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def clean(value):
    """Do not expose encrypted reasoning/signatures or runtime instruction envelopes."""
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items() if k not in
                ('encrypted_content', 'signature', 'internal_chat_message_metadata_passthrough',
                 'raw_content', 'base_instructions')}
    if isinstance(value, list):
        return [clean(v) for v in value]
    return value


def blocks(content):
    if isinstance(content, str):
        return [{'type': 'text', 'text': content}]
    if isinstance(content, dict):
        return [{'type': 'record', 'data': clean(content)}]
    result = []
    for b in content or []:
        if not isinstance(b, dict):
            result.append({'type': 'record', 'data': b})
            continue
        typ = b.get('type', '').lower()
        if typ in ('text', 'input_text', 'output_text'):
            result.append({'type': 'text', 'text': b.get('text', '')})
        elif typ in ('thinking', 'redacted_thinking', 'reasoning'):
            result.append({'type': 'notice', 'text': '原生思考记录：私有推理内容不在共享展示范围。'})
        elif typ in ('tool_use', 'server_tool_use'):
            result.append({'type': 'tool_call', 'name': b.get('name', ''), 'call_id': b.get('id'), 'input': clean(b.get('input'))})
        elif typ == 'tool_result':
            result.append({'type': 'tool_result', 'call_id': b.get('tool_use_id'), 'error': b.get('is_error', False), 'blocks': blocks(b.get('content'))})
        elif typ in ('image', 'input_image', 'localimage', 'local_image', 'document', 'file', 'audio', 'input_audio'):
            # Embedded image bytes are kept intact. The UI only displays raster data URLs.
            result.append({'type': 'attachment', 'kind': typ, 'data': clean(b)})
        else:
            result.append({'type': 'record', 'name': b.get('type', 'unknown'), 'data': clean(b)})
    return result


def codex_item(p, fallback):
    typ = p.get('type', '')
    kind = typ[:1].lower() + typ[1:]
    identity = p.get('id') or fallback
    role = 'activity'
    body = []
    if kind in ('message', 'userMessage', 'agentMessage'):
        role = p.get('role') or ('user' if kind == 'userMessage' else 'assistant')
        if role not in ('user', 'assistant'):
            return None
        body = blocks(p.get('text') if p.get('text') is not None else p.get('content', []))
        # Injected environment/config wrappers are context, not human chat bubbles.
        if role == 'user' and any(b.get('text', '').lstrip().startswith((
                '<environment_context>', '<permissions', '<user_instructions>',
                '<recommended_plugins>', '# AGENTS.md')) for b in body):
            role = 'context'
    elif kind in ('reasoning',):
        body = [{'type': 'notice', 'text': '原生思考记录：私有推理内容不在共享展示范围。'}]
        return {'id': identity, 'kind': kind, 'role': role, 'blocks': body, 'details': {'type': typ}, 'phase': p.get('phase')}
    elif kind in ('function_call', 'custom_tool_call'):
        identity = p.get('call_id') or identity
        body = [{'type': 'tool_call', 'name': p.get('name'), 'call_id': identity, 'input': p.get('arguments', p.get('input'))}]
    elif kind in ('function_call_output', 'custom_tool_call_output', 'functionCallOutput'):
        if p.get('call_id'):
            identity = p['call_id'] + ':result'
        body = [{'type': 'tool_result', 'call_id': p.get('call_id'), 'name': p.get('name'), 'blocks': blocks(p.get('output', ''))}]
        if p.get('namespace') == 'codex_app' and p.get('name') in ('create_thread', 'send_message_to_thread'):
            role = 'peer'
            match = re.search(r'<input>([\s\S]*)</input>', p.get('output', ''))
            if match: body = blocks(match.group(1))
    elif kind == 'commandExecution':
        body = [{'type': 'tool_call', 'name': 'terminal', 'input': p.get('command'), 'call_id': identity},
                {'type': 'tool_result', 'call_id': identity, 'blocks': blocks(p.get('aggregatedOutput', '')), 'exit_code': p.get('exitCode')}]
    elif kind in ('mcpToolCall', 'dynamicToolCall'):
        body = [{'type': 'tool_call', 'name': '.'.join(filter(None, (p.get('server'), p.get('tool')))), 'input': clean(p.get('arguments')), 'call_id': identity},
                {'type': 'record', 'name': 'result', 'data': clean(p.get('result', p.get('contentItems')))}]
    elif kind == 'fileChange':
        changes = p.get('changes') or []
        if isinstance(changes, dict):
            changes = [{'path': path, **(value if isinstance(value, dict) else {'diff': str(value)})} for path, value in changes.items()]
        body = [{'type': 'diff', 'path': c.get('path'), 'text': c.get('diff', c.get('unified_diff', '')), 'change': c.get('kind', c.get('type'))} for c in changes if isinstance(c, dict)]
    elif kind in ('imageView', 'imageGeneration'):
        body = [{'type': 'attachment', 'kind': kind, 'data': clean(p)}]
    else:
        body = [{'type': 'record', 'name': kind, 'data': clean(p)}]
    return {'id': str(identity), 'kind': kind, 'role': role, 'blocks': body,
            'details': clean(p), 'phase': p.get('phase'), 'status': p.get('status')}


def from_row(engine, row, ordinal, turn):
    """Returns item/priority/turn. Unsupported bookkeeping is counted, not invented."""
    typ = row.get('type')
    if engine == 'codex':
        p = row.get('payload') or {}
        if typ == 'turn_context' or (typ == 'event_msg' and p.get('type') == 'task_started'):
            turn = p.get('turn_id') or turn
        item = None; priority = 1
        if typ == 'response_item':
            item = codex_item(p, f'row:{ordinal}')
        elif typ == 'event_msg' and p.get('type') in ('item_started', 'item_completed'):
            item = codex_item(p.get('item', {}), f'row:{ordinal}'); priority = 2
            turn = p.get('turn_id') or turn
        elif typ == 'event_msg' and p.get('type') in ('task_started', 'task_complete', 'task_completed', 'turn_aborted', 'task_aborted'):
            item = {'id': f'event:{ordinal}', 'kind': p['type'], 'role': 'event', 'blocks': [], 'details': clean(p)}
        elif typ == 'compacted':
            item = {'id': f'event:{ordinal}', 'kind': 'contextCompaction', 'role': 'event', 'blocks': blocks(p.get('message', '')), 'details': {'type': typ}}
        if item:
            item.update(turn_id=turn, timestamp=row.get('timestamp'))
        return item, priority, turn
    if typ in ('user', 'assistant'):
        msg = row.get('message') or {}
        origin = row.get('origin') or {}
        item = {'id': row.get('uuid') or f'row:{ordinal}', 'kind': typ, 'role': 'peer' if origin.get('kind') == 'peer' else typ,
                'blocks': blocks(msg.get('content', [])), 'timestamp': row.get('timestamp'),
                'parent_id': row.get('parentUuid'), 'sidechain': bool(row.get('isSidechain')),
                'details': {'message_id': msg.get('id'), 'model': msg.get('model'), 'usage': msg.get('usage'),
                            'stop_reason': msg.get('stop_reason'), 'origin': clean(origin)}, 'turn_id': row.get('promptId')}
        if origin.get('kind') == 'peer' and isinstance(origin.get('body'), str):
            item['blocks'] = blocks(origin['body'])
        return item, 1, turn
    if typ in ('system', 'attachment', 'summary', 'progress'):
        content = row.get('attachment', row.get('data', row.get('content', row.get('summary', ''))))
        item = {'id': row.get('uuid') or f'row:{ordinal}', 'kind': row.get('subtype') or typ,
                'role': 'event' if typ == 'system' else 'context' if typ == 'attachment' else 'activity',
                'blocks': blocks(content) if isinstance(content, (str, list)) else [{'type': 'record', 'data': clean(content)}],
                'timestamp': row.get('timestamp'), 'parent_id': row.get('parentUuid'),
                'sidechain': bool(row.get('isSidechain')), 'details': clean(row), 'turn_id': turn}
        return item, 1, turn
    return None, 0, turn


class TranscriptStore:
    def __init__(self, readers, cache_path):
        self.readers = readers
        self.path = Path(cache_path)
        self.lock = threading.RLock()
        with self.db() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS sources(session TEXT PRIMARY KEY, path TEXT, inode TEXT, offset INTEGER,
              ordinal INTEGER, generation TEXT, norm INTEGER, turn_id TEXT, skipped INTEGER, malformed INTEGER);
            CREATE TABLE IF NOT EXISTS items(session TEXT, id TEXT, position INTEGER, priority INTEGER, revision INTEGER,
              body TEXT, PRIMARY KEY(session,id));
            CREATE INDEX IF NOT EXISTS timeline ON items(session,position,id);
            CREATE INDEX IF NOT EXISTS changes ON items(session,revision);
            CREATE TABLE IF NOT EXISTS cache_version(version INTEGER);
            ''')
            # Normalization changes must rebuild the derived cache, never native history.
            version = c.execute('SELECT version FROM cache_version').fetchone()
            if not version or version[0] != 2:
                c.execute('DELETE FROM items'); c.execute('DELETE FROM sources')
                c.execute('DELETE FROM cache_version'); c.execute('INSERT INTO cache_version VALUES(2)')

    @contextmanager
    def db(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(self.path, timeout=30)
        c.row_factory = sqlite3.Row
        try:
            with c: yield c
        finally:
            c.close()

    def put(self, c, key, item, ordinal, priority):
        old = c.execute('SELECT * FROM items WHERE session=? AND id=?', (key, item['id'])).fetchone()
        if old and old['priority'] > priority:
            return
        if old:
            previous = json.loads(old['body'])
            for field in ('timestamp', 'turn_id'):
                item[field] = item.get(field) or previous.get(field)
        body = dump(item)
        if old and old['body'] == body:
            return
        revision = c.execute('SELECT coalesce(max(revision),0)+1 FROM items WHERE session=?', (key,)).fetchone()[0]
        c.execute('INSERT OR REPLACE INTO items VALUES(?,?,?,?,?,?)',
                  (key, item['id'], old['position'] if old else ordinal, priority, revision, body))

    def sync(self, engine, sid, c):
        s = self.readers.resolve(engine, sid)
        path = Path(s['path']); key = engine + ':' + s['session_id']
        try: stat = path.stat()
        except FileNotFoundError: stat = None
        state = c.execute('SELECT * FROM sources WHERE session=?', (key,)).fetchone()
        inode = str(stat.st_ino) if stat else ''
        if state and (state['path'] != str(path) or state['inode'] != inode or (stat and stat.st_size < state['offset'])):
            c.execute('DELETE FROM items WHERE session=?', (key,)); state = None
        if not state:
            state = dict(offset=0, ordinal=0, generation=uuid.uuid4().hex, norm=-1, turn_id='', skipped=0, malformed=0)
        else: state = dict(state)
        offset, ordinal, turn = state['offset'], state['ordinal'], state['turn_id']
        if stat:
            with path.open('rb') as f:
                f.seek(offset)
                while True:
                    raw = f.readline()
                    if not raw or not raw.endswith(b'\n'):
                        break
                    offset = f.tell()
                    try:
                        row = json.loads(raw)
                        if not isinstance(row, dict): raise ValueError('not an object')
                        item, priority, turn = from_row(engine, row, ordinal, turn)
                        if item: self.put(c, key, item, ordinal, priority)
                        else: state['skipped'] += 1
                    except (ValueError, TypeError, KeyError):
                        state['malformed'] += 1
                    ordinal += 1
        warnings = []
        if not stat: warnings.append('本地 rollout 文件缺失；只能显示仍可读取的规范化记录。')
        if engine == 'codex' and s.get('history_mode') != 'legacy':
            try:
                with readonly(self.readers.codex/'thread_history_1.sqlite') as native:
                    rows = native.execute('SELECT * FROM thread_items WHERE thread_id=? AND updated_at_ordinal>=? ORDER BY updated_at_ordinal', (s['session_id'], state['norm']))
                    for row in rows:
                        item = codex_item(json.loads(row['item_json']), row['item_id'])
                        if item:
                            item['turn_id'] = row['turn_id']
                            item['timestamp'] = row['created_at_ms']
                            self.put(c, key, item, row['rollout_ordinal'], 3)
                        state['norm'] = max(state['norm'], row['updated_at_ordinal'])
            except (sqlite3.Error, ValueError, TypeError) as exc:
                warnings.append('规范化历史读取失败，当前使用 rollout：' + str(exc))
        c.execute('INSERT OR REPLACE INTO sources VALUES(?,?,?,?,?,?,?,?,?,?)',
                  (key, str(path), inode, offset, ordinal, state['generation'], state['norm'], turn, state['skipped'], state['malformed']))
        if state['malformed']: warnings.append(f"{state['malformed']} 条损坏的完整记录未能解析。")
        return s, key, state['generation'], dict(source_bytes=stat.st_size if stat else 0, indexed_bytes=offset,
              scanned_records=ordinal, bookkeeping_records=state['skipped'], malformed_records=state['malformed'], warnings=warnings)

    def cursor(self, key, generation, position, identity):
        return base64.urlsafe_b64encode(dump([key, generation, position, identity]).encode()).decode()

    def parse_cursor(self, cursor, key, generation):
        try:
            values = json.loads(base64.urlsafe_b64decode(cursor))
            if not isinstance(values, list) or len(values) != 4 or values[:2] != [key, generation]: raise ValueError()
            if not isinstance(values[2], int) or not isinstance(values[3], str): raise ValueError()
            return values[2:]
        except Exception as exc: raise ValueError('会话游标失效或属于其他会话，请重新加载。') from exc

    def asset(self, engine, session_id, item_id, asset_path):
        """Only raster files explicitly referenced by this native image item.

        No arbitrary path-read endpoint, remote downloads, HTML/SVG or credentials.
        """
        with self.lock, self.db() as c:
            s, key, _, _ = self.sync(engine, session_id, c)
            row = c.execute('SELECT body FROM items WHERE session=? AND id=?', (key, item_id)).fetchone()
            if not row: raise ValueError('图片记录不存在。')
            allowed = []
            def visit(value):
                if isinstance(value, dict):
                    if str(value.get('type', '')).lower() in ('localimage', 'local_image', 'imageview', 'imagegeneration', 'image', 'input_image'):
                        allowed.extend(p for p in (value.get('path'), value.get('savedPath')) if isinstance(p, str))
                    for child in value.values(): visit(child)
                elif isinstance(value, list):
                    for child in value: visit(child)
            visit(json.loads(row['body']))
            if not isinstance(asset_path, str) or asset_path not in allowed:
                raise ValueError('路径不是这个会话记录中的图片引用。')
            if asset_path.startswith(('\\\\', '//')): raise ValueError('不自动读取网络文件。')
            path = Path(asset_path)
            if not path.is_absolute(): path = Path(s['cwd'])/path
            path = path.resolve()
            if path.suffix.lower() not in ('.png', '.jpg', '.jpeg', '.gif', '.webp'):
                raise ValueError('只预览 PNG/JPEG/GIF/WebP 图片。')
            with path.open('rb') as f: data = f.read(16*1024*1024+1)
            if len(data) > 16*1024*1024: raise ValueError('图片超过 16 MB，请在原 App 中打开。')
            mime = 'image/png' if data.startswith(b'\x89PNG\r\n\x1a\n') else 'image/jpeg' if data.startswith(b'\xff\xd8\xff') else 'image/gif' if data.startswith((b'GIF87a', b'GIF89a')) else 'image/webp' if data.startswith(b'RIFF') and data[8:12] == b'WEBP' else None
            if not mime: raise ValueError('文件不是可识别的栅格图片。')
            return {'data_url': 'data:'+mime+';base64,'+base64.b64encode(data).decode(), 'bytes': len(data)}

    def document(self, engine, session_id, item_id, href):
        with self.lock, self.db() as c:
            s,key,_,_=self.sync(engine,session_id,c)
            row=c.execute('SELECT body FROM items WHERE session=? AND id=?',(key,item_id)).fetchone()
            if not row:raise ValueError('会话记录不存在。')
            return documents.read(json.loads(row['body']),href,s['cwd'])

    def attach_changes(self,c,key,items):
        # Read complete turns from the local index, independently of the visible
        # message page. Never infer changed files from prose or current git state.
        turns={i.get('turn_id') for i in items if i['role']=='assistant' and i.get('phase')!='commentary'}-{None,''}
        if not turns:return
        rows=c.execute("SELECT body FROM items WHERE session=? AND json_extract(body,'$.turn_id') IN ("+','.join('?' for _ in turns)+") ORDER BY position,id",(key,*turns)).fetchall()
        finals={};changes={}
        for row in rows:
            item=json.loads(row['body']);turn=item['turn_id']
            if item['role']=='assistant' and item.get('phase')!='commentary':finals[turn]=item['id']
            if item['kind']=='fileChange':changes.setdefault(turn,[]).append(item)
        for item in items:
            if finals.get(item.get('turn_id'))==item['id'] and changes.get(item.get('turn_id')):
                item['change_summary']=documents.change_summary(changes[item['turn_id']])

    def page(self, engine, session_id, cursor='', limit=40, since=None, generation=None):
        limit = max(1, min(int(limit), 100))
        with self.lock, self.db() as c:
            s, key, gen, coverage = self.sync(engine, session_id, c)
            maximum = c.execute('SELECT coalesce(max(revision),0),count(*) FROM items WHERE session=?', (key,)).fetchone()
            where = ''; args = [key]
            if since is not None:
                if generation != gen: raise ValueError('会话来源已变化，请重新加载。')
                where = ' AND revision>?'; args.append(int(since)); order = 'revision ASC'
            else:
                order = 'position DESC,id DESC'
                if cursor:
                    position, identity = self.parse_cursor(cursor, key, gen)
                    where = ' AND (position<? OR (position=? AND id<?))'; args += [position, position, identity]
            rows = c.execute('SELECT * FROM items WHERE session=?'+where+' ORDER BY '+order+' LIMIT ?', (*args, limit+1)).fetchall()
            more = len(rows) > limit; rows = rows[:limit]
            next_cursor = self.cursor(key, gen, rows[-1]['position'], rows[-1]['id']) if rows and since is None and more else None
            revision = rows[-1]['revision'] if since is not None and more else maximum[0]
            items = [{**json.loads(r['body']), 'position': r['position'], 'revision': r['revision']} for r in rows]
            if since is None: items.reverse()
            self.attach_changes(c,key,items)
            return {'engine': engine, 'session_id': s['session_id'], 'app_session_id': s.get('app_session_id'),
                    'title': s['title'], 'cwd': s['cwd'], 'items': items, 'total': maximum[1],
                    'next_cursor': next_cursor, 'has_more': more, 'revision': revision, 'generation': gen,
                    'coverage': coverage, 'scope': 'local persisted conversation, tools and artifacts; not private App state',
                    'sync_mode': 'polling persisted native records', 'copied_session': False}
