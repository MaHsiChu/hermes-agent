import { beforeEach, expect, it, vi } from 'vitest'
import { Api } from '../lib/api'
import { AccountStorage } from '../lib/storage'
import { SessionModel } from './session'
import { Outbox } from './outbox'

beforeEach(() => localStorage.clear())
it('keeps the loaded oldest boundary across live appends and repairs revisions through that boundary', async () => {
  const rows = Array.from({ length: 201 }, (_, index) => ({
    id: String(index + 1),
    ordinal: index + 1,
    revision: 1,
    content: `message ${index + 1}`,
    deleted: false
  }))
  let historyReads = 0
  const api = new Api('csrf', async path => {
    if (!String(path).includes('/messages'))
      return new Response(
        JSON.stringify({ session: { id: 's' }, capabilities: {}, sync: {}, pending_requests: [], online: true })
      )
    historyReads++
    const url = new URL(String(path), 'http://localhost')
    const boundary = Number(url.searchParams.get('cursor') || Infinity)
    const remaining = rows.filter(row => row.ordinal < boundary).sort((a, b) => b.ordinal - a.ordinal)
    const page = remaining.slice(0, 100)
    return new Response(
      JSON.stringify({
        messages: [...page].reverse(),
        next_cursor: remaining.length > 100 ? String(page.at(-1)!.ordinal) : null,
        sync: {}
      })
    )
  })
  const storage = new AccountStorage('a'),
    model = new SessionModel('s', api, storage, new Outbox(api, storage))
  await model.refresh()
  await model.more()
  const before = model.state.get()
  const ids = before.messages.map(row => row.id)
  rows.push({ id: '202', ordinal: 202, revision: 1, content: 'new arrival', deleted: false })
  historyReads = 0
  await model.refresh()
  expect(model.state.get().messages.map(row => row.id)).toEqual([...ids, '202'])
  expect(model.state.get().next).toBe(before.next)
  expect(historyReads).toBe(3)
  historyReads = 0
  await model.refreshMetadata()
  expect(historyReads).toBe(0)
  expect(model.state.get().messages.map(row => row.id)).toEqual([...ids, '202'])
  rows[1] = { ...rows[1], revision: 2, content: 'edited old row' }
  rows[9] = { ...rows[9], revision: 2, content: '', deleted: true }
  await model.refresh()
  expect(model.state.get().messages.find(row => row.id === '2')?.content).toBe('edited old row')
  expect(model.state.get().messages.find(row => row.id === '10')?.deleted).toBe(true)
  expect(model.state.get().next).toBe(before.next)
  await model.more()
  expect(model.state.get().messages[0].id).toBe('1')
  expect(new Set(model.state.get().messages.map(row => row.id)).size).toBe(rows.length)
})
it('starts at latest history, prepends older rows and replaces stale snapshots on repair', async () => {
  let revision = 1
  const fetcher = vi.fn(async (path: RequestInfo | URL) => {
    if (!String(path).includes('/messages'))
      return new Response(
        JSON.stringify({ session: { id: 's' }, capabilities: {}, sync: {}, pending_requests: [], online: true })
      )
    const url = new URL(String(path), 'http://localhost')
    expect(url.searchParams.get('order')).toBe('latest')
    const older = url.searchParams.has('cursor')
    return new Response(
      JSON.stringify({
        messages: older
          ? [{ id: 'old', revision: 1, ordinal: 1, content: 'earlier' }]
          : [{ id: 'new', revision, ordinal: 200, ...(revision === 1 ? { content: 'latest' } : { deleted: true }) }],
        next_cursor: older ? null : 'older',
        sync: {}
      })
    )
  })
  const api = new Api('csrf', fetcher),
    storage = new AccountStorage('a'),
    model = new SessionModel('s', api, storage, new Outbox(api, storage))
  await model.refresh()
  expect(model.state.get().messages.map(row => row.id)).toEqual(['new'])
  await model.more()
  expect(model.state.get().messages.map(row => row.id)).toEqual(['old', 'new'])
  revision++
  await model.refresh()
  expect(model.state.get().messages.find(row => row.id === 'new')?.deleted).toBe(true)
})
it('preserves draft edits made while submission is in flight', async () => {
  let resolve!: (response: Response) => void
  const api = new Api(
      'csrf',
      () =>
        new Promise<Response>(done => {
          resolve = done
        })
    ),
    storage = new AccountStorage('a'),
    outbox = new Outbox(api, storage),
    model = new SessionModel('s', api, storage, outbox)
  model.edit({ text: 'first', attachment_ids: ['a'] })
  const submitted = model.draft.get()
  const request = outbox.submit(
    's',
    'send',
    { text: submitted.text, attachment_ids: submitted.attachment_ids },
    submitted
  )
  model.edit({ text: 'new text', attachment_ids: ['a', 'b'] })
  resolve(new Response(JSON.stringify({ request_id: 'r', state: 'accepted' })))
  await request
  model.settleDraft()
  expect(model.draft.get().text).toBe('new text')
  expect(model.draft.get().attachment_ids).toEqual(['b'])
  model.settleDraft()
  expect(model.draft.get().text).toBe('new text')
})
