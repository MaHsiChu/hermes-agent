import {createElement as h,useEffect,useRef,useState} from 'react'
import {Button,Textarea,usePluginI18n} from '@hermes/plugin-sdk'
import {ImagePreview} from './image-preview.js'

// A retained task tab owns its draft. A failed HTTP response retains the exact
// request key across remounts; checking it again cannot deliver a second turn.
export function SessionComposer({target,rpc,storage}){
 const translate=usePluginI18n('session-hub'),t=key=>translate(key).replaceAll('Codex',target.engine==='claude'?'Claude':'Codex'),identity=`${target.engine}:${target.host_id||'local'}:${target.session_id}`
 const key='session-composer:'+identity
 const [saved,setSaved]=useState(()=>storage.get(key,{draft:'',attempt:null,job:null}))
 const [busy,setBusy]=useState(false),[error,setError]=useState(''),[job,setJob]=useState(null)
 const current=useRef(saved),sending=useRef(false),mounted=useRef(true),fileInput=useRef(null),uploading=useRef(false)
 const [uploadBusy,setUploadBusy]=useState(false),[dragging,setDragging]=useState(false)
 const scope={engine:target.engine,session_id:target.session_id,host_id:target.host_id||'local'}
 const save=next=>{storage.set(key,next);current.current=next;setSaved(next)}
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false}},[])
 useEffect(()=>{let active=true,timer
  const poll=async()=>{try{const result=await rpc('app_jobs',{});if(!active)return;const row=result.jobs.find(j=>j.id===saved.job);setJob(row||null)}catch(e){if(active)setError(String(e))}finally{if(active)timer=setTimeout(poll,3000)}}
  if(saved.job)void poll()
  return()=>{active=false;clearTimeout(timer)}
 },[saved.job])
 const addImages=async files=>{
  if(sending.current||uploading.current||current.current.attempt)return
  const list=Array.from(files);if(!list.length)return
  if((current.current.images||[]).length+list.length>5){setError(t('imageLimit'));return}
  uploading.current=true;setUploadBusy(true);setError('')
  try{for(const file of list){
   if(!['image/png','image/jpeg','image/webp'].includes(file.type)||file.size>8*1024*1024)throw Error(t('imageTypes'))
   const data_url=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=()=>reject(Error(t('imageReadFailed')));reader.readAsDataURL(file)})
   const image=await rpc('app_upload_image',{...scope,name:file.name,data_url})
   const next={...current.current,images:[...(current.current.images||[]),image]}
   storage.set(key,next);current.current=next;if(mounted.current)setSaved(next)
  }}catch(e){if(mounted.current)setError(String(e))}
  finally{uploading.current=false;if(mounted.current)setUploadBusy(false)}
 }
 const send=async()=>{
  if(sending.current||uploading.current||!target.session_id||(!current.current.draft.trim()&&!current.current.images?.length&&!current.current.attempt))return
  sending.current=true;setBusy(true);setError('')
  try{
   const attempt=current.current.attempt||{request_key:crypto.randomUUID(),prompt:current.current.draft,attachments:(current.current.images||[]).map(i=>i.id)}
   // Persist before submitting, including before a possible navigation/reload.
   save({...current.current,attempt})
   const result=await rpc('app_dispatch',{engine:target.engine,session_id:target.session_id,host_id:target.host_id||'local',...attempt})
   if(!result.id)throw Error(t('deliveryUnknown'))
   const next={draft:'',images:[],attempt:null,job:result.id};storage.set(key,next);current.current=next
   if(mounted.current){setSaved(next);setJob(result)}
  }catch(e){
   // A definite validation failure occurred before enqueueing. Transport
   // failures keep the same key and immutable payload for a safe lookup/retry.
   if(/\b400\b/.test(String(e))&&/App message must|stable request_key|Sending into the control task itself|Claude peer is not live|Claude peer name is ambiguous|图片附件不存在|图片附件已变化|图片附件目前仅支持|每条消息最多/.test(String(e))){const next={...current.current,attempt:null};storage.set(key,next);current.current=next;if(mounted.current)setSaved(next)}
   if(mounted.current)setError(String(e))
  }finally{sending.current=false;if(mounted.current)setBusy(false)}
 }
 const unresolved=!!saved.attempt
 return h('section',{className:'hub-composer'+(dragging?' hub-dragging':''),'aria-label':t('continueOriginal'),onDragOver:e=>{if(e.dataTransfer.types.includes('Files')){e.preventDefault();setDragging(true)}},onDragLeave:e=>{if(!e.currentTarget.contains(e.relatedTarget))setDragging(false)},onDrop:e=>{e.preventDefault();setDragging(false);void addImages(e.dataTransfer.files)},onPaste:e=>{const files=Array.from(e.clipboardData.items||[]).filter(i=>i.kind==='file').map(i=>i.getAsFile()).filter(Boolean);if(files.length){e.preventDefault();void addImages(files)}}},
  error&&h('p',{role:'alert',className:'hub-alert'},error),
  unresolved&&!busy&&h('p',{className:'hub-muted'},t('deliveryUnknown')),
  job&&h('div',{role:'status',className:'hub-send-status','data-delivery-state':job.state},t('delivery_'+job.state),['needs_attention','delivery_uncertain'].includes(job.state)&&' · '+t('nativeAction'),['needs_attention','delivery_uncertain'].includes(job.state)&&job.detail&&h('p',null,job.detail)),
  target.engine==='claude'&&h('small',{className:'hub-muted'},t('claudeContinueHint')),
  h('input',{ref:fileInput,type:'file',accept:'image/png,image/jpeg,image/webp',multiple:true,hidden:true,'aria-label':t('insertImages'),onChange:e=>{void addImages(e.target.files);e.target.value=''}}),
  (saved.images||[]).length>0&&h('div',{className:'hub-attachment-strip'},...saved.images.map(image=>h('div',{key:image.id,className:'hub-attachment'},
   h(ImagePreview,{src:image.thumbnail,name:image.name,load:async()=>(await rpc('app_attachment',{...scope,attachment_id:image.id})).data_url}),
   h('button',{type:'button',className:'hub-remove-image','aria-label':t('removeImage')+': '+image.name,disabled:busy||unresolved||uploadBusy,onClick:()=>save({...current.current,images:current.current.images.filter(i=>i.id!==image.id)})},'×')))),
  uploadBusy&&h('p',{role:'status'},t('uploadingImages')),
  h(Textarea,{'aria-label':t('continueOriginal'),placeholder:t('continuePlaceholder'),value:saved.draft,readOnly:busy||unresolved,maxLength:20000,onChange:e=>save({...current.current,draft:e.target.value}),onKeyDown:e=>{if((e.ctrlKey||e.metaKey)&&e.key==='Enter'&&!e.nativeEvent.isComposing){e.preventDefault();void send()}}}),
  h('div',{className:'hub-composer-footer'},h(Button,{size:'sm',variant:'ghost','aria-label':t('insertImages'),title:t('imageTypes'),disabled:busy||unresolved||uploadBusy,onClick:()=>fileInput.current.click()},'+'),h('small',{className:'hub-muted'},t('originalExecution')),h(Button,{size:'sm',disabled:busy||uploadBusy||(!saved.draft.trim()&&!saved.images?.length),onClick:()=>void send()},busy?t('sendingOriginal'):unresolved?t('checkDelivery'):t('sendOriginal'))))
}
