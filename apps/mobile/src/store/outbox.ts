import { atom } from 'nanostores'
import { Api, HttpError, sessionPath } from '../lib/api'
import type { AccountStorage } from '../lib/storage'
import type { Draft, Operation, PendingCommand, Receipt } from '../lib/protocol'
import { emptyDraft, remainingDraft } from '../lib/models'
const receiptProgress: Record<Receipt['state'], number> = {
  accepted: 0,
  dispatched: 1,
  received: 2,
  delivery_uncertain: 3,
  acknowledged: 4,
  response_submitted: 4,
  completed: 5,
  failed: 5
}
export function blocksNewCommand(pending: PendingCommand | null): boolean {
  return (
    !!pending &&
    (!pending.receipt || !['acknowledged', 'completed', 'failed', 'response_submitted'].includes(pending.receipt.state))
  )
}
export class Outbox {
  state = atom<PendingCommand | null>(null)
  history = atom<PendingCommand[]>([])
  busy = atom(false)
  private receiptSequence = 0
  private appliedReceiptSequence = 0
  constructor(
    private api: Api,
    private storage: AccountStorage
  ) {
    const saved = storage.read<PendingCommand | null>('outbox', null)
    this.state.set(saved ? { ...saved, uncertain: !saved.receipt || saved.uncertain } : null)
    this.history.set(storage.read<PendingCommand[]>('receipts', []).slice(-10))
  }
  private save(value: PendingCommand | null) {
    this.api.assertActive()
    this.storage.write('outbox', value)
    this.state.set(value)
  }
  private applyReceipt(requestId: string, receipt: Receipt, sequence: number) {
    const latest = this.state.get()
    if (!latest || latest.command.request_id !== requestId) return
    const previous = latest.receipt
    if (previous) {
      if (['completed', 'failed'].includes(previous.state)) return
      const progress = receiptProgress[receipt.state] - receiptProgress[previous.state]
      if (
        progress < 0 ||
        (progress === 0 && (previous.state !== receipt.state || sequence < this.appliedReceiptSequence))
      )
        return
    }
    this.appliedReceiptSequence = sequence
    this.save({ ...latest, receipt, uncertain: receipt.state === 'delivery_uncertain', error: undefined })
  }
  markDraftSettled() {
    const current = this.state.get()
    if (current) this.save({ ...current, draftSettled: true })
  }
  dismiss(reviewed = false) {
    if (!reviewed && blocksNewCommand(this.state.get())) return
    this.archive()
  }
  private archive() {
    const current = this.state.get()
    if (!current) return
    if (
      current.submitted &&
      !current.draftSettled &&
      current.receipt &&
      !['failed', 'delivery_uncertain'].includes(current.receipt.state)
    ) {
      const draft = this.storage.read(`draft:${current.session_id}`, emptyDraft())
      this.storage.write(`draft:${current.session_id}`, remainingDraft(draft, current.submitted))
    }
    const history = [
      ...this.history.get().filter(item => item.command.request_id !== current.command.request_id),
      current
    ].slice(-10)
    this.storage.write('receipts', history)
    this.history.set(history)
    this.save(null)
  }
  close() {
    this.state.set(null)
    this.history.set([])
    this.busy.set(false)
  }
  async submit(session: string, operation: Operation, payload: Record<string, unknown>, submitted?: Draft) {
    if (blocksNewCommand(this.state.get()) || this.busy.get()) throw new Error('请先核对上一条操作的回执')
    this.archive()
    this.save(
      structuredClone({
        session_id: session,
        command: { request_id: crypto.randomUUID(), operation, payload },
        submitted
      })
    )
    await this.dispatch()
  }
  private async dispatch() {
    const current = this.state.get()!
    const sequence = ++this.receiptSequence
    this.busy.set(true)
    try {
      const receipt = await this.api.post<Receipt>(`${sessionPath(current.session_id)}/commands`, current.command)
      this.applyReceipt(current.command.request_id, receipt, sequence)
    } catch (error) {
      this.api.assertActive()
      const latest = this.state.get()
      if (!latest || latest.command.request_id !== current.command.request_id || latest.receipt) return
      const definite =
        error instanceof HttpError && [400, 401, 403, 404, 409, 410, 413, 415, 422].includes(error.status)
      this.save({
        ...latest,
        uncertain: !definite,
        error: error instanceof Error ? error.message : '发送失败',
        receipt: definite
          ? { request_id: current.command.request_id, state: 'failed', error: String(error) }
          : undefined
      })
    } finally {
      this.busy.set(false)
    }
  }
  async check(): Promise<boolean> {
    const current = this.state.get()
    if (!current) return false
    const sequence = ++this.receiptSequence
    try {
      const receipt = await this.api.request<Receipt>(
        `/api/remote/commands/${encodeURIComponent(current.command.request_id)}`
      )
      this.applyReceipt(current.command.request_id, receipt, sequence)
      return true
    } catch (error) {
      this.api.assertActive()
      if (this.state.get()?.command.request_id !== current.command.request_id) return true
      if (error instanceof HttpError && error.status === 404) return false
      throw error
    }
  }
  async retry() {
    if (this.busy.get() || !this.state.get()) return
    const requestId = this.state.get()!.command.request_id
    this.busy.set(true)
    try {
      if (!(await this.check()) && this.state.get()?.command.request_id === requestId && !this.state.get()?.receipt)
        await this.dispatch()
    } finally {
      this.busy.set(false)
    }
  }
}
