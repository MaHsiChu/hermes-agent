"""Read-only acceptance for full history pages and the Hermes MCP entry point."""
import asyncio
import json
from pathlib import Path
import sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from client import call

ROOT=Path(__file__).resolve().parent


async def main():
    summaries=[]
    for engine,sid in [('codex','01a0b3a9-1834-7140-8393-0f167c52b8f1'),('claude','2a180f82-79ef-4d06-907d-1f00b3b86a31')]:
        cursor='';items=[];pages=0
        while True:
            p=call('transcript',dict(engine=engine,session_id=sid,cursor=cursor,limit=7))
            items=p['items']+items;pages+=1;cursor=p['next_cursor']
            if not cursor:break
        assert len(items)==p['total']==len({i['id'] for i in items})
        assert any(i['role']=='peer' for i in items)
        assert p['coverage']['malformed_records']==0
        assert p['coverage']['source_bytes']==p['coverage']['indexed_bytes']
        summaries.append(dict(engine=engine,session_id=sid,pages=pages,records=len(items),coverage=p['coverage'],same_session=True))
    params=StdioServerParameters(command=sys.executable,args=[str(ROOT/'mcp_server.py')])
    async with stdio_client(params) as (read,write):
        async with ClientSession(read,write) as client:
            await client.initialize()
            names=[t.name for t in (await client.list_tools()).tools]
            assert 'hub_session_transcript' in names
            result=await client.call_tool('hub_session_transcript',{'engine':'codex','session_id':summaries[0]['session_id'],'limit':2})
            assert not result.is_error
            data=json.loads(next(c.text for c in result.content if c.type=='text'))
            assert len(data['items'])==2 and data['next_cursor']
    evidence=dict(version='0.3.0',native_readonly_pages=summaries,mcp_transcript_tool=True,
                  limits=['Local persisted records only; private App UI and hidden reasoning are not mirrored.',
                          'Claude Desktop target message delivery still awaits its dedicated acceptance.'])
    (ROOT/'transcript-acceptance-results.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(evidence,ensure_ascii=False))


if __name__=='__main__':asyncio.run(main())
