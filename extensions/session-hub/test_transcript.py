import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from transcript import TranscriptStore


class FakeReaders:
    def __init__(self, root): self.codex = root
    def resolve(self, engine, sid):
        return dict(engine=engine, session_id=sid, title=sid, cwd=str(self.codex),
                    path=str(self.codex/(sid+'.jsonl')), history_mode='legacy')


class TranscriptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.readers = FakeReaders(self.root)
        self.store = TranscriptStore(self.readers, self.root/'index.sqlite')
    def tearDown(self): self.tmp.cleanup()
    def write(self, rows, sid='a', mode='w'):
        with (self.root/(sid+'.jsonl')).open(mode, encoding='utf-8') as f:
            for row in rows: f.write(json.dumps(row)+'\n')
    def message(self, i, text=None):
        return {'type':'user' if i%2==0 else 'assistant', 'uuid':str(i), 'message':{'content':[{'type':'text','text':text or str(i)}]}}
    def test_full_history_exceeds_old_tail_and_limit_without_loss(self):
        self.write([self.message(i, str(i)+':'+'中'*10000) for i in range(250)])
        all_items=[]; cursor=''
        while True:
            page=self.store.page('claude','a',cursor,37)
            all_items=page['items']+all_items;cursor=page['next_cursor']
            if not cursor:break
        self.assertEqual([x['id'] for x in all_items], [str(i) for i in range(250)])
        self.assertEqual(len(all_items[0]['blocks'][0]['text']),10002)
        self.assertEqual(page['coverage']['indexed_bytes'],(self.root/'a.jsonl').stat().st_size)
    def test_append_partial_and_in_place_updates(self):
        self.write([self.message(0,'old')]); p=self.store.page('claude','a')
        with (self.root/'a.jsonl').open('ab') as f:f.write(b'{"type":"user"')
        q=self.store.page('claude','a',since=p['revision'],generation=p['generation'])
        self.assertEqual(q['items'],[])
        with (self.root/'a.jsonl').open('ab') as f:f.write(b',"uuid":"new","message":{"content":"done"}}\n')
        self.write([self.message(0,'updated')],mode='a')
        q=self.store.page('claude','a',since=p['revision'],generation=p['generation'])
        self.assertEqual(len(q['items']),2)
        self.assertEqual(q['total'],2)
        self.assertEqual(q['items'][-1]['blocks'][0]['text'],'updated')
    def test_cursor_is_session_bound_and_rotation_invalidates_it(self):
        self.write([self.message(i) for i in range(3)])
        self.write([self.message(0)],sid='b');p=self.store.page('claude','a',limit=1)
        with self.assertRaises(ValueError):self.store.page('claude','b',p['next_cursor'])
        self.write([self.message(9)])
        with self.assertRaises(ValueError):self.store.page('claude','a',p['next_cursor'])
    def test_tool_results_diff_unknown_and_private_content(self):
        self.write([{'type':'assistant','uuid':'one','message':{'content':[
            {'type':'tool_use','id':'call','name':'Read','input':{'file':'x'}},
            {'type':'thinking','thinking':'PRIVATE','signature':'PRIVATE'}]}},
            {'type':'user','uuid':'two','message':{'content':[{'type':'tool_result','tool_use_id':'call','content':'X'*50000}]}},
            {'type':'assistant','uuid':'three','message':{'content':[{'type':'futureType','extra':42}]}}])
        p=self.store.page('claude','a')
        self.assertNotIn('PRIVATE',json.dumps(p))
        self.assertEqual(p['items'][0]['blocks'][0]['call_id'],p['items'][1]['blocks'][0]['call_id'])
        self.assertEqual(len(p['items'][1]['blocks'][0]['blocks'][0]['text']),50000)
        self.assertEqual(p['items'][2]['blocks'][0]['data']['extra'],42)
    def test_codex_normalized_and_rollout_merge(self):
        self.write([{'type':'response_item','payload':{'type':'message','id':'m','role':'assistant','content':[{'type':'output_text','text':'partial'}]}},
                    {'type':'event_msg','payload':{'type':'item_completed','item':{'type':'AgentMessage','id':'m','content':[{'type':'Text','text':'done'}]}}},
                    {'type':'response_item','payload':{'type':'function_call','id':'fc','call_id':'call','name':'exec','arguments':'hello'}},
                    {'type':'response_item','payload':{'type':'reasoning','id':'rs','encrypted_content':'SECRET'}}])
        original=self.readers.resolve
        self.readers.resolve=lambda *a:{**original(*a),'history_mode':'paginated'}
        with sqlite3.connect(self.root/'thread_history_1.sqlite') as c:
            c.execute('CREATE TABLE thread_items(thread_id,turn_id,item_id,rollout_ordinal,created_at_ms,item_json,updated_at_ordinal)')
            c.execute('INSERT INTO thread_items VALUES(?,?,?,?,?,?,?)',('a','t','m',1,1,json.dumps({'type':'agentMessage','id':'m','text':'complete'}),5))
            c.execute('INSERT INTO thread_items VALUES(?,?,?,?,?,?,?)',('a','t','call',2,2,json.dumps({'type':'commandExecution','id':'call','command':'hello','aggregatedOutput':'RESULT'}),6))
        c.close()
        p=self.store.page('codex','a');self.assertEqual(p['total'],3)
        self.assertEqual(p['items'][0]['blocks'][0]['text'],'complete')
        self.assertEqual(p['items'][1]['blocks'][1]['blocks'][0]['text'],'RESULT')
        self.assertNotIn('SECRET',json.dumps(p))
        q=self.store.page('codex','a',since=p['revision'],generation=p['generation'])
        self.assertEqual(q['items'],[])
    def test_changes_paginate_all_without_losing_newer_records(self):
        self.write([self.message(0)]);p=self.store.page('claude','a')
        self.write([self.message(i) for i in range(1,18)],mode='a');ids=[]
        while True:
            q=self.store.page('claude','a',since=p['revision'],generation=p['generation'],limit=4)
            ids += [i['id'] for i in q['items']];p=q
            if not q['has_more']:break
        self.assertEqual(ids,[str(i) for i in range(1,18)])
    def test_asset_only_reads_exact_native_image_reference(self):
        image=self.root/'image.png';image.write_bytes(b'\x89PNG\r\n\x1a\nTEST')
        other=self.root/'private.png';other.write_text('not an image')
        self.write([{'type':'response_item','payload':{'type':'imageView','id':'img','path':str(image)}}])
        self.assertEqual(self.store.asset('codex','a','img',str(image))['bytes'],12)
        with self.assertRaises(ValueError):self.store.asset('codex','a','img',str(other))
        with self.assertRaises(ValueError):self.store.asset('codex','a','not-the-item',str(image))
        image.write_text('arbitrary non-image content')
        with self.assertRaises(ValueError):self.store.asset('codex','a','img',str(image))
    def test_file_change_map_and_peer_text_are_preserved(self):
        self.write([{'type':'event_msg','payload':{'type':'item_completed','item':{'type':'FileChange','id':'diff','changes':{'a.py':{'unified_diff':'+hello'}}}}},
                    {'type':'response_item','payload':{'type':'function_call_output','id':'peer','name':'send_message_to_thread','namespace':'codex_app','output':'<codex_delegation><input>keep this task</input></codex_delegation>'}}])
        p=self.store.page('codex','a')
        self.assertEqual(p['items'][0]['blocks'][0]['text'],'+hello')
        self.assertEqual(p['items'][1]['role'],'peer')
        self.assertEqual(p['items'][1]['blocks'][0]['text'],'keep this task')


if __name__=='__main__':unittest.main()
