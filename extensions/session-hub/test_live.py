import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import live
import claude_guard


class LiveContracts(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.patch=patch.object(live,'DATA',self.root);self.patch.start();live.initialize()
    def tearDown(self):
        self.patch.stop();self.tmp.cleanup()
    def submit(self,**fields):
        return live.submit(dict(engine='codex',prompt='test',request_key='stable',**fields))
    def test_idempotency_and_conflicting_retry(self):
        one=self.submit();self.assertEqual(one['id'],self.submit()['id'])
        with self.assertRaises(ValueError):live.submit({'engine':'codex','prompt':'changed','request_key':'stable'})
    def test_restart_marks_uncertain_send_without_requeue(self):
        job=self.submit();live.update(job['id'],state='sending');live.initialize()
        self.assertEqual(live.jobs()[0]['state'],'delivery_uncertain')
    def test_failed_app_delivery_is_not_retried_or_changed_to_cli(self):
        self.submit()
        with patch.object(live.codex_app,'call',side_effect=TimeoutError('uncertain')) as call:
            live.deliver(live.jobs()[0]);live.deliver(live.jobs()[0])
            self.assertEqual(call.call_count,1)
        self.assertEqual(live.jobs()[0]['state'],'delivery_uncertain')
    def test_old_codex_completed_turn_cannot_complete_new_delivery(self):
        j=self.submit();live.update(j['id'],session_id='target',state='delivered',baseline=json.dumps({'before_turn':'old','before_active':False}))
        with patch.object(live,'snapshot',return_value={'latestTurn':{'id':'old','status':'completed'}}):
            events=[];live.poll(live.jobs()[0],lambda *x:events.append(x));self.assertFalse(events)
        self.assertEqual(live.jobs()[0]['state'],'delivered')
    def test_claude_completion_requires_exact_consumed_message_id(self):
        p=self.root/'history.jsonl'
        records=[{'type':'assistant','message':{'stop_reason':'end_turn','content':'OLD'}},{'type':'user','origin':{'msg_id':'expected'}},{'type':'assistant','message':{'stop_reason':'end_turn','content':'NEW'}}]
        p.write_text('\n'.join(json.dumps(r) for r in records))
        self.assertEqual(live.claude_completion(p,'different'),(False,''))
        self.assertEqual(live.claude_completion(p,None),(False,''))
        self.assertEqual(live.claude_completion(p,'expected'),(True,'NEW'))
    def test_claude_guard_blocks_wrong_target_and_changed_message(self):
        spec={'name':'chosen','message':'literal','session_id':'sid'}
        self.assertTrue(claude_guard.validate(spec,{'to':'other','message':'literal'}))
        self.assertTrue(claude_guard.validate(spec,{'to':'chosen','message':'altered'}))
        with patch('claude_live.sessions',return_value=[{'title':'chosen','session_id':'sid'}]):
            self.assertEqual(claude_guard.validate(spec,{'to':'chosen','message':'literal'}),'')
        with patch('claude_live.sessions',return_value=[{'title':'chosen','session_id':'different'}]):
            self.assertTrue(claude_guard.validate(spec,{'to':'chosen','message':'literal'}))
    def test_no_unimplemented_claude_gui_creation(self):
        with self.assertRaises(ValueError):live.submit({'engine':'claude','prompt':'test','request_key':'new'})

    def test_codex_open_uses_original_id_and_fixed_protocol_with_visible_fallback(self):
        sid='01a0b338-5a7a-7be1-80ae-826d146de5cb'
        with patch.object(live.codex_app,'call',return_value={'navigated':True}) as call,patch.object(live.os,'startfile',create=True) as activate:
            result=live.rpc('app_open',{'session_id':sid})
            call.assert_called_once_with('navigate_to_codex_page',{'threadId':sid})
            if live.os.name=='nt':
                activate.assert_called_once_with('codex://threads/'+sid)
                self.assertTrue(result['activated'])
            with self.assertRaises(ValueError):live.rpc('app_open',{'session_id':'cmd.exe & invalid'})
        with patch.object(live.codex_app,'call',return_value={'navigated':True}),patch.object(live.os,'startfile',create=True,side_effect=OSError):
            result=live.rpc('app_open',{'session_id':sid})
            self.assertTrue(result['navigated']);self.assertFalse(result['activated'])
        with patch.object(live.codex_app,'call',return_value={'navigated':False}),patch.object(live.os,'startfile',create=True) as activate:
            with self.assertRaises(ValueError):live.rpc('app_open',{'session_id':sid})
            activate.assert_not_called()


if __name__=='__main__':unittest.main()
