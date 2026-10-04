import argparse
import asyncio
import json
import os
import time
import webbrowser
from pathlib import Path

import httpx
import portalocker

from .config import BridgeConfig, load, source_key
from .bridge_state import BridgeState
from .relay_link import RelayLink
from .bridge_sync import SourceSync
from .protocol import validate_payload
from .security import digest,redact


def write_credential(path,value):
    target=Path(path); target.parent.mkdir(parents=True,exist_ok=True)
    flags=os.O_WRONLY|os.O_CREAT|os.O_EXCL
    fd=os.open(target,flags,0o600)
    with os.fdopen(fd,'w',encoding='utf-8') as f:
        json.dump(value,f)
    if os.name=='nt':
        # Files inherit the user's directory ACL; deployment docs require a private user directory.
        # Never shell-expand a username or credential into an ACL command.
        pass


async def pair(config):
    if Path(config.credential_file).exists():
        raise ValueError('Credential file exists; revoke the old device before pairing another account')
    sources=[{k:getattr(b,k) for k in ('backend_id','profile','engine')} for b in config.backends]
    print('Requested synchronization sources (backend credentials stay on this PC):')
    for source in sources:
        print('  ',source_key(source))
    async with httpx.AsyncClient(base_url=config.relay_url,timeout=20) as client:
        response=await client.post('/api/remote/pairings',json={'name':config.device_name,'sources':sources})
        response.raise_for_status(); p=response.json()
        print('Open',p['verification_uri'],'and verify code',p['user_code'],'before approving sources.')
        webbrowser.open(p['verification_uri'])
        deadline=time.monotonic()+p['expires_in']
        while time.monotonic()<deadline:
            await asyncio.sleep(3)
            response=await client.post('/api/remote/pairings/'+p['pairing_id']+'/exchange',json={'device_code':p['device_code']})
            response.raise_for_status(); value=response.json()
            if value['status']=='approved':
                value['relay_url']=config.relay_url
                write_credential(config.credential_file,value)
                print('Device paired:',value['device_id'],'; credentials saved privately. Start Bridge to sync.')
                return
    raise TimeoutError('Pairing expired; no session content was synchronized')


