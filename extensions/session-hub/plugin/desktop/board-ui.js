import {createElement as h,useEffect,useState,useSyncExternalStore} from 'react'
import {host,Button,Input,Textarea,RowButton,usePluginI18n} from '@hermes/plugin-sdk'
import {normalizePrefs,hermesTask,selectTasks,groupTasks} from './board-model.js'
import {Control,FilterControl,FieldsControl} from './board-controls.js'
import {boardLocales} from './board-i18n.js'
import {conversationCss} from './conversation-style.js'
import {SessionComposer} from './session-composer.js'

let ctx,rpc,Transcript,timer,pending=false,disposed=false,closureVersion=0
const closing=new Set()
let snapshot={tasks:[],errors:[],loading:true,synced_at:0},external=[]
const listeners=new Set()
const publish=()=>{
 const rows=host.state.sessions?.get()||[],status=host.state.sessionStatus?.get()||{}
 snapshot={...snapshot,tasks:[...rows.filter(r=>!r.archived).map(r=>hermesTask(r,status[r.id])),...external].map(row=>({...row,closed:snapshot.closures?.[row.key]??row.closed??false}))}
 for(const listener of listeners)listener()
}
export async function refreshBoard(){
 if(pending||disposed)return
 pending=true
 const version=closureVersion
 try{const result=await rpc('board',{});if(disposed)return;external=result.tasks;snapshot={...snapshot,...result,closures:version===closureVersion?(result.closures||{}):{...result.closures,...snapshot.closures},loading:false};publish()}
 catch(e){if(!disposed){snapshot={...snapshot,loading:false,errors:[String(e)]};publish()}}
 finally{pending=false}
}
function subscribe(listener){listeners.add(listener);if(listeners.size===1){void refreshBoard();timer=setInterval(()=>{if(!document.hidden)void refreshBoard()},5000)}return()=>{listeners.delete(listener);if(!listeners.size)clearInterval(timer)}}
function useBoard(){return useSyncExternalStore(subscribe,()=>snapshot)}
const css=`
.hub-sidebar-task{display:flex;align-items:center;gap:6px;min-width:0;width:100%}.hub-sidebar-title{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1}.hub-sidebar-task small{font-size:9px;color:var(--ui-text-tertiary)}.hub-sidebar-task .hub-dot{background:var(--ui-text-tertiary);flex-shrink:0}.hub-sidebar-task[data-state=running] .hub-dot,.hub-sidebar-task[data-state=attention] .hub-dot{background:var(--ui-yellow);animation:hub-breathe 2s ease-in-out infinite}.hub-sidebar-task[data-state=unread] .hub-dot{background:var(--ui-green);animation:hub-breathe 2s ease-in-out infinite}@media(prefers-reduced-motion:reduce){.hub-sidebar-task .hub-dot{animation:none!important}}
.hub-conversation{padding:14px 24px;gap:8px;overflow:hidden}.hub-conversation-heading{display:flex;align-items:center;gap:12px;flex-wrap:wrap;flex-shrink:0}.hub-conversation-heading h2{font-size:14px;font-weight:600;margin:0;flex:1;min-width:180px}.hub-session-meta{font-size:11px;color:var(--ui-text-tertiary)}.hub-session-meta summary{cursor:pointer}.hub-session-meta code{overflow-wrap:anywhere}.hub-conversation-transcript{display:flex;flex-direction:column;flex:1;min-height:180px;overflow:hidden}.hub-conversation-transcript>div:first-child{font-size:11px;border-bottom:0!important;padding:4px 0!important;color:var(--ui-text-tertiary)}.hub-conversation-transcript>div:first-child button{padding:3px 7px!important;font-size:11px}.hub-conversation-transcript [data-testid=transcript-scroll]{height:auto!important;flex:1;min-height:0!important;padding:16px max(12px,calc((100% - 800px)/2))!important}.hub-conversation-transcript>div:last-child{border:0!important;font-size:10px!important}.hub-message{padding:14px 0;overflow-wrap:anywhere;font-size:14px;line-height:1.65}.hub-message[data-role=user]{margin:16px 0 16px 18%;padding:12px 18px;border-radius:18px;background:var(--ui-control-hover-background)}.hub-message[data-role=activity],.hub-message[data-role=event]{padding:5px 0;font-size:12px;color:var(--ui-text-secondary);border-bottom:1px solid var(--ui-stroke-tertiary)}.hub-message[data-role=event]>div:first-child,.hub-message[data-role=activity]>div:first-child{display:none!important}.hub-composer{flex-shrink:0;width:min(840px,100%);align-self:center;padding:12px 16px;border:1px solid var(--ui-stroke-tertiary);border-radius:20px;background:var(--ui-surface-background)}.hub-composer textarea{display:block;width:100%;min-height:72px;max-height:200px;resize:vertical;border:0;box-shadow:none;background:transparent}.hub-composer-footer{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-top:8px}.hub-send-status{font-size:12px;color:var(--ui-text-secondary);margin-bottom:6px}
.hub-board{height:100%;overflow:auto;padding:28px;display:flex;flex-direction:column;gap:20px;color:var(--ui-text-primary);background:var(--ui-surface-background)}
.hub-heading,.hub-toolbar,.hub-actions{display:flex;align-items:center;gap:10px;flex-wrap:wrap}.hub-heading{justify-content:space-between}.hub-heading h2{font-size:25px;font-weight:650;margin:0}.hub-muted{color:var(--ui-text-tertiary);font-size:12px}.hub-toolbar{padding-block:12px;border-block:1px solid var(--ui-stroke-tertiary)}
.hub-select{font:inherit;font-size:12px;color:var(--ui-text-primary);background:var(--ui-surface-background);border:1px solid var(--ui-stroke-tertiary);border-radius:6px;padding:6px;max-width:200px}.hub-select-label{display:flex;align-items:center;gap:6px;font-size:12px}.hub-columns{display:flex;align-items:flex-start;gap:16px;overflow-x:auto;padding-bottom:20px;flex:1;min-height:240px}.hub-column{flex:0 0 258px;min-width:0}.hub-column>header{display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;font-size:13px;font-weight:600}.hub-column-title{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:220px}.hub-column-items{display:flex;flex-direction:column;gap:10px}.hub-empty{padding:22px 8px;text-align:center;color:var(--ui-text-tertiary);font-size:12px;border:1px dashed var(--ui-stroke-tertiary);border-radius:8px}
.hub-task{--task-tone:var(--ui-text-tertiary);position:relative;display:flex;flex-direction:column;gap:10px;text-align:left;width:100%;padding:15px;border:1px solid color-mix(in srgb,var(--task-tone) 24%,var(--ui-stroke-tertiary));border-radius:10px;background:color-mix(in srgb,var(--task-tone) 6%,var(--ui-surface-background));color:var(--ui-text-primary);overflow:hidden;cursor:pointer;transition:border-color 120ms,background-color 120ms}.hub-task:hover{border-color:var(--task-tone)}.hub-task:focus-visible{outline:2px solid var(--ui-accent);outline-offset:2px}.hub-task[data-state=running]{--task-tone:var(--ui-yellow);background:color-mix(in srgb,var(--ui-yellow) 11%,var(--ui-surface-background))}.hub-task[data-state=attention]{--task-tone:var(--ui-yellow);background:color-mix(in srgb,var(--ui-yellow) 25%,var(--ui-surface-background))}.hub-task[data-state=unread]{--task-tone:var(--ui-green);background:color-mix(in srgb,var(--ui-green) 12%,var(--ui-surface-background))}.hub-task[data-state=interrupted]{--task-tone:var(--ui-orange)}.hub-task[data-state=queued]{--task-tone:var(--ui-accent)}.hub-task-title{font-size:13px;font-weight:600;line-height:1.55;overflow-wrap:anywhere}.hub-status{font-size:11px;display:flex;align-items:center;gap:6px;color:var(--ui-text-secondary)}.hub-dot{display:inline-block;width:6px;height:6px;background:var(--task-tone);border-radius:50%;flex-shrink:0}.hub-task[data-state=running] .hub-dot,.hub-task[data-state=unread] .hub-dot,.hub-task[data-state=attention] .hub-dot{animation:hub-breathe 2.2s ease-in-out infinite}.hub-task[data-state=running]:after{content:'';position:absolute;left:0;bottom:0;height:2px;width:35%;background:var(--ui-yellow);animation:hub-progress 2.4s ease-in-out infinite}.hub-task[data-state=attention]{border-left:3px solid var(--ui-yellow)}.hub-task dl{margin:0;display:grid;grid-template-columns:auto minmax(0,1fr);gap:6px 10px;font-size:11px;color:var(--ui-text-secondary)}.hub-task dd{margin:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;text-align:right}.hub-task dt{color:var(--ui-text-tertiary)}.hub-task-inline{display:inline-flex;vertical-align:middle;max-width:350px;min-width:180px;margin:4px 3px;padding:9px 12px;gap:4px}.hub-list{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px}.hub-fields{display:flex;gap:16px;flex-wrap:wrap;padding:8px}.hub-create{display:flex;flex-direction:column;gap:12px;padding:18px 0;max-width:700px}.hub-detail{padding:24px;overflow:auto;height:100%;display:flex;flex-direction:column;gap:14px}.hub-alert{color:var(--ui-orange);font-size:12px;white-space:pre-wrap}.hub-foot{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;font-size:11px;color:var(--ui-text-tertiary)}
.hub-card-actions{display:flex;align-items:center;justify-content:space-between;gap:4px;margin-top:4px}.hub-card-actions button{font-size:11px}.hub-popover{color:var(--ui-text-primary);font-size:13px;max-width:calc(100vw - 24px);max-height:var(--radix-popover-content-available-height,80vh);overflow:auto}.hub-filter-panel{width:780px}.hub-fields-panel{width:340px}.hub-value-options{width:240px}.hub-panel-body{padding:10px;display:flex;flex-direction:column;gap:14px}.hub-panel-heading{display:flex;justify-content:space-between;align-items:center;gap:8px}.hub-panel-heading strong{font-weight:600}.hub-condition{display:grid;grid-template-columns:22px minmax(110px,1fr) minmax(90px,.8fr) minmax(150px,1.5fr) 30px;align-items:center;gap:8px}.hub-condition>.hub-select-label{font-size:0;min-width:0}.hub-condition .hub-select{width:100%;max-width:none}.hub-condition>input{width:100%;min-width:0}.hub-condition>button:last-child{grid-column:5}.hub-value-picker{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;justify-content:flex-start}.hub-option{display:flex;align-items:center;gap:8px;padding:8px;cursor:pointer}.hub-option input{accent-color:var(--ui-accent)}.hub-field-row{display:flex;align-items:center;gap:6px;min-height:34px}.hub-field-name{flex:1}.hub-drag{cursor:grab;color:var(--ui-text-tertiary);padding:4px}.hub-field-row button[aria-pressed=false]{color:var(--ui-text-tertiary)}.hub-count{border-radius:4px;padding:0 5px;background:var(--ui-control-hover-background)}.hub-toolbar button[data-active=true]{color:var(--ui-accent)}.hub-detail{background:var(--ui-surface-background)}
@keyframes hub-breathe{50%{opacity:.35;transform:scale(.8)}}@keyframes hub-progress{0%{transform:translateX(-100%)}100%{transform:translateX(390%)}}@media(prefers-reduced-motion:reduce){.hub-task .hub-dot,.hub-task:after{animation:none!important}.hub-task{transition:none}}@media(max-width:650px){.hub-board{padding:16px}.hub-column{flex-basis:235px}.hub-condition{grid-template-columns:20px minmax(90px,1fr) minmax(80px,1fr) 28px}.hub-condition>:nth-child(4){grid-column:2/4;grid-row:2}.hub-condition>button:last-child{grid-column:4;grid-row:1}.hub-popover{max-width:calc(100vw - 24px)}}
`
// One stylesheet belongs to the plugin lifetime, not to retained task tabs.
// Constructed sheets cascade after DOM sheets, including styles emitted by
// pre-hot-reload task panes that the user still has open. Those panes can stay
// mounted without repainting the current board with an older accent fill.
export function installBoardStyles(){
 const sheet=new CSSStyleSheet()
 sheet.replaceSync(css+conversationCss)
 document.adoptedStyleSheets=[...document.adoptedStyleSheets,sheet]
 return()=>{document.adoptedStyleSheets=document.adoptedStyleSheets.filter(s=>s!==sheet)}
}
function timeLabel(value){return value?new Date(value*1000).toLocaleString(): '—'}
function ClosureButton({task}){
 const t=usePluginI18n('session-hub'),[busy,setBusy]=useState(false)
 const toggle=async()=>{
  if(closing.has(task.key))return
  closing.add(task.key);setBusy(true)
  try{const result=await rpc('task_closed',{key:task.key,closed:!task.closed});closureVersion++;snapshot={...snapshot,closures:{...snapshot.closures,...result.closures}};publish()}
  catch(e){host.notify({kind:'error',message:String(e)})}
  finally{closing.delete(task.key);setBusy(false)}
 }
 return h(Button,{variant:'ghost',size:'sm',disabled:busy,'aria-label':t(task.closed?'reopenTask':'closeTask'),'aria-pressed':!!task.closed,title:t('closeHint'),onClick:()=>void toggle()},t(task.closed?'closedTask':'openTask'))
}
function NativeButton({task}){
 const t=usePluginI18n('session-hub'),[busy,setBusy]=useState(false)
 if(!['codex','claude'].includes(task.engine)||!task.session_id)return null
 const open=async()=>{setBusy(true);try{await openNativeTask(task);await markRead(task)}catch(e){host.notify({kind:'error',message:String(e)})}finally{setBusy(false)}}
 return h(Button,{variant:'ghost',size:'sm',disabled:busy,onClick:()=>void open()},t(busy?'nativeOpening':'native').replaceAll('Codex',task.engine==='claude'?'Claude':'Codex'))
}
export async function openNativeTask(task){
 const result=await rpc('app_open',{engine:task.engine,session_id:task.session_id})
 if(task.engine==='claude'&&result.requested){host.notify({kind:'info',message:ctx.i18n.t('claudeOpenRequested')});return result}
 if(result.navigated!==true)throw Error(ctx.i18n.t('nativeFailed'))
 // The native adapter selects the task and activates the original App.
 host.notify({kind:'info',message:ctx.i18n.t(result.activated?'nativeOpened':'nativeSelected')})
 return result
}
function fieldValue(task,field,t){const value=task[field];return field==='updated_at'?timeLabel(value):typeof value==='boolean'?t(value?'yes':'no'):field==='engine'?({hermes:'Hermes',codex:'Codex',claude:'Claude'})[value]:field==='transport'&&value?t(value):value??'—'}
function TaskCard({task,fields=[],inline=false,label}){
 const t=usePluginI18n('session-hub')
 const card=h(RowButton,{className:'hub-task'+(inline?' hub-task-inline':''),'data-state':task.state,'data-task-key':task.key,onClick:()=>void openTask(task),'aria-label':`${task.title} · ${t(task.state)}`},
  h('span',{className:'hub-status'},h('span',{className:'hub-dot','aria-hidden':true}),t(task.state),inline&&` · ${task.engine}`,task.closed&&' · '+t('closedTask')),
  h('span',{className:'hub-task-title'},task.title||label),
  fields.length>0&&h('dl',null,...fields.flatMap(field=>[h('dt',{key:field+'l'},t(field)),h('dd',{key:field,title:String(fieldValue(task,field,t)||'—')},fieldValue(task,field,t)||'—')])) )
 return inline?card:h('div',{style:{position:'relative'}},card,h(Button,{variant:'ghost',size:'icon-xs',style:{position:'absolute',right:8,top:8},'aria-label':t('copy'),onClick:()=>void copyTask(task,t)},'↗'),h('div',{className:'hub-card-actions'},h(ClosureButton,{task}),h(NativeButton,{task})))
}
async function copyTask(task,t){try{if(!await ctx.os.writeClipboard(task.reference))throw Error(t('copyFailed'));host.notify({kind:'info',message:t('copied')})}catch(e){host.notify({kind:'error',message:String(e)})}}
async function markRead(task){if(task.engine!=='hermes'&&task.revision){await rpc('task_read',{key:task.key,revision:task.revision});await refreshBoard()}}
function SidebarTaskLabel({initial}){
 const data=useBoard(),t=usePluginI18n('session-hub')
 const task=data.tasks.find(row=>row.key===initial.key||row.job_id&&row.job_id===initial.job_id)||initial
 return h('span',{className:'hub-sidebar-task','data-state':task.state,title:`${task.title} · ${task.engine} · ${t(task.state)}`},
  h('span',{className:'hub-dot','aria-hidden':true}),h('span',{className:'hub-sidebar-title'},task.title),h('small',null,task.engine==='codex'?'Codex':'Claude'))
}
function TaskDetail({initial}){
 const data=useBoard(),t=usePluginI18n('session-hub'),task=data.tasks.find(r=>r.key===initial.key||r.job_id&&r.job_id===initial.job_id)||initial
 const [error,setError]=useState('')
 return h('section',{className:'hub-detail hub-conversation'},h('header',{className:'hub-conversation-heading'},h(Button,{variant:'ghost',size:'sm',onClick:()=>host.navigate('/session-board')},'← '+t('back')),h('h2',null,task.title),h('span',{className:'hub-status'},t(task.state),' · ',task.engine)),
  h('details',{className:'hub-session-meta'},h('summary',null,t('sessionInfo')),h('code',null,task.session_id||task.key),task.summary&&h('p',null,task.summary)),
  h('div',{className:'hub-actions'},h(Button,{variant:'secondary',size:'sm',onClick:()=>void copyTask(task,t)},t('copy')),
   h(NativeButton,{task}),h(ClosureButton,{task}),
   task.state==='unread'&&h(Button,{variant:'ghost',size:'sm',onClick:()=>void markRead(task).catch(e=>setError(String(e)))},t('read'))),
  error&&h('p',{role:'alert',className:'hub-alert'},error),
  task.session_id&&h(Transcript,{target:task,conversation:true,onLoaded:()=>{if(task.state==='unread')void markRead(task).catch(e=>setError(String(e)))}}),
  task.session_id&&['codex','claude'].includes(task.engine)&&h(SessionComposer,{key:task.key,target:task,rpc,storage:ctx.storage}) )
}
async function openTask(task){
 try{
  if(task.engine==='hermes'){
   const parts=task.key.split(':').map(decodeURIComponent),connection=parts[1],profile=parts[2],sid=parts.slice(3).join(':')
   await host.openSession(sid,{profile,...(connection?{route:{connectionId:connection,profile,targetProfile:profile,mode:'remote'}}:{})});return
  }
  host.openWorkspace('session-hub-task:'+task.key,{title:task.title,render:()=>h(TaskDetail,{initial:task}),sidebarSession:{searchText:`${task.engine} ${task.session_id||''}`,render:()=>h(SidebarTaskLabel,{initial:task})}})
 }catch(e){host.notify({kind:'error',message:String(e)})}
}
export function TaskReference({value,children}){
 const data=useBoard(),t=usePluginI18n('session-hub'),[resolved,setResolved]=useState(null),[error,setError]=useState('')
 const task=data.tasks.find(r=>r.key===value||'job:'+r.job_id===value)
 useEffect(()=>{if(task)return;let active=true;setResolved(null);setError('');if(value.startsWith('hermes:')){const parts=value.split(':').map(decodeURIComponent);setResolved({key:value,engine:'hermes',session_id:parts[3],title:parts[3],state:'unknown'});return}rpc('task',{key:value}).then(row=>{if(active)setResolved(row)}).catch(e=>{if(active)setError(String(e))});return()=>{active=false}},[value,task,data.synced_at])
 const row=task||resolved
 return h('span',null,row?h(TaskCard,{task:row,inline:true,label:children}):h('span',{className:'hub-muted',role:error?'status':undefined},children,' · ',error?t('unavailable'):t('loading')))
}
function CreateTask({onClose}){
 const t=usePluginI18n('session-hub'),[engine,setEngine]=useState('codex'),[transport,setTransport]=useState('app'),[title,setTitle]=useState(''),[prompt,setPrompt]=useState(''),[cwd,setCwd]=useState(host.state.cwd.get()||''),[mode,setMode]=useState('read-only'),[busy,setBusy]=useState(false),[error,setError]=useState(''),[request,setRequest]=useState(null)
 const create=async()=>{setBusy(true);setError('');try{const body=request||{engine,transport,title,prompt,cwd,mode,request_key:crypto.randomUUID()};setRequest(body);if(engine==='claude'&&transport==='app'){await rpc('app_prepare_claude',{prompt:(title?title+'\n\n':'')+prompt});host.notify({kind:'info',message:t('claudeDraftReady')});return}const result=await rpc('task_create',body);await refreshBoard();await openTask({key:result.task_key,job_id:result.id,engine,title:title||prompt.slice(0,80),state:'queued',reference:result.reference});onClose()}catch(e){setError(String(e))}finally{setBusy(false)}}
 const edit=fn=>value=>{setRequest(null);fn(value)}
 return h('section',{className:'hub-create','aria-label':t('newTask')},
  h(Control,{label:t('engine'),value:engine,onChange:edit(v=>{setEngine(v);setTransport('app')}),options:[['hermes','Hermes'],['codex','Codex'],['claude','Claude Code']]}),
  engine==='hermes'?h('p',{className:'hub-muted'},t('hermesHint')):h('div',{className:'hub-create'},
   engine==='claude'&&h('p',{className:'hub-muted'},t('claudeHint')),
   ['codex','claude'].includes(engine)&&h(Control,{label:t('transport'),value:transport,onChange:edit(setTransport),options:[['app',t('app')],['cli',t('cli')]]}),
   h(Input,{'aria-label':t('taskTitle'),placeholder:t('taskTitle'),value:title,onChange:e=>edit(setTitle)(e.target.value)}),
   h(Textarea,{'aria-label':t('prompt'),placeholder:t('prompt'),value:prompt,onChange:e=>edit(setPrompt)(e.target.value)}),
   transport==='cli'&&h(Input,{'aria-label':t('cwd'),placeholder:t('cwd'),value:cwd,onChange:e=>edit(setCwd)(e.target.value)}),
   transport==='cli'&&h(Control,{label:t('mode'),value:mode,onChange:edit(setMode),options:[['read-only',t('readOnly')],['workspace-write',t('write')]]})),
  error&&h('p',{role:'alert',className:'hub-alert'},error),h('div',{className:'hub-actions'},
   h(Button,{size:'sm',disabled:busy||(engine!=='hermes'&&(!prompt.trim()||(transport==='cli'&&!cwd.trim()))),onClick:()=>engine==='hermes'?host.newChat():void create()},engine==='hermes'?t('hermesNew'):busy?t('creating'):engine==='claude'&&transport==='app'?t('claudePrepare'):t('create')),
   h(Button,{variant:'ghost',size:'sm',onClick:onClose,disabled:busy},t('cancel'))))
}
export function BoardPage(){
 const data=useBoard(),t=usePluginI18n('session-hub'),[prefs,setPrefs]=useState(()=>normalizePrefs(ctx.storage.get('board.presentation.v1',{}))),[query,setQuery]=useState(''),[creating,setCreating]=useState(false)
 const change=patch=>setPrefs(old=>{const next={...old,...patch};ctx.storage.set('board.presentation.v1',next);return next})
 const set=(key,value)=>change({[key]:value})
 const fields=prefs.fieldOrder.filter(f=>prefs.fields.includes(f))
 const rows=selectTasks(data.tasks,prefs,query),groups=groupTasks(rows,prefs.group)
 return h('main',{className:'hub-board'},
  h('header',{className:'hub-heading'},h('div',null,h('p',{className:'hub-muted'},t('subtitle')),h('h2',null,t('title'))),h('div',{className:'hub-actions'},h(Button,{size:'sm',variant:'secondary',onClick:()=>set('view',prefs.view==='board'?'list':'board')},t(prefs.view==='board'?'list':'board')),h(Button,{size:'sm',onClick:()=>setCreating(v=>!v)},'+ '+t('newTask')))),
  h('div',{className:'hub-toolbar'},h(Input,{'aria-label':t('search'),placeholder:t('search'),value:query,onChange:e=>setQuery(e.target.value),style:{maxWidth:280}}),
   h(Control,{label:t('completion'),value:prefs.completion,onChange:v=>set('completion',v),options:[['open',t('openTask')],['closed',t('closedTask')],['unfinished',t('unfinished')],['finished',t('finished')],['all',t('allTasks')]]}),
   h(FilterControl,{prefs,set}),
   h(Control,{label:t('sort'),value:prefs.sort,onChange:v=>set('sort',v),options:[['attention',t('priority')],['recent',t('recent')],['oldest',t('oldest')],['title',t('taskTitle')]]}),
   h(Control,{label:t('group'),value:prefs.group,onChange:v=>set('group',v),options:['state','engine','cwd','none'].map(s=>[s,t(s)])}),
   h(FieldsControl,{prefs,change}),
   h(Button,{variant:'ghost',size:'sm',onClick:()=>void refreshBoard()},t('refresh'))),
  h('div',{className:'hub-actions'},h(Control,{label:t('scope'),value:prefs.scope,onChange:v=>set('scope',v),options:[['active',t('active')],['all',t('history')]]}),h('small',{className:'hub-muted'},`${rows.length} ${t('count')}`)),
  creating&&h(CreateTask,{onClose:()=>setCreating(false)}),
  data.errors.length>0&&h('div',{role:'alert',className:'hub-alert'},t('stale'),' ',data.errors.join('\n')),
  data.loading&&h('p',{role:'status'},t('loading')),
  !data.loading&&!rows.length&&h('div',{className:'hub-empty'},t('empty'),' ',h(Button,{variant:'ghost',size:'sm',onClick:()=>{setQuery('');change({completion:'all',conditions:[],match:'all',scope:'all'})}},t('clear'))),
  prefs.view==='list'?h('div',{className:'hub-list'},...rows.map(task=>h(TaskCard,{key:task.key,task,fields}))):h('div',{className:'hub-columns'},...groups.map(([key,items])=>h('section',{key,className:'hub-column','aria-label':prefs.group==='state'?t(key):key},h('header',null,h('span',{className:'hub-column-title'},prefs.group==='state'||['all','noProject'].includes(key)?t(key):key),h('span',{className:'hub-muted'},items.length)),h('div',{className:'hub-column-items'},...items.map(task=>h(TaskCard,{key:task.key,task,fields})),!items.length&&h('div',{className:'hub-empty'},t('emptyColumn')))))),
  h('footer',{className:'hub-foot'},h('span',null,t('synced'),' · ',timeLabel(data.synced_at),' · 5s'),h('span',null,t('historyLimit'),` ${data.history_loaded||0} / ${data.history_total||0}`),h('span',null,t('reduced'))))
}
export function setupBoard(context,request,TranscriptComponent){
 ctx=context;rpc=request;Transcript=TranscriptComponent;disposed=false
 const unsubscribers=[ctx.i18n.register(boardLocales),installBoardStyles()]
 // Register translations under the board's own namespace.
 // createPluginI18n is scoped to the owning plugin, so hooks use that same id.
 for(const store of [host.state.sessions,host.state.sessionStatus])if(store)unsubscribers.push(store.subscribe(publish))
 publish()
 return()=>{disposed=true;clearInterval(timer);unsubscribers.forEach(fn=>fn());listeners.clear()}
}
