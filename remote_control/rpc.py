"""One reader resolves RPC futures immediately; notification processing is separate."""
import asyncio
import json
from contextlib import suppress

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed


class RpcError(RuntimeError):
    pass


class RpcClient:
    def __init__(self,url,token):
        self.url=url; self.token=token; self.ws=None; self.reader=None
        self.pending={}; self.counter=0; self.events=asyncio.Queue(maxsize=512); self.gap=False

    async def connect(self):
        self.ws=await connect(self.url,additional_headers={'Authorization':'Bearer '+self.token},
                              max_size=8*1024*1024,max_queue=32,open_timeout=10)
        self.reader=asyncio.create_task(self._read())

    async def _read(self):
        try:
            async for raw in self.ws:
                for line in raw.splitlines():
                    frame=json.loads(line)
                    rid=frame.get('id')
                    if rid in self.pending and 'method' not in frame:
                        future=self.pending.pop(rid)
                        if not future.done():
                            if 'error' in frame:
                                future.set_exception(RpcError(str(frame['error'].get('message','Backend RPC rejected'))))
                            else:
                                future.set_result(frame.get('result'))
                    else:
                        try:
                            self.events.put_nowait(frame)
                        except asyncio.QueueFull:
                            self.gap=True
        finally:
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(ConnectionError('Backend disconnected'))
            self.pending.clear()

    async def call(self,method,params,timeout=30):
        if not self.ws or self.reader.done():
            raise ConnectionError('Backend disconnected')
        self.counter+=1; rid=self.counter
        future=asyncio.get_running_loop().create_future(); self.pending[rid]=future
        try:
            await self.ws.send(json.dumps({'jsonrpc':'2.0','id':rid,'method':method,'params':params}))
            return await asyncio.wait_for(future,timeout)
        finally:
            self.pending.pop(rid,None)

    async def respond(self,rid,result):
        await self.ws.send(json.dumps({'jsonrpc':'2.0','id':rid,'result':result}))

    async def close(self):
        if self.ws:
            await self.ws.close()
        if self.reader:
            self.reader.cancel()
            with suppress(asyncio.CancelledError,ConnectionError,ConnectionClosed):
                await self.reader