class Bridge:
    def __init__(self,config):
        self.config=config
        self.credential=json.loads(Path(config.credential_file).read_text(encoding='utf-8'))
        if self.credential.get('relay_url')!=config.relay_url:
            raise ValueError('Credential belongs to a different relay')
        Path(config.state_file).parent.mkdir(parents=True,exist_ok=True)
        self.state=BridgeState(config.state_file); self.link=None; self.sources={}; self.locks={}

    async def heartbeat(self):
        while True:
            await self.link.send({'type':'heartbeat','sources':[{'source':s.source,'online':s.adapter.online} for s in self.sources.values()]})
            await asyncio.sleep(15)

    async def reconcile(self):
        for receipt in self.state.receipts():
            response=await self.link.request({'type':'receipt.query','request_id':receipt['request_id']},'receipt.status')
            if response['state']=='unknown' or response['digest']!=receipt['digest']:
                continue
            if receipt['state']=='received':
                receipt=self.state.mark(receipt['request_id'],'failed',error='Bridge restarted before dispatch; submit a new request explicitly')
            await self.link.request(dict(receipt,type='receipt'),'receipt.ack')

    async def execute(self,command):
        rid=command.get('request_id',''); old=self.state.get(rid)
        try:
            key=source_key(command['source']); source=self.sources.get(key)
            if command['device_id']!=self.credential['device_id'] or not source:
                raise ValueError('Foreign device or unpaired source')
            if command['digest']!=digest([command['session_id'],command['operation'],command['payload']]):
                raise ValueError('Command digest mismatch')
            if old:
                if old['digest']!=command['digest']:
                    raise ValueError('Request payload differs')
                await self.link.request(dict(old,type='receipt'),'receipt.ack')
                return
            receipt=self.state.begin(command)
            if command['expires_at']<=time.time():
                raise ValueError('Command expired; no offline execution')
            native=command['native_session_id']; known=source.rows.get(native)
            if not known or source.public.get(native)!=command['session_id']:
                raise ValueError('Original session identity is not synchronized')
            validate_payload(command['operation'],command['payload'])
            await self.link.request(dict(receipt,type='receipt'),'receipt.ack')
            lock=self.locks.setdefault((key,native),asyncio.Lock())
            async with lock:
                if command['expires_at']<=time.time() or not source.adapter.online:
                    raise ValueError('Command expired or backend offline before dispatch')
                images=[]
                async with httpx.AsyncClient(base_url=self.config.relay_url,headers={'Authorization':'Bearer '+self.credential['device_token']},timeout=20) as http:
                    for aid in command['payload'].get('attachment_ids',[]):
                        response=await http.get(f"/api/remote/bridge/attachments/{command['session_id']}/{aid}")
                        response.raise_for_status()
                        if len(response.content)>8*1024*1024:
                            raise ValueError('Attachment exceeds PC limit')
                        images.append((aid,response.content))
                command['native_source']=known.get('source')
                await source.adapter.prepare(command)
                if command['expires_at']<=time.time():
                    raise ValueError('Command expired during backend preflight')
                self.state.mark(rid,'dispatching')
                state,result=await source.adapter.execute(command,images)
                receipt=self.state.mark(rid,state,result=redact(result))
        except asyncio.CancelledError:
            if self.state.get(rid) and self.state.get(rid)['state']=='dispatching':
                self.state.mark(rid,'delivery_uncertain',error='Connection ended during dispatch; inspect original session')
            raise
        except Exception as exc:
            record=self.state.get(rid)
            if not record:
                # Invalid source/digest commands never enter the executable journal.
                return
            uncertain=record['state']=='dispatching'
            receipt=self.state.mark(rid,'delivery_uncertain' if uncertain else 'failed',
                                    error=str(exc) if isinstance(exc,ValueError) else type(exc).__name__)
        await self.link.request(dict(receipt,type='receipt'),'receipt.ack')

    async def workers(self):
        # Four bounded consumers; the session lock guarantees one writer independently of source.
        async def worker():
            while True:
                command=await self.link.commands.get()
                await self.execute(command)
        await asyncio.gather(*(worker() for _ in range(4)))

    async def connected(self):
        from .adapters.hermes import HermesAdapter
        from .adapters.hub import HubAdapter
        approved={source_key(s) for s in self.link.allowed}
        local_approved={source_key(s) for s in self.credential['allowed_sources']}
        self.sources={}
        for backend in self.config.backends:
            key=source_key(backend.model_dump())
            if key not in approved or key not in local_approved:
                continue
            adapter=HermesAdapter(backend) if backend.engine=='hermes' else HubAdapter(backend)
            self.sources[key]=SourceSync(self,backend,adapter)
        await self.reconcile()
        tasks=[asyncio.create_task(s.run()) for s in self.sources.values()]
        tasks.extend([asyncio.create_task(self.heartbeat()),asyncio.create_task(self.workers())])
        tasks.append(self.link.reader)
        try:
            done,_=await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                await task
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
            await asyncio.gather(*(s.adapter.close() for s in self.sources.values()),return_exceptions=True)

    async def run(self):
        while True:
            self.link=RelayLink(self.config,self.credential)
            try:
                await self.link.connect(); await self.connected()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                print('Relay disconnected:',type(exc).__name__,'; no command will be retried automatically',flush=True)
            finally:
                await self.link.close()
            await asyncio.sleep(3)


def repair_history(config,source,native):
    """Schedule an explicit full scan of one configured, paired, already-known identity."""
    credential=json.loads(Path(config.credential_file).read_text(encoding='utf-8'))
    key=source_key(source)
    backend=next((b for b in config.backends if source_key(b.model_dump())==key),None)
    if credential.get('relay_url')!=config.relay_url or not backend or key not in {source_key(s) for s in credential['allowed_sources']}:
        raise ValueError('Source must be configured and paired on this device')
    state=BridgeState(config.state_file)
    if native not in state.read('catalog:'+key,{}):
        raise ValueError('Session must already be synchronized for this source')
    state.request_repair(digest([key,native]),'Explicit operator history audit')


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--config',required=True)
    parser.add_argument('action',choices=['run','pair','repair'],nargs='?',default='run')
    parser.add_argument('--backend-id');parser.add_argument('--profile');parser.add_argument('--engine',choices=['hermes','codex','claude']);parser.add_argument('--session-id')
    args=parser.parse_args(); config=load(args.config,BridgeConfig)
    if args.action=='pair':
        asyncio.run(pair(config)); return
    with portalocker.Lock(config.state_file+'.lock',timeout=0):
        if args.action=='repair':
            if not all((args.backend_id,args.profile,args.engine,args.session_id)):
                parser.error('repair requires --backend-id, --profile, --engine and --session-id')
            repair_history(config,{'backend_id':args.backend_id,'profile':args.profile,'engine':args.engine},args.session_id)
            print('History repair scheduled; start Bridge to reconcile the original session.')
        else:
            asyncio.run(Bridge(config).run())


if __name__=='__main__':
    main()
