// Exercise the real plugin component and local service without taking App focus.
import fs from 'node:fs/promises'
import path from 'node:path'
import {fileURLToPath} from 'node:url'
import {createServer} from 'node:http'
import {build} from '../../node_modules/esbuild/lib/main.js'
import {chromium} from '@playwright/test'

const root=path.dirname(fileURLToPath(import.meta.url))
const settings=JSON.parse(await fs.readFile(path.join(root,'settings.json'),'utf8'))
const token=await fs.readFile(path.join(root,'data/token'),'utf8')
const acceptance=JSON.parse(await fs.readFile(path.join(root,'acceptance-results.json'),'utf8'))
const sid=acceptance.results.find(r=>r.engine==='codex').session_id
const sdk=`export {Streamdown} from 'streamdown';export const ROUTES_AREA='routes',SIDEBAR_NAV_AREA='nav',STATUSBAR_AREAS={right:'status'};
export const Button=()=>null,Input=()=>null,Textarea=()=>null,RowButton=()=>null,Popover=()=>null,PopoverContent=()=>null,PopoverTrigger=()=>null,Codicon=()=>null,usePluginI18n=()=>key=>key;
export const host={notify(){},notifyError(){},navigate(){},state:{busyBySession:{get:()=>({})}},restartGateway:async()=>{throw Error('Unexpected reconnect')}};`
const bundle=await build({stdin:{contents:`
import React from 'react'; import {createRoot} from 'react-dom/client';
import plugin from './plugin/desktop/plugin.js';
let items=[];plugin.register({rest:(route,{body})=>window.hubRpc(route.split('/').pop(),body),storage:{get:(k,d)=>JSON.parse(localStorage.getItem(k)||JSON.stringify(d)),set:(k,v)=>localStorage.setItem(k,JSON.stringify(v))},i18n:{register:()=>()=>{},t:key=>key},onDispose(){},registerMany(x){items.push(...x)}});
createRoot(document.getElementById('root')).render(React.createElement(React.Fragment,null,items.find(x=>x.id==='page').render(),items.find(x=>x.id==='inbox').render()));
`,resolveDir:root,loader:'js'},bundle:true,write:false,format:'iife',nodePaths:[path.resolve(root,'../../node_modules')],plugins:[{name:'test-sdk',setup(b){b.onResolve({filter:/^@hermes\/plugin-sdk$/},()=>({path:'sdk',namespace:'mock'}));b.onLoad({filter:/.*/,namespace:'mock'},()=>({contents:sdk,loader:'js',resolveDir:root}))}}]})
const server=createServer((req,res)=>{res.setHeader('Content-Type',req.url==='/app.js'?'application/javascript':'text/html; charset=utf-8');res.end(req.url==='/app.js'?bundle.outputFiles[0].text:'<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>Session Hub UI verification</title><style>body{margin:0;background:#111820;color:#e6edf4;font-family:Segoe UI,Microsoft Yahei,sans-serif}*{box-sizing:border-box}select option{background:#111820}</style><div id="root"></div><script src="/app.js"></script></html>')})
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve))
const browser=await chromium.launch({headless:true,executablePath:'D:/_cache/playwright/chromium-1234/chrome-win64/chrome.exe'})
const errors=[]
const fixtureId='ui-transcript-fixture'
const fixtureItems=Array.from({length:85},(_,n)=>({id:'fixture-'+n,position:n,revision:n+1,kind:'agentMessage',role:n%2?'assistant':'user',blocks:[{type:'text',text:'完整消息 '+n}],details:{}}))
fixtureItems[81].blocks=[{type:'text',text:'# Markdown 验收\n\n| 引擎 | 会话 |\n|---|---|\n| Codex | 原 ID |\n\n```python\nprint("hello")\n```\n\n<script>window.transcriptXss=true</script><img src="https://example.invalid/tracker" onerror="window.transcriptXss=true">'}]
fixtureItems[82]={...fixtureItems[82],role:'activity',kind:'commandExecution',blocks:[{type:'tool_call',name:'terminal',input:'test',call_id:'fixture-call'},{type:'tool_result',call_id:'fixture-call',blocks:[{type:'text',text:'完整输出 '+ 'RESULT '.repeat(5000)}]}]}
fixtureItems[83].blocks=[{type:'attachment',kind:'image',data:{source:{type:'base64',media_type:'image/png',data:'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII='}}}]
let fixtureUpdated=false
try{
 const page=await browser.newPage({viewport:{width:1440,height:1080},deviceScaleFactor:1})
 page.on('pageerror',e=>errors.push(e.message))
 await page.exposeFunction('hubRpc',async(op,body)=>{
  if(op==='transcript'&&body.session_id===fixtureId){
   const end=body.cursor?Number(body.cursor):85,start=Math.max(0,end-(body.limit||40));const delta=body.since!=null
   const changed={...fixtureItems[84],revision:86,blocks:[{type:'text',text:'同步更新成功'}]}
   const items=delta?body.since<86?[changed]:[]:fixtureItems.slice(start,end).map(i=>fixtureUpdated&&i.id===changed.id?changed:i)
   if(delta)fixtureUpdated=true
   return {engine:'codex',session_id:fixtureId,items,total:85,revision:fixtureUpdated?86:85,generation:'fixture',next_cursor:!delta&&start?String(start):null,has_more:!delta&&start>0,coverage:{scanned_records:85,warnings:[]},scope:'synthetic UI test'}
  }
  const result=await fetch(`http://127.0.0.1:${settings.port}/rpc/${op}`,{method:'POST',headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},body:JSON.stringify(body)})
  if(!result.ok)throw Error('RPC failed: '+result.status)
  const value=await result.json()
  if(op==='app_sessions')value.sessions.push({engine:'codex',session_id:fixtureId,title:'共享会话 UI 验收',status:'completed',origin:'fixture'})
  return value
 })
 await page.goto(`http://127.0.0.1:${server.address().port}`)
 await page.getByRole('heading',{name:'共享会话 · App 实时控制',exact:true}).waitFor()
 await page.getByPlaceholder('搜索 App 任务标题或 ID').fill('01a0b3a9-1834-7140-8393-0f167c52b8f1')
 await page.getByRole('button').filter({has:page.locator('small',{hasText:'01a0b3a9-1834-7140-8393-0f167c52b8f1'})}).click()
 await page.getByRole('region',{name:'共享会话时间线'}).getByText('HERMES-APP-LIVE-918 LIVE-STEER-OK HUB-SERVICE-OK',{exact:true}).waitFor()
 await page.getByRole('region',{name:'共享会话时间线'}).getByText('跨会话指令',{exact:true}).first().waitFor()
 await page.getByPlaceholder('搜索任务标题、工作目录、session ID').fill(sid)
 await page.getByRole('button').filter({hasText:'session-hub-acceptance'}).first().click()
 await page.locator('code').filter({hasText:sid}).first().waitFor()
 await page.getByText('CODEX-'+acceptance.run,{exact:true}).first().waitFor()
 await page.getByRole('button',{name:'关注后续完成',exact:true}).click()
 await page.getByRole('heading',{name:'会话协作 · Session Hub',exact:true}).scrollIntoViewIfNeeded()
 await page.screenshot({path:path.join(root,'ui-preview.png'),fullPage:false})
 // Synthetic long transcript tests the real UI; it never writes foreign history.
 await page.getByPlaceholder('搜索 App 任务标题或 ID').fill(fixtureId)
 await page.getByRole('button').filter({has:page.locator('small',{hasText:fixtureId})}).click()
 const transcript=page.getByRole('region',{name:'共享会话时间线'})
 await transcript.getByRole('heading',{name:'Markdown 验收',exact:true}).waitFor()
 if(await transcript.locator('table').count()!==1)throw Error('Markdown table missing')
 await transcript.locator('pre code').filter({hasText:'print'}).first().waitFor();
 if(!(await transcript.locator('pre code').allTextContents()).some(t=>t.trim()==='print("hello")'))throw Error('Code block missing')
 await transcript.getByText('commandExecution · 展开查看',{exact:true}).click()
 const output=await transcript.locator('pre').filter({hasText:'完整输出'}).first().innerText()
 if(output.length<35000)throw Error('Tool result was truncated')
 if(await transcript.locator('.hub-image-button img').count()!==1)throw Error('Inline image missing')
 await transcript.getByText('同步更新成功',{exact:true}).waitFor({timeout:10000})
 if(await page.locator('[data-transcript-id="fixture-84"]').count()!==1)throw Error('Polling duplicated a record')
 await transcript.getByRole('button',{name:'加载更早记录',exact:true}).click()
 await transcript.getByText('完整消息 5',{exact:true}).waitFor()
 await transcript.getByRole('button',{name:'加载更早记录',exact:true}).click()
 await transcript.getByText('完整消息 0',{exact:true}).waitFor()
 if(await transcript.locator('article').count()!==85)throw Error('Pagination lost or duplicated items')
 if(await page.evaluate(()=>Boolean(window.transcriptXss)))throw Error('Untrusted HTML executed')
 if(await transcript.locator('script,img[src^="http"]').count())throw Error('Untrusted remote resources rendered')
 const downloadEvent=page.waitForEvent('download')
 await transcript.getByRole('button',{name:'导出全部记录',exact:true}).click()
 const download=await downloadEvent;const exported=JSON.parse(await fs.readFile(await download.path(),'utf8'))
 if(exported.items.length!==85||exported.items[0].id!=='fixture-0')throw Error('Export omitted old history')
 if(errors.length)throw Error(errors.join('\n'))
 const denied=await fetch(`http://127.0.0.1:${settings.port}/rpc/health`,{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'})
 if(denied.status!==401)throw Error('Unauthenticated request was not rejected')
 const result={real_plugin_render:true,real_app_task_list:true,real_service_read:true,same_session_history_displayed:true,full_timeline_and_peer_messages:true,watch_action:true,fixture_checks:{pagination_85_records:true,incremental_update_without_duplicate:true,markdown_table_and_code:true,full_tool_output:true,inline_image:true,html_not_executed:true,export_all_pages:true},unauthenticated_http_status:denied.status,page_errors:errors,scope:'Headless component harness with actual Streamdown renderer; fixture checks are synthetic, not App end-to-end proof.'}
 await fs.writeFile(path.join(root,'ui-test-results.json'),JSON.stringify(result,null,2)+'\n')
 console.log(JSON.stringify(result))
}finally{await browser.close();server.close()}
