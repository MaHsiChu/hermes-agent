import {createElement as h,useRef,useState} from 'react'
import {usePluginI18n} from '@hermes/plugin-sdk'

export function ImagePreview({src,name,load}){
 const t=usePluginI18n('session-hub'),dialog=useRef(null)
 const [full,setFull]=useState(''),[error,setError]=useState(''),[busy,setBusy]=useState(false)
 const open=async()=>{
  dialog.current.showModal();setError('')
  if(load&&!full){setBusy(true);try{setFull(await load())}catch(e){setError(String(e))}finally{setBusy(false)}}
 }
 return h('div',{className:'hub-image'},
  h('button',{type:'button',className:'hub-image-button',onClick:()=>void open(),'aria-label':t('previewImage')+': '+name},h('img',{src,alt:name,loading:'lazy'})),
  h('dialog',{ref:dialog,className:'hub-image-dialog','aria-label':name,onClick:e=>{if(e.target===e.currentTarget)e.currentTarget.close()}},
   h('header',null,h('span',null,name),h('button',{type:'button',onClick:()=>dialog.current.close(),'aria-label':t('closePreview')},'×')),
   busy&&h('p',{role:'status'},t('loading')),
   error&&h('p',{role:'alert'},error),
   h('img',{src:full||src,alt:name})))
}
