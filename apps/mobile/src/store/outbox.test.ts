import { beforeEach, expect, it, vi } from 'vitest'
import { Api, StaleAccountError } from '../lib/api'
import { AccountStorage, clearAccountStorage } from '../lib/storage'
import { Outbox } from './outbox'

beforeEach(() => localStorage.clear())
it('does not let a delayed receipt for archived A replace uncertain B in memory or storage', async () => {
  let finish!: (response: Response) => void
  let posts = 0
  const api = new Api('csrf', async (_path, options) => {
    if (!options?.method)
      return new Promise<Response>(resolve => {
        finish = resolve
      })
    if (++posts === 2) throw new TypeError('B response lost')
    return new Response(
      JSON.stringify({ request_id: JSON.parse(options.body as string).request_id, state: 'acknowledged' })
    )
  })
  const storage = new AccountStorage('alice'),
    box = new Outbox(api, storage)
  await box.submit('s', 'send', { text: 'A' })
  const a = box.state.get()!.command.request_id
  const checking = box.check()
  await box.submit('s', 'send', { text: 'B' })
  const b = structuredClone(box.state.get())
  finish(new Response(JSON.stringify({ request_id: a, state: 'acknowledged' })))
  await checking
  expect(box.state.get()).toEqual(b)
  expect(storage.read('outbox', null)).toEqual(b)
  expect(box.state.get()?.uncertain).toBe(true)
})
it('merges same-command receipts without regressing state or draft settlement and never restores a dismissed envelope', async () => {
  const finishes: ((response: Response) => void)[] = []
  const api = new Api('csrf', async (_path, options) =>
    options?.method
      ? new Response(JSON.stringify({ request_id: JSON.parse(options.body as string).request_id, state: 'accepted' }))
      : new Promise<Response>(resolve => finishes.push(resolve))
  )
  const box = new Outbox(api, new AccountStorage('alice'))
  await box.submit('s', 'send', { text: 'A' })
  const id = box.state.get()!.command.request_id
  const stale = box.check(),
    fresh = box.check()
  box.markDraftSettled()
  finishes[1](new Response(JSON.stringify({ request_id: id, state: 'acknowledged' })))
  await fresh
  finishes[0](new Response(JSON.stringify({ request_id: id, state: 'received' })))
  await stale
  expect(box.state.get()?.receipt?.state).toBe('acknowledged')
  expect(box.state.get()?.draftSettled).toBe(true)
  const dismissed = box.check()
  box.dismiss()
  finishes[2](new Response(JSON.stringify({ request_id: id, state: 'completed' })))
  await dismissed
  expect(box.state.get()).toBeNull()
})
it('allows an explicit next operation after acknowledgement but never clears uncertain delivery', async () => {
  let uncertain = false
  const fetcher = vi.fn(
    async (_path: RequestInfo | URL, options?: RequestInit) =>
      new Response(
        JSON.stringify({
          request_id: JSON.parse(options!.body as string).request_id,
          state: uncertain ? 'delivery_uncertain' : 'acknowledged'
        })
      )
  )
  const box = new Outbox(new Api('csrf', fetcher), new AccountStorage('alice'))
  await box.submit('s', 'send', { text: 'start' })
  const first = box.state.get()!.command.request_id
  await expect(box.submit('s', 'clarify', { pending_request_id: 'p', answer: 'yes' })).resolves.toBeUndefined()
  expect(box.state.get()?.command.request_id).not.toBe(first)
  uncertain = true
  await box.submit('s', 'send', { text: 'network ambiguity' })
  await expect(box.submit('s', 'approval', { pending_request_id: 'a', choice: 'once' })).rejects.toThrow('回执')
  expect(fetcher).toHaveBeenCalledTimes(3)
})
it('resolves ambiguity by receipt before resubmitting the immutable payload and request ID', async () => {
  const calls: { path: string; body?: string }[] = []
  let attempt = 0
  const fetcher = vi.fn(async (path: RequestInfo | URL, options?: RequestInit) => {
    calls.push({ path: String(path), body: options?.body as string })
    attempt++
    if (attempt === 1) throw new TypeError('connection reset')
    if (attempt === 2) return new Response(JSON.stringify({ detail: 'not found' }), { status: 404 })
    return new Response(JSON.stringify({ request_id: 'receipt', state: 'accepted' }), { status: 202 })
  })
  const box = new Outbox(new Api('csrf', fetcher), new AccountStorage('alice'))
  const payload = { text: 'original', attachment_ids: ['image'] }
  await box.submit('session', 'queue', payload)
  expect(box.state.get()?.uncertain).toBe(true)
  payload.text = 'later editing'
  const restored = new Outbox(new Api('csrf', fetcher), new AccountStorage('alice'))
  await restored.retry()
  expect(calls[1].path).toContain('/commands/')
  expect(calls[1].body).toBeUndefined()
  expect(calls[2].body).toBe(calls[0].body)
  expect(JSON.parse(calls[2].body!).payload.text).toBe('original')
})
it('never resends a delivery_uncertain receipt and discards late account A results after switching to B', async () => {
  let resolve!: (response: Response) => void
  const api = new Api(
    'csrf',
    () =>
      new Promise<Response>(done => {
        resolve = done
      })
  )
  const box = new Outbox(api, new AccountStorage('alice'))
  const sending = box.submit('session', 'send', { text: 'private' })
  api.close()
  clearAccountStorage()
  resolve(new Response(JSON.stringify({ request_id: 'r', state: 'accepted' }), { status: 202 }))
  await expect(sending).rejects.toBeInstanceOf(StaleAccountError)
  expect(localStorage.length).toBe(0)
  const fetcher = vi.fn(async () => new Response(JSON.stringify({ request_id: 'r', state: 'delivery_uncertain' })))
  const second = new Outbox(new Api('b', fetcher), new AccountStorage('bob'))
  await second.submit('session', 'send', { text: 'new' })
  await second.retry()
  expect(fetcher).toHaveBeenCalledTimes(2)
  expect(second.state.get()?.receipt?.state).toBe('delivery_uncertain')
})
