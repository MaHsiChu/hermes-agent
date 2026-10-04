import copy
import json
import re
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import url2pathname

import httpx

from .attachments import authorized_image
from .security import digest


IMAGE_LINE=re.compile(r'^@image:([^\r\n]*)\r?\n?',re.M)
SCREENSHOT_LINE=re.compile(r'^\[screenshot\]\r?\n?',re.M)


def native_image_content(content):
    """Mirror persisted desktop directive lines without importing the agent runtime."""
    if isinstance(content,list):
        parts=[]
        for part in content:
            if isinstance(part,dict) and part.get('type')=='text' and isinstance(part.get('text'),str):
                converted=native_image_content(part['text'])
                parts.extend(converted if isinstance(converted,list) else [part])
            else:
                parts.append(part)
        return parts
    if not isinstance(content,str):
        return content
    refs=[]
    def extract(match):
        raw=match[1].strip()
        # Same wrappers emitted by agent.context_references.format_reference_value.
        if len(raw)>=2 and raw[0]==raw[-1] and raw[0] in '`"\'':
            raw=raw[1:-1]
        path=Path(raw)
        if raw.startswith(('\\\\','//')) or not path.is_absolute():
            refs.append({'type':'attachment','kind':'image','status':'unavailable','reason':'Only authorized absolute local image paths can be exported'})
        else:
            refs.append({'type':'image_url','image_url':{'url':path.as_uri()}})
        return ''
    text=IMAGE_LINE.sub(extract,content)
    if not refs:
        return content
    text=SCREENSHOT_LINE.sub('',text)
    return ([{'type':'text','text':text}] if text else [])+refs


async def rewrite_images(sync,rows):
    serialized=json.dumps(rows)
    native_refs=getattr(sync.backend,'engine',None)=='hermes' and '@image:' in serialized
    if 'file:' not in serialized and not native_refs:
        return rows
    native=sync.current_native
    sid=sync.public.get(native)
    if not sid:
        return rows
    async with httpx.AsyncClient(base_url=sync.bridge.config.relay_url,
        headers={'Authorization':'Bearer '+sync.bridge.credential['device_token']},timeout=30) as http:
        async def visit(value):
            if isinstance(value,list):
                return [await visit(x) for x in value]
            if not isinstance(value,dict):
                return value
            raw=value.get('image_url') if value.get('type')=='image_url' else None
            url=raw.get('url') if isinstance(raw,dict) else raw
            if isinstance(url,str) and url.startswith('file:'):
                parsed=urlsplit(url)
                if parsed.netloc:
                    return {'type':'attachment','status':'unavailable','reason':'Network file paths are not authorized'}
                try:
                    name,content=authorized_image(url2pathname(parsed.path),sync.backend.attachment_roots,8*1024*1024)
                    key='asset:'+digest([sid,digest(content.hex())])
                    asset=sync.bridge.state.read(key)
                    if not asset:
                        response=await http.post('/api/remote/bridge/attachments/'+sid,files={'file':(name,content)})
                        response.raise_for_status();asset=response.json();sync.bridge.state.write(key,asset)
                    return {'type':'attachment','kind':'image','id':asset['id'],'name':asset['name'],
                            'mime':asset['mime'],'url':f"/api/remote/sessions/{sid}/attachments/{asset['id']}",'status':'available'}
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code not in {413,415}:
                        raise
                    return {'type':'attachment','kind':'image','status':'unavailable','reason':'Source image content is invalid, unsupported, or exceeds image limits'}
                except (ValueError,OSError):
                    return {'type':'attachment','kind':'image','status':'unavailable','reason':'Local image is outside allowed roots, missing, or too large'}
            return {k:await visit(v) for k,v in value.items()}
        result=[]
        for row in rows:
            value=copy.deepcopy(row)
            if native_refs and 'content' in value:
                value['content']=native_image_content(value['content'])
            result.append(await visit(value))
        return result
