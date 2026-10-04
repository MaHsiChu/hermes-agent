export interface Source {
  backend_id: string
  profile: string
  engine: 'hermes' | 'codex' | 'claude'
}
export interface User {
  id: string
  name: string
}
export interface Identity {
  user: User | null
  csrf_token: string | null
  login_url: string | null
}
export interface Device {
  id: string
  name: string
  online: boolean
  last_seen: number
  backends: Source[]
}
export interface Session extends Source {
  id: string
  device_id: string
  native_session_id: string
  title: string
  archived: boolean
  updated_at: number
  revision: number
  status?: string
  source?: unknown
  cwd?: string
  online?: boolean
}
export interface Capability {
  status: 'supported' | 'unavailable' | 'unsupported'
  reason?: string
}
export type Operation = 'send' | 'queue' | 'steer' | 'interrupt' | 'approval' | 'clarify'
export type Capabilities = Partial<Record<Operation | 'history' | 'attachments', Capability>>
export interface Sync {
  complete?: boolean
  last_synced?: number
  offset?: number
  total?: number
  error?: string
  catalog_complete?: boolean
  epoch?: string
}
export interface Message {
  id: string
  revision: number
  ordinal: number
  role?: string
  content?: string | unknown[]
  blocks?: unknown[]
  tool_calls?: unknown[]
  tool_call_id?: string
  timestamp?: number
  deleted?: boolean
  [key: string]: unknown
}
export interface Question {
  qid: string
  question: string
  choices?: unknown[]
  multi_select?: boolean
}
export interface Pending {
  id: string
  method: string
  params: {
    request_id?: string
    command?: string
    description?: string
    choices?: unknown[]
    question?: string
    questions?: Question[]
    multi_select?: boolean
    answers?: Record<string, string>
    expires_at?: number
    expired?: boolean
    secret?: boolean
    sensitive?: boolean
    [key: string]: unknown
  }
}
export interface Detail {
  session: Session
  online: boolean
  capabilities: Capabilities
  sync: Sync
  pending_requests: Pending[]
}
export interface Page<T> {
  next_cursor: string | null
  [key: string]: T[] | string | null | Sync
}
export interface MessagePage {
  messages: Message[]
  next_cursor: string | null
  sync: Sync
}
export interface SessionPage {
  sessions: Session[]
  next_cursor: string | null
}
export interface Receipt {
  request_id: string
  state:
    | 'accepted'
    | 'dispatched'
    | 'received'
    | 'acknowledged'
    | 'response_submitted'
    | 'completed'
    | 'failed'
    | 'delivery_uncertain'
  result?: unknown
  error?: string
}
export interface Command {
  request_id: string
  operation: Operation
  payload: Record<string, unknown>
}
export interface Draft {
  text: string
  attachment_ids: string[]
  revision: number
}
export interface PendingCommand {
  session_id: string
  command: Command
  submitted?: Draft
  receipt?: Receipt
  uncertain?: boolean
  error?: string
  draftSettled?: boolean
}
export interface Pairing {
  pairing_id: string
  name: string
  sources: Source[]
  expires_at: number
}
