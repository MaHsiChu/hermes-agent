export const states = ['attention','running','queued','unread','completed','idle','interrupted','unknown']
export const fieldDefinitions = [
 {id:'title',type:'text'}, {id:'state',type:'enum',values:states},
 {id:'engine',type:'enum',values:['hermes','codex','claude']},
 {id:'cwd',type:'text'}, {id:'updated_at',type:'date'},
 {id:'session_id',type:'text'}, {id:'summary',type:'text'},
 {id:'transport',type:'enum',values:['app','cli']},
 {id:'managed',type:'boolean'}, {id:'live',type:'boolean'},
 {id:'closed',type:'boolean'}
]
export const cardFields = fieldDefinitions.filter(f=>!['title','state'].includes(f.id)).map(f=>f.id)
export const defaultPrefs = {view:'board',engine:'all',status:'all',scope:'active',completion:'all',sort:'attention',group:'state',fields:['engine','cwd','updated_at','summary'],fieldOrder:cardFields,conditions:[],match:'all'}
export function normalizePrefs(saved={}){
 const prefs={...defaultPrefs,...saved}
 prefs.fields=Array.isArray(saved.fields)?saved.fields.filter(f=>cardFields.includes(f)):[...defaultPrefs.fields]
 prefs.fieldOrder=[...new Set([...(Array.isArray(saved.fieldOrder)?saved.fieldOrder:prefs.fields),...cardFields])].filter(f=>cardFields.includes(f))
 prefs.conditions=Array.isArray(saved.conditions)?saved.conditions.filter(c=>fieldDefinitions.some(f=>f.id===c.field)):[]
 for(const [key,field] of [['engine','engine'],['status','state']])if(prefs[key]&&prefs[key]!=='all')prefs.conditions.push({id:'legacy-'+key,field,operator:'is',value:[prefs[key]]})
 prefs.engine='all';prefs.status='all'
 return prefs
}
export function operatorsFor(field){
 const type=fieldDefinitions.find(f=>f.id===field)?.type
 return type==='date'?['on','before','after','empty','notEmpty']:type==='text'?['contains','notContains','is','isNot','empty','notEmpty']:['is','isNot','empty','notEmpty']
}
export function activeCondition(c){return operatorsFor(c.field).includes(c.operator)&&(['empty','notEmpty'].includes(c.operator)||(Array.isArray(c.value)?c.value.length>0:String(c.value??'').trim()!==''))}
export function matchesCondition(row,c){
 const definition=fieldDefinitions.find(f=>f.id===c.field),raw=row[c.field]
 const empty=raw===undefined||raw===null||raw===''
 if(c.operator==='empty')return empty
 if(c.operator==='notEmpty')return !empty
 if(definition?.type==='date'){
  if(empty||!Number.isFinite(Number(raw)))return false
  // Date inputs are calendar days in the user's timezone, not UTC days.
  const start=new Date(c.value+'T00:00:00'),end=new Date(start)
  end.setDate(end.getDate()+1)
  const time=Number(raw)*1000
  return c.operator==='before'?time<+start:c.operator==='after'?time>=+end:time>=+start&&time<+end
 }
 const value=String(raw??'').toLocaleLowerCase()
 const expected=(Array.isArray(c.value)?c.value:[c.value]).map(v=>String(v).toLocaleLowerCase())
 const match=c.operator==='contains'||c.operator==='notContains'?value.includes(expected[0]):expected.includes(value)
 return c.operator==='isNot'||c.operator==='notContains'?!match:match
}
export function taskHref(key){return '#task/session-hub/'+encodeURIComponent(key)}
export function hermesTask(row,status){
 const key=['hermes',row.connection_id||'',row.profile||'default',row._lineage_root_id||row.id].map(encodeURIComponent).join(':')
 const state=({'needs-input':'attention',working:'running',background:'running',stalled:'running',unread:'unread',draft:'queued'})[status]||(row.ended_at?'completed':'idle')
 return {...row,key,engine:'hermes',session_id:row._lineage_root_id||row.id,title:row.title||row.preview||row.id,state,updated_at:row.last_active,cwd:row.cwd||'',summary:row.preview||'',live:true,reference:`[${(row.title||row.id).replace(/[\[\]\\]/g,'\\$&')}](${taskHref(key)})`}
}
export function selectTasks(rows,prefs,query=''){
 const needle=query.trim().toLowerCase()
 const conditions=(prefs.conditions||[]).filter(activeCondition)
 const result=rows.filter(r=>{
  const complete=['unread','completed'].includes(r.state)
  return (!prefs.engine||prefs.engine==='all'||r.engine===prefs.engine)&&(!prefs.status||prefs.status==='all'||r.state===prefs.status)
   &&(prefs.scope==='all'||r.live||r.managed||['running','attention'].includes(r.state))
   &&(prefs.completion==='unfinished'?!complete:prefs.completion==='finished'?complete:prefs.completion==='open'?!r.closed:prefs.completion==='closed'?!!r.closed:true)
   &&(!conditions.length||(prefs.match==='any'?conditions.some(c=>matchesCondition(r,c)):conditions.every(c=>matchesCondition(r,c))))
   &&(!needle||[r.title,r.cwd,r.session_id,r.summary].join(' ').toLowerCase().includes(needle))
 })
 const rank=r=>states.indexOf(r.state)<0?99:states.indexOf(r.state)
 return result.sort((a,b)=>(prefs.sort==='title'?a.title.localeCompare(b.title):prefs.sort==='oldest'?(a.updated_at||0)-(b.updated_at||0):prefs.sort==='attention'?rank(a)-rank(b):0)||((b.updated_at||0)-(a.updated_at||0))||a.key.localeCompare(b.key))
}
export function groupTasks(rows,by){
 const groups=new Map(by==='state'?states.map(s=>[s,[]]):[])
 for(const row of rows){const key=by==='none'?'all':by==='cwd'?(row.cwd||'noProject'):row[by];if(!groups.has(key))groups.set(key,[]);groups.get(key).push(row)}
 return [...groups]
}
