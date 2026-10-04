import { afterEach, expect, it, vi } from 'vitest'
import { EventLink } from './events'

class Socket {
  onmessage: ((event: { data: string }) => void) | null = null
  onclose: ((event: { code: number }) => void) | null = null
  onerror: (() => void) | null = null
  sent: unknown[] = []
  send(data: string) {
    this.sent.push(JSON.parse(data))
  }
  close(code = 1000) {
    this.onclose?.({ code })
  }
  frame(value: unknown) {
    this.onmessage?.({ data: JSON.stringify(value) })
  }
}
afterEach(() => vi.useRealTimers())
it('repairs a Bridge generation rollback and accepts its low sequence while dropping a delayed old generation', async () => {
  vi.useFakeTimers()
  const sockets: Socket[] = [],
    live = vi.fn(),
    repair = vi.fn(async () => true)
  const link = new EventLink(
    () => ['s'],
    { repair, live, update: async () => {}, status: vi.fn(), unauthorized: vi.fn() },
    () => {
      const socket = new Socket()
      sockets.push(socket)
      return socket as unknown as WebSocket
    }
  )
  await link.start()
  const frame = (cursor: number, seq: number, generation: string, type = 'message.delta') => ({
    type: 'event',
    cursor,
    session_id: 's',
    event: {
      type: 'gateway.event',
      payload: {
        epoch: 'same-native',
        session_id: 'same-runtime',
        bridge_generation: generation,
        seq,
        type,
        payload: { text: 'resumed' }
      }
    }
  })
  sockets[0].frame(frame(1, 100, 'old'))
  sockets[0].frame(frame(2, 0, 'new', 'history.repair'))
  await vi.advanceTimersByTimeAsync(500)
  expect(repair).toHaveBeenCalledTimes(2)
  sockets[1].frame(frame(3, 1, 'new'))
  sockets[1].frame(frame(4, 101, 'old'))
  expect(live).toHaveBeenCalledTimes(2)
  expect(live.mock.calls[1][0].event.payload.seq).toBe(1)
  await vi.advanceTimersByTimeAsync(1000)
  expect(sockets).toHaveLength(2)
  link.stop()
})
it('repairs and resets native sequence tracking when a runtime session changes within the same process epoch', async () => {
  vi.useFakeTimers()
  const sockets: Socket[] = [],
    live = vi.fn(),
    resetLive = vi.fn()
  const link = new EventLink(
    () => ['public'],
    { repair: async () => true, update: async () => {}, status: vi.fn(), unauthorized: vi.fn(), live, resetLive },
    () => {
      const socket = new Socket()
      sockets.push(socket)
      return socket as unknown as WebSocket
    }
  )
  await link.start()
  const frame = (cursor: number, session_id: string, seq: number) => ({
    type: 'event',
    cursor,
    session_id: 'public',
    event: {
      type: 'gateway.event',
      payload: { session_id, epoch: 'same-process', seq, type: 'message.delta', payload: { text: 'chunk' } }
    }
  })
  sockets[0].frame(frame(1, 'runtime-A', 100))
  sockets[0].frame(frame(2, 'runtime-B', 1))
  await vi.advanceTimersByTimeAsync(500)
  expect(sockets).toHaveLength(2)
  expect(resetLive).toHaveBeenCalled()
  sockets[1].frame(frame(3, 'runtime-B', 2))
  sockets[1].frame(frame(4, 'runtime-B', 2))
  expect(live).toHaveBeenCalledTimes(2)
  link.stop()
})
it('repairs after the first hello barrier and subscribes from it without losing snapshot-race events', async () => {
  vi.useFakeTimers()
  const socket = new Socket(),
    live = vi.fn()
  let finish!: (value: boolean) => void
  const repair = vi
    .fn()
    .mockResolvedValueOnce(true)
    .mockImplementationOnce(
      () =>
        new Promise<boolean>(resolve => {
          finish = resolve
        })
    )
  const link = new EventLink(
    () => ['s'],
    { repair, live, update: async () => {}, status: vi.fn(), unauthorized: vi.fn() },
    () => socket as unknown as WebSocket
  )
  await link.start()
  socket.frame({ type: 'hello', cursor: 500 })
  expect(socket.sent).toEqual([])
  expect(repair).toHaveBeenCalledTimes(2)
  finish(true)
  await vi.advanceTimersByTimeAsync(0)
  expect(socket.sent).toEqual([{ type: 'subscribe', session_ids: ['s'], cursor: 500 }])
  socket.frame({
    type: 'event',
    cursor: 501,
    session_id: 's',
    event: {
      type: 'gateway.event',
      payload: { epoch: 'native', seq: 22, type: 'message.delta', payload: { text: 'during snapshot' } }
    }
  })
  expect(live).toHaveBeenCalledOnce()
  link.stop()
})
it('keeps the replay cursor monotonic through consecutive gaps and delayed resubscribe acknowledgements', async () => {
  vi.useFakeTimers()
  const sockets: Socket[] = []
  let ids = ['a']
  const link = new EventLink(
    () => ids,
    { repair: async () => true, update: async () => {}, status: vi.fn(), unauthorized: vi.fn() },
    () => {
      const socket = new Socket()
      sockets.push(socket)
      return socket as unknown as WebSocket
    }
  )
  await link.start()
  sockets[0].frame({ type: 'hello' })
  sockets[0].frame({ type: 'subscribed', cursor: 0 })
  sockets[0].frame({ type: 'gap', cursor: 204 })
  await vi.advanceTimersByTimeAsync(500)
  sockets[1].frame({ type: 'hello' })
  sockets[1].frame({ type: 'subscribed', cursor: 204 })
  sockets[1].frame({ type: 'gap', cursor: 405 })
  await vi.advanceTimersByTimeAsync(500)
  sockets[2].frame({ type: 'hello' })
  sockets[2].frame({ type: 'subscribed', cursor: 405 })
  sockets[2].frame({
    type: 'event',
    cursor: 406,
    session_id: 'a',
    event: { type: 'gateway.event', payload: { epoch: 'old', seq: 1 } }
  })
  ids = ['a', 'b']
  link.resubscribe()
  sockets[2].frame({
    type: 'event',
    cursor: 407,
    session_id: 'a',
    event: { type: 'gateway.event', payload: { epoch: 'new', seq: 1 } }
  })
  sockets[2].frame({ type: 'subscribed', cursor: 406 })
  await vi.advanceTimersByTimeAsync(500)
  sockets[3].frame({ type: 'hello' })
  expect(sockets[3].sent[0]).toEqual({ type: 'subscribe', session_ids: ['a', 'b'], cursor: 407 })
  link.stop()
})
it('tracks native epochs per session instead of mistaking interleaved sessions for restarts', async () => {
  vi.useFakeTimers()
  const sockets: Socket[] = []
  const link = new EventLink(
    () => ['a', 'b'],
    { repair: async () => true, update: async () => {}, status: vi.fn(), unauthorized: vi.fn() },
    () => {
      const socket = new Socket()
      sockets.push(socket)
      return socket as unknown as WebSocket
    }
  )
  await link.start()
  sockets[0].frame({
    type: 'event',
    cursor: 1,
    session_id: 'a',
    event: { type: 'gateway.event', payload: { epoch: 'a1', seq: 1 } }
  })
  sockets[0].frame({
    type: 'event',
    cursor: 2,
    session_id: 'b',
    event: { type: 'gateway.event', payload: { epoch: 'b1', seq: 1 } }
  })
  await vi.advanceTimersByTimeAsync(1000)
  expect(sockets).toHaveLength(1)
  sockets[0].frame({
    type: 'event',
    cursor: 3,
    session_id: 'a',
    event: { type: 'gateway.event', payload: { epoch: 'a2', seq: 1 } }
  })
  await vi.advanceTimersByTimeAsync(500)
  expect(sockets).toHaveLength(2)
  sockets[1].frame({
    type: 'event',
    cursor: 4,
    session_id: 'a',
    event: { type: 'gateway.event', payload: { epoch: 'a2', seq: 2 } }
  })
  await vi.advanceTimersByTimeAsync(1000)
  expect(sockets).toHaveLength(2)
  link.stop()
})
it('repairs snapshots before subscribing after a gap and coalesces event bursts', async () => {
  vi.useFakeTimers()
  const sockets: Socket[] = [],
    repair = vi.fn(async () => true),
    update = vi.fn(async () => {})
  const link = new EventLink(
    () => ['s'],
    { repair, update, status: vi.fn(), unauthorized: vi.fn() },
    () => {
      const socket = new Socket()
      sockets.push(socket)
      return socket as unknown as WebSocket
    }
  )
  await link.start()
  sockets[0].frame({ type: 'hello' })
  expect(sockets[0].sent).toEqual([{ type: 'subscribe', session_ids: ['s'], cursor: 0 }])
  sockets[0].frame({ type: 'subscribed', cursor: 10 })
  for (let cursor = 11; cursor <= 1000; cursor++)
    sockets[0].frame({ type: 'event', cursor, session_id: 's', event: { type: 'session.updated' } })
  await vi.advanceTimersByTimeAsync(750)
  expect(update).toHaveBeenCalledTimes(1)
  sockets[0].frame({ type: 'gap', cursor: 1100 })
  await vi.advanceTimersByTimeAsync(500)
  expect(repair).toHaveBeenCalledTimes(2)
  sockets[1].frame({ type: 'hello' })
  expect(sockets[1].sent[0]).toEqual({ type: 'subscribe', session_ids: ['s'], cursor: 1100 })
  sockets[1].frame({ type: 'event', cursor: 1099, event: { type: 'session.updated' } })
  await vi.advanceTimersByTimeAsync(750)
  expect(update).toHaveBeenCalledTimes(1)
  link.stop()
})
it('does not reconnect forbidden sockets or resume after a failed account check', async () => {
  vi.useFakeTimers()
  const socket = new Socket(),
    factory = vi.fn(() => socket as unknown as WebSocket),
    unauthorized = vi.fn()
  const link = new EventLink(
    () => ['s'],
    { repair: async () => true, update: async () => {}, status: vi.fn(), unauthorized },
    factory
  )
  await link.start()
  socket.close(4403)
  await vi.advanceTimersByTimeAsync(20000)
  expect(factory).toHaveBeenCalledTimes(1)
  expect(unauthorized).toHaveBeenCalledOnce()
  const denied = new EventLink(
    () => ['s'],
    { repair: async () => false, update: async () => {}, status: vi.fn(), unauthorized },
    factory
  )
  await denied.start()
  expect(factory).toHaveBeenCalledTimes(1)
})
