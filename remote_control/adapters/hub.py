"""Session Hub native App handoff only. No CLI dispatch fallback."""
import httpx
from datetime import datetime, timezone

from ..security import redact


def message_timestamp(row):
    """Hub ISO rollout time and normalized Codex epoch milliseconds → protocol seconds."""
    if row.get('created_at_ms') is not None:
        return float(row['created_at_ms'])/1000
    value=row.get('timestamp')
    if isinstance(value,str):
        parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
        return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).timestamp()
    if isinstance(value,(int,float)):
        # TranscriptStore puts normalized thread_items.created_at_ms in timestamp.
        return value/1000 if abs(value)>=100000000000 else value
    return None


class HubAdapter:
    def __init__(self,config):
        self.config=config; self.online=False; self.catalog_complete=False
        self.http=httpx.AsyncClient(base_url=config.url,headers={'Authorization':'Bearer '+config.token.read()},timeout=45)

    async def rpc(self,op,body=None):
        response=await self.http.post('/rpc/'+op,json=body or {})
        response.raise_for_status(); return response.json()

    async def connect(self):
        await self.rpc('health'); self.online=True

    async def close(self):
        self.online=False; await self.http.aclose()

    async def catalog(self):
        offset=0; snapshot_id=None; self.catalog_complete=True
        while True:
            args={'engine':self.config.engine,'limit':100,'offset':offset,'include_archived':True}
            if snapshot_id:
                args['snapshot_id']=snapshot_id
            page=await self.rpc('sessions',args)
            for row in page['sessions']:
                if row.get('engine')!=self.config.engine:
                    raise ValueError('Hub returned foreign engine')
                yield dict(redact(row),native_session_id=row['session_id'],profile=self.config.profile)
            pagination=page.get('pagination')
            if not pagination:
                self.catalog_complete=False
                return
            self.catalog_complete=self.catalog_complete and bool(pagination.get('complete'))
            snapshot_id=pagination['snapshot_id']; offset=pagination.get('next_offset')
            if offset is None:
                return

    async def history(self,native,offset='',recent=False):
        page=await self.rpc('transcript',{'engine':self.config.engine,'session_id':native,
                                        'cursor':'' if recent else offset or '', 'limit':100})
        rows=[dict(redact(row),id=str(row['id']),ordinal=row.get('position',0),timestamp=message_timestamp(row)) for row in page['items']]
        return rows,page.get('next_cursor'),{'complete':not page.get('has_more'),'total':page.get('total'),
                                           'generation':page.get('generation'),'revision':page.get('revision')}

    async def changed(self,native,checkpoint):
        if not checkpoint.get('generation') or checkpoint.get('revision') is None:
            return True
        try:
            page=await self.rpc('transcript',{'engine':self.config.engine,'session_id':native,'limit':1,
                'since':checkpoint['revision'],'generation':checkpoint['generation']})
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code==400:
                # Hub rejects a since cursor when its source generation has changed.
                return True
            raise
        return bool(page['items']) or page.get('generation')!=checkpoint['generation']

    def capabilities(self):
        caps={k:{'status':'unsupported','reason':'Session Hub does not expose this original App operation'} for k in
              ('steer','queue','interrupt','approval','clarify','attachments')}
        caps.update(history={'status':'supported'},send={'status':'supported'})
        return caps

    async def execute(self,command,attachments):
        if command['operation']!='send' or attachments:
            raise ValueError('Hub supports text handoff only; approvals, stop and images remain local')
        result=await self.rpc('app_dispatch',{'engine':self.config.engine,'session_id':command['native_session_id'],
            'prompt':command['payload']['text'],'request_key':command['request_id']})
        return 'acknowledged',{'job_id':result.get('id'),'status':result.get('state'),
                               'reason':'Native App handoff accepted; consult original session for completion'}

    async def prepare(self,command):
        if command['operation']!='send' or command['payload'].get('attachment_ids'):
            raise ValueError('Hub supports text handoff only')

    async def exists(self,native):
        # An incomplete Hub source read must never be interpreted as a deletion.
        return True
