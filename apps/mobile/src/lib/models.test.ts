import { describe, expect, it } from 'vitest'
import { canAnswer, mergeMessages, remainingDraft } from './models'

describe('revision and draft contracts', () => {
  it('applies revisions by identity, retaining tombstones against older pages', () => {
    const first = [
      { id: 'a', revision: 1, ordinal: 1, content: 'old' },
      { id: 'b', revision: 1, ordinal: 2, content: 'keep' }
    ]
    const updated = mergeMessages(first, [{ id: 'a', revision: 3, ordinal: 1, deleted: true }])
    const replayed = mergeMessages(updated, [{ id: 'a', revision: 2, ordinal: 1, content: 'resurrect' }])
    expect(replayed.find(m => m.id === 'a')).toEqual({ id: 'a', revision: 3, ordinal: 1, deleted: true })
    expect(replayed.find(m => m.id === 'b')?.content).toBe('keep')
  })
  it('clears only the submitted draft version, keeping typing and new attachments', () => {
    const submitted = { text: 'hello', attachment_ids: ['img1'], revision: 2 }
    expect(remainingDraft(submitted, submitted)).toEqual({ text: '', attachment_ids: [], revision: 3 })
    const newer = { text: 'hello next', attachment_ids: ['img1', 'img2'], revision: 3 }
    expect(remainingDraft(newer, submitted)).toEqual({ ...newer, attachment_ids: ['img2'] })
  })
})
it('rejects expired, secret and unsupported pending requests', () => {
  const pending = { id: 'p', method: 'approval', params: { choices: ['once', 'deny'], expires_at: 100 } }
  expect(canAnswer(pending, { status: 'supported' }, 101)).toBe(false)
  expect(canAnswer({ ...pending, params: { secret: true } }, { status: 'supported' }, 1)).toBe(false)
  expect(canAnswer({ ...pending, method: 'sudo' }, { status: 'supported' }, 1)).toBe(false)
  expect(canAnswer(pending, { status: 'unavailable' }, 1)).toBe(false)
  expect(canAnswer(pending, { status: 'supported' }, 1)).toBe(true)
})
