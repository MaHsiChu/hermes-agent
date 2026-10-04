import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { Transcript } from './Transcript'
import { PendingCard } from './PendingCard'
import { ReceiptCard } from './Composer'
import { Runtime } from '../store/runtime'
import { SessionModel } from '../store/session'

it('an acknowledged stop directs users to authoritative session state without claiming their stop completed', () => {
  const runtime = new Runtime({ id: 'receipt-user', name: 'User' }, 'csrf')
  runtime.outbox.state.set({
    session_id: 's',
    command: { request_id: 'stop', operation: 'interrupt', payload: {} },
    receipt: { request_id: 'stop', state: 'acknowledged' },
    uncertain: false
  })
  const model = new SessionModel('s', runtime.api, runtime.storage, runtime.outbox)
  runtime.selected.set(model)
  render(<ReceiptCard runtime={runtime} />)
  expect(screen.getByText(/停止请求已送达/)).toBeTruthy()
  expect(screen.queryByText(/等待执行端确认/)).toBeNull()
  expect(screen.queryByText(/已确认会话停止/)).toBeNull()
  runtime.close()
})

afterEach(cleanup)
it('preserves locked batch answers and serializes multi-select like the native renderer', () => {
  const submit = vi.fn(async () => {})
  render(
    <PendingCard
      pending={{
        id: 'batch',
        method: 'clarify',
        params: {
          questions: [
            { qid: 'locked', question: 'Existing answer' },
            { qid: 'multi', question: 'Choose environments', choices: ['staging', 'production'], multi_select: true }
          ],
          answers: { locked: 'already decided' }
        }
      }}
      capability={{ status: 'supported' }}
      online
      busy={false}
      submit={submit}
    />
  )
  fireEvent.click(screen.getByLabelText('staging'))
  fireEvent.click(screen.getByLabelText('production'))
  fireEvent.click(screen.getByRole('button', { name: '提交回答' }))
  expect(submit).toHaveBeenCalledWith({
    pending_request_id: 'batch',
    answers: { locked: 'already decided', multi: JSON.stringify(['staging', 'production']) }
  })
})
it('renders safe markdown, complete collapsed outputs and stable message updates', () => {
  const long = 'line\n'.repeat(1000) + 'END OF OUTPUT'
  const { container, rerender } = render(
    <Transcript
      session="s"
      messages={[
        {
          id: 'm',
          revision: 1,
          ordinal: 1,
          content: '<script>alert(1)</script>**hello** ![tracking](https://evil.invalid/x)'
        },
        { id: 'tool', revision: 1, ordinal: 2, role: 'tool', content: long }
      ]}
    />
  )
  expect(container.querySelector('script')).toBeNull()
  expect(container.querySelector('img')).toBeNull()
  expect(container.querySelector('strong')?.textContent).toBeTruthy()
  expect(container.textContent).toContain('END OF OUTPUT')
  const original = container.querySelector('[data-message-id="m"]')
  rerender(
    <Transcript
      session="s"
      messages={[
        { id: 'm', revision: 2, ordinal: 1, content: 'updated' },
        { id: 'tool', revision: 2, ordinal: 2, deleted: true }
      ]}
    />
  )
  expect(container.querySelector('[data-message-id="m"]')).toBe(original)
  expect(container.textContent).not.toContain('END OF OUTPUT')
})
it('disables stale approval and submits only a current offered choice', () => {
  const submit = vi.fn(async () => {})
  const pending = {
    id: 'p',
    method: 'approval',
    params: { command: 'git status', choices: ['once', 'deny'], expires_at: 100 }
  }
  const { rerender } = render(
    <PendingCard pending={pending} capability={{ status: 'supported' }} online busy={false} now={101} submit={submit} />
  )
  fireEvent.click(screen.getByText('允许一次'))
  expect(submit).not.toHaveBeenCalled()
  rerender(
    <PendingCard pending={pending} capability={{ status: 'supported' }} online busy={false} now={99} submit={submit} />
  )
  fireEvent.click(screen.getByText('允许一次'))
  expect(submit).toHaveBeenCalledWith({ pending_request_id: 'p', choice: 'once' })
  expect(screen.queryByText('始终允许')).toBeNull()
})
