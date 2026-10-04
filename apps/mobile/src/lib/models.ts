import type { Capability, Draft, Message, Pending } from './protocol'

export function mergeMessages(current: Message[], incoming: Message[]): Message[] {
  const rows = new Map(current.map(row => [row.id, row]))
  for (const row of incoming) {
    if (!rows.has(row.id) || rows.get(row.id)!.revision < row.revision) {
      rows.set(row.id, row.deleted ? { id: row.id, revision: row.revision, ordinal: row.ordinal, deleted: true } : row)
    }
  }
  return [...rows.values()].sort((a, b) => a.ordinal - b.ordinal || a.id.localeCompare(b.id))
}
export function remainingDraft(current: Draft, submitted: Draft): Draft {
  if (current.revision === submitted.revision) return { text: '', attachment_ids: [], revision: current.revision + 1 }
  return { ...current, attachment_ids: current.attachment_ids.filter(id => !submitted.attachment_ids.includes(id)) }
}
export function canAnswer(pending: Pending, capability: Capability | undefined, now: number): boolean {
  const p = pending.params
  return (
    ['approval', 'clarify'].includes(pending.method) &&
    capability?.status === 'supported' &&
    !p.secret &&
    !p.sensitive &&
    !p.expired &&
    !(typeof p.expires_at === 'number' && p.expires_at <= now) &&
    !['sudo', 'secret', 'vault', 'password'].includes(String(p.type || p.kind || '').toLowerCase())
  )
}
export const emptyDraft = (): Draft => ({ text: '', attachment_ids: [], revision: 0 })
export const statusLabel: Record<string, string> = {
  idle: '空闲',
  starting: '启动中',
  waiting: '等待回复',
  working: '处理中',
  streaming: '生成中',
  resuming: '恢复中',
  unknown: '状态未知',
  completed: '已完成',
  failed: '失败',
  interrupted: '已停止'
}
export const receiptLabel: Record<string, string> = {
  accepted: '中继已接收',
  dispatched: '已派送到电脑',
  received: '电脑已接收',
  acknowledged: '执行端已接受 · 完成状态见会话',
  response_submitted: '回答已提交，等待源端确认',
  completed: '操作已完成',
  failed: '操作失败',
  delivery_uncertain: '送达不确定 · 请核对原会话'
}
export const operationLabel: Record<string, string> = {
  send: '继续会话',
  queue: '排队下一轮',
  steer: '引导当前执行',
  interrupt: '请求停止',
  approval: '审批',
  clarify: '回答问题'
}
export function dateLabel(seconds?: number): string {
  return seconds ? new Date(seconds * 1000).toLocaleString('zh-CN', { hour12: false }) : '尚未同步'
}
