import { atom } from 'nanostores'
import { Api, identity } from '../lib/api'
import { EventLink } from '../lib/events'
import type { Device, Identity, Session, SessionPage, User } from '../lib/protocol'
import { AccountStorage, clearAccountStorage } from '../lib/storage'
import { Outbox } from './outbox'
import { SessionModel } from './session'

export interface Filters {
  engine: string
  profile: string
  status: string
  q: string
  device_id: string
  archived: string
}
export const defaultFilters: Filters = {
  engine: '',
  profile: '',
  status: '',
  q: '',
  device_id: '',
  archived: 'exclude'
}
export interface Catalog {
  sessions: Session[]
  next: string | null
  devices: Device[]
  filters: Filters
  loading: boolean
  error: string
}
export class Runtime {
  api: Api
  storage: AccountStorage
  outbox: Outbox
  catalog = atom<Catalog>({ sessions: [], next: null, devices: [], filters: defaultFilters, loading: false, error: '' })
  selected = atom<SessionModel | null>(null)
  connection = atom('正在连接')
  private events?: EventLink
  private listVersion = 0
  private closed = false
  constructor(
    public user: User,
    csrf: string
  ) {
    this.api = new Api(csrf)
    this.storage = new AccountStorage(user.id)
    this.outbox = new Outbox(this.api, this.storage)
  }
  close() {
    this.closed = true
    this.events?.stop()
    this.selected.get()?.close()
    this.selected.set(null)
    this.api.close()
    this.outbox.close()
    this.catalog.set({ ...this.catalog.get(), sessions: [], devices: [], filters: defaultFilters })
  }
  refreshCatalog() {
    return this.list(false, true)
  }
  async list(more = false, refresh = false) {
    const before = this.catalog.get(),
      version = ++this.listVersion
    this.catalog.set({ ...before, loading: true, error: '' })
    const query = new URLSearchParams(Object.entries(before.filters).filter(([, value]) => value))
    query.set('limit', '30')
    if (more && before.next) query.set('cursor', before.next)
    try {
      const loaded = async () => {
        let page = await this.api.request<SessionPage>(`/api/remote/sessions?${query}`)
        const sessions = [...page.sessions]
        // Re-read the loaded extent to reconcile deletions/order and its new continuation cursor.
        while (refresh && sessions.length < before.sessions.length && page.next_cursor) {
          query.set('cursor', page.next_cursor)
          page = await this.api.request<SessionPage>(`/api/remote/sessions?${query}`)
          sessions.push(...page.sessions)
        }
        return { ...page, sessions }
      }
      const [page, devices] = await Promise.all([
        loaded(),
        this.api.request<{ devices: Device[] }>('/api/remote/devices')
      ])
      if (this.closed || version !== this.listVersion) return
      const rows = new Map((more ? before.sessions : []).map(row => [row.id, row]))
      for (const row of page.sessions) rows.set(row.id, row)
      this.catalog.set({
        ...before,
        sessions: [...rows.values()],
        next: page.next_cursor,
        devices: devices.devices,
        loading: false,
        error: ''
      })
      this.events?.resubscribe()
    } catch (error) {
      if (!this.closed && version === this.listVersion)
        this.catalog.set({ ...before, loading: false, error: String(error) })
    }
  }
  filter(values: Partial<Filters>) {
    this.catalog.set({ ...this.catalog.get(), filters: { ...this.catalog.get().filters, ...values } })
    void this.list()
  }
  open(id: string | null) {
    this.selected.get()?.close()
    this.selected.set(id ? new SessionModel(id, this.api, this.storage, this.outbox) : null)
    this.connect()
  }
  connect() {
    this.events?.stop()
    const selected = this.selected.get()
    this.events = new EventLink(() => (selected ? [selected.id] : this.catalog.get().sessions.map(row => row.id)), {
      live: frame => {
        if (selected && this.selected.get() === selected && frame.session_id === selected.id)
          selected.live.event(frame.event?.payload || {})
      },
      resetLive: () => selected?.live.clear(),
      repair: async () => {
        selected?.live.clear()
        const me = await identity()
        if (this.closed) return false
        if (me.user?.id !== this.user.id) {
          acceptIdentity(me)
          return false
        }
        this.api.csrf = me.csrf_token || ''
        await Promise.all([this.refreshCatalog(), selected?.refresh(), this.outbox.check()])
        if (this.catalog.get().error || selected?.state.get().error) throw new Error('Snapshot repair failed')
        if (
          selected &&
          ['starting', 'working', 'streaming', 'resuming'].includes(selected.state.get().detail?.session.status || '')
        )
          selected.live.recovering()
        selected?.settleDraft()
        return !this.closed
      },
      update: async frames => {
        const sessionUpdates = frames.filter(frame => frame.event?.type === 'session.updated')
        const detailUpdates = sessionUpdates.filter(frame => frame.session_id === selected?.id)
        const pending = this.outbox.state.get()
        const receiptChanged =
          pending &&
          frames.some(
            frame =>
              frame.event?.type === 'command.updated' &&
              frame.session_id === pending.session_id &&
              (!frame.event.payload?.request_id || frame.event.payload.request_id === pending.command.request_id)
          )
        const historyChanged = detailUpdates.some(frame => frame.event?.payload?.messages_changed !== false)
        await Promise.all([
          detailUpdates.length ? (historyChanged ? selected?.refresh() : selected?.refreshMetadata()) : undefined,
          sessionUpdates.length ? this.refreshCatalog() : undefined,
          receiptChanged ? this.outbox.check() : undefined
        ])
        if (
          (sessionUpdates.length && this.catalog.get().error) ||
          (detailUpdates.length && selected?.state.get().error)
        )
          throw new Error('Snapshot refresh failed')
        selected?.settleDraft()
      },
      status: status => {
        if (!this.closed) this.connection.set(status)
      },
      unauthorized: () => {
        if (!this.closed) {
          this.close()
          $auth.set({ ...$auth.get(), runtime: null, loading: true })
          void bootstrap()
        }
      }
    })
    void this.events.start()
  }
}
export interface AuthState {
  loading: boolean
  runtime: Runtime | null
  loginUrl: string | null
  error: string
}
export const $auth = atom<AuthState>({ loading: true, runtime: null, loginUrl: null, error: '' })
let authVersion = 0
function acceptIdentity(me: Identity) {
  const old = $auth.get().runtime
  if (old && old.user.id === me.user?.id) return
  old?.close()
  const previous = localStorage.getItem('hermes.remote.account')
  if (!me.user || previous !== me.user.id) clearAccountStorage()
  if (me.user) localStorage.setItem('hermes.remote.account', me.user.id)
  else localStorage.removeItem('hermes.remote.account')
  const runtime = me.user && me.csrf_token ? new Runtime(me.user, me.csrf_token) : null
  $auth.set({ loading: false, runtime, loginUrl: me.login_url, error: '' })
  runtime?.connect()
}
export async function bootstrap() {
  const version = ++authVersion
  try {
    const me = await identity()
    if (version === authVersion) acceptIdentity(me)
  } catch (error) {
    if (version === authVersion) $auth.set({ ...$auth.get(), loading: false, error: String(error) })
  }
}
export async function logout() {
  authVersion++
  const runtime = $auth.get().runtime
  let error = ''
  try {
    await runtime?.api.post('/auth/logout', {})
  } catch {
    error = '服务器退出未确认，请联网后重试退出。此设备的会话和草稿已清除。'
  }
  runtime?.close()
  clearAccountStorage()
  localStorage.removeItem('hermes.remote.account')
  sessionStorage.removeItem('hermes.remote.pairing')
  $auth.set({ loading: false, runtime: null, loginUrl: error ? null : '/auth/login', error })
}
export function pairingId() {
  const incoming = new URL(location.href).searchParams.get('pairing_id')
  if (incoming) sessionStorage.setItem('hermes.remote.pairing', incoming)
  return incoming || sessionStorage.getItem('hermes.remote.pairing')
}
