import json
from pathlib import Path
import tempfile
import unittest
import documents
from transcript import TranscriptStore
from test_transcript import FakeReaders

class DocumentContracts(unittest.TestCase):
    def test_exact_link_and_local_text_preview(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'report notes.md';path.write_text('# Report\nverified',encoding='utf-8')
            href='/'+path.as_posix().replace(' ','%20')+':2' if path.drive else path.as_posix()+':2'
            item={'blocks':[{'type':'text','text':'[report](<'+href+'>)'}]}
            result=documents.read(item,href,root)
            self.assertEqual(result['text'],'# Report\nverified');self.assertEqual(result['line'],2)
            self.assertTrue(result['markdown'])
            with self.assertRaises(ValueError):documents.read(item,str(path),root)
            relative={'blocks':[{'type':'text','text':'[reference][report]\n\n[report]: <report notes.md>'}]}
            self.assertEqual(documents.read(relative,'report%20notes.md',root)['name'],'report notes.md')
            for href in ['https://example.com/a.md','file://server/shared.md','//server/shared.md','javascript:alert(1)']:
                with self.assertRaises(ValueError):documents.location(href,root)
    def test_native_added_and_deleted_files_contain_raw_text(self):
        result=documents.change_summary([{'id':'add','status':'completed','blocks':[{'type':'diff','path':'new.py','text':'import x\n+literal\n\n','change':{'type':'add'}}]}, {'id':'delete','status':'completed','blocks':[{'type':'diff','path':'old.py','text':'old\nlines\n','change':{'type':'delete'}}]}])
        self.assertEqual((result['added'],result['removed']),(3,2))
        self.assertEqual(result['files'][0]['patches'][0]['diff'],'+import x\n++literal\n+')

    def test_changes_from_complete_turn_survive_small_pages(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root);store=TranscriptStore(FakeReaders(root),root/'cache.sqlite')
            rows=[{'type':'turn_context','payload':{'turn_id':'turn-a'}}]
            def change(id,path,diff,status='completed'):
                return {'type':'event_msg','payload':{'type':'item_completed','item':{'type':'fileChange','id':id,'status':status,'changes':[{'path':path,'diff':diff,'kind':{'type':'update'}}]}}}
            rows.extend([change('one','a.py','--- a/a.py\n+++ b/a.py\n-old\n+new\n'),change('two','a.py','+more\n'),change('three','b.py','+new\n'),change('declined','secret.py','+x\n','declined'),{'type':'response_item','payload':{'type':'message','id':'answer','role':'assistant','phase':'final_answer','content':[{'type':'text','text':'done'}]}}])
            (root/'a.jsonl').write_text('\n'.join(json.dumps(r) for r in rows)+'\n',encoding='utf-8')
            page=store.page('codex','a',limit=1);self.assertEqual(len(page['items']),1)
            summary=page['items'][0]['change_summary']
            self.assertEqual([f['path'] for f in summary['files']],['a.py','b.py'])
            self.assertEqual((summary['added'],summary['removed']),(3,1))
            self.assertEqual(len(summary['files'][0]['patches']),2)
            # Repeated polling does not double count, and later turns stay separate.
            with (root/'a.jsonl').open('a',encoding='utf-8') as f:
                for r in [{'type':'turn_context','payload':{'turn_id':'turn-b'}},change('other','c.py','+next\n'),{'type':'response_item','payload':{'type':'message','id':'answer-b','role':'assistant','phase':'final_answer','content':[{'type':'text','text':'next'}]}}]:f.write(json.dumps(r)+'\n')
            recent=store.page('codex','a',limit=1)
            self.assertEqual(recent['items'][0]['change_summary']['added'],1)
            self.assertEqual(store.page('codex','a',limit=1)['items'][0]['change_summary']['added'],1)

if __name__=='__main__':unittest.main()
