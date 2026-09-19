import {createElement as h,useState} from 'react'
import {Button,Input,Popover,PopoverContent,PopoverTrigger,Codicon,usePluginI18n} from '@hermes/plugin-sdk'
import {activeCondition,cardFields,defaultPrefs,fieldDefinitions,operatorsFor} from './board-model.js'

const icon=name=>h(Codicon,{name,'aria-hidden':true})
export function Control({label,value,onChange,options}){
 return h('label',{className:'hub-select-label'},label,h('select',{className:'hub-select','aria-label':label,value,onChange:e=>onChange(e.target.value)},...options.map(([value,label])=>h('option',{key:value,value},label))))
}
function Panel({label,children,className='',active=false}){
 return h(Popover,null,h(PopoverTrigger,{asChild:true},h(Button,{variant:'ghost',size:'sm','data-active':active},label)),
  h(PopoverContent,{align:'start',className:'hub-popover '+className},children))
}
function ValuePicker({definition,value,onChange,label}){
 const t=usePluginI18n('session-hub'),selected=Array.isArray(value)?value:[]
 const values=definition.type==='boolean'?['true','false']:definition.values
 const display=v=>definition.type==='boolean'?t(v==='true'?'yes':'no'):definition.id==='engine'?({hermes:'Hermes',codex:'Codex',claude:'Claude'})[v]:t(v)
 return h(Popover,null,h(PopoverTrigger,{asChild:true},h(Button,{variant:'secondary',size:'sm','aria-label':label,className:'hub-value-picker'},selected.length?selected.map(display).join('、'):t('chooseValue'))),
  h(PopoverContent,{align:'start',className:'hub-popover hub-value-options'},...values.map(v=>h('label',{key:v,className:'hub-option'},h('input',{type:'checkbox',checked:selected.includes(v),onChange:e=>onChange(e.target.checked?[...selected,v]:selected.filter(x=>x!==v))}),display(v)))))
}
export function FilterControl({prefs,set}){
 const t=usePluginI18n('session-hub'),conditions=prefs.conditions,count=conditions.filter(activeCondition).length
 const update=(id,patch)=>set('conditions',conditions.map(c=>c.id===id?{...c,...patch}:c))
 return h(Panel,{label:h('span',{className:'hub-actions'},icon('filter'),t('filter'),count>0&&h('span',{className:'hub-count'},count)),className:'hub-filter-panel',active:count>0},
  h('div',{className:'hub-panel-body'},h('header',{className:'hub-panel-heading'},h('strong',null,t('filter')),h(Button,{variant:'ghost',size:'sm',disabled:!conditions.length,onClick:()=>set('conditions',[])},t('clearConditions'))),
   h(Control,{label:t('matchLabel'),value:prefs.match,onChange:v=>set('match',v),options:[['all',t('matchAll')],['any',t('matchAny')]]}),
   !conditions.length&&h('p',{className:'hub-muted'},t('filterHint')),
   ...conditions.map((c,index)=>{
    const definition=fieldDefinitions.find(f=>f.id===c.field)
    return h('div',{key:c.id,className:'hub-condition','data-condition':c.id},
     h('span',{className:'hub-muted'},index===0?t('when'):t(prefs.match==='any'?'or':'and')),
     h(Control,{label:t('filterField'),value:c.field,onChange:field=>update(c.id,{field,operator:operatorsFor(field)[0],value:''}),options:fieldDefinitions.map(f=>[f.id,t(f.id==='title'?'titleField':f.id)])}),
     h(Control,{label:t('operator'),value:c.operator,onChange:operator=>update(c.id,{operator}),options:operatorsFor(c.field).map(op=>[op,t(op==='empty'?'emptyValue':op)])}),
     !['empty','notEmpty'].includes(c.operator)&&(definition.values||definition.type==='boolean'?h(ValuePicker,{definition,label:t('filterValue'),value:c.value,onChange:value=>update(c.id,{value})}):h(Input,{type:definition.type==='date'?'date':'text','aria-label':t('filterValue'),placeholder:t('enterValue'),value:c.value,onChange:e=>update(c.id,{value:e.target.value})})),
     h(Button,{variant:'ghost',size:'icon-sm','aria-label':t('removeCondition'),onClick:()=>set('conditions',conditions.filter(row=>row.id!==c.id))},icon('close')))
   }),
   h(Button,{variant:'secondary',size:'sm',style:{alignSelf:'flex-start'},onClick:()=>set('conditions',[...conditions,{id:crypto.randomUUID(),field:'engine',operator:'is',value:[]}])},icon('add'),t('addCondition'))))
}
export function FieldsControl({prefs,change}){
 const t=usePluginI18n('session-hub'),[dragged,setDragged]=useState(null)
 const move=(field,target)=>{
  const order=prefs.fieldOrder.filter(f=>f!==field),index=order.indexOf(target)
  if(field!==target&&index>=0){order.splice(index,0,field);change({fieldOrder:order})}
 }
 const step=(field,offset)=>{
  const order=[...prefs.fieldOrder],index=order.indexOf(field),next=index+offset
  if(next>=0&&next<order.length){[order[index],order[next]]=[order[next],order[index]];change({fieldOrder:order})}
 }
 return h(Panel,{label:h('span',{className:'hub-actions'},icon('settings'),t('fields')),className:'hub-fields-panel'},
  h('div',{className:'hub-panel-body'},h('header',{className:'hub-panel-heading'},h('strong',null,t('fields')),h(Button,{variant:'ghost',size:'sm',onClick:()=>change({fields:[...defaultPrefs.fields],fieldOrder:[...cardFields]})},t('restoreFields'))),
   h('p',{className:'hub-muted'},t('fieldsHint')),
   ...prefs.fieldOrder.map((field,index)=>h('div',{key:field,className:'hub-field-row','data-field':field,onDragOver:e=>{e.preventDefault();e.dataTransfer.dropEffect='move'},onDrop:e=>{e.preventDefault();if(dragged)move(dragged,field);setDragged(null)}},
    h('span',{className:'hub-drag',draggable:true,title:t('dragField'),onDragStart:e=>{setDragged(field);e.dataTransfer.effectAllowed='move';e.dataTransfer.setData('text/plain',field)},onDragEnd:()=>setDragged(null)},icon('gripper')),
    h('span',{className:'hub-field-name'},t(field)),
    h(Button,{variant:'ghost',size:'icon-xs',disabled:index===0,'aria-label':t('moveUp')+' '+t(field),onClick:()=>step(field,-1)},icon('chevron-up')),
    h(Button,{variant:'ghost',size:'icon-xs',disabled:index===prefs.fieldOrder.length-1,'aria-label':t('moveDown')+' '+t(field),onClick:()=>step(field,1)},icon('chevron-down')),
    h(Button,{variant:'ghost',size:'icon-sm','aria-label':t('visibility')+' '+t(field),'aria-pressed':prefs.fields.includes(field),onClick:()=>change({fields:prefs.fields.includes(field)?prefs.fields.filter(f=>f!==field):[...prefs.fields,field]})},icon(prefs.fields.includes(field)?'eye':'eye-closed'))))))
}
