"""Content-validated image storage; no arbitrary remote path or URL endpoint."""
import io
from pathlib import Path

from fastapi import HTTPException
from PIL import Image

from . import db
from .security import require,opaque


def save_image(store,sid,name,content):
    require(len(content)<=store.config.attachment_limit,413,'Image too large')
    try:
        with Image.open(io.BytesIO(content)) as image:
            mime=Image.MIME.get(image.format)
            require(image.width*image.height<=40000000,413,'Image pixel limit exceeded')
            image.verify()
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(415,'Invalid image') from None
    require(mime in {'image/png','image/jpeg','image/webp','image/gif'},415,'Unsupported image type')
    aid=opaque(); name=(name or 'image').replace('\\','/').split('/')[-1][:255]
    with store.transaction() as c:
        c.execute(db.attachments.insert().values(id=aid,session_id=sid,name=name,mime=mime,size=len(content),data=content))
    return {'id':aid,'name':name,'mime':mime,'size':len(content)}


def authorized_image(path,roots,limit):
    candidate=Path(path).resolve(strict=True)
    if not any(candidate.is_relative_to(Path(root).resolve(strict=True)) for root in roots):
        raise ValueError('Image is outside explicitly authorized attachment roots')
    if not candidate.is_file() or candidate.stat().st_size>limit:
        raise ValueError('Image missing or exceeds transfer limit')
    with candidate.open('rb') as f:
        content=f.read(limit+1)
    if len(content)>limit:
        raise ValueError('Image exceeds transfer limit')
    return candidate.name,content
