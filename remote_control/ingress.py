"""Bound request bodies before multipart spooling and unauthenticated pairing writes."""
import time

from fastapi import HTTPException
from starlette.responses import JSONResponse


class IngressLimits:
    def __init__(self,app,attachment_limit):
        self.app=app;self.attachment_limit=attachment_limit;self.pairing_requests={}

    async def __call__(self,scope,receive,send):
        if scope['type']!='http':
            return await self.app(scope,receive,send)
        headers=dict(scope.get('headers',[]))
        limit=self.attachment_limit+65536 if '/attachments' in scope['path'] else 262144
        if scope['path']=='/api/remote/bridge/snapshot':
            limit=64*1024*1024
        try:
            declared=int(headers.get(b'content-length',b'0'))
        except ValueError:
            return await JSONResponse({'detail':'Invalid content length'},400)(scope,receive,send)
        if declared<0 or declared>limit:
            return await JSONResponse({'detail':'Request body too large'},413)(scope,receive,send)
        if scope['method']=='POST' and scope['path']=='/api/remote/pairings':
            now=time.monotonic()
            self.pairing_requests={k:v for k,v in self.pairing_requests.items() if now-v[0]<60}
            key=(scope.get('client') or ('unknown',0))[0]
            started,count=self.pairing_requests.get(key,(now,0))
            if count>=20 or len(self.pairing_requests)>=4096:
                return await JSONResponse({'detail':'Pairing rate limit; retry later'},429)(scope,receive,send)
            self.pairing_requests[key]=(started,count+1)
        size=0
        async def bounded_receive():
            nonlocal size
            message=await receive()
            size+=len(message.get('body',b''))
            if size>limit:
                raise HTTPException(413,'Request body too large')
            return message
        await self.app(scope,bounded_receive,send)
