import { atom } from 'nanostores'
import { Api, sessionPath } from '../lib/api'
import { emptyDraft, mergeMessages, remainingDraft } from '../lib/models'
import type { Detail, Draft, Message, MessagePage } from '../lib/protocol'
import { AccountStorage } from '../lib/storage'
import { Outbox } from './outbox'
import { LiveOutput } from './live'

export interface SessionState {
  detail: Detail | null
  messages: Message[]
  next: string | null
  loading: boolean
  error: string
}
export class SessionModel {
  state = atom<SessionState>({ detail: null, messages: [], next: null, loading: false, error: '' })
  draft = atom<Draft>(emptyDraft())
  live = new LiveOutput()
  private active = true
  private requestVersion = 0
  private metadataVersion = 0
  constructor(
    public id: string,
    private api: Api,
    private storage: AccountStorage,
    public outbox: Outbox
  ) {
    this.draft.set(storage.read(`draft:${id}`, emptyDraft()))
  }
  close() {
    this.active = false
    this.live.clear()
    this.requestVersion++
    this.draft.set(emptyDraft())
    this.state.set({ detail: null, messages: [], next: null, loading: false, error: '' })
  }
  edit(change: Partial<Draft>) {
    if (!this.active) return
    this.api.assertActive()
    const value = { ...this.draft.get(), ...change, revision: this.draft.get().revision + 1 }
    this.draft.set(value)
    this.storage.write(`draft:${this.id}`, value)
  }
  settleDraft() {
    if (!this.active) return
    const pending = this.outbox.state.get()
    if (
      pending?.session_id !== this.id ||
      !pending.submitted ||
      pending.draftSettled ||
      !pending.receipt ||
      ['failed', 'delivery_uncertain'].includes(pending.receipt.state)
    )
      return
    this.edit(remainingDraft(this.draft.get(), pending.submitted))
    this.outbox.markDraftSettled()
  }
  async refreshMetadata() {
    const version = ++this.metadataVersion
    try {
      const detail = await this.api.request<Detail>(sessionPath(this.id))
      if (!this.active || version !== this.metadataVersion) return
      const current = this.state.get()
      if (current.detail && current.detail.session.revision > detail.session.revision) return
      this.state.set({ ...current, detail, error: '' })
    } catch (error) {
      if (this.active && version === this.metadataVersion) this.state.set({ ...this.state.get(), error: String(error) })
    }
  }
  async refresh() {
    const version = ++this.requestVersion
    const before = this.state.get()
    const oldest = before.messages[0]
    const boundary = oldest
    const atOrBefore = (row: Message, edge: Message) =>
      row.ordinal < edge.ordinal || (row.ordinal === edge.ordinal && row.id <= edge.id)
    this.state.set({ ...before, loading: true, error: '' })
    try {
      let detail = await this.api.request<Detail>(sessionPath(this.id))
      let rows: Message[] = [],
        cursor: string | null = null
      const seen = new Set<string>()
      while (true) {
        const result: MessagePage = await this.api.request(
          `${sessionPath(this.id)}/messages?order=latest&limit=100${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`
        )
        if (!this.active || version !== this.requestVersion) return
        rows = mergeMessages(rows, result.messages)
        cursor = result.next_cursor
        if (!cursor || !boundary || result.messages.some(row => row.id === boundary.id || atOrBefore(row, boundary)))
          break
        if (seen.has(cursor)) throw new Error('历史分页游标重复，请重新同步')
        seen.add(cursor)
      }
      if (!this.active || version !== this.requestVersion) return
      // A keyset cursor is the loaded boundary; page count changes whenever new rows arrive.
      const priorIds = new Set(before.messages.map(row => row.id))
      if (oldest && before.next) rows = rows.filter(row => priorIds.has(row.id) || !atOrBefore(row, oldest))
      const fetched = new Set(rows.map(row => row.id))
      const next = !oldest || !before.next ? cursor : before.next
      rows = mergeMessages(before.messages, rows).filter(row => fetched.has(row.id))
      const newerDetail = this.state.get().detail
      if (newerDetail && newerDetail.session.revision > detail.session.revision) detail = newerDetail
      this.state.set({ detail, messages: rows, next, loading: false, error: '' })
      this.settleDraft()
    } catch (error) {
      if (!this.active || version !== this.requestVersion) return
      this.state.set({
        ...this.state.get(),
        loading: false,
        error: error instanceof Error ? error.message : '同步失败'
      })
    }
  }
  async more() {
    const before = this.state.get()
    if (before.loading || !before.next) return
    const version = ++this.requestVersion
    this.state.set({ ...before, loading: true })
    try {
      const page = await this.api.request<MessagePage>(
        `${sessionPath(this.id)}/messages?order=latest&limit=100&cursor=${encodeURIComponent(before.next)}`
      )
      if (!this.active || version !== this.requestVersion) return
      this.state.set({
        ...this.state.get(),
        messages: mergeMessages(before.messages, page.messages),
        next: page.next_cursor,
        loading: false
      })
    } catch (error) {
      if (this.active && version === this.requestVersion)
        this.state.set({ ...before, loading: false, error: String(error) })
    }
  }
}
