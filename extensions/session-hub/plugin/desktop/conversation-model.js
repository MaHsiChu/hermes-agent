// Keep turn boundaries and final answers intact. Only adjacent execution and
// progress records collapse together; identical messages are never deduplicated.
export function conversationGroups(items){
 const groups=[]
 for(const item of items){
  const toolOnly=['assistant','user'].includes(item.role)&&item.blocks?.length>0&&item.blocks.every(b=>['tool_call','tool_result','notice'].includes(b.type))
  const activity=toolOnly||item.role==='activity'||item.role==='assistant'&&item.phase==='commentary'
  const last=groups.at(-1)
  if(activity&&last?.activity&&(!last.items.at(-1).turn_id||!item.turn_id||last.items.at(-1).turn_id===item.turn_id))last.items.push(item)
  else groups.push({activity,items:[item]})
 }
 return groups
}
