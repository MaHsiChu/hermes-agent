import {build} from '../../node_modules/esbuild/lib/main.js'
import {fileURLToPath} from 'node:url'
import path from 'node:path'
const root=path.dirname(fileURLToPath(import.meta.url))
await build({entryPoints:[path.join(root,'plugin/desktop/plugin.js')],outfile:path.join(root,'build/plugin.js'),bundle:true,format:'esm',external:['react','@hermes/plugin-sdk'],logLevel:'info'})
