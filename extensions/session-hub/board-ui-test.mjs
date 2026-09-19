import fs from 'node:fs/promises'
import path from 'node:path'
import {fileURLToPath} from 'node:url'
import {createServer} from 'node:http'
import assert from 'node:assert/strict'
import {build} from '../../node_modules/esbuild/lib/main.js'
import {chromium} from '@playwright/test'
import {selectTasks,hermesTask} from './plugin/desktop/board-model.js'

const root=path.dirname(fileURLToPath(import.meta.url))
const claudeLive=process.argv.includes('--claude-live')
const claudeSend=process.argv.includes('--claude-send')
const artifactsLive=process.argv.includes('--artifacts-live')
const imageLive=process.argv.includes('--image-live')
const continueLive=process.argv.includes('--continue-live')||imageLive
const inspectConversation=process.argv.includes('--inspect-conversation')
const live=process.argv.includes('--live')||continueLive||inspectConversation||artifactsLive||claudeLive
const sdk=`import React from 'react';import {Popover as P} from 'radix-ui';import {boardLocales} from '${path.join(root,'plugin/desktop/board-i18n.js').replaceAll('\\','/')}';
export const Popover=P.Root,PopoverTrigger=P.Trigger,PopoverContent=({children,...props})=>React.createElement(P.Portal,null,React.createElement(P.Content,{sideOffset:6,collisionPadding:8,...props},children));
export const Codicon=({name,...props})=>React.createElement('span',props,({'eye':'◉','eye-closed':'◌','gripper':'⠿','chevron-up':'⌃','chevron-down':'⌄','filter':'▽','settings':'☷','add':'+','close':'×'})[name]||name);
export {Streamdown} from 'streamdown';export const ROUTES_AREA='routes',SIDEBAR_NAV_AREA='nav',STATUSBAR_AREAS={right:'status'};
const atom=value=>({get:()=>value,subscribe:()=>()=>{}});
export const host={notify(v){window.notifications.push(v)},navigate(v){window.navigated=v},openSession:async(id,options)=>{window.opened={id,options}},newChat(){window.newChat=true},openWorkspace:(id,options)=>{window.workspace={id,title:options.title};window.showDetail(options.render());window.showSidebar(options.sidebarSession?.render())},state:{sessions:atom([{id:'hermes-1',profile:'default',title:'Hermes · 角色记忆系统设计',last_active:1,preview:'正在校验接口契约',message_count:3}]),sessionStatus:atom({'hermes-1':'working'}),cwd:atom('/workspace'),busyBySession:atom({})}};
export const usePluginI18n=()=>key=>boardLocales.zh[key]||key;
export const Button=({variant,size,...props})=>React.createElement('button',props),RowButton=props=>React.createElement('button',props),Input=props=>React.createElement('input',props),Textarea=props=>React.createElement('textarea',props);`
const bundle=await build({stdin:{contents:`import React from 'react';import {createRoot} from 'react-dom/client';import plugin from './plugin/desktop/plugin.js';import {installBoardStyles} from './plugin/desktop/board-ui.js';import {boardLocales} from './plugin/desktop/board-i18n.js';
let items=[];window.notifications=[];const detail=createRoot(document.getElementById('detail'));window.showDetail=node=>detail.render(node);const sidebarElement=document.createElement('div');sidebarElement.id='sidebar-fixture';document.body.append(sidebarElement);const sidebar=createRoot(sidebarElement);window.showSidebar=node=>sidebar.render(node);
plugin.register({rest:(route,{body})=>window.hubRpc(route.split('/').pop(),body),storage:{get:(k,d)=>JSON.parse(localStorage.getItem(k)||JSON.stringify(d)),set:(k,v)=>localStorage.setItem(k,JSON.stringify(v))},i18n:{register:()=>()=>{},t:k=>boardLocales.zh[k]||k},os:{openExternal:async url=>{window.nativeUrl=url;return true},writeClipboard:async s=>{window.copied=s;return true}},onDispose(){},registerMany(x){items.push(...x)}});
createRoot(document.getElementById('root')).render(items.find(x=>x.id==='board').render());
window.boardNav=items.find(x=>x.id==='board-nav').data;
window.testStyleLifecycle=()=>{const before=document.adoptedStyleSheets.length;const dispose=installBoardStyles();const during=document.adoptedStyleSheets.length;dispose();return {before,during,after:document.adoptedStyleSheets.length}};
createRoot(document.getElementById('reference')).render(React.createElement(items.find(x=>x.id==='task-reference').data.render,{value:'codex:running',children:'任务引用'}));`,resolveDir:root,loader:'js'},bundle:true,write:false,format:'iife',nodePaths:[path.resolve(root,'../../node_modules')],plugins:[{name:'sdk',setup(b){b.onResolve({filter:/^@hermes\/plugin-sdk$/},()=>({path:'sdk',namespace:'mock'}));b.onLoad({filter:/.*/,namespace:'mock'},()=>({contents:sdk,loader:'js',resolveDir:root}))}}]})
const theme=`:root{--ui-bg-primary:#a5b8f0;--ui-surface-background:#ffffff;--ui-text-primary:#223049;--ui-text-secondary:#58677c;--ui-text-tertiary:#8793a5;--ui-stroke-tertiary:#dce3eb;--ui-accent:#568aff;--ui-yellow:#c58a23;--ui-green:#3a9d78;--ui-orange:#ce6944}body{margin:0;font:14px Segoe UI,Microsoft Yahei,sans-serif;background:var(--ui-surface-background)}*{box-sizing:border-box}button,input,textarea{font:inherit;padding:7px 10px;border:1px solid var(--ui-stroke-tertiary);border-radius:6px;color:inherit;background:transparent}button{cursor:pointer}.hub-popover{background:white;border:1px solid #dce3eb;border-radius:8px;padding:8px;z-index:50;box-shadow:0 10px 30px #0001}#reference{padding:12px 28px}#detail:empty{display:none}`
const server=createServer((req,res)=>{res.setHeader('Content-Type',req.url==='/app.js'?'application/javascript':'text/html; charset=utf-8');res.end(req.url==='/app.js'?bundle.outputFiles[0].text:`<!doctype html><html lang="zh-CN"><meta charset="utf-8"><style>${theme}</style><div id="root"></div><div id="reference"></div><div id="detail"></div><script src="/app.js"></script></html>`)})
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve))
const browser=await chromium.launch({headless:true,executablePath:'D:/_cache/playwright/chromium-1234/chrome-win64/chrome.exe'})
const fixture=[['running','Codex · Session 看板开发'],['attention','Claude · 等待确认目录权限'],['unread','Codex · API 契约评审完成'],['completed','Claude · 回归测试通过'],['queued','Codex · 文档更新排队中']].map(([state,title],i)=>({key:'codex:'+state,engine:i%2?'claude':'codex',session_id:state,title,state,revision:state==='unread'?'r1':'',live:true,cwd:'/projects/Verse',updated_at:1789730000+i,summary:'保留原生会话与执行权限',reference:`[${title}](#task/session-hub/codex%3A${state})`}))
const settings=live?JSON.parse(await fs.readFile(path.join(root,'settings.json'),'utf8')):null
const token=live?await fs.readFile(path.join(root,'data/token'),'utf8'):null
const errors=[],calls=[],closures={},deliveries=new Map(),uploads=new Map()
let loseReceipt=true
try{
 const page=await browser.newPage({viewport:{width:1680,height:960}})
 page.on('pageerror',e=>errors.push(e.message))
 await page.exposeFunction('hubRpc',async(op,body)=>{
  calls.push({op,body})
  if(live){const r=await fetch(`http://127.0.0.1:${settings.port}/rpc/${op}`,{method:'POST',headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},body:JSON.stringify(body)});if(!r.ok)throw Error(await r.text());return r.json()}
  if(op==='board')return {tasks:fixture,closures,errors:[],synced_at:Date.now()/1000,history_loaded:5,history_total:5}
  if(op==='task_closed'){closures[body.key]=body.closed;return {closures:{[body.key]:body.closed}}}
  if(op==='task')return fixture.find(r=>r.key===body.key)||{key:body.key,title:'Created task',engine:'codex',state:'queued'}
  if(op==='task_read'){fixture.find(r=>r.key===body.key).state='completed';return {ok:true}}
  if(op==='task_create')return {id:'job-1',task_key:'job:job-1',reference:'[New task](#task/session-hub/job%3Ajob-1)'}
  if(op==='transcript')return {items:[],next_cursor:null,revision:1,generation:1,total:0,session_id:body.session_id,coverage:{scanned_records:0,warnings:[]}}
  if(op==='app_open')return {navigated:true,activated:true}
  if(op==='app_prepare_claude')return {requested:true,state:'draft',requires_send:true}
  if(op==='app_upload_image'){const image={id:'image-'+uploads.size,name:body.name,thumbnail:body.data_url};uploads.set(image.id,image);return image}
  if(op==='app_attachment')return {data_url:uploads.get(body.attachment_id).thumbnail}
  if(op==='app_dispatch'){
   if(!deliveries.has(body.request_key))deliveries.set(body.request_key,{id:'delivery-'+deliveries.size,engine:body.engine,session_id:body.session_id,state:'running'})
   if(loseReceipt){loseReceipt=false;throw Error('Response connection lost after enqueue')}
   return deliveries.get(body.request_key)
  }
  if(op==='app_jobs')return {jobs:[...deliveries.values()]}
  throw Error('Unexpected operation '+op)
 })
 await page.goto(`http://127.0.0.1:${server.address().port}`)
 await page.getByRole('heading',{name:'Session 任务看板'}).waitFor()
 await page.locator('.hub-task').first().waitFor()
 if(live)await page.locator('#root [data-task-key^="codex:"]').first().waitFor({timeout:60000})
 if(claudeLive){
  const sid='2a180f82-79ef-4d06-907d-1f00b3b86a31'
  await page.getByLabel('会话范围',{exact:true}).selectOption('all')
  await page.locator(`#root [data-task-key="claude:${sid}"]`).click()
  await page.addStyleTag({content:'#root,#reference,#sidebar-fixture{display:none}#detail{height:100vh}body{margin:0}'})
  await page.getByRole('textbox',{name:'继续原 Claude 任务',exact:true}).waitFor()
  const marker=claudeSend?'HERMES-CLAUDE-COMPOSER-0919-OK':'DESKTOP-0919-OK'
  if(claudeSend){
   await page.getByRole('textbox',{name:'继续原 Claude 任务',exact:true}).fill('Hermes 界面专用验收：不要读写文件，不要联网，不要调用工具，不要向其他会话发消息。在当前原会话中复述本消息之前的最后一条助手回答，末尾追加 HERMES-CLAUDE-COMPOSER-0919-OK。只输出一行。')
   await page.getByRole('button',{name:'发送到原任务 ↑',exact:true}).click()
   await page.waitForFunction(()=>document.querySelector('[data-delivery-state=completed]'),{},{timeout:180000})
  }
  await page.waitForFunction(marker=>[...document.querySelectorAll('.hub-message[data-role=assistant]')].some(e=>e.textContent.includes(marker)),marker,{timeout:30000})
  const answer=await page.locator('.hub-message[data-role=assistant]').filter({hasText:marker}).last().innerText()
  assert.ok(answer.includes('HUB-CLAUDE-SERVICE-OK'))
  assert.equal(calls.filter(c=>c.op==='app_dispatch').length,claudeSend?1:0)
  if(claudeSend){const body=calls.find(c=>c.op==='app_dispatch').body;assert.equal(body.engine,'claude');assert.equal(body.session_id,sid)}
  await page.getByRole('button',{name:'跳到最新',exact:true}).click()
  await page.screenshot({path:path.join(root,'claude-conversation-live.png')})
  assert.deepEqual(errors,[])
  await fs.writeFile(path.join(root,'claude-conversation-live-results.json'),JSON.stringify({passed:true,session_id:sid,marker,answer,dispatchCount:calls.filter(c=>c.op==='app_dispatch').length,errors},null,2))
 }else if(artifactsLive){
  const sid='01a0b43c-7f4e-71b1-b345-951ea71fae89'
  await page.getByLabel('会话范围',{exact:true}).selectOption('all')
  await page.locator(`#root [data-task-key="codex:${sid}"]`).click()
  await page.addStyleTag({content:'#root,#reference,#sidebar-fixture{display:none}#detail{height:100vh}body{margin:0}'})
  const link=page.getByRole('link',{name:'能力与验收记录',exact:false})
  await page.locator('[data-testid=transcript-scroll]').waitFor()
  await page.waitForFunction(()=>document.querySelectorAll('.hub-message').length>0)
  for(let i=0;i<20&&!await link.count();i++){
   const older=page.getByRole('button',{name:'加载更早记录',exact:true});if(!await older.count())break
   await older.click();await page.getByRole('button',{name:'读取中…',exact:true}).waitFor({state:'detached'})
  }
  await link.waitFor();await link.click()
  await page.locator('.hub-document-content').getByRole('heading').first().waitFor()
  assert.ok((await page.locator('.hub-document-content').innerText()).includes('Codex'))
  await page.screenshot({path:path.join(root,'document-preview-live.png')})
  await page.keyboard.press('Escape')
  const article=page.locator('.hub-message').filter({has:link})
  await article.getByRole('region',{name:'修改文件列表'}).waitFor()
  assert.equal(await article.locator('.hub-changed-file').count(),3)
  await article.getByRole('button',{name:'再显示 5 个文件',exact:true}).click()
  assert.equal(await article.locator('.hub-changed-file').count(),8)
  assert.equal((await article.locator('.hub-changed-files>header .hub-diff-counts').innerText()).replace(/\s/g,''),'+220-3')
  await article.locator('.hub-changed-file summary').first().click()
  await article.locator('.hub-changed-file[open] pre').first().waitFor()
  await article.locator('.hub-changed-file summary').first().click()
  await article.locator('.hub-changed-files').scrollIntoViewIfNeeded()
  await page.screenshot({path:path.join(root,'changed-files-live.png')})
  assert.equal(calls.filter(c=>['app_dispatch','task_create','app_open'].includes(c.op)).length,0)
  assert.deepEqual(errors,[])
  const result={passed:true,session_id:sid,tests:['real report link and Markdown preview','original turn has 8 files and +220 -3','expand all files and inspect patch','changes before loaded page included','no App dispatch or navigation'],errors}
  await fs.writeFile(path.join(root,'artifacts-live-results.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result))
 }else if(continueLive||inspectConversation){
  // Explicit opt-in: only the pre-existing disposable acceptance task.
  const acceptance=JSON.parse(await fs.readFile(path.join(root,'data/codex-app-acceptance.json'),'utf8'))
  const sid=acceptance.created.threadId
  assert.equal(sid,'01a0b3a9-1834-7140-8393-0f167c52b8f1')
  await page.getByLabel('会话范围',{exact:true}).selectOption('all')
  await page.locator(`#root [data-task-key="codex:${sid}"]`).click()
  await page.addStyleTag({content:'#root,#reference,#sidebar-fixture{display:none}#detail{height:100vh}body{margin:0}'})
  const marker=continueLive?'HERMES-BOARD-CONTINUE-'+Date.now():JSON.parse(await fs.readFile(path.join(root,'codex-conversation-live-results.json'),'utf8')).marker
  if(continueLive){
  if(imageLive){await page.locator('.hub-composer input[type=file]').setInputFiles(path.join(root,'data/image-acceptance.png'));await page.locator('.hub-composer .hub-image-button').waitFor();await page.getByRole('textbox',{name:'继续原 Codex 任务',exact:true}).fill(`This is a disposable image integration check. Inspect the attached image using your image-viewing tool. Reply in English with the color and shape on the left, color and shape on the right, and the exact four-character label. End with ${marker}. Do not modify files, access the network, or perform other work.`)}
  else await page.getByRole('textbox',{name:'继续原 Codex 任务',exact:true}).fill(`This is a disposable UI integration check. Do not use tools, read files, modify files, or access networks. Reply with exactly ${marker} and then wait.`)
  await page.getByRole('button',{name:'发送到原任务 ↑',exact:true}).click()
  await page.waitForFunction(()=>document.querySelector('[data-delivery-state=completed]'),{},{timeout:180000})
  }
  await page.waitForFunction(marker=>[...document.querySelectorAll('.hub-message[data-role=assistant]')].some(e=>e.textContent.includes(marker)),marker,{timeout:30000})
  await page.getByRole('button',{name:'跳到最新',exact:true}).click()
  await page.waitForFunction(()=>{const e=document.querySelector('[data-testid=transcript-scroll]');return e.scrollHeight-e.scrollTop-e.clientHeight<10})
  assert.equal(calls.filter(c=>c.op==='app_dispatch').length,continueLive?1:0)
  if(continueLive)assert.equal(calls.find(c=>c.op==='app_dispatch').body.session_id,sid)
  assert.equal(calls.filter(c=>c.op==='task_create'||c.op==='app_open').length,0)
  if(imageLive){
   await page.locator('.hub-message[data-role=user] .hub-image-button').waitFor({timeout:20000})
   const answer=await page.locator('.hub-message[data-role=assistant]').filter({hasText:marker}).last().innerText()
   for(const term of ['red','triangle','blue','circle','Q7M4'])assert.ok(answer.toLowerCase().includes(term.toLowerCase()),'Missing visual evidence: '+term)
   await fs.writeFile(path.join(root,'image-acceptance-result.json'),JSON.stringify({session_id:sid,marker,answer,originalSession:true,dispatchCount:calls.filter(c=>c.op==='app_dispatch').length,uploadCount:calls.filter(c=>c.op==='app_upload_image').length,transcriptThumbnail:true},null,2))
  }
  await page.screenshot({path:path.join(root,imageLive?'codex-image-live.png':'codex-conversation-live.png')})
  const result={passed:true,session_id:sid,marker,tests:continueLive?['Hermes composer to original Codex task','single dispatch','completed turn','assistant reply in native transcript','no new task or native navigation']:['read-only original conversation rendering','saved assistant reply','no dispatch or native navigation'],errors}
  if(continueLive)await fs.writeFile(path.join(root,'codex-conversation-live-results.json'),JSON.stringify(result,null,2))
  assert.deepEqual(errors,[]);console.log(JSON.stringify(result));process.exitCode=0
 }else{
 if(!live){
  assert.equal(await page.locator('.hub-board').evaluate(e=>getComputedStyle(e).backgroundColor),'rgb(255, 255, 255)')
  // Reproduce the actual desktop bug: hidden task panes from an earlier
  // plugin revision retain DOM styles AFTER the new board in document order.
  const unreadBefore=await page.locator('#root .hub-task[data-state="unread"]').evaluate(e=>getComputedStyle(e).backgroundColor)
  await page.evaluate(()=>{const pane=document.createElement('section');pane.hidden=true;pane.className='retained-old-task';pane.innerHTML='<style>.hub-board,.hub-select{background:var(--ui-bg-primary)}.hub-task{background:var(--ui-bg-primary)}.hub-task[data-state=unread]{background:color-mix(in srgb,var(--ui-green) 12%,var(--ui-bg-primary))}</style>';document.body.append(pane)})
  assert.equal(await page.locator('.hub-board').evaluate(e=>getComputedStyle(e).backgroundColor),'rgb(255, 255, 255)')
  assert.equal(await page.locator('.hub-select').first().evaluate(e=>getComputedStyle(e).backgroundColor),'rgb(255, 255, 255)')
  const unreadColor=await page.locator('#root .hub-task[data-state="unread"]').evaluate(e=>getComputedStyle(e).backgroundColor)
  assert.equal(unreadColor,unreadBefore)
  assert.equal((await page.evaluate(()=>window.boardNav)).path,'/session-board')
  const runningCard=page.locator('#root [data-task-key="codex:running"]').locator('..')
  await runningCard.getByRole('button',{name:'关闭任务',exact:true}).click()
  await page.getByLabel('快捷筛选',{exact:true}).selectOption('closed')
  assert.equal(await page.locator('#root .hub-task').count(),1)
  assert.equal(await page.locator('#root .hub-task').getAttribute('data-state'),'running')
  await page.reload()
  await page.locator('#root .hub-task').first().waitFor()
  assert.equal(await page.locator('#root .hub-task').count(),1)
  assert.equal(calls.filter(c=>c.op==='app_open').length,0)
  await page.locator('#root .hub-task').click()
  assert.equal(calls.filter(c=>c.op==='app_open').length,0)
  await page.locator('#sidebar-fixture .hub-sidebar-task[data-state=running]').waitFor();
  fixture[0].state='attention';await page.getByRole('button',{name:'刷新',exact:true}).click();await page.locator('#sidebar-fixture .hub-sidebar-task[data-state=attention]').waitFor();
  fixture[0].state='running';await page.getByRole('button',{name:'刷新',exact:true}).click();await page.locator('#sidebar-fixture .hub-sidebar-task[data-state=running]').waitFor();
  const composer=page.locator('#detail').getByRole('textbox',{name:'继续原 Codex 任务',exact:true})
  await composer.fill('继续当前任务，不创建新 Session')
  await page.locator('#detail').getByRole('button',{name:'发送到原任务 ↑',exact:true}).click()
  await page.locator('#detail').getByRole('button',{name:'核对发送结果',exact:true}).waitFor()
  const firstSend=calls.find(c=>c.op==='app_dispatch')
  assert.equal(firstSend.body.session_id,'running')
  assert.equal(firstSend.body.host_id,'local')
  assert.equal(firstSend.body.engine,'codex')
  assert.equal(firstSend.body.target,undefined)
  // Reopen a retained workspace: the uncertain delivery and draft survive.
  await page.evaluate(()=>window.showDetail(null))
  await composer.waitFor({state:'detached'})
  await page.locator('#root .hub-task').click()
  assert.equal(await composer.inputValue(),'继续当前任务，不创建新 Session')
  await page.locator('#detail').getByRole('button',{name:'核对发送结果',exact:true}).click()
  await page.waitForFunction(()=>document.querySelector('[data-delivery-state=running]'))
  assert.equal(calls.filter(c=>c.op==='app_dispatch').length,2)
  assert.deepEqual(calls.filter(c=>c.op==='app_dispatch').map(c=>c.body),[firstSend.body,firstSend.body])
  assert.equal(deliveries.size,1)
  assert.equal(await composer.inputValue(),'')
  // Clipboard, picker and drop share persisted attachment IDs and scoped reads.
  const imageFile={name:'picker.png',mimeType:'image/png',buffer:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jG3kAAAAASUVORK5CYII=','base64')}
  await page.locator('.hub-composer input[type=file]').setInputFiles(imageFile)
  await page.locator('.hub-composer .hub-image-button').waitFor()
  await page.getByRole('button',{name:'预览图片: picker.png',exact:true}).click()
  await page.locator('.hub-image-dialog[open]').waitFor()
  assert.equal(calls.filter(c=>c.op==='app_attachment').at(-1).body.session_id,'running')
  await page.keyboard.press('Escape')
  await composer.evaluate((e,base64)=>{const bytes=Uint8Array.from(atob(base64),c=>c.charCodeAt(0));const d=new DataTransfer();d.items.add(new File([bytes],'pasted.png',{type:'image/png'}));e.dispatchEvent(new ClipboardEvent('paste',{clipboardData:d,bubbles:true,cancelable:true}))},imageFile.buffer.toString('base64'))
  await page.waitForFunction(()=>document.querySelectorAll('.hub-composer .hub-image-button').length===2)
  await page.locator('.hub-composer').evaluate((e,base64)=>{const bytes=Uint8Array.from(atob(base64),c=>c.charCodeAt(0));const d=new DataTransfer();d.items.add(new File([bytes],'dropped.png',{type:'image/png'}));e.dispatchEvent(new DragEvent('drop',{dataTransfer:d,bubbles:true,cancelable:true}))},imageFile.buffer.toString('base64'))
  await page.waitForFunction(()=>document.querySelectorAll('.hub-composer .hub-image-button').length===3)
  await page.getByRole('button',{name:'移除图片: pasted.png',exact:true}).click()
  await page.evaluate(()=>window.showDetail(null));await composer.waitFor({state:'detached'});await page.locator('#root .hub-task').click()
  assert.equal(await page.locator('.hub-composer .hub-image-button').count(),2)
  assert.equal(await composer.inputValue(),'')
  loseReceipt=true
  await page.locator('#detail').getByRole('button',{name:'发送到原任务 ↑',exact:true}).click()
  await page.getByRole('button',{name:'核对发送结果',exact:true}).waitFor()
  assert.equal(await page.getByRole('button',{name:'移除图片: picker.png',exact:true}).isDisabled(),true)
  await page.getByRole('button',{name:'核对发送结果',exact:true}).click()
  await page.waitForFunction(()=>document.querySelectorAll('.hub-composer .hub-image-button').length===0)
  const imageAttempts=calls.filter(c=>c.op==='app_dispatch').slice(-2)
  assert.deepEqual(imageAttempts[0].body,imageAttempts[1].body)
  assert.deepEqual(imageAttempts[0].body.attachments,['image-0','image-2'])
  assert.equal(imageAttempts[0].body.prompt,'')
  assert.equal(deliveries.size,2)
  await page.locator('.hub-composer input[type=file]').setInputFiles({name:'bad.svg',mimeType:'image/svg+xml',buffer:Buffer.from('<svg/>')})
  await page.getByRole('alert').filter({hasText:'PNG、JPEG、WebP'}).waitFor()
  await page.screenshot({path:path.join(root,'codex-conversation-ui.png')})
  await page.locator('#detail').getByRole('button',{name:'在 Codex App 中打开',exact:true}).click()
  await page.waitForFunction(()=>window.notifications.some(n=>n.message==='已在 Codex 中打开原任务。'))
  assert.equal(calls.filter(c=>c.op==='app_open').length,1)
  assert.equal(calls.find(c=>c.op==='app_open').body.session_id,'running')
  await page.locator('#detail').getByRole('button',{name:'重新开启任务',exact:true}).click()
  await page.getByLabel('快捷筛选',{exact:true}).selectOption('open')
  assert.equal(await page.locator('#root .hub-task').count(),6)
  await page.getByLabel('快捷筛选',{exact:true}).selectOption('unfinished')
  assert.equal(await page.locator('#root .hub-task').count(),4)
  await page.getByLabel('快捷筛选',{exact:true}).selectOption('finished')
  assert.equal(await page.locator('#root .hub-task').count(),2)
  await page.getByLabel('快捷筛选',{exact:true}).selectOption('all')
  await page.getByRole('button',{name:'筛选',exact:true}).click()
  await page.getByRole('button',{name:'添加条件',exact:true}).click()
  await page.getByRole('button',{name:'筛选值',exact:true}).click()
  await page.getByRole('checkbox',{name:'Claude',exact:true}).check()
  assert.equal(await page.locator('#root .hub-task').count(),2)
  await page.keyboard.press('Escape')
  await page.getByRole('button',{name:'添加条件',exact:true}).click()
  await page.getByLabel('筛选字段',{exact:true}).nth(1).selectOption('title')
  await page.getByRole('textbox',{name:'筛选值',exact:true}).fill('权限')
  assert.equal(await page.locator('#root .hub-task').count(),1)
  await page.getByLabel('匹配方式').selectOption('any')
  assert.equal(await page.locator('#root .hub-task').count(),2)
  await page.screenshot({path:path.join(root,'board-filter-preview.png')})
  await page.keyboard.press('Escape')
  await page.reload()
  await page.locator('#root .hub-task').first().waitFor()
  assert.equal(await page.locator('#root .hub-task').count(),2)
  await page.getByRole('button',{name:'筛选 2',exact:true}).click()
  await page.getByRole('button',{name:'清空',exact:true}).click()
  await page.keyboard.press('Escape')
  await page.getByLabel('搜索任务、项目或 Session ID').fill('API')
  assert.equal(await page.locator('#root .hub-task').count(),1)
  await page.getByLabel('搜索任务、项目或 Session ID').fill('')
  await page.getByRole('button',{name:'字段配置',exact:true}).click()
  await page.getByRole('button',{name:'显示字段 Session ID',exact:true}).click()
  await page.getByRole('button',{name:'上移 Session ID',exact:true}).click()
  assert.deepEqual(await page.locator('#root .hub-task').first().locator('dt').allTextContents(),['引擎','项目','更新时间','Session ID','最新动态'])
  await page.locator('[data-field="session_id"] .hub-drag').dragTo(page.locator('[data-field="engine"]'))
  assert.equal(await page.locator('#root .hub-task').first().locator('dt').first().textContent(),'Session ID')
  await page.screenshot({path:path.join(root,'board-fields-preview.png')})
  await page.keyboard.press('Escape')
  await page.getByLabel('分组',{exact:true}).selectOption('engine')
  assert.equal(await page.locator('.hub-column').count(),3)
  await page.reload()
  await page.locator('[data-task-key="codex:running"]').first().waitFor()
  assert.equal(await page.getByLabel('分组',{exact:true}).inputValue(),'engine')
  assert.equal(await page.locator('#root .hub-task').first().locator('dt').first().textContent(),'Session ID')
  await page.locator('#reference button').click()
  assert.equal((await page.evaluate(()=>window.workspace)).id,'session-hub-task:codex:running')
  await page.getByRole('button',{name:'← 返回看板',exact:true}).click()
  assert.equal(await page.evaluate(()=>window.navigated),'/session-board')
  fixture[0].state='unread';fixture[0].revision='r2'
  await page.getByRole('button',{name:'刷新',exact:true}).click()
  await page.locator('#reference [data-state="unread"]').waitFor()
  await page.locator('#detail').getByRole('button',{name:'标记结果已查看'}).click()
  await page.locator('#reference [data-state="completed"]').waitFor()
  await page.locator('[data-task-key^="hermes:"]').click()
  assert.equal((await page.evaluate(()=>window.opened)).id,'hermes-1')
  await page.getByRole('button',{name:'+ 新建任务'}).click()
  await page.getByLabel('描述要执行的任务',{exact:true}).fill('Only test dispatch payload')
  await page.getByRole('button',{name:'创建并运行',exact:true}).click()
  await page.waitForFunction(()=>window.workspace?.id==='session-hub-task:job:job-1')
  assert.equal(calls.filter(c=>c.op==='task_create').length,1)
  // Claude shares the original-session composer and engine-specific identity.
  await page.locator('#root [data-task-key="codex:attention"]').click()
  await page.getByRole('textbox',{name:'继续原 Claude 任务',exact:true}).fill('Claude original session followup')
  await page.locator('#detail').getByRole('button',{name:'发送到原任务 ↑',exact:true}).click()
  await page.waitForFunction(()=>document.querySelector('#detail [data-delivery-state]'))
  assert.equal(calls.filter(c=>c.op==='app_dispatch').at(-1).body.engine,'claude')
  assert.equal(calls.filter(c=>c.op==='app_dispatch').at(-1).body.session_id,'attention')
  await page.locator('#detail').getByRole('button',{name:'在 Claude App 中打开',exact:true}).click()
  assert.equal(calls.filter(c=>c.op==='app_open').at(-1).body.engine,'claude')
  await page.screenshot({path:path.join(root,'claude-conversation-preview.png')})
  await page.getByRole('button',{name:'+ 新建任务'}).click()
  await page.getByLabel('引擎',{exact:true}).selectOption('claude')
  assert.equal(await page.getByLabel('执行通道',{exact:true}).inputValue(),'app')
  await page.getByLabel('描述要执行的任务',{exact:true}).fill('Claude dedicated draft')
  await page.getByRole('button',{name:'在 Claude App 准备草稿',exact:true}).click()
  await page.waitForFunction(()=>window.notifications.some(n=>n.message.includes('Claude 草稿')))
  assert.equal(calls.filter(c=>c.op==='app_prepare_claude').length,1)
  assert.equal(calls.filter(c=>c.op==='task_create').length,1)
  await page.getByRole('button',{name:'取消',exact:true}).click()
  await page.getByLabel('分组',{exact:true}).selectOption('state')
  fixture[0].state='running';await page.getByRole('button',{name:'刷新',exact:true}).click()
  await page.locator('#reference [data-state="running"]').waitFor()
  await page.emulateMedia({reducedMotion:'reduce'})
  assert.equal(await page.locator('#reference .hub-dot').evaluate(e=>getComputedStyle(e).animationName),'none')
  await page.emulateMedia({reducedMotion:'no-preference'})
 }
 await page.screenshot({path:path.join(root,live?'board-live-preview.png':'board-preview.png'),fullPage:false})
 await page.setViewportSize({width:600,height:850});assert.equal(await page.locator('body').evaluate(e=>e.scrollWidth<=innerWidth),true)
 if(!live){
  await page.getByRole('button',{name:'筛选',exact:true}).click()
  await page.getByRole('button',{name:'添加条件',exact:true}).click()
  assert.equal(await page.locator('.hub-filter-panel').evaluate(e=>e.scrollWidth<=e.clientWidth),true)
  await page.keyboard.press('Escape')
 }
 if(errors.length)throw Error(errors.join('\n'))
 if(!live){const lifecycle=await page.evaluate(()=>window.testStyleLifecycle());assert.equal(lifecycle.during,lifecycle.before+1);assert.equal(lifecycle.after,lifecycle.before)}
 const result={mode:live?'real-service-readonly':'interactive-fixture',passed:true,errors,tests:live?['real inventory','render','narrow viewport']:['Claude same-session composer and engine-specific App open','Claude new App draft does not create a fake task','paste/picker/drop images, remove, preview, restore and image-only stable retry','invalid image rejection','workspace sidebar label follows task state','same-session composer with stable request after lost receipt and remount','manual close/reopen persisted independently of running state','open/closed quick filters','default Hermes detail and explicit Codex native activation','neutral surface with blue accent theme','retained legacy task styles cannot override current board/select/cards','stylesheet lifetime cleanup','permanent navigation contribution and return','quick completion filters','multi-condition AND/OR filters','persisted conditions','search','field visibility and drag/keyboard order','persisted fields/preferences','grouping','inline status update','mark-read synchronization','open Hermes owner','Agent task dispatch payload','reduced motion','narrow viewport and popovers']}
 await fs.writeFile(path.join(root,live?'board-live-results.json':'board-ui-results.json'),JSON.stringify(result,null,2))
 console.log(JSON.stringify(result))
 }
}finally{await browser.close();server.close()}
