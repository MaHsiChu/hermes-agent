import asyncio
import json
from contextlib import suppress

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed
import httpx


class RelayLink:
    def __init__(self,config,credential):
        self.config=config; self.credential=credential; self.ws=None
        self.pending={}; self.commands=asyncio.Queue(maxsize=32); self.reader=None

    async def connect(self):
        url=self.config.relay_url.replace('https://','wss://').replace('http://','ws://')+'/api/remote/bridge'
        self.ws=await connect(url,additional_headers={'Authorization':'Bearer '+self.credential['device_token']},
                              max_size=2*1024*1024,max_queue=32,open_timeout=10)
        welcome=json.loads(await asyncio.wait_for(self.ws.recv(),10))
        if welcome.get('device_id')!=self.credential['device_id']:
            raise ValueError('Relay device identity mismatch')
        self.allowed=welcome['allowed_sources']
        self.upload_lease=welcome.get('upload_lease')
        self.reader=asyncio.create_task(self.read())

    async def read(self):
        try:
            async for raw in self.ws:
                frame=json.loads(raw); kind=frame.get('type'); rid=frame.get('request_id')
                if kind=='command':
                    try:
                        self.commands.put_nowait(frame)
                    except asyncio.QueueFull:
                        await self.ws.close(code=1013,reason='Command buffer full; reconcile receipt')
                        return
                else:
                    future=self.pending.get((kind,rid))
                    if future and not future.done():
                        future.set_result(frame)
                    if kind=='error':
                        for (expected,pending_id),future in self.pending.items():
                            if pending_id==rid and not future.done():
                                future.set_exception(ValueError(frame['error']))
        finally:
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(ConnectionError('Relay disconnected'))

    async def send(self,frame):
        await self.ws.send(json.dumps(frame,separators=(',',':'),ensure_ascii=False))

    async def request(self,frame,expected):
        encoded=json.dumps(frame,separators=(',',':'),ensure_ascii=False).encode()
        if frame.get('type')=='snapshot' and len(encoded)>1500000:
            async with httpx.AsyncClient(base_url=self.config.relay_url,timeout=60) as http:
                response=await http.post('/api/remote/bridge/snapshot',content=encoded,headers={
                    'Authorization':'Bearer '+self.credential['device_token'],
                    'X-Remote-Bridge-Lease':self.upload_lease or '', 'Content-Type':'application/json'})
                response.raise_for_status()
                return response.json()
        key=(expected,frame.get('request_id'))
        future=asyncio.get_running_loop().create_future(); self.pending[key]=future
        try:
            await self.send(frame)
            return await asyncio.wait_for(future,30)
        finally:
            self.pending.pop(key,None)

    async def close(self):
        if self.ws:
            await self.ws.close()
        if self.reader:
            self.reader.cancel()
            with suppress(asyncio.CancelledError,ConnectionClosed):
                await self.reader
