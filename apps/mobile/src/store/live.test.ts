import { expect, it } from 'vitest'
import { Api } from '../lib/api'
import type { Message } from '../lib/protocol'
import { AccountStorage } from '../lib/storage'
import { Outbox } from './outbox'
import { SessionModel } from './session'

function session(rows: () => Message[]) {
  const api = new Api(
    'csrf',
    async path =>
      new Response(
        JSON.stringify(
          String(path).includes('/messages')
            ? { messages: rows(), next_cursor: null, sync: {} }
            : { session: { id: 's', revision: 1 }, capabilities: {}, sync: {}, pending_requests: [], online: true }
        )
      )
  )
  const storage = new AccountStorage('live-test')
  return new SessionModel('s', api, storage, new Outbox(api, storage))
}
const event = (type: string, text = '') => ({ type, payload: { text } })
it('keeps replay and delayed persistence independent from the current temporary stream', async () => {
  let rows: Message[] = [{ id: '1', ordinal: 1, revision: 1, role: 'assistant', content: 'Already durable' }]
  const model = session(() => rows)
  await model.refresh()
  // Completion happened during handshake/repair, before its events were replayed.
  model.live.event(event('message.start'))
  model.live.event(event('message.delta', 'Already durable'))
  model.live.event(event('message.complete', 'Already durable'))
  expect(model.live.state.get().text).toBe('')
  expect(model.live.state.get().reasoning).toBe('')
  await model.refresh()
  expect(model.live.state.get().status).toBe('')
  expect(model.state.get().messages).toEqual(rows)
  // New output may finish before the next durable snapshot arrives.
  model.live.event(event('message.start'))
  model.live.event(event('message.delta', 'Interim'))
  model.live.event(event('message.interim', 'Interim'))
  expect(model.live.state.get().text).toBe('')
  model.live.event(event('message.delta', 'Later persisted'))
  model.live.event(event('message.complete', 'Later persisted'))
  expect(model.live.state.get().text.length).toBe(0)
  expect(model.state.get().messages).toHaveLength(1)
  rows = [...rows, { id: '2', ordinal: 2, revision: 1, role: 'assistant', content: 'Later persisted' }]
  await model.refresh()
  expect(model.state.get().messages).toEqual(rows)
  expect(model.live.state.get().status).toBe('')
})
it('bounds active output and clears an oversized completion before the complete durable row arrives', async () => {
  let rows: Message[] = []
  const model = session(() => rows),
    full = 'x'.repeat(262145)
  await model.refresh()
  model.live.event(event('message.delta', full))
  expect(model.live.state.get().text.length).toBeLessThanOrEqual(262144)
  expect(model.live.state.get().limited).toBe(true)
  model.live.event(event('message.complete', full))
  expect(model.live.state.get().text).toBe('')
  expect(model.live.state.get().limited).toBe(false)
  rows = [{ id: '1', ordinal: 1, revision: 1, role: 'assistant', content: full }]
  await model.refresh()
  expect(model.state.get().messages[0].content).toBe(full)
  expect(model.live.state.get().status).toBe('')
})
