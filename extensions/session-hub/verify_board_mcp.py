"""Read-only integration probe of the actual MCP process used by Hermes."""
import asyncio
import json
from pathlib import Path
import sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT=Path(__file__).resolve().parent


async def main():
    params=StdioServerParameters(command=sys.executable,args=[str(ROOT/'mcp_server.py')])
    async with stdio_client(params) as (reader,writer):
        async with ClientSession(reader,writer) as client:
            await client.initialize()
            names={tool.name for tool in (await client.list_tools()).tools}
            required={'hub_task_board','hub_task_reference','hub_create_task_session'}
            assert required<=names, required-names
            result=await client.call_tool('hub_task_board',{},read_timeout_seconds=60)
            assert not result.is_error
            board=json.loads(next(c.text for c in result.content if c.type=='text'))
            assert board['tasks']
            result=await client.call_tool('hub_task_reference',{'key':board['tasks'][0]['key']},read_timeout_seconds=60)
            assert not result.is_error
            task=json.loads(next(c.text for c in result.content if c.type=='text'))
            assert '#task/session-hub/' in task['reference']
            report={'tools_registered':sorted(required),'real_board_read':True,'real_reference_read':True,'tasks':len(board['tasks']),'creation_test':'isolated contract and browser payload only; no live model work dispatched'}
            (ROOT/'board-mcp-results.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
            print(json.dumps(report))


if __name__=='__main__': asyncio.run(main())
