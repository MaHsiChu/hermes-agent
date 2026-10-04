import { afterEach, expect, it, vi } from 'vitest'
import { $auth, bootstrap, Runtime } from './runtime'
import { StaleAccountError } from '../lib/api'
import type { Session } from '../lib/protocol'

it('live catalog reconciliation preserves loaded extent, deletions, order and continued cursor; filters reset it', async () => {
  vi.useFakeTimers()
  const sockets: { onmessage?: (event: { data: string }) => void }[] = []
  vi.stubGlobal(
    'WebSocket',
    class {
      onmessage?: (event: { data: string }) => void
      constructor() {
        sockets.push(this)
      }
      close() {}
      send() {}
    }
  )
  let rows = Array.from({ length: 75 }, (_, n) => ({ id: `s${n}`, revision: 1 }) as Session)
  vi.stubGlobal(
    'fetch',
    vi.fn(async (path: string) => {
      if (path.endsWith('/me'))
        return new Response(JSON.stringify({ user: { id: 'alice', name: 'alice' }, csrf_token: 'csrf' }))
      if (path.includes('/devices')) return new Response(JSON.stringify({ devices: [] }))
      const query = new URL(path, 'http://localhost').searchParams
      const offset = Number(query.get('cursor') || 0)
      return new Response(
        JSON.stringify({
          sessions: rows.slice(offset, offset + 30),
          next_cursor: offset + 30 < rows.length ? String(offset + 30) : null
        })
      )
    })
  )
  const runtime = new Runtime({ id: 'alice', name: 'alice' }, 'csrf')
  await runtime.list()
  await runtime.list(true)
  runtime.connect()
  await vi.waitFor(() => expect(sockets).toHaveLength(1))
  rows = [rows[70], ...rows.filter(row => !['s70', 's5'].includes(row.id))]
  sockets[0].onmessage?.({
    data: JSON.stringify({
      type: 'event',
      cursor: 1,
      session_id: 's10',
      event: { type: 'session.updated', payload: { messages_changed: false } }
    })
  })
  await vi.advanceTimersByTimeAsync(750)
  expect(runtime.catalog.get().sessions).toHaveLength(60)
  expect(runtime.catalog.get().sessions[0].id).toBe('s70')
  expect(runtime.catalog.get().sessions.some(row => row.id === 's5')).toBe(false)
  expect(runtime.catalog.get().sessions.some(row => row.id === 's59')).toBe(true)
  expect(runtime.catalog.get().next).toBe('60')
  await runtime.list(true)
  expect(runtime.catalog.get().sessions).toHaveLength(74)
  runtime.filter({ q: 'new filter' })
  await vi.waitFor(() => expect(runtime.catalog.get().loading).toBe(false))
  expect(runtime.catalog.get().sessions).toHaveLength(30)
  runtime.close()
})

