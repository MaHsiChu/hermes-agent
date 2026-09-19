import base64
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
import attachments
import live

class ImageContracts(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        for owner,key,value in [(attachments,'ROOT',self.root/'images'),(live,'DATA',self.root)]:
            p=patch.object(owner,key,value);p.start();self.addCleanup(p.stop)
        binding=self.root/'binding.json';binding.write_text(json.dumps({'caller_thread_id':'control'}))
        p=patch.object(live.codex_app,'BINDING',binding);p.start();self.addCleanup(p.stop)
        live.initialize()
        self.target={'engine':'codex','host_id':'local','session_id':'01a0b3a9-1834-7140-8393-0f167c52b8f1'}
        data=io.BytesIO();Image.new('RGB',(40,30),'purple').save(data,format='PNG')
        self.url='data:image/png;base64,'+base64.b64encode(data.getvalue()).decode()
    def upload(self):return attachments.upload({**self.target,'name':'../../sample.png','data_url':self.url})
    def test_raster_normalization_preview_and_scope(self):
        image=self.upload();self.assertEqual(image['name'],'sample.png')
        self.assertEqual(image['width'],40)
        result=attachments.read({**self.target,'attachment_id':image['id']})
        self.assertTrue(result['data_url'].startswith('data:image/png;base64,'))
        with self.assertRaises(ValueError):attachments.read({**self.target,'session_id':'11a0b3a9-1834-7140-8393-0f167c52b8f1','attachment_id':image['id']})
        with self.assertRaises(ValueError):attachments.read({**self.target,'attachment_id':'../../secret'})
        with self.assertRaises(ValueError):attachments.upload({**self.target,'host_id':'remote','data_url':self.url})
    def test_reject_invalid_and_changed_images(self):
        for url in ['data:image/svg+xml;base64,PHN2Zz4=','data:image/png;base64,aW52YWxpZA==','data:image/png;base64,%%%']:
            with self.assertRaises(ValueError):attachments.upload({**self.target,'data_url':url})
        image=self.upload();meta,path=attachments.resolve(self.target,image['id']);path.write_bytes(b'changed')
        with self.assertRaises(ValueError):attachments.prepare({**self.target,'attachments':[image['id']]})
        with self.assertRaises(ValueError):attachments.prepare({**self.target,'attachments':['x']*6})
    def test_image_only_delivery_retry_and_native_history_enrichment(self):
        image=self.upload();body={**self.target,'prompt':'','request_key':'image-only','attachments':[image['id']]}
        first=live.submit(body);second=live.submit(body);self.assertEqual(first['id'],second['id'])
        spec=json.loads(live.jobs()[0]['spec'])
        with patch.object(live,'snapshot',return_value={}),patch.object(live.codex_app,'call',return_value={'sent':True}) as call:
            live.deliver(live.jobs()[0]);live.deliver(live.jobs()[0])
            call.assert_called_once_with('send_message_to_thread',{'threadId':self.target['session_id'],'hostId':'local','prompt':spec['delivery_prompt']})
        page={**self.target,'items':[{'role':'peer','blocks':[{'type':'text','text':spec['delivery_prompt']}]},{'role':'assistant','blocks':[{'type':'text','text':spec['delivery_prompt']}]}]}
        result=live.enrich_transcript(page)
        self.assertTrue(result['items'][0]['local_input'])
        self.assertEqual(result['items'][0]['blocks'][0]['data']['attachment_id'],image['id'])
        self.assertNotIn('local_input',result['items'][1])
        with self.assertRaises(ValueError):live.submit({**body,'prompt':'changed'})

if __name__=='__main__':unittest.main()
