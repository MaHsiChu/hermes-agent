import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from readers import SessionReaders
from transcript import TranscriptStore


@unittest.skipUnless(os.name == 'nt', 'Windows extended-length native paths')
class WindowsPaths(unittest.TestCase):
    def test_extended_paths_load_real_transcript_but_outside_paths_stay_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp); home = base/'codex'; home.mkdir()
            inside = home/'sessions'/'record.jsonl'; inside.parent.mkdir()
            outside = base/'outside.jsonl'
            message = {'type':'response_item','payload':{'type':'message','role':'assistant','content':[{'type':'output_text','text':'fixture result'}]}}
            for file in (inside, outside): file.write_text(json.dumps(message)+'\n', encoding='utf-8')
            with sqlite3.connect(home/'state_5.sqlite') as c:
                c.execute('CREATE TABLE threads(id TEXT, rollout_path TEXT, cwd TEXT, title TEXT, name TEXT, updated_at REAL, archived INTEGER, source TEXT, history_mode TEXT)')
                c.executemany('INSERT INTO threads VALUES(?,?,?,?,?,?,?,?,?)', [
                    ('inside', '\\\\?\\'+str(inside), str(home), 'Inside', '', 1, 0, 'cli', 'legacy'),
                    ('outside', '\\\\?\\'+str(outside), str(home), 'Outside', '', 2, 0, 'cli', 'legacy'),
                    ('traversal', '\\\\?\\'+str(home/'..'/'outside.jsonl'), str(home), 'Traversal', '', 3, 0, 'cli', 'legacy')])
            c.close()
            readers = SessionReaders({'codex_home':str(home),'claude_home':str(base/'claude'),'claude_desktop_home':str(base/'desktop')})
            self.assertEqual([r['session_id'] for r in readers.sessions()['sessions']], ['inside'])
            self.assertEqual(readers.resolve('codex','inside')['path'],str(inside.resolve()))
            page = TranscriptStore(readers,base/'transcript.sqlite').page('codex','inside')
            self.assertEqual(page['items'][0]['blocks'][0]['text'],'fixture result')
            for sid in ('outside','traversal'):
                with self.assertRaises(ValueError):readers.resolve('codex',sid)
