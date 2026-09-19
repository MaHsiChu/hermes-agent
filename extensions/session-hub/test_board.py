import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import service
import live
from board import TaskBoard, state_of
from readers import SessionReaders


class BoardContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.patches = [patch.object(service, 'DATA', self.root), patch.object(live, 'DATA', self.root)]
        for p in self.patches: p.start()
        service.initialize()
        live.initialize()

    def tearDown(self):
        for p in self.patches: p.stop()
        self.temp.cleanup()

    def test_native_completion_receipt_survives_restart_and_new_completion_is_unread(self):
        folder = self.root/'claude/projects/project'
        folder.mkdir(parents=True)
        log = folder/'session-1.jsonl'
        log.write_text('{"type":"user","cwd":"/project","message":{"content":"Build feature"}}\n'
                       '{"type":"assistant","uuid":"done-1","message":{"content":"Result","stop_reason":"end_turn"}}\n')
        readers = SessionReaders({'codex_home':str(self.root/'codex'), 'claude_home':str(self.root/'claude'), 'claude_desktop_home':str(self.root/'desktop')})
        board = TaskBoard(readers, live, service.db, service.READ_LOCK)
        with patch.object(live,'app_sessions',return_value={'sessions':[], 'errors':[]}):
            task = board.get('claude:session-1')
            self.assertEqual(task['state'],'unread')
            board.mark_read(task['key'],task['revision'])
            service.initialize()
            self.assertEqual(board.get(task['key'])['state'],'completed')
            with log.open('a') as f:
                f.write('{"type":"assistant","uuid":"done-2","message":{"content":"New result","stop_reason":"end_turn"}}\n')
            board.snapshot(force=True)
            board.mark_read(task['key'],task['revision'])
            self.assertEqual(board.get(task['key'])['state'],'unread')
            with log.open('a') as f:
                f.write('{"type":"user","message":{"content":"A turn whose process crashed"}}\n')
            board.snapshot(force=True)
            self.assertEqual(board.get(task['key'])['state'],'unknown')

    def test_creation_is_idempotent_and_job_reference_follows_the_native_session(self):
        readers = SessionReaders({'codex_home':str(self.root/'codex'), 'claude_home':str(self.root/'claude'), 'claude_desktop_home':str(self.root/'desktop')})
        board = TaskBoard(readers, live, service.db, service.READ_LOCK)
        body={'engine':'codex','prompt':'Build feature','request_key':'request-1','title':'Feature card'}
        first=board.create(body, service.dispatch)
        self.assertEqual(first['id'],board.create(body,service.dispatch)['id'])
        live.update(first['id'],session_id='native-id',state='completed')
        with patch.object(live,'app_sessions',return_value={'sessions':[], 'errors':[]}):
            task=board.get(first['task_key'])
        self.assertEqual(task['session_id'],'native-id')
        self.assertEqual(task['title'],'Feature card')
        self.assertEqual(task['state'],'unread')
        self.assertIn('#task/session-hub/',first['reference'])
        newer=live.submit({**body,'request_key':'followup'})
        live.update(newer['id'],session_id='native-id',state='running')
        with patch.object(live,'app_sessions',return_value={'sessions':[], 'errors':[]}):
            board.snapshot(force=True)
            self.assertEqual(board.get(first['task_key'])['session_id'],'native-id')
        self.assertEqual(state_of({'status':'completed'},'running',None),'running')
        self.assertEqual(state_of({'status':'completed'},'needsInput',None),'attention')
        self.assertEqual(state_of({},'idle',None),'unknown')
        self.assertEqual(state_of({'status':'completed'},{'type':'active','activeFlags':['waitingOnApproval']},None),'attention')
        self.assertEqual(state_of({'status':'completed'},'active',None),'running')
        self.assertEqual(state_of({'status':'running'},'notLoaded',None),'unknown')

    def test_user_closure_is_durable_and_independent_of_running_state_and_read_receipts(self):
        board=TaskBoard(None,live,service.db,service.READ_LOCK)
        snapshot={'tasks':[{'key':'codex:a','title':'A','state':'running','revision':''}]}
        board.set_closed('codex:a',True)
        service.initialize()
        restarted=TaskBoard(None,live,service.db,service.READ_LOCK)
        row=restarted._receipts(snapshot)['tasks'][0]
        self.assertTrue(row['closed']);self.assertEqual(row['state'],'running')
        restarted.mark_read('codex:a','revision')
        self.assertTrue(restarted._receipts(snapshot)['tasks'][0]['closed'])
        restarted.set_closed('codex:a',False)
        self.assertFalse(restarted._receipts(snapshot)['tasks'][0]['closed'])
        restarted.set_closed('hermes:connection:profile:session',True)
        self.assertTrue(restarted._receipts(snapshot)['closures']['hermes:connection:profile:session'])
        for key,value in [('codex:a','false'),('codex:a',1),('invalid:key',True),('codex:',True)]:
            with self.assertRaises(ValueError): restarted.set_closed(key,value)

    def test_closure_follows_queued_job_into_session_and_newer_edits_win(self):
        board=TaskBoard(None,live,service.db,service.READ_LOCK)
        job=live.submit({'engine':'codex','prompt':'fixture','request_key':'closure'})
        key='job:'+job['id'];board.set_closed(key,True)
        live.update(job['id'],session_id='session-a',state='running')
        snapshot={'tasks':[{'key':'codex:session-a','job_id':job['id'],'title':'A','state':'running','revision':''}]}
        self.assertTrue(board._receipts(snapshot)['tasks'][0]['closed'])
        board.set_closed('codex:session-a',False)
        self.assertFalse(board._receipts(snapshot)['tasks'][0]['closed'])
        board.set_closed(key,True)
        self.assertTrue(board._receipts(snapshot)['tasks'][0]['closed'])


if __name__=='__main__': unittest.main()
