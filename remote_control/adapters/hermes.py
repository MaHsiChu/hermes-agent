import base64
import json
from urllib.parse import quote, urlencode

import httpx

from ..rpc import RpcClient, RpcError
from ..security import redact


def validate_answer(request,payload):
    p=request['params']
    if request['method']=='approval':
        if payload.get('choice') not in p.get('choices',[]):
            raise ValueError('Approval choice is no longer offered')
        return {'choice':payload['choice']}
    if request['method']!='clarify':
        raise ValueError('Secret and unsupported prompts stay local')
    questions=p.get('questions')
    if questions:
        answers=payload.get('answers',{})
        if set(answers)!= {q['qid'] for q in questions}:
            raise ValueError('Answer every original question')
        for q in questions:
            answer=answers[q['qid']]
            if q['qid'] in p.get('answers',{}) and answer!=p['answers'][q['qid']]:
                raise ValueError('Question already locked')
            validate_choice(q,answer)
        return {'answers':answers}
    answer=payload.get('answer')
    validate_choice(p,answer)
    return {'answer':answer}


def validate_choice(question,answer):
    if not isinstance(answer,str) or len(answer)>60000:
        raise ValueError('Invalid answer')
    # The native clarify contract permits freeform answers alongside suggested choices.
    # Multi-select uses the same serialized string as the original renderer.


