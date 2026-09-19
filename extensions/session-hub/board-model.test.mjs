import assert from 'node:assert/strict'
import {test} from 'node:test'
import {defaultPrefs,normalizePrefs,selectTasks,matchesCondition} from './plugin/desktop/board-model.js'

const rows=[
 {key:'one',title:'Review API',engine:'codex',state:'unread',live:true,updated_at:100,cwd:'E:/Verse'},
 {key:'two',title:'Build UI',engine:'claude',state:'running',managed:true,updated_at:200,cwd:'E:/Hermes'},
 {key:'three',title:'Old task',engine:'codex',state:'completed',updated_at:1},
 {key:'four',title:'Idle conversation',engine:'hermes',state:'idle',live:true,updated_at:3}
]
const condition=(field,operator,value)=>({id:field,field,operator,value})
const select=patch=>selectTasks(rows,{...defaultPrefs,...patch}).map(r=>r.key)

test('quick completion includes unread results but never infers completion from idle',()=>{
 assert.deepEqual(select({completion:'finished'}),['one'])
 assert.deepEqual(select({completion:'finished',scope:'all'}),['one','three'])
 assert.deepEqual(select({completion:'unfinished'}),['two','four'])
})
test('manual open/closed filters do not derive from execution or completion state',()=>{
 const tasks=rows.map(r=>({...r,closed:r.key==='two'}))
 assert.deepEqual(selectTasks(tasks,{...defaultPrefs,completion:'closed'}).map(r=>r.key),['two'])
 assert.deepEqual(selectTasks(tasks,{...defaultPrefs,completion:'open'}).map(r=>r.key),['one','four'])
 assert.deepEqual(selectTasks(tasks,{...defaultPrefs,conditions:[condition('closed','is',['true'])]}).map(r=>r.key),['two'])
})
test('AND/OR, multi-select and global quick/scope filters compose',()=>{
 const conditions=[condition('engine','is',['codex','claude']),condition('title','contains','api')]
 assert.deepEqual(select({conditions}),['one'])
 assert.deepEqual(select({conditions,match:'any'}),['two','one'])
 assert.deepEqual(select({conditions,match:'any',completion:'unfinished'}),['two'])
})
test('unfinished conditions are ignored in OR as well as AND',()=>{
 const conditions=[condition('engine','is',[]),condition('title','contains','API')]
 assert.deepEqual(select({conditions,match:'any'}),['one'])
 assert.deepEqual(select({conditions:[condition('engine','is',[])]}),['two','one','four'])
})
test('text exclusion, empty values, booleans, and mixed-case search',()=>{
 assert.deepEqual(select({conditions:[condition('cwd','notContains','verse')]}),['two','four'])
 assert.deepEqual(select({conditions:[condition('cwd','empty','')]}),['four'])
 assert.equal(matchesCondition({managed:false},condition('managed','is',['false'])),true)
 assert.equal(matchesCondition({managed:false},condition('managed','empty','')),false)
 assert.deepEqual(selectTasks(rows,{...defaultPrefs},'reVIEW').map(r=>r.key),['one'])
})
test('calendar date comparisons use local midnight boundaries, inclusive whole day',()=>{
 const start=new Date(2026,8,18),next=new Date(2026,8,19)
 const c=condition('updated_at','on','2026-09-18')
 assert.equal(matchesCondition({updated_at:+start/1000},c),true)
 assert.equal(matchesCondition({updated_at:+next/1000-1},c),true)
 assert.equal(matchesCondition({updated_at:+next/1000},c),false)
 assert.equal(matchesCondition({updated_at:+next/1000},{...c,operator:'after'}),true)
 assert.equal(matchesCondition({updated_at:+start/1000-1},{...c,operator:'before'}),true)
 assert.equal(matchesCondition({},c),false)
 assert.equal(matchesCondition({updated_at:+start/1000},{...c,value:'invalid'}),false)
})
test('old engine/status and display preferences migrate without losing visibility or order',()=>{
 const saved={engine:'codex',status:'unread',fields:['summary','cwd','obsolete']}
 const prefs=normalizePrefs(saved)
 assert.deepEqual(prefs.fields,['summary','cwd'])
 assert.deepEqual(prefs.fieldOrder.slice(0,2),['summary','cwd'])
 assert.deepEqual(selectTasks(rows,prefs).map(r=>r.key),['one'])
 assert.deepEqual(normalizePrefs(prefs),prefs)
 assert.deepEqual(saved.fields,['summary','cwd','obsolete'])
})
