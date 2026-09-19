import fs from 'node:fs'
import vm from 'node:vm'
import {build} from '../../node_modules/esbuild/lib/main.js'
import {fileURLToPath} from 'node:url'
const path=new URL('./plugin/desktop/plugin.js',import.meta.url)
let source=fs.readFileSync(path,'utf8')
source=source.replace(/^import .*$/gm,'').replace('export default','globalThis.testPlugin =')
new vm.Script(source,{filename:'plugin-no-imports.js'})
console.log('Plugin body parses successfully')
const moduleUrl='data:text/javascript,'+encodeURIComponent('export const createElement=()=>null,useState=()=>[null,()=>{}],useEffect=()=>{},useLayoutEffect=()=>{},useRef=()=>({current:null}),useSyncExternalStore=()=>null;export const host={},Button=()=>null,Input=()=>null,Textarea=()=>null,RowButton=()=>null,Popover=()=>null,PopoverContent=()=>null,PopoverTrigger=()=>null,Codicon=()=>null,usePluginI18n=()=>()=>"",Streamdown=()=>null,ROUTES_AREA="routes",SIDEBAR_NAV_AREA="sidebar.nav",STATUSBAR_AREAS={right:"statusBar.right"};')
const bundled=await build({entryPoints:[fileURLToPath(path)],bundle:true,write:false,format:'esm',external:['react','@hermes/plugin-sdk']})
let esm=bundled.outputFiles[0].text.replace(/(from\s*|import\s*\(\s*|import\s+)(['"])([^'"]+)\2/g,(whole,pre,quote,spec)=>['react','@hermes/plugin-sdk'].includes(spec)?`${pre}${quote}${moduleUrl}${quote}`:whole)
await import('data:text/javascript,'+encodeURIComponent(esm))
console.log('Rewritten ESM imports parse successfully')