class HermesAdapter:
    def __init__(self,config):
        self.config=config; self.token=config.token.read(); self.runtime={}; self.snapshots={}
        self.http=httpx.AsyncClient(base_url=config.url,headers={'Authorization':'Bearer '+self.token},timeout=30)
        url=config.url.replace('https://','wss://').replace('http://','ws://')+'/api/ws'
        # Hermes' legacy WS authentication reads a query token, unlike its REST Bearer path.
        self.rpc=RpcClient(url+'?'+urlencode({'token':self.token}),self.token)
        self.online=False
        self.gateway_caps={}

    async def connect(self):
        self.online=False
        self.gateway_caps={}
        # Electron rotates its Secret at backend restart. Endpoint changes still require config refresh.
        self.token=self.config.token.read()
        self.http.headers['Authorization']='Bearer '+self.token
        url=self.config.url.replace('https://','wss://').replace('http://','ws://')+'/api/ws'
        self.rpc.url=url+'?'+urlencode({'token':self.token})
        self.rpc.token=self.token
        await self.rpc.connect()
        await self.rpc.call('client.capabilities',{'server_requests':True})
        try:
            caps=await self.rpc.call('gateway.capabilities',{})
            self.gateway_caps=caps if isinstance(caps,dict) else {}
        except RpcError:
            # Older backends may not implement the feature probe. History/control remain usable.
            self.gateway_caps={}
        self.online=True

    async def close(self):
        self.online=False; await self.rpc.close(); await self.http.aclose()

    async def catalog(self):
        offset=0; seen=set()
        while True:
            response=await self.http.get('/api/sessions',params={'profile':self.config.profile,'archived':'include',
                'order':'created','offset':offset,'limit':100})
            response.raise_for_status(); page=response.json()
            for row in page['sessions']:
                if row.get('profile')!=self.config.profile:
                    raise ValueError('Backend returned a foreign profile')
                if row['id'] in seen:
                    continue
                seen.add(row['id'])
                # Native pages append off-page pins; activity is a source timestamp, not sync time.
                activity=row.get('last_active') or row.get('started_at') or 0
                yield dict(row,native_session_id=row['id'],updated_at=float(activity))
            offset+=page['limit']
            if offset>=page['total']:
                return
            if not page['sessions']:
                raise ValueError('Incomplete backend catalog')

    async def history(self,native,offset=0,recent=False):
        response=await self.http.get('/api/sessions/'+quote(native,safe='')+'/messages',params={
            'profile':self.config.profile,'limit':100,'offset':offset,'order':'latest' if recent else 'oldest','include_compacted':'true'})
        response.raise_for_status(); page=response.json()
        if page.get('profile')!=self.config.profile:
            raise ValueError('Backend history profile mismatch')
        rows=[]
        for raw in page['messages']:
            mid=raw.get('id',raw.get('_row_id'))
            if mid is None:
                raise ValueError('Backend message has no stable row identity')
            rows.append(dict(redact(raw),id=str(mid),ordinal=float(mid)))
        return rows, (offset+len(rows) if len(rows)==100 else None), {'complete':len(rows)<100}

    async def attach(self,native,source=None):
        params={'session_id':native,'profile':self.config.profile,'lazy':True,'omit_messages':True,'close_on_disconnect':False}
        if source:
            params['source']=source
        snapshot=await self.rpc.call('session.resume',params)
        runtime=snapshot['session_id']; self.runtime[native]=runtime; self.snapshots[native]=snapshot
        return snapshot

    async def replay(self,native,last_seen=0):
        runtime=self.runtime[native]
        return await self.rpc.call('session.events.since',{'session_id':runtime,'profile':self.config.profile,'last_seen':last_seen})

    def capabilities(self):
        caps={k:{'status':'supported'} for k in ('history','steer','interrupt','approval','clarify')}
        safe=(self.gateway_caps.get('request_owned_prompt_images') is True
              and self.gateway_caps.get('prompt_reject_if_busy') is True)
        reason='Backend has not advertised atomic request-owned images and busy rejection; update/reconnect the native backend'
        for operation in ('send','queue'):
            caps[operation]={'status':'supported'} if safe else {'status':'unavailable','reason':reason}
        limits={key:self.gateway_caps.get(key) for key in (
            'prompt_image_max_count','prompt_image_max_total_bytes','prompt_image_max_request_bytes')}
        uploads=(safe and self.gateway_caps.get('prompt_image_uploads') is True
                 and all(type(value) is int and value>0 for value in limits.values()))
        caps['attachments']=({'status':'supported'} if uploads else {'status':'unavailable',
            'reason':reason if not safe else 'Backend image validation or upload limits are unavailable'})
        return caps

    def _require_submit_capability(self, operation, has_images=False):
        caps=self.capabilities()
        for feature in [operation, *(['attachments'] if has_images else [])]:
            if caps[feature]['status']!='supported':
                raise ValueError(caps[feature]['reason'])

    async def prepare(self,command):
        native=command['native_session_id']; operation=command['operation']; payload=command['payload']
        if operation in {'send','queue'}:
            self._require_submit_capability(operation,bool(payload.get('attachment_ids')))
        snapshot=await self.attach(native,command.get('native_source'))
        if operation=='send' and snapshot.get('running'):
            raise ValueError('Session is busy; choose queue or steer explicitly')
        pending=None
        if operation in {'approval','clarify'}:
            replay=await self.replay(native)
            pending=next((r for r in replay['open_requests'] if r['id']==payload['pending_request_id'] and r['method']==operation),None)
            if not pending or pending['params'].get('session_id')!=snapshot['session_id']:
                raise ValueError('Request was answered, expired or belongs to another session')
            validate_answer(pending,payload)
        command['_prepared']={'runtime':snapshot['session_id'],'pending':pending}

    async def execute(self,command,attachments):
        operation=command['operation'];payload=command['payload']
        if operation in {'send','queue'}:
            self._require_submit_capability(operation,bool(attachments or payload.get('attachment_ids')))
        if '_prepared' not in command:
            await self.prepare(command)
        params={'session_id':command['_prepared']['runtime'],'profile':self.config.profile}
        if operation in {'send','queue'}:
            if len(attachments)!=len(payload.get('attachment_ids',[])):
                raise ValueError('Attachment payload is incomplete')
            if attachments and (len(attachments)>self.gateway_caps['prompt_image_max_count']
                                or sum(len(data) for _,data in attachments)>self.gateway_caps['prompt_image_max_total_bytes']):
                raise ValueError('Images exceed the native backend count or total byte limit')
            submit={**params,'text':payload['text'],'queued':True,'reject_if_busy':operation=='send',
                    'image_inputs':[{'filename':name,'content_base64':base64.b64encode(data).decode('ascii')}
                                    for name,data in attachments]}
            limit=self.gateway_caps.get('prompt_image_max_request_bytes')
            if type(limit) is int and len(json.dumps(submit).encode('utf-8'))>limit:
                raise ValueError('Prompt and encoded images exceed the native request size limit')
            return 'acknowledged',await self.rpc.call('prompt.submit',submit)
        if operation in {'steer','interrupt'}:
            return 'acknowledged',await self.rpc.call('session.'+operation,{**params,**({'text':payload['text']} if operation=='steer' else {})})
        pending=command['_prepared']['pending']
        answer=validate_answer(pending,payload)
        if operation=='approval':
            result=await self.rpc.call('approval.respond',{**params,'request_id':pending['params']['request_id'],**answer})
            if result['resolved']!=1:
                raise ValueError('Approval already answered or expired')
            return 'completed',result
        await self.rpc.respond(pending['id'],answer)
        return 'response_submitted',{'confirmed_winner':False,'reason':'Native response frames have no winner ACK'}

    async def exists(self,native):
        response=await self.http.get('/api/sessions/'+quote(native,safe=''),params={'profile':self.config.profile})
        if response.status_code==404:
            return False
        response.raise_for_status(); return True
