import {createElement,useState,useEffect,useLayoutEffect,useRef} from 'react'
import {host,Streamdown,usePluginI18n,ROUTES_AREA,SIDEBAR_NAV_AREA,STATUSBAR_AREAS} from '@hermes/plugin-sdk'
import {BoardPage,TaskReference,setupBoard,openNativeTask} from './board-ui.js'
import {ImagePreview} from './image-preview.js'
import {conversationGroups} from './conversation-model.js'
import {DocumentLink,ChangedFiles,isLocalLink,safeLink} from './conversation-artifacts.js'
const h=createElement
let rpc,storage
const style={fontFamily:'inherit',fontSize:13,padding:10,border:'1px solid #8a8a8a55',borderRadius:8,background:'transparent',color:'inherit'}
const btn=(label,onClick,disabled=false)=>h('button',{style:{...style,cursor:'pointer',padding:'7px 10px',whiteSpace:'nowrap',flexShrink:0},onClick,disabled},label)
const input=(value,onChange,placeholder)=>h('input',{style:{...style,width:'100%',minWidth:0},value,onChange:e=>onChange(e.target.value),placeholder})
const pre={whiteSpace:'pre-wrap',overflowWrap:'anywhere',fontSize:12,fontFamily:'ui-monospace,Consolas,monospace',margin:'8px 0',maxHeight:420,overflow:'auto'}
const stringify=value=>typeof value==='string'?value:JSON.stringify(value,null,2)
const labels={user:'你',assistant:'助手',peer:'跨会话指令',activity:'工具与执行',context:'上下文 / 附件',event:'会话事件'}
function NativeImage({data,kind,target,itemId}){
 const [loaded,setLoaded]=useState(''),[error,setError]=useState(''),[busy,setBusy]=useState(false)
 const managed=data.attachment_id
 const source=data.source||{},url=source.type==='base64'?`data:${source.media_type};base64,${source.data}`:data.image_url||data.url||''
 const safe=typeof url==='string'&&/^data:image\/(png|jpeg|gif|webp);base64,/i.test(url),path=data.path||data.savedPath
 const load=async()=>{setBusy(true);try{const r=managed?await rpc('app_attachment',{...target,attachment_id:managed}):await rpc('transcript_asset',{engine:target.engine,session_id:target.session_id,item_id:itemId,asset_path:path});setLoaded(r.data_url);setError('');return r.data_url}catch(e){setError(String(e))}finally{setBusy(false)}}
 if(managed&&data.thumbnail)return h(ImagePreview,{src:data.thumbnail,name:data.name||'image.png',load:async()=>(await rpc('app_attachment',{...target,attachment_id:managed})).data_url})
 return h('div',null,safe||loaded?h(ImagePreview,{src:loaded||url,name:data.name||'原会话附件'}):h('div',{style:{...style,opacity:.8}},`附件 · ${kind} · ${path||data.filename||data.title||source.url||'本地文件或远程资源（未自动加载）'}`,path&&target&&btn(busy?'读取图片…':'预览图片',load,busy)),error&&h('small',{style:{color:'#ef9f8f'}},error))
}
function Block({block:b,target,itemId}){
 if(b.type==='text')return h(Streamdown,{mode:'static',skipHtml:true,urlTransform:safeLink,components:{img:({alt})=>h('span',{style:{opacity:.65}},`[图片：${alt||'请在原 App 查看'}]`),a:({href,children})=>/^https?:\/\//i.test(href||'')?h('a',{href,target:'_blank',rel:'noreferrer noopener',className:'hub-external-link'},children):isLocalLink(href)?h(DocumentLink,{href,target,itemId,rpc},children):h('span',null,children)},controls:{code:true,table:true}},b.text)
 if(b.type==='notice')return h('small',{style:{opacity:.65}},b.text)
 if(b.type==='attachment')return h(NativeImage,{data:b.data,kind:b.kind,target,itemId})
 if(b.type==='tool_call')return h('div',null,h('strong',null,b.name||'工具调用'),h('small',{style:{display:'block',opacity:.55}},b.call_id),h('pre',{style:pre},stringify(b.input)))
 if(b.type==='tool_result')return h('div',null,h('small',{style:{opacity:.7}},`执行结果${b.error?' · 错误':''}${b.exit_code!=null?' · exit '+b.exit_code:''}`),...((b.blocks||[]).map((v,i)=>v.type==='text'?h('pre',{key:i,style:pre},v.text):h(Block,{key:i,block:v,target,itemId}))))
 if(b.type==='diff')return h('div',null,h('code',null,b.path),h('pre',{style:pre,className:'hub-diff'},...String(b.text||'').split('\n').map((line,i)=>h('span',{key:i,'data-change':line.startsWith('+')?'add':line.startsWith('-')?'remove':'context'},line+'\n'))))
 return h('pre',{style:pre},stringify(b.data))
}
function TimelineItem({item,target,conversation=false,showSource=true}){
 const t=usePluginI18n('session-hub'),[copied,setCopied]=useState(false)
 const chat=['user','assistant','peer'].includes(item.role),user=item.role==='user'||item.local_input
 const images=conversation&&user?item.blocks.filter(b=>b.type==='attachment'):[]
 const body=images.length?item.blocks.filter(b=>b.type!=='attachment'):item.blocks
 const content=h('div',{className:'hub-message-body'},...body.map((b,i)=>h(Block,{key:i,block:b,target,itemId:item.id})))
 const copy=async()=>{try{await navigator.clipboard.writeText(item.blocks.filter(b=>b.type==='text').map(b=>b.text).join('\n\n'));setCopied(true);setTimeout(()=>setCopied(false),1800)}catch{setCopied(false)}}
 return h('article',{'data-transcript-id':item.id,'data-role':user?'user':item.role,className:conversation?'hub-message':undefined,style:conversation?undefined:{padding:'14px 18px',margin:'10px 0',marginLeft:user?'12%':0,marginRight:user?0:'4%',borderRadius:12,background:user?'#637fff18':'#8899aa08',border:'1px solid #8882',overflowWrap:'anywhere'}},
  images.length>0&&h('div',{className:'hub-attachment-strip'},...images.map((b,i)=>h(Block,{key:i,block:b,target,itemId:item.id}))),
  (!conversation||!user&&!chat)&&h('div',{className:'hub-message-label'},h('strong',null,labels[item.role]||item.role),h('small',null,item.phase==='commentary'?'进展':item.phase==='final_answer'?'回复':chat?'':item.kind),item.sidechain&&h('small',null,'分支记录')),
  chat?content:h('details',null,h('summary',{style:{cursor:'pointer',opacity:.85}},item.kind==='reasoning'?'思考记录（不含私有推理内容）':item.kind==='fileChange'?`已修改 ${item.blocks.filter(b=>b.type==='diff').length} 个文件 · 展开查看`:`${item.kind} · 展开查看`),content),
  conversation&&chat&&body.some(b=>b.type==='text')&&h('button',{className:'hub-copy-message',onClick:()=>void copy(),'aria-label':t('copyMessage')},copied?t('copiedMessage'):t('copyMessage')),
  conversation&&h(ChangedFiles,{summary:item.change_summary,cwd:target.cwd}),
  showSource&&h('details',{style:{fontSize:11,opacity:.6,marginTop:10}},h('summary',null,'来源记录'),h('code',null,item.id),h('pre',{style:pre},stringify({turn_id:item.turn_id,parent_id:item.parent_id,timestamp:item.timestamp,...item.details}))))
}
function ConversationRows({items,target,showSource}){
 const t=usePluginI18n('session-hub'),groups=conversationGroups(items)
 return groups.map((group,index)=>group.activity?h('details',{className:'hub-execution',key:group.items[0].id,open:index===groups.length-1?true:undefined},
  h('summary',null,t('processing')+' · '+group.items.length),...group.items.map(item=>h(TimelineItem,{key:item.id,item,target,conversation:true,showSource})))
  :h(TimelineItem,{key:group.items[0].id,item:group.items[0],target,conversation:true,showSource}))
}
function Transcript({target,onLoaded,conversation=false}){
 const [items,setItems]=useState([]),[meta,setMeta]=useState(null),[cursor,setCursor]=useState(null),[error,setError]=useState(''),[busy,setBusy]=useState(false),[showContext,setShowContext]=useState(false),[exporting,setExporting]=useState(false)
 const viewport=useRef(null),state=useRef(null),follow=useRef(true),loaded=useRef(onLoaded)
 loaded.current=onLoaded
 const merge=(old,incoming)=>{const map=new Map(old.map(i=>[i.id,i]));for(const i of incoming)map.set(i.id,i);return [...map.values()].sort((a,b)=>a.position-b.position||a.id.localeCompare(b.id))}
 const bottom=()=>requestAnimationFrame(()=>{if(follow.current&&viewport.current)viewport.current.scrollTop=viewport.current.scrollHeight})
 useLayoutEffect(()=>{if(follow.current&&viewport.current)viewport.current.scrollTop=viewport.current.scrollHeight},[items])
 useEffect(()=>{let active=true,timer;setItems([]);setMeta(null);setCursor(null);setError('');state.current=null;follow.current=true
  const load=async()=>{try{const previous=state.current;const result=await rpc('transcript',{engine:target.engine,session_id:target.session_id,limit:40,...(previous?{since:previous.revision,generation:previous.generation}:{})});if(!active)return
   if(!previous){setItems(result.items);setCursor(result.next_cursor)}else setItems(old=>merge(old,result.items))
   state.current=result;setMeta(result);setError('');bottom();if(follow.current)loaded.current?.();timer=setTimeout(load,previous&&result.has_more?100:3000)
  }catch(e){if(active){setError(String(e));if(String(e).includes('重新加载')){state.current=null;setItems([]);setCursor(null)}timer=setTimeout(load,8000)}}}
  load();return()=>{active=false;clearTimeout(timer)}
 },[target.engine,target.session_id])
 const older=async()=>{setBusy(true);const saved=viewport.current,oldHeight=saved?.scrollHeight||0;try{const r=await rpc('transcript',{engine:target.engine,session_id:target.session_id,cursor,limit:40});setItems(old=>merge(old,r.items));setCursor(r.next_cursor);requestAnimationFrame(()=>{if(saved)saved.scrollTop+=saved.scrollHeight-oldHeight})}catch(e){setError(String(e))}finally{setBusy(false)}}
 const exportHistory=async()=>{setExporting(true);try{let next='',all=[];do{const r=await rpc('transcript',{engine:target.engine,session_id:target.session_id,cursor:next,limit:100});all=[...r.items,...all];next=r.next_cursor}while(next);const link=document.createElement('a');const url=URL.createObjectURL(new Blob([JSON.stringify({engine:target.engine,session_id:target.session_id,scope:meta?.scope,coverage:meta?.coverage,exported_at:new Date().toISOString(),items:all},null,2)],{type:'application/json'}));link.href=url;link.download=`${target.engine}-${target.session_id}.json`;link.click();setTimeout(()=>URL.revokeObjectURL(url),30000)}catch(e){setError(String(e))}finally{setExporting(false)}}
 return h('section',{'aria-label':'共享会话时间线',className:conversation?'hub-conversation-transcript':undefined,style:conversation?undefined:{border:'1px solid #8883',borderRadius:12,overflow:'hidden'}},
  h('div',{style:{display:'flex',alignItems:'center',flexWrap:'wrap',gap:10,padding:12,borderBottom:'1px solid #8883'}},h('strong',null,'原会话记录'),h('small',null,meta?`已载入 ${items.length} / ${meta.total} 条 · 每 3 秒同步`:'正在读取本地历史…'),btn('跳到最新',()=>{follow.current=true;bottom()}),btn(exporting?'正在导出…':'导出全部记录',exportHistory,!meta||exporting),h('label',{style:{fontSize:12}},h('input',{type:'checkbox',checked:showContext,onChange:e=>setShowContext(e.target.checked)}),'显示上下文记录')),
  error&&h('p',{role:'alert',style:{color:'#ef9f8f',padding:12}},error),
  h('div',{ref:viewport,'data-testid':'transcript-scroll',onScroll:()=>{const e=viewport.current;follow.current=e.scrollHeight-e.scrollTop-e.clientHeight<100},style:{height:560,minHeight:250,overflow:'auto',padding:'12px 22px'}},
   cursor&&btn(busy?'读取中…':'加载更早记录',older,busy),!cursor&&meta&&h('p',{style:{textAlign:'center',fontSize:11,opacity:.5}},'已到本地历史开头'),
   conversation?h(ConversationRows,{items:items.filter(i=>showContext||!['context','event'].includes(i.role)),target:{...target,cwd:meta?.cwd||target.cwd},showSource:showContext}):items.filter(i=>showContext||i.role!=='context').map(i=>h(TimelineItem,{key:i.id,item:i,target,showSource:true}))),
  meta&&h('div',{style:{padding:'8px 12px',fontSize:11,opacity:.65,borderTop:'1px solid #8882'}},`原 session ID：${meta.session_id} · ${meta.coverage.scanned_records} 条源记录已扫描 · 保留原 App 会话`,...meta.coverage.warnings.map((w,i)=>h('p',{key:i,style:{color:'#ef9f8f'}},w))))
}
function LivePanel(){
 const [engine,setEngine]=useState('codex'),[query,setQuery]=useState(''),[rows,setRows]=useState([]),[target,setTarget]=useState(null),[prompt,setPrompt]=useState(''),[jobs,setJobs]=useState([]),[error,setError]=useState(''),[sending,setSending]=useState(false)
 const request=useRef(0)
 const refresh=async()=>{const ticket=++request.current;try{const [s,j,history]=await Promise.all([rpc('app_sessions',{engine}),rpc('app_jobs',{}),rpc('sessions',{engine,query,limit:200})]);if(ticket!==request.current)return;const live=new Map(s.sessions.map(r=>[r.session_id,{...r,live:true}]));const merged=history.sessions.map(r=>({...r,...live.get(r.session_id),live:live.has(r.session_id)}));const seen=new Set(merged.map(r=>r.session_id));setRows([...s.sessions.filter(r=>!seen.has(r.session_id)).map(r=>({...r,live:true})),...merged]);setJobs(j.jobs);setError((s.errors||[]).join('; '))}catch(e){if(ticket===request.current)setError(String(e))}}
 useEffect(()=>{refresh();const t=setInterval(refresh,10000);return()=>{++request.current;clearInterval(t)}},[engine,query])
 const send=async()=>{setSending(true);try{const job=await rpc('app_dispatch',{engine,session_id:target?.session_id||'',host_id:target?.host_id||'local',prompt,request_key:crypto.randomUUID()});setPrompt('');host.notify({kind:'info',message:`App 任务已排队 ${job.id.slice(0,8)}`});await refresh()}catch(e){setError(String(e))}finally{setSending(false)}}
 return h('section',{style:{...style,padding:18,borderColor:'#628bea',display:'flex',flexDirection:'column',gap:12}},
  h('h3',{style:{fontSize:20,margin:0}},'共享会话 · App 实时控制'),
  h('p',{style:{margin:0,opacity:.75}},'在 Hermes 查看原会话历史，消息继续发回同一个 session。支持 Codex 与 Claude Code；本地已保存的消息、工具调用和执行结果可逐页读取。'),
  h('div',{style:{display:'flex',gap:8}},h('select',{style,value:engine,onChange:e=>{setEngine(e.target.value);setTarget(null)}},h('option',{value:'codex'},'Codex App'),h('option',{value:'claude'},'Claude Code')),input(query,setQuery,'搜索 App 任务标题或 ID'),btn('刷新 App',refresh),engine==='codex'&&btn('新建 Codex App 任务',()=>setTarget(null))),
  error&&h('pre',{style:{color:'#e77966',whiteSpace:'pre-wrap'}},error),
  h('div',{style:{maxHeight:180,overflow:'auto',display:'flex',flexDirection:'column',gap:6}},...rows.filter(r=>!query||(r.title+' '+r.session_id).toLowerCase().includes(query.toLowerCase())).map(r=>h('button',{key:r.engine+r.session_id,style:{...style,textAlign:'left',background:target?.session_id===r.session_id?'#618aff22':'transparent'},onClick:()=>{setTarget(r);setPrompt('')},disabled:sending},`${r.title} · ${typeof r.status==='object'?r.status?.type:r.status||'本地历史'} · ${r.origin}`,h('small',{style:{display:'block',opacity:.65}},r.session_id)))),
  h('strong',null,target?`目标：${target.title}`:engine==='codex'?'新建：独立 Codex App 任务（无项目）':'请先打开并选择一个 Claude Code 会话'),
  target&&engine==='codex'&&btn('在 Codex App 中打开',()=>openNativeTask(target).catch(e=>setError(String(e)))),
  target&&h(Transcript,{key:target.engine+target.session_id,target}),
  target&&engine==='claude'&&!rows.some(r=>r.session_id===target.session_id&&r.live)&&h('p',{style:{color:'#ddbd81'}},'这个 Claude Code 会话目前未打开，可浏览全部本地记录。请在 Claude App 打开原会话后再发送。'),
  h('textarea',{style:{...style,minHeight:80},value:prompt,onChange:e=>setPrompt(e.target.value),placeholder:'任务会真实发送到选中的 App 会话；执行中也可以追加指令。'}),
  btn(sending?'正在提交…':target?'发送到 App 原会话':'创建 Codex App 任务',send,sending||!prompt.trim()||(engine==='claude'&&(!target||!rows.some(r=>r.session_id===target.session_id&&r.live)))),
  ...jobs.slice(0,8).map(j=>h('details',{key:j.id,style},h('summary',null,`${j.engine} · ${j.state} · ${j.session_id||j.id.slice(0,8)}`),h('p',null,j.detail),j.answer&&h('pre',{style:{whiteSpace:'pre-wrap'}},j.answer))),
  h('small',{style:{opacity:.7}},'共享的是原会话和已保存的记录。原 App 的私有界面、审批弹窗、未落盘内容与私有推理无法完整镜像；审批仍在原 App 处理。Claude 接收的是同 session 的官方跨会话消息。')
 )
}
function Page(){
 const [engine,setEngine]=useState(''),[query,setQuery]=useState(''),[rows,setRows]=useState([]),[selected,setSelected]=useState(null),[detail,setDetail]=useState(null),[jobs,setJobs]=useState([]),[events,setEvents]=useState([]),[error,setError]=useState(''),[prompt,setPrompt]=useState(''),[cwd,setCwd]=useState(''),[mode,setMode]=useState('read-only'),[sending,setSending]=useState(false)
 const run=async f=>{try{setError('');return await f()}catch(e){setError(String(e));return null}}
 const refresh=()=>run(async()=>{const [s,j,e]=await Promise.all([rpc('sessions',{engine,query,limit:100}),rpc('jobs',{}),rpc('events',{recent:true})]);setRows(s.sessions);setJobs(j.jobs);setEvents(e.events);if(s.errors?.length)setError(s.errors.join('; '))})
 useEffect(()=>{refresh();const timer=setInterval(refresh,7000);return()=>clearInterval(timer)},[engine,query])
 useEffect(()=>{if(!selected){setDetail(null);return}let live=true;const read=()=>run(async()=>{const s=await rpc('read',{engine:selected.engine,session_id:selected.session_id,limit:15});if(live)setDetail(s)});read();const t=setInterval(read,5000);return()=>{live=false;clearInterval(t)}},[selected?.session_id,selected?.engine])
 const submit=()=>run(async()=>{setSending(true);try{const result=await rpc('dispatch',{engine:selected?.engine||engine||'codex',session_id:selected?.session_id||'',cwd,prompt,mode,request_key:crypto.randomUUID()});host.notify({kind:'info',message:`任务已排队：${result.id.slice(0,8)}`});setPrompt('');await refresh()}finally{setSending(false)}})
 const status=s=>s?.writer_owned?'App 持有 · 等待交接':({running:'执行中',completed:'本轮已完成',interrupted:'已中断',unknown:'状态待确认'}[s?.status]||'')
 return h('div',{style:{padding:24,height:'100%',overflow:'auto',display:'flex',flexDirection:'column',gap:16}},
  h('div',null,h('h2',{style:{fontSize:24,fontWeight:650}},'会话协作 · Session Hub'),h('p',{style:{opacity:.7}},'读取原生历史 · 同 ID 交接续开发 · 异步任务 · 完成收件箱')),
  btn('打开统一任务看板',()=>host.navigate('/session-board')),
  h(LivePanel),
  h('h3',{style:{fontSize:20}},'历史与 CLI 交接'),
  h('div',{style:{padding:12,background:'#618aff15',borderRadius:8}},'下方保留原生历史查询和 CLI 交接。要直接向 App 当前会话发消息，请使用上方“App 实时控制”。Claude Chat / Cowork 不在当前接入范围。'),
  error&&h('pre',{style:{color:'#e77966',whiteSpace:'pre-wrap'}},error),
  h('div',{style:{display:'flex',gap:8}},h('select',{style,value:engine,onChange:e=>{setEngine(e.target.value);setSelected(null)}},h('option',{value:''},'全部引擎'),h('option',{value:'codex'},'Codex'),h('option',{value:'claude'},'Claude Code')),input(query,setQuery,'搜索任务标题、工作目录、session ID'),btn('刷新',refresh),btn('新建会话任务',()=>setSelected(null))),
  h('div',{style:{display:'grid',gridTemplateColumns:'minmax(240px,32%) minmax(0,1fr)',gap:18,minHeight:380}},
   h('div',{style:{maxHeight:600,overflow:'auto',display:'flex',flexDirection:'column',gap:6}},...rows.map(s=>h('button',{key:s.engine+s.session_id,onClick:()=>{setSelected(s);setCwd(s.cwd)},style:{...style,textAlign:'left',background:selected?.session_id===s.session_id?'#618aff22':'transparent'}},h('small',null,`${s.engine} · ${s.origin}`),h('div',{style:{fontWeight:600,margin:'4px 0'}},s.title),h('small',{style:{opacity:.65,wordBreak:'break-all'}},s.cwd)))),
   h('div',{style:{display:'flex',flexDirection:'column',gap:10}},
    h('h3',{style:{fontSize:18,fontWeight:600}},selected?'续接：'+selected.title:'新建原生会话'),
    detail&&h('div',null,
     h('div',null,status(detail)),
     h('code',{style:{fontSize:11}},detail.session_id),
     detail.recent_tools?.length>0&&h('div',{style:{fontSize:12,opacity:.7,marginTop:6}},'最近工具：'+detail.recent_tools.map(t=>t.tool).join(' → ')),
     h('div',{style:{marginTop:8}},
      btn('关注后续完成',()=>run(()=>rpc('watch',{engine:detail.engine,session_id:detail.session_id,enabled:true}))),
      ' ',btn('取消关注',()=>run(()=>rpc('watch',{engine:detail.engine,session_id:detail.session_id,enabled:false})))
     )
    ),
    detail&&h('div',{style:{maxHeight:330,overflow:'auto',padding:12,border:'1px solid #8884',borderRadius:8}},...detail.messages.map((m,i)=>h('div',{key:i,style:{marginBottom:12}},h('strong',null,m.role==='user'?'用户':'助手'),h('pre',{style:{whiteSpace:'pre-wrap',fontFamily:'inherit',fontSize:12,overflowWrap:'anywhere'}},m.text)))),
    !selected&&input(cwd,setCwd,'新会话的绝对工作目录'),
    h('select',{style,value:mode,onChange:e=>setMode(e.target.value)},h('option',{value:'read-only'},'分析 / 只读评审'),h('option',{value:'workspace-write'},'开发：允许修改工作区（保留引擎权限约束）')),
    h('textarea',{style:{...style,minHeight:110,width:'100%'},value:prompt,onChange:e=>setPrompt(e.target.value),placeholder:selected?'发送到这个原生 session；若仍被 App 持有，会等待交接。':'输入开发任务，自动创建原生 session。'}),
    btn(sending?'正在提交…':`交给 ${selected?.engine||engine||'codex'} 执行`,submit,sending||!prompt.trim())
   )),
  h('h3',{style:{fontSize:18,fontWeight:600}},'任务队列'),
  ...jobs.slice(0,15).map(j=>h('div',{key:j.id,style},h('strong',null,`${j.engine} · ${j.state} · ${j.id.slice(0,8)}`),h('div',null,j.prompt.slice(0,180)),h('small',null,j.detail),j.session_id&&h('div',null,h('code',null,j.session_id),' ',btn('读取结果会话',()=>setSelected({engine:j.engine,session_id:j.session_id,title:j.prompt.slice(0,40),cwd:j.cwd}))),['queued','waiting_handoff'].includes(j.state)&&btn('取消排队',()=>run(async()=>{await rpc('cancel',{job_id:j.id});await refresh()})),j.answer&&h('details',null,h('summary',null,'执行结果'),h('pre',{style:{whiteSpace:'pre-wrap'}},j.answer)))),
  h('h3',{style:{fontSize:18,fontWeight:600}},'完成收件箱'),
  ...events.slice(-20).reverse().map(e=>h('details',{key:e.seq,style},h('summary',null,`${e.engine} · ${e.kind} · ${new Date(e.created*1000).toLocaleString()}`),h('code',null,e.session_id),h('pre',{style:{whiteSpace:'pre-wrap'}},e.text))),
  h('p',{style:{opacity:.6}},'完成代表原生引擎的一轮已结束，是否达到开发目标请查看结果。被持有的 session 不会强行抢占。')
 )
}
function InboxBadge(){
 const [count,setCount]=useState(0)
 useEffect(()=>{let live=true,cursor=storage.get('eventCursor',0);const poll=async()=>{try{const e=await rpc('events',{after:cursor});if(!live)return;setCount(e.latest);if(e.events.length){const item=e.events[e.events.length-1];host.notify({kind:item.kind==='failed'?'error':'info',title:'会话协作',message:`收到 ${e.events.length} 条完成/结果通知`,detail:`${item.engine}：${item.kind}。点击底部“会话协作”查看结果。`})}cursor=e.cursor;storage.set('eventCursor',cursor)}catch{}};poll();const t=setInterval(poll,5000);return()=>{live=false;clearInterval(t)}},[])
 return h('button',{style:{fontSize:12,padding:'2px 8px'},onClick:()=>host.navigate('/session-hub')},`会话协作 · ${count}`)
}
export default {id:'session-hub',name:'会话协作 Session Hub',register(ctx){
 rpc=async(operation,body)=>{
  try{return await ctx.rest('/rpc/'+operation,{method:'POST',body,timeoutMs:60000})}
  catch(error){if(/\b(404|405)\b/.test(String(error)))throw new Error('插件后端尚未加载。结束当前 Hermes 回复后，重启桌面后端或退出并重新打开 Hermes Desktop。');throw error}
 }
 storage=ctx.storage
 ctx.onDispose(setupBoard(ctx,rpc,Transcript))
 ctx.registerMany([{id:'board',area:ROUTES_AREA,title:ctx.i18n.t('boardView'),data:{path:'/session-board'},render:()=>h(BoardPage)},{id:'board-nav',area:SIDEBAR_NAV_AREA,data:{path:'/session-board',label:ctx.i18n.t('boardView'),codicon:'layout'}},{id:'task-reference',area:'chat.task-reference',data:{namespace:'session-hub',render:TaskReference}}])
 ctx.registerMany([{id:'page',area:ROUTES_AREA,data:{path:'/session-hub'},render:()=>h(Page)},{id:'nav',area:SIDEBAR_NAV_AREA,data:{path:'/session-hub',label:'会话协作',codicon:'comment-discussion'}},{id:'inbox',area:STATUSBAR_AREAS.right,order:140,render:()=>h(InboxBadge)}])
}}
