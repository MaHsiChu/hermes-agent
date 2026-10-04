export interface RemoteEvent {
  type: string
  cursor?: number
  event?: { type: string; payload?: Record<string, unknown> }
  session_id?: string
  reason?: string
}
export interface EventCallbacks {
  repair: () => Promise<boolean>
  update: (frames: RemoteEvent[]) => Promise<void>
  status: (status: string) => void
  unauthorized: () => void
  live?: (frame: RemoteEvent) => void
  resetLive?: () => void
}

// Events are coalesced into one refresh, never queued as unbounded token frames.
export class EventLink {
  private socket: WebSocket | null = null
  private timer: ReturnType<typeof setTimeout> | undefined
  private refreshTimer: ReturnType<typeof setTimeout> | undefined
  private stopped = false
  private cursor = 0
  private initialized = false
  private attempts = 0
  private refreshing = false
  private latest = new Map<string, RemoteEvent>()
  private native = new Map<
    string,
    { epoch: unknown; runtime: unknown; generation: unknown; retired: unknown[]; seq: number }
  >()
  private subscription = ''
  private ready = false
  constructor(
    private ids: () => string[],
    private callbacks: EventCallbacks,
    private makeSocket = (url: string) => new WebSocket(url)
  ) {}
  async start() {
    this.callbacks.status('正在同步')
    try {
      if (!(await this.callbacks.repair()) || this.stopped) return
      const url = new URL('/api/remote/events', location.href)
      url.protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
      const socket = this.makeSocket(url.href)
      this.socket = socket
      let retiring = false
      const retire = () => {
        retiring = true
        this.ready = false
        clearTimeout(this.refreshTimer)
        this.refreshTimer = undefined
        this.latest.clear()
        this.callbacks.resetLive?.()
        socket.close()
      }
      socket.onmessage = async event => {
        if (this.stopped || retiring || this.socket !== socket) return
        let frame: RemoteEvent
        try {
          frame = JSON.parse(event.data)
        } catch {
          retire()
          return
        }
        if (frame.type === 'hello') {
          if (!this.initialized && typeof frame.cursor === 'number') {
            this.cursor = frame.cursor
            try {
              if (!(await this.callbacks.repair()) || this.stopped || retiring || this.socket !== socket) return
            } catch {
              retire()
              return
            }
          }
          this.initialized = true
          this.ready = true
          this.subscription = ''
          this.resubscribe()
        }
        if (frame.type === 'subscribed') {
          this.attempts = 0
          this.cursor = Math.max(this.cursor, frame.cursor ?? this.cursor)
          this.callbacks.status('实时连接')
        }
        if (frame.type === 'gap') {
          this.cursor = Math.max(this.cursor, frame.cursor ?? 0)
          retire()
          return
        }
        if (frame.type !== 'event' || typeof frame.cursor !== 'number' || frame.cursor <= this.cursor) return
        this.cursor = frame.cursor
        const native = frame.event?.payload
        if (frame.event?.type === 'gateway.event') {
          const id = frame.session_id || ''
          const previous = this.native.get(id)
          if (native?.bridge_generation !== undefined && previous?.retired.includes(native.bridge_generation)) return
          const generationChanged =
            native?.bridge_generation !== undefined &&
            previous?.generation !== undefined &&
            previous.generation !== native.bridge_generation
          const changed =
            generationChanged ||
            (native?.epoch !== undefined && previous?.epoch !== undefined && previous.epoch !== native.epoch) ||
            (native?.session_id !== undefined &&
              previous?.runtime !== undefined &&
              previous.runtime !== native.session_id)
          const repair = native?.type === 'history.repair'
          if (!changed && !repair && typeof native?.seq === 'number' && previous && native.seq <= previous.seq) return
          if (!this.native.has(id) && this.native.size >= 32) this.native.delete(this.native.keys().next().value!)
          this.native.set(id, {
            epoch: native?.epoch ?? previous?.epoch,
            runtime: native?.session_id ?? previous?.runtime,
            generation: native?.bridge_generation ?? previous?.generation,
            retired: generationChanged
              ? [...(previous?.retired || []), previous?.generation].slice(-4)
              : previous?.retired || [],
            seq:
              typeof native?.seq === 'number'
                ? Math.max(changed ? 0 : previous?.seq || 0, native.seq)
                : changed
                  ? 0
                  : previous?.seq || 0
          })
          if (changed || repair) {
            retire()
            return
          }
          this.callbacks.live?.(frame)
          return
        }
        if (!['session.updated', 'command.updated'].includes(frame.event?.type || '')) return
        const key = `${frame.session_id}:${frame.event!.type}`
        const previous = this.latest.get(key)
        if (
          previous &&
          frame.event?.type === 'session.updated' &&
          previous.event?.payload?.messages_changed !== false
        ) {
          frame = { ...frame, event: { ...frame.event, payload: { ...frame.event.payload, messages_changed: true } } }
        }
        this.latest.set(key, frame)
        if (this.latest.size > 64) {
          retire()
          return
        }
        this.scheduleUpdate()
      }
      socket.onclose = event => {
        if (this.stopped || this.socket !== socket) return
        retiring = true
        this.ready = false
        this.callbacks.resetLive?.()
        if ([4401, 4403].includes(event.code)) {
          this.stop()
          this.callbacks.unauthorized()
          return
        }
        this.callbacks.status('连接中断 · 正在重连')
        this.timer = setTimeout(() => void this.start(), Math.min(500 * 2 ** this.attempts++, 4000))
      }
      socket.onerror = retire
    } catch {
      if (!this.stopped) {
        this.callbacks.status('网络离线 · 草稿仅保存在本机')
        this.timer = setTimeout(() => void this.start(), 4000)
      }
    }
  }
  resubscribe() {
    if (!this.ready || this.stopped || !this.socket) return
    const ids = this.ids().slice(0, 32)
    const subscription = JSON.stringify(ids)
    if (subscription === this.subscription) return
    this.subscription = subscription
    this.socket.send(JSON.stringify({ type: 'subscribe', session_ids: ids, cursor: this.cursor }))
  }
  private scheduleUpdate() {
    if (this.refreshTimer || this.refreshing || this.stopped) return
    this.refreshTimer = setTimeout(async () => {
      this.refreshTimer = undefined
      const events = [...this.latest.values()]
      this.latest.clear()
      this.refreshing = true
      try {
        if (events.length && !this.stopped) await this.callbacks.update(events)
      } catch {
        if (!this.stopped) {
          this.callbacks.status('同步失败 · 正在恢复')
          this.socket?.close()
        }
      } finally {
        this.refreshing = false
        if (this.latest.size) this.scheduleUpdate()
      }
    }, 750)
  }
  stop() {
    this.stopped = true
    this.ready = false
    clearTimeout(this.timer)
    clearTimeout(this.refreshTimer)
    this.latest.clear()
    this.native.clear()
    this.socket?.close()
    this.socket = null
  }
}