afterEach(() => {
  vi.useRealTimers()
  $auth.get().runtime?.close()
  $auth.set({ loading: false, runtime: null, loginUrl: null, error: '' })
  vi.unstubAllGlobals()
  localStorage.clear()
})
it('routes message changes, metadata, receipts and other-session events to only their required reads', async () => {
  vi.useFakeTimers()
  class Socket {
    onmessage: ((event: { data: string }) => void) | null = null
    constructor() {
      sockets.push(this)
    }
    send() {}
    close() {}
    frame(value: unknown) {
      this.onmessage?.({ data: JSON.stringify(value) })
    }
  }
  const sockets: Socket[] = [],
    reads: string[] = []
  const session = { id: 'chosen', revision: 1 }
  vi.stubGlobal('WebSocket', Socket)
  vi.stubGlobal(
    'fetch',
    vi.fn(async (path: string, options?: RequestInit) => {
      reads.push(path)
      const command = path.includes('/commands')
      const result = path.endsWith('/me')
        ? { user: { id: 'alice', name: 'alice' }, csrf_token: 'csrf' }
        : path.includes('/devices')
          ? { devices: [] }
          : path.includes('/sessions?')
            ? { sessions: [session], next_cursor: null }
            : path.includes('/messages?')
              ? { messages: [{ id: 'm', revision: 1, ordinal: 1, content: 'history' }], next_cursor: null, sync: {} }
              : command
                ? {
                    request_id: options?.body ? JSON.parse(options.body as string).request_id : path.split('/').at(-1),
                    state: options?.method ? 'accepted' : 'acknowledged'
                  }
                : { session, online: true, capabilities: {}, sync: {}, pending_requests: [] }
      return new Response(JSON.stringify(result))
    })
  )
  const runtime = new Runtime({ id: 'alice', name: 'alice' }, 'csrf')
  $auth.set({ runtime, loading: false, loginUrl: null, error: '' })
  runtime.open('chosen')
  await vi.waitFor(() => expect(sockets).toHaveLength(1))
  sockets[0].frame({ type: 'hello' })
  sockets[0].frame({ type: 'subscribed', cursor: 0 })
  let cursor = 0
  const emit = (type: string, payload: Record<string, unknown>, id = 'chosen') =>
    sockets[0].frame({ type: 'event', cursor: ++cursor, session_id: id, event: { type, payload } })
  reads.length = 0
  emit('session.updated', { messages_changed: false })
  await vi.advanceTimersByTimeAsync(750)
  expect(reads.some(path => path.includes('/messages?'))).toBe(false)
  expect(reads).toContain('/api/remote/sessions/chosen')
  reads.length = 0
  emit('session.updated', { messages_changed: true })
  emit('session.updated', { messages_changed: false })
  await vi.advanceTimersByTimeAsync(750)
  expect(reads.filter(path => path.includes('/messages?'))).toHaveLength(1)
  reads.length = 0
  emit('session.updated', {}, 'other')
  await vi.advanceTimersByTimeAsync(750)
  expect(reads.some(path => path.includes('/sessions/chosen'))).toBe(false)
  reads.length = 0
  emit('session.updated', {})
  await vi.advanceTimersByTimeAsync(750)
  expect(reads.some(path => path.includes('/messages?'))).toBe(true)
  await runtime.outbox.submit('chosen', 'send', { text: 'submitted' })
  const id = runtime.outbox.state.get()!.command.request_id
  reads.length = 0
  emit('command.updated', { request_id: id })
  await vi.advanceTimersByTimeAsync(750)
  expect(reads).toEqual([`/api/remote/commands/${id}`])
  reads.length = 0
  emit('gateway.event', { epoch: 'native', seq: 1, type: 'message.delta', payload: { text: 'Hello' } })
  emit('gateway.event', { epoch: 'native', seq: 1, type: 'message.delta', payload: { text: 'duplicate' } })
  emit('gateway.event', { epoch: 'native', seq: 2, type: 'message.delta', payload: { text: ' world' } })
  emit('gateway.event', { epoch: 'native', seq: 3, type: 'message.delta', payload: { text: 'foreign' } }, 'other')
  await vi.advanceTimersByTimeAsync(750)
  expect(reads).toEqual([])
  expect(runtime.selected.get()?.live.state.get().text).toBe('Hello world')
  runtime.open(null)
  expect(runtime.selected.get()).toBeNull()
})
it('a foreground identity change clears account A while its in-flight command resolves', async () => {
  let account = 'alice'
  let finish!: (response: Response) => void
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url === '/api/remote/me')
        return new Response(
          JSON.stringify({ user: { id: account, name: account }, csrf_token: account, login_url: null })
        )
      if (url.endsWith('/commands'))
        return new Promise<Response>(resolve => {
          finish = resolve
        })
      return new Response(
        JSON.stringify(url.includes('/devices') ? { devices: [] } : { sessions: [], next_cursor: null })
      )
    })
  )
  vi.stubGlobal(
    'WebSocket',
    class {
      close() {}
    }
  )
  await bootstrap()
  const alice = $auth.get().runtime!
  alice.storage.write('draft:s', { text: 'private A', attachment_ids: [], revision: 1 })
  const pending = alice.outbox.submit('s', 'send', { text: 'private A' })
  account = 'bob'
  await bootstrap()
  expect($auth.get().runtime?.user.id).toBe('bob')
  expect(Object.keys(localStorage).some(key => key.includes('alice'))).toBe(false)
  finish(new Response(JSON.stringify({ request_id: 'late', state: 'accepted' })))
  await expect(pending).rejects.toBeInstanceOf(StaleAccountError)
  expect($auth.get().runtime?.outbox.state.get()).toBeNull()
  expect(Object.keys(localStorage).some(key => key.includes('alice'))).toBe(false)
})
