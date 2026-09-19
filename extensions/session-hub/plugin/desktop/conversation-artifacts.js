import {createElement as h,useRef,useState} from 'react'
import {Streamdown,usePluginI18n} from '@hermes/plugin-sdk'

export function isLocalLink(href){
 if(typeof href!=='string'||!href||href.startsWith('#')||/^[\\/]{2}/.test(href))return false
 return /^\/?[a-z]:[/\\]/i.test(href)||/^file:\/\/\//i.test(href)||(!/^[a-z][\w+.-]*:/i.test(href)&&/\.[a-z0-9]+(?:[:#].*)?$/i.test(href))
}
export function safeLink(href){return /^https?:\/\//i.test(href)||isLocalLink(href)?href:''}

export function DocumentLink({href,children,target,itemId,rpc}){
 const t=usePluginI18n('session-hub'),dialog=useRef(null)
 const [document,setDocument]=useState(null),[error,setError]=useState('')
 const open=async()=>{dialog.current.showModal();setError('');setDocument(null);try{setDocument(await rpc('transcript_document',{engine:target.engine,session_id:target.session_id,item_id:itemId,href}))}catch(e){setError(String(e))}}
 return h('span',{className:'hub-document-link'},
  h('button',{type:'button',role:'link',title:href,onClick:()=>void open()},h('span',{'aria-hidden':true},'▤ '),children),
  h('dialog',{ref:dialog,className:'hub-document-dialog','aria-label':t('documentPreview'),onClick:e=>{if(e.target===e.currentTarget)e.currentTarget.close()}},
   h('header',null,h('strong',null,document?.name||t('documentPreview')),h('button',{onClick:()=>dialog.current.close(),'aria-label':t('closePreview')},'×')),
   error?h('p',{role:'alert'},error):!document?h('p',{role:'status'},t('loading')):h('div',null,
    h('p',{className:'hub-document-path'},document.path,document.line?':'+document.line:''),
    h('div',{className:'hub-document-content'},document.markdown?h(Streamdown,{mode:'static',skipHtml:true,components:{img:({alt})=>h('span',null,alt),a:({href,children})=>/^https?:\/\//i.test(href||'')?h('a',{href,target:'_blank',rel:'noreferrer noopener'},children):h('span',null,children)}},document.text):h('pre',null,document.text)))))
}

export function ChangedFiles({summary,cwd}){
 const t=usePluginI18n('session-hub'),[expanded,setExpanded]=useState(false)
 if(!summary?.files?.length)return null
 const root=String(cwd||'').replace(/^\\\\\?\\/,'').replaceAll('\\','/').replace(/\/$/,'')+'/'
 const short=path=>{const normalized=path.replaceAll('\\','/');return normalized.toLowerCase().startsWith(root.toLowerCase())?normalized.slice(root.length):normalized}
 return h('section',{className:'hub-changed-files','aria-label':t('changedFiles')},
  h('header',null,h('strong',null,t('editedFiles').replace('{count}',summary.files.length)),h('span',{className:'hub-diff-counts'},h('span',{'data-change':'add'},'+'+summary.added),' ',h('span',{'data-change':'remove'},'-'+summary.removed))),
  ...(expanded?summary.files:summary.files.slice(0,3)).map(file=>h('details',{key:file.path,className:'hub-changed-file'},
   h('summary',null,h('span',{title:file.path},short(file.path)),h('span',{className:'hub-diff-counts'},h('span',{'data-change':'add'},'+'+file.added),' ',h('span',{'data-change':'remove'},'-'+file.removed))),
   ...file.patches.map((patch,i)=>h('pre',{key:patch.item_id+':'+i,className:'hub-diff'},...patch.diff.split('\n').map((line,n)=>h('span',{key:n,'data-change':line.startsWith('+')?'add':line.startsWith('-')?'remove':'context'},line+'\n')))))),
  summary.files.length>3&&h('button',{className:'hub-show-files',onClick:()=>setExpanded(!expanded)},expanded?t('collapseFiles'):t('moreFiles').replace('{count}',summary.files.length-3)))
}
