import asyncio
import time
import json
from collections import deque

from .config import source_key
from .security import digest, opaque, redact

MAX_MESSAGE_BYTES=60*1024*1024
MAX_EVENT_BYTES=1500000

class SourceSync:
    def __init__(self,bridge,backend,adapter):
        self.bridge=bridge; self.backend=backend; self.adapter=adapter
        self.source={k:getattr(backend,k) for k in ('backend_id','profile','engine')}
        self.key=source_key(self.source)
        self.rows={}; self.public={}; self.pending={}; self.sync={}
        self.publish_lock=asyncio.Lock()
        self.epochs={};self.replay_locks={}
        self.generations={};self.verify_live=set()

    def local_key(self,native):
        return digest([self.key,native])

    def request_repair(self,native,reason):
        local=self.local_key(native)
        self.bridge.state.request_repair(local,reason)
        self.sync[local]=dict(self.sync.get(local,{}),complete=False)

    async def forward(self,native,event):
        event=redact(dict(event,epoch=self.epochs[native],bridge_generation=self.generations.get(native)))
        frame={'type':'event','session_id':self.public[native],'event':event}
        if len(json.dumps(frame,ensure_ascii=False,separators=(',',':')).encode())>MAX_EVENT_BYTES:
            self.request_repair(native,'Native event exceeds the bounded relay event transport')
            frame['event']={k:event[k] for k in ('session_id','seq','epoch','bridge_generation') if k in event}
            frame['event'].update(type='history.repair',payload={'reason':'oversized_native_event','original_type':event.get('type')})
        await self.bridge.link.send(frame)

    async def publish(self,row,messages=(),sync=None,pending=None):
        async with self.publish_lock:
            chunks=[]; chunk=[]; size=0
            local=self.local_key(row['native_session_id'])
            oversized=self.bridge.state.read('oversized:'+local,{})
            for message in messages:
                encoded=len(json.dumps(message,ensure_ascii=False,separators=(',',':')).encode())
                if encoded>MAX_MESSAGE_BYTES:
                    oversized[str(message['id'])]='Message exceeds 60 MiB transfer bound; original remains on PC'
                    continue
                oversized.pop(str(message['id']),None)
                if chunk and (len(chunk)>=500 or size+encoded>1000000):
                    chunks.append(chunk);chunk=[];size=0
                chunk.append(message);size+=encoded
            if chunk or not chunks:
                chunks.append(chunk)
            self.bridge.state.write('oversized:'+local,oversized)
            effective=dict(sync or self.sync.get(local,{}))
            if oversized:
                effective.update(complete=False,error='Some source messages exceed the transfer bound',unavailable_message_ids=list(oversized))
            sid=None
            for index,chunk in enumerate(chunks):
                progress=dict(effective)
                if index<len(chunks)-1:
                    progress['complete']=False
                sid=await self._publish(row,chunk,progress,pending)
            return sid

    async def _publish(self,row,messages=(),sync=None,pending=None):
        state=self.bridge.state; local=self.local_key(row['native_session_id'])
        frame={'type':'snapshot','request_id':opaque(),'source':self.source,
               'session':dict(redact(row),revision=state.next_revision(),capabilities=self.adapter.capabilities()),
               'messages':list(messages),'sync':dict(sync or self.sync.get(local,{}),last_synced=time.time()),
               'pending_requests':pending if pending is not None else self.pending.get(local,[])}
        # Persist the exact upload before send; revisions are only acknowledged after relay commit.
        state.write('outbox:'+self.key,frame)
        ack=await self.bridge.link.request(frame,'snapshot.ack')
        state.write('outbox:'+self.key,None)
        self.public[row['native_session_id']]=ack['session_id']
        state.write('public:'+local,ack['session_id'])
        return ack['session_id']

    async def recover(self):
        frame=self.bridge.state.read('outbox:'+self.key)
        if frame:
            # Older Bridge versions may have journaled an unbounded deletion page.
            # Repartition on recovery instead of replaying a permanently invalid frame.
            await self.publish(frame['session'],frame.get('messages',[]),frame.get('sync'),frame.get('pending_requests'))
        # A crash can occur after updating a row revision but before creating its outbox.
        # Re-send journaled rows once on reconnect; relay revisions make this idempotent.
        for native,row in self.bridge.state.read('catalog:'+self.key,{}).items():
            local=self.local_key(native)
            rows=self.bridge.state.message_rows(local)
            for start in range(0,len(rows),100):
                await self.publish(row,rows[start:start+100],sync={'complete':False,'recovering':True})
            checkpoint=self.bridge.state.read('scan:'+local)
            if checkpoint and checkpoint.get('finished') and not self.bridge.state.read('repair:'+local):
                await self.publish(row,sync=checkpoint.get('sync',{'complete':True}))

    async def cycle(self):
        catalog=[]
        async for row in self.adapter.catalog():
            catalog.append(row)
        complete=getattr(self.adapter,'catalog_complete',True)
        previous=self.bridge.state.read('catalog:'+self.key,{})
        self.rows={r['native_session_id']:r for r in catalog}
        if complete:
            for native,row in previous.items():
                if native not in self.rows and not await self.adapter.exists(native):
                    await self.publish(dict(row,deleted=True),sync={'complete':True,'deleted':True})
        self.bridge.state.write('catalog:'+self.key,self.rows)
        older=deque()
        # Recent history for EVERY source session is visible before long-session backfills.
        for row in catalog:
            native=row['native_session_id']; local=self.local_key(native)
            self.public[native]=self.bridge.state.read('public:'+local)
            if not self.public[native]:
                await self.publish(row,sync={'complete':False,'catalog_complete':complete})
            if self.backend.engine=='hermes' and (row.get('is_active') or native in self.adapter.runtime):
                snapshot=await self.adapter.attach(native,row.get('source'))
                row['status']=snapshot.get('status','unknown')
                self.pending[local]=[redact(p) for p in snapshot.get('open_requests',[]) if p['method'] in {'approval','clarify'}]
                await self.replay(row)
            checkpoint=self.bridge.state.read('scan:'+local)
            repair=self.bridge.state.read('repair:'+local)
            evidence=digest([row.get(k) for k in ('updated_at','last_active','message_count','tool_call_count','path','history_mode')])
            if checkpoint and checkpoint.get('finished') and not repair and hasattr(self.adapter,'changed'):
                if await self.adapter.changed(native,checkpoint):
                    self.request_repair(native,'Hub transcript revision or source generation changed')
                    checkpoint=None
                    repair=self.bridge.state.read('repair:'+local)
            if checkpoint and checkpoint.get('finished') and checkpoint.get('evidence')==evidence and not repair:
                self.sync[local]=checkpoint.get('sync',{'complete':True,'catalog_complete':complete})
                pending=self.pending.get(local,[])
                metadata=digest([row,pending,self.adapter.capabilities(),complete])
                if self.bridge.state.read('metadata:'+local)!=metadata:
                    await self.publish(row)
                    self.bridge.state.write('metadata:'+local,metadata)
                continue
            recent,_,info=await self.adapter.history(native,recent=True)
            from .bridge_attachments import rewrite_images
            self.current_native=native
            recent=await rewrite_images(self,recent)
            generation=info.get('generation')
            if (not checkpoint or checkpoint.get('finished') or checkpoint.get('evidence')!=evidence
                or checkpoint.get('generation')!=generation):
                checkpoint={'scan':opaque(),'offset':0 if self.backend.engine=='hermes' else '', 'finished':0,
                            'generation':generation,'revision':info.get('revision'),'evidence':evidence,'repair':repair}
            changes=self.bridge.state.revise(local,recent,scan=checkpoint['scan'])
            self.sync[local]={'complete':bool(checkpoint.get('finished')),'catalog_complete':complete,
                              'offset':checkpoint['offset'],'total':info.get('total')}
            await self.publish(row,changes)
            if not checkpoint.get('finished'):
                self.bridge.state.write('scan:'+local,checkpoint)
                older.append((row,checkpoint))
        while older:
            row,checkpoint=older.popleft(); native=row['native_session_id']; local=self.local_key(native)
            messages,next_offset,info=await self.adapter.history(native,checkpoint['offset'])
            if info.get('generation')!=checkpoint.get('generation') or info.get('revision')!=checkpoint.get('revision'):
                self.bridge.state.write('scan:'+local,None)
                raise ValueError('Source history generation changed during scan; restart required')
            self.current_native=native
            messages=await rewrite_images(self,messages)
            done=next_offset is None
            changes=self.bridge.state.revise(local,messages,complete=done,scan=checkpoint['scan'])
            checkpoint['offset']=next_offset
            checkpoint['finished']=time.time() if done else 0
            self.sync[local]={'complete':done,'catalog_complete':complete,'offset':next_offset,'total':info.get('total')}
            await self.publish(row,changes)
            checkpoint['sync']=self.sync[local]
            self.bridge.state.write('scan:'+local,checkpoint)
            if done:
                if self.bridge.state.read('repair:'+local)==checkpoint.get('repair'):
                    self.bridge.state.write('repair:'+local,None)
                metadata=digest([row,self.pending.get(local,[]),self.adapter.capabilities(),complete])
                self.bridge.state.write('metadata:'+local,metadata)
            if not done:
                older.append((row,checkpoint))
            await asyncio.sleep(0)

    async def replay(self,row):
        lock=self.replay_locks.setdefault(row['native_session_id'],asyncio.Lock())
        async with lock:
            return await self._replay(row)

    async def _replay(self,row):
        native=row['native_session_id']; local=self.local_key(native)
        previous=self.bridge.state.read('event:'+local,{'seq':0,'epoch':None})
        runtime=self.adapter.runtime[native]
        replay=await self.adapter.replay(native,previous['seq'])
        epoch=replay['epoch']
        if not isinstance(epoch,str) or not epoch:
            raise ValueError('Native replay epoch is required')
        identity_changed=previous['epoch']!=epoch or previous.get('runtime_id')!=runtime
        native_generation=replay.get('replay_generation')
        if native_generation is not None and (not isinstance(native_generation,str) or not native_generation):
            raise ValueError('Invalid native replay generation')
        ring_changed=native_generation!=previous.get('native_generation')
        rollback=not identity_changed and replay['latest_seq']<previous['seq']
        generation=previous.get('generation') or opaque()
        if previous['seq'] and (identity_changed or ring_changed or rollback):
            # An old high watermark otherwise hides every event from a restarted PC.
            replay=await self.adapter.replay(native,0)
            if replay['epoch']!=epoch or replay.get('replay_generation')!=native_generation:
                raise ConnectionError('Native replay identity changed during repair')
        needs_repair=replay['truncated'] or (previous['seq'] and (identity_changed or ring_changed or rollback)) or self.adapter.rpc.gap
        if needs_repair:
            self.request_repair(native,'Native replay gap or sequence identity changed')
            self.adapter.rpc.gap=False
        if rollback or (previous['seq'] and (identity_changed or ring_changed)):
            generation=opaque()
            self.verify_live.add(native)
        pending=[redact(p) for p in replay.get('open_requests',[]) if p['method'] in {'approval','clarify'}]
        control_changed=pending!=self.pending.get(local,[]) or any(event.get('type') in {
            'request.cancel','message.complete','agent.complete','turn.complete','session.status'} for event in replay['events'])
        self.pending[local]=pending
        self.epochs[native]=epoch
        self.generations[native]=generation
        sid=self.public.get(native)
        if sid:
            if needs_repair:
                await self.forward(native,{'session_id':runtime,'type':'history.repair','payload':{'reason':'native_replay_gap'}})
            for event in replay['events']:
                await self.forward(native,event)
                if event.get('type') in {'message.complete','agent.complete','turn.complete'}:
                    self.request_repair(native,'Native completion changed persisted history')
        self.bridge.state.write('event:'+local,{'seq':replay['latest_seq'],'epoch':replay['epoch'],'runtime_id':runtime,'generation':generation,
                                               'native_generation':native_generation,
                                               'verify_live':native in self.verify_live or previous.get('verify_live',False)})
        return control_changed

    async def live_event(self,native,params):
        lock=self.replay_locks.setdefault(native,asyncio.Lock())
        async with lock:
            if native not in self.epochs:
                await self._replay(self.rows[native])
            local=self.local_key(native)
            previous=self.bridge.state.read('event:'+local,{'seq':0})
            seq=params.get('seq')
            # Live seq is only a hint; replay.latest_seq decides rollback. After rollback,
            # authoritative replay also rejects delayed frames from the former ring.
            if params.get('replay_generation')!=previous.get('native_generation') or previous.get('verify_live') or native in self.verify_live or (type(seq) is int and seq!=previous['seq']+1):
                if await self._replay(self.rows[native]):
                    await self.publish(self.rows[native])
                return
            await self.forward(native,params)
            if type(seq) is int:
                self.bridge.state.write('event:'+local,dict(previous,seq=seq))
            kind=params.get('type','')
            if kind in {'request.cancel','message.complete','agent.complete','turn.complete','session.status'}:
                if kind in {'message.complete','agent.complete','turn.complete'}:
                    self.request_repair(native,'Native completion changed persisted history')
                await self._replay(self.rows[native])
                await self.publish(self.rows[native])

    async def events(self):
        rpc=self.adapter.rpc
        while True:
            frame=await rpc.events.get()
            params=frame.get('params',{}); runtime=params.get('session_id')
            native=next((n for n,r in self.adapter.runtime.items() if r==runtime),None)
            if not native or not self.public.get(native):
                continue
            method=frame.get('method')
            if method=='event':
                await self.live_event(native,params)
            elif method in {'approval','clarify'}:
                await self.replay(self.rows[native])
                await self.publish(self.rows[native])

    async def run(self):
        while True:
            event_task=None
            try:
                if self.backend.engine=='hermes':
                    self.epochs.clear()
                    # Frames buffered by the old reader must never inherit a new epoch.
                    while not self.adapter.rpc.events.empty():
                        self.adapter.rpc.events.get_nowait()
                await self.adapter.connect(); await self.recover()
                if self.backend.engine=='hermes':
                    event_task=asyncio.create_task(self.events())
                while True:
                    await self.cycle()
                    if event_task and event_task.done():
                        await event_task
                    await asyncio.sleep(self.bridge.config.poll_seconds)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.adapter.online=False
                await self.bridge.link.send({'type':'heartbeat','sources':[{'source':self.source,'online':False}]})
                # Do not emit exception URLs (native WS URLs contain a token).
                print('Source unavailable:',self.key,type(exc).__name__,flush=True)
                await asyncio.sleep(3)
            finally:
                if event_task:
                    event_task.cancel()
                    await asyncio.gather(event_task,return_exceptions=True)
                if self.backend.engine=='hermes':
                    await self.adapter.rpc.close()
