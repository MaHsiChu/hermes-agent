"""Use the installed Codex App Tools MCP, with its real originating task context.

No raw app-server pipe injection and no foreign database mutations.
Only the explicitly allowlisted task operations are exposed to Session Hub.
"""
import asyncio
import json
import os
from pathlib import Path
import sys
import shutil
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import RequestParamsMeta

ROOT=Path(__file__).resolve().parent
BINDING=ROOT/'data/codex-app-binding.json'
ALLOWED={'list_threads','read_thread','list_projects','create_thread','send_message_to_thread','wait_threads','navigate_to_codex_page'}


def bind():
    pipe=os.environ.get('CODEX_APP_TOOLS_PIPE_PATH')
    caller=os.environ.get('CODEX_THREAD_ID')
    if not pipe or not caller: raise ValueError('Run binding from an authorized Codex App task, with its App Tools environment.')
    cache=Path.home()/'.codex/plugins/cache/openai-bundled/codex-app-tools'
    servers=sorted(cache.glob('*/server.mjs'),key=lambda p:p.stat().st_mtime,reverse=True)
    if not servers: raise ValueError('Installed Codex App Tools MCP was not found.')
    node=os.environ.get('CODEX_MCP_NODE_PATH') or shutil.which('node')
    if not node: raise ValueError('Node.js was not found; install Node or configure CODEX_MCP_NODE_PATH.')
    BINDING.parent.mkdir(exist_ok=True)
    BINDING.write_text(json.dumps({'pipe':pipe,'caller_thread_id':caller,'server':str(servers[0]),'node':node}),encoding='utf-8')
    return {'bound':True,'caller_thread_id':caller,'server_version':servers[0].parent.name}


async def invoke(name,arguments=None):
    if name not in ALLOWED and name!='catalog': raise ValueError('App operation not exposed by Session Hub')
    if not BINDING.exists(): raise ValueError('Codex App is not bound. Run codex_app.py bind from a Codex App task.')
    binding=json.loads(BINDING.read_text(encoding='utf-8'))
    env=dict(os.environ,CODEX_APP_TOOLS_PIPE_PATH=binding['pipe'])
    params=StdioServerParameters(command=binding['node'],args=[binding['server']],env=env)
    async with stdio_client(params) as (reader,writer):
        async with ClientSession(reader,writer) as client:
            await client.initialize()
            if name=='catalog':
                result=await client.list_tools()
                return {t.name:t.input_schema for t in result.tools if t.name in ALLOWED}
            result=await client.call_tool(name,arguments or {},meta={'openai/threadId':binding['caller_thread_id']},read_timeout_seconds=75)
            texts=[c.text for c in result.content if c.type=='text']
            if result.is_error: raise RuntimeError('\n'.join(texts))
            if len(texts)==1:
                try:return json.loads(texts[0])
                except ValueError:pass
            return {'text':'\n'.join(texts)}


def call(name,arguments=None):
    return asyncio.run(invoke(name,arguments))


if __name__=='__main__':
    name=sys.argv[1] if len(sys.argv)>1 else 'catalog'
    result=bind() if name=='bind' else call(name,json.loads(sys.argv[2]) if len(sys.argv)>2 else {})
    print(json.dumps(result,ensure_ascii=False,indent=2))
