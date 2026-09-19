"""Isolated behavioral checks; no native model calls, no user's session modifications."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import service
from readers import lines


class Contracts(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.old=service.DATA
        service.DATA=self.root
        service.initialize()
        self.body={'engine':'codex','cwd':str(self.root),'prompt':'fixture','request_key':'retry-1'}
    def tearDown(self):
        service.DATA=self.old
        self.temp.cleanup()

    def test_idempotent_submission_does_not_duplicate_or_change_payload(self):
        first=service.dispatch(self.body)
        second=service.dispatch(self.body)
        self.assertEqual(first['id'],second['id'])
        with self.assertRaises(ValueError): service.dispatch({**self.body,'prompt':'different'})
        with service.db() as db: self.assertEqual(db.execute('SELECT count(*) FROM jobs').fetchone()[0],1)

    def test_busy_session_waits_and_cancel_cannot_be_resurrected(self):
        first=service.dispatch(self.body)
        with service.db() as db: job=dict(db.execute('SELECT * FROM jobs').fetchone())
        with patch.object(service,'native_busy',return_value='held by App'),patch.object(service.subprocess,'Popen') as process:
            service.run_job(job)
            self.assertEqual(service.rpc('jobs',{'job_id':first['id']})['jobs'][0]['state'],'waiting_handoff')
            service.rpc('cancel',{'job_id':first['id']})
            service.run_job(job)
            process.assert_not_called()
        self.assertEqual(service.rpc('jobs',{'job_id':first['id']})['jobs'][0]['state'],'cancelled')

    def test_events_survive_restart_and_are_independent_for_two_readers(self):
        service.event('completion-1','completed','codex','sid','result')
        service.event('completion-1','completed','codex','sid','result')
        service.initialize()
        a=service.rpc('events',{'after':0});b=service.rpc('events',{'after':0})
        self.assertEqual(a,b); self.assertEqual(len(a['events']),1)
        self.assertFalse(service.rpc('events',{'after':a['cursor']})['events'])

    def test_crash_does_not_reexecute_uncertain_running_task(self):
        j=service.dispatch(self.body)
        service.update_job(j['id'],state='running')
        service.initialize()
        self.assertEqual(service.rpc('jobs',{'job_id':j['id']})['jobs'][0]['state'],'needs_attention')

    def test_live_truncated_jsonl_tolerates_partial_tail(self):
        p=self.root/'live.jsonl'
        p.write_text('{"type":"user"}\n{"type":',encoding='utf-8')
        self.assertEqual(list(lines(p)),[{'type':'user'}])

    def test_workspace_and_engine_validation(self):
        for body in ({**self.body,'cwd':'relative/path'},{**self.body,'engine':'shell'},{**self.body,'mode':'bypass'}):
            with self.assertRaises(ValueError): service.dispatch(body)

if __name__=='__main__': unittest.main(verbosity=2)
