import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import live
import claude_live
import attachments


class ClaudeAppContracts(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        p=patch.object(live,'DATA',self.root);p.start();self.addCleanup(p.stop);live.initialize()
        self.sid='2a180f82-79ef-4d06-907d-1f00b3b86a31'
        self.gui='local_6c5f8d38-bbc4-40c3-a146-94260fc94a9e'
        self.peer={'session_id':self.sid,'app_session_id':self.gui,'title':'Dedicated test'}
        self.body={'engine':'claude','session_id':self.sid,'prompt':'literal','request_key':'one'}

    def test_offline_rejects_before_enqueue_and_accepted_retry_survives_offline(self):
        with patch.object(claude_live,'sessions',return_value=[]):
            with self.assertRaisesRegex(ValueError,'not live'):live.submit(self.body)
        self.assertEqual(live.jobs(),[])
        with patch.object(claude_live,'sessions',return_value=[self.peer]):first=live.submit(self.body)
        with patch.object(claude_live,'sessions',return_value=[]):
            self.assertEqual(first['id'],live.submit(self.body)['id'])
            live.deliver(live.jobs()[0])
        self.assertEqual(live.jobs()[0]['state'],'needs_attention')

    def test_duplicate_name_is_not_delivered_to_wrong_peer(self):
        with patch.object(claude_live,'sessions',return_value=[self.peer,{**self.peer,'session_id':'other'}]):
            with self.assertRaisesRegex(ValueError,'ambiguous'):live.submit(self.body)
        self.assertEqual(live.jobs(),[])

    def test_gui_id_resolves_original_and_delivery_prompt_is_preserved(self):
        path=self.root/'native.jsonl';path.write_text('{}\n')
        image={'id':'image','path':'C:/test/image.png','name':'image.png','thumbnail':'preview'}
        with patch.object(claude_live,'sessions',return_value=[self.peer]),patch.object(attachments,'prepare',return_value=[image]):
            live.submit({**self.body,'session_id':self.gui})
        receipt={'guard_claimed':True,'message_id':'receipt','receipts':[{'is_error':False}]}
        with patch.object(claude_live,'sessions',return_value=[self.peer]),patch.object(live.READERS,'read',return_value={'path':str(path),'completion_marker':'old'}),patch.object(claude_live,'send',return_value=receipt) as send:
            live.deliver(live.jobs()[0])
        job=live.jobs()[0];self.assertEqual(job['session_id'],self.sid)
        self.assertIn('C:/test/image.png',send.call_args.args[1]);self.assertEqual(send.call_args.args[0],self.sid)
        self.assertEqual(json.loads(job['baseline'])['offset'],path.stat().st_size)
        self.assertEqual(job['state'],'delivered')

    def test_receipt_survives_long_output_and_partial_final_line(self):
        path=self.root/'native.jsonl'
        rows=[{'type':'assistant','message':{'content':'old','stop_reason':'end_turn'}},
              {'type':'user','origin':{'msg_id':'wanted'}},
              {'type':'progress','data':'x'*3_000_000}]
        path.write_text(''.join(json.dumps(r)+'\n' for r in rows))
        progress=live.claude_progress(path,'wanted')
        self.assertTrue(progress['received']);self.assertFalse(progress.get('completed'))
        with path.open('a') as f:f.write('{"type":"assistant",')
        partial=live.claude_progress(path,'wanted',progress)
        self.assertEqual(progress['offset'],partial['offset'])
        with path.open('a') as f:f.write('"message":{"content":"new","stop_reason":"end_turn"}}\n')
        final=live.claude_progress(path,'wanted',partial)
        self.assertTrue(final['completed']);self.assertEqual(final['answer'],'new')
        self.assertFalse(live.claude_progress(path,'other').get('completed'))

    def test_open_exact_desktop_id_does_not_claim_navigation_ack(self):
        with patch.object(live.READERS,'resolve',return_value={**self.peer,'path':'unused'}),patch.object(live.os,'startfile',create=True) as open_app:
            result=live.rpc('app_open',{'engine':'claude','session_id':self.sid})
            open_app.assert_called_once_with('claude://code/continue?session='+self.gui)
            self.assertTrue(result['requested']);self.assertFalse(result['navigated'])
        with patch.object(live.READERS,'resolve',return_value={'session_id':self.sid}),patch.object(live.os,'startfile',create=True) as open_app:
            with self.assertRaisesRegex(ValueError,'no Desktop session'):live.rpc('app_open',{'engine':'claude','session_id':self.sid})
            open_app.assert_not_called()

    def test_new_draft_is_not_a_fake_running_job(self):
        with patch.object(live.os,'startfile',create=True) as open_app:
            result=live.rpc('app_prepare_claude',{'prompt':'hi & project?'})
            self.assertEqual(result['state'],'draft');self.assertTrue(result['requires_send'])
            open_app.assert_called_once_with('claude://code/new?q=hi+%26+project%3F')
            with self.assertRaises(ValueError):live.rpc('app_prepare_claude',{'prompt':'x'*12001})
        self.assertEqual(live.jobs(),[])

    def test_attachment_namespaces_are_isolated(self):
        codex=attachments.folder({'engine':'codex','session_id':self.sid})
        claude=attachments.folder({'engine':'claude','session_id':self.sid})
        self.assertNotEqual(codex,claude)


if __name__=='__main__':unittest.main()
