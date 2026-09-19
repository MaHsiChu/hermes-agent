import test from 'node:test'
import assert from 'node:assert/strict'
import {conversationGroups} from './plugin/desktop/conversation-model.js'
test('execution groups preserve user/final boundaries and repeated real messages',()=>{
 const rows=[{role:'user',text:'same'},{role:'assistant',phase:'commentary',turn_id:'1'},{role:'activity',turn_id:'1'},{role:'assistant',phase:'final_answer'},{role:'user',text:'same'},{role:'activity',turn_id:'2'},{role:'activity',turn_id:'3'}]
 const groups=conversationGroups(rows)
 assert.deepEqual(groups.map(g=>g.items.length),[1,2,1,1,1,1])
 assert.deepEqual(groups.flatMap(g=>g.items),rows)
})

test('Claude native tool rows collapse but peer requests and final text stay visible',()=>{
 const rows=[{role:'peer',blocks:[{type:'text',text:'continue'}]},
 {role:'assistant',blocks:[{type:'tool_call',name:'Read'}]},
 {role:'user',blocks:[{type:'tool_result'}]},
 {role:'assistant',blocks:[{type:'text',text:'done'}]}]
 assert.deepEqual(conversationGroups(rows).map(g=>[g.activity,g.items.length]),[[false,1],[true,2],[false,1]])
})
