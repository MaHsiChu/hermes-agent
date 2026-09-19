"""Session-scoped raster uploads for the local original-App transport."""
import base64
import hashlib
import io
import json
from pathlib import Path
import uuid
from PIL import Image, ImageOps

ROOT=Path(__file__).resolve().parent/'data/attachments'
MAX_BYTES=8*1024*1024

def folder(body):
    if body.get('engine') not in ('codex','claude') or body.get('host_id','local') not in ('local',None,''):
        raise ValueError('图片附件目前仅支持本机 Codex / Claude 原任务。')
    sid=str(uuid.UUID(body['session_id']))
    return ROOT/sid if body['engine']=='codex' else ROOT/'claude'/sid

def upload(body):
    directory=folder(body)
    value=body.get('data_url','')
    if not isinstance(value,str) or len(value)>MAX_BYTES*4//3+200:
        raise ValueError('每张图片最多 8 MB。')
    if not value.startswith(('data:image/png;base64,','data:image/jpeg;base64,','data:image/webp;base64,')):
        raise ValueError('支持 PNG、JPEG、WebP 图片。')
    try:
        raw=base64.b64decode(value.split(',',1)[1],validate=True)
        if len(raw)>MAX_BYTES:raise ValueError('每张图片最多 8 MB。')
        with Image.open(io.BytesIO(raw)) as source:
            if source.format not in ('PNG','JPEG','WEBP') or source.width*source.height>32_000_000:
                raise ValueError('图片格式不支持或尺寸超过 3200 万像素。')
            if getattr(source,'is_animated',False):raise ValueError('请使用静态图片。')
            source.load()
            raster=ImageOps.exif_transpose(source).convert('RGBA')
    except (OSError,Image.DecompressionBombError) as e:
        raise ValueError('无法解码这张图片。') from e
    uid=uuid.uuid4().hex
    directory.mkdir(parents=True,exist_ok=True)
    path=directory/(uid+'.png')
    raster.save(path)
    thumb=raster.copy();thumb.thumbnail((240,180));buffer=io.BytesIO();thumb.save(buffer,format='PNG')
    name=Path(str(body.get('name') or 'image.png').replace('\\','/')).name[:120]
    meta={'id':uid,'name':name,'width':raster.width,'height':raster.height,
          'thumbnail':'data:image/png;base64,'+base64.b64encode(buffer.getvalue()).decode(),
          'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    (directory/(uid+'.json')).write_text(json.dumps(meta,ensure_ascii=False),encoding='utf-8')
    return {k:v for k,v in meta.items() if k!='sha256'}

def resolve(body,identity):
    uid=uuid.UUID(identity).hex
    directory=folder(body);path=directory/(uid+'.png')
    try:meta=json.loads((directory/(uid+'.json')).read_text(encoding='utf-8'))
    except (OSError,ValueError) as e:raise ValueError('图片附件不存在或不属于这个任务。') from e
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=meta['sha256']:
        raise ValueError('图片附件已变化，请重新插入。')
    return meta,path.resolve()

def read(body):
    meta,path=resolve(body,body['attachment_id'])
    return {'data_url':'data:image/png;base64,'+base64.b64encode(path.read_bytes()).decode()}

def prepare(body):
    ids=body.get('attachments') or []
    if not isinstance(ids,list) or len(ids)>5 or any(not isinstance(i,str) for i in ids):
        raise ValueError('每条消息最多 5 张图片。')
    if not ids:return []
    return [{**meta,'path':str(path)} for meta,path in (resolve(body,i) for i in dict.fromkeys(ids))]

def delivery_prompt(prompt,images):
    if not images:return prompt
    paths='\n'.join(f'{i+1}. {image["path"]}' for i,image in enumerate(images))
    return (prompt+'\n\n[Images attached from Hermes]\n'+paths+
            '\nUse your available image-viewing tool to inspect these local images before answering. '
            'If you cannot open them, say so explicitly; do not infer their contents from filenames.').strip()
