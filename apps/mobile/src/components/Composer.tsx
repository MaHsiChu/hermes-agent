import { localizedReason } from '../lib/reasons'
import { useState } from 'react'
import { useStore } from '@nanostores/react'
import type { Runtime } from '../store/runtime'
import type { SessionModel } from '../store/session'
import type { Operation } from '../lib/protocol'
import { operationLabel, receiptLabel } from '../lib/models'
import { sessionPath } from '../lib/api'
import { blocksNewCommand } from '../store/outbox'

export function ReceiptHistory({ runtime }: { runtime: Runtime }) {
  const history = useStore(runtime.outbox.history)
  const selected = useStore(runtime.selected)
  const visible = history.filter(item => !selected || item.session_id === selected.id)
  if (!visible.length) return null
  return (
    <details className="receipt-history">
      <summary>近期操作回执（{visible.length}）</summary>
      {[...visible].reverse().map(item => (
        <details key={item.command.request_id}>
          <summary>
            {operationLabel[item.command.operation]} · {item.receipt ? receiptLabel[item.receipt.state] : '结果待核对'}
          </summary>
          <code>{item.command.request_id}</code>
          <pre>{JSON.stringify(item.command.payload, null, 2)}</pre>
        </details>
      ))}
    </details>
  )
}

export function ReceiptCard({ runtime }: { runtime: Runtime }) {
  const pending = useStore(runtime.outbox.state),
    busy = useStore(runtime.outbox.busy),
    selected = useStore(runtime.selected)
  const [error, setError] = useState('')
  if (!pending) return null
  const state = pending.receipt?.state
  const check = async (retry = false) => {
    try {
      setError('')
      if (retry) await runtime.outbox.retry()
      else await runtime.outbox.check()
      runtime.selected.get()?.settleDraft()
    } catch (error) {
      setError(String(error))
    }
  }
  return (
    <section className="receipt" aria-live="polite">
      <strong>
        {operationLabel[pending.command.operation]} · {state ? receiptLabel[state] : '发送结果待核对'}
      </strong>
      {pending.command.operation === 'interrupt' && !['completed', 'failed'].includes(state || '') && (
        <p>
          {state === 'acknowledged'
            ? '停止请求已送达。请查看会话状态和电脑上的结果；此回执不确认该请求已完成停止。'
            : '停止请求送达情况待核对。会话状态仍以电脑为准。'}
        </p>
      )}
      <p>
        {pending.receipt?.error ||
          pending.error ||
          (pending.uncertain
            ? '请查看原会话和回执，避免重复执行。'
            : '回执表示操作送达情况，任务执行状态显示在会话标题下。')}
      </p>
      <details>
        <summary>操作详情</summary>
        <code>{pending.command.request_id}</code>
        <pre>{JSON.stringify(pending.command.payload, null, 2)}</pre>
      </details>
      <div className="button-row">
        <button disabled={busy} onClick={() => void check()}>
          查询回执
        </button>
        {pending.uncertain && !state && (
          <button disabled={busy} onClick={() => void check(true)}>
            核对后重试原请求
          </button>
        )}
        {state && ['completed', 'failed', 'acknowledged', 'response_submitted'].includes(state) && (
          <button onClick={() => runtime.outbox.dismiss()}>收起回执</button>
        )}
        {pending.session_id !== selected?.id && (
          <button onClick={() => runtime.open(pending.session_id)}>查看对应会话</button>
        )}
      </div>
      {state === 'delivery_uncertain' && (
        <label className="choice">
          <input
            type="checkbox"
            onChange={event => {
              if (event.target.checked) runtime.outbox.dismiss(true)
            }}
          />
          我已在电脑核对结果，允许手动开始新操作
        </label>
      )}
      {error && <p role="alert">{error}</p>}
    </section>
  )
}
export function Composer({ runtime, model }: { runtime: Runtime; model: SessionModel }) {
  const draft = useStore(model.draft),
    state = useStore(model.state),
    pending = useStore(runtime.outbox.state),
    connection = useStore(runtime.connection)
  const [operation, setOperation] = useState<Operation>('send'),
    [error, setError] = useState(''),
    [uploading, setUploading] = useState(false)
  const capability = state.detail?.capabilities[operation]
  const online = connection === '实时连接' && state.detail?.online && !state.error
  const canSend =
    online &&
    capability?.status === 'supported' &&
    !blocksNewCommand(pending) &&
    !uploading &&
    (draft.text.trim() || draft.attachment_ids.length) &&
    !(operation === 'steer' && draft.attachment_ids.length)
  const uploadCapability = state.detail?.capabilities.attachments
  const send = async () => {
    if (!canSend) return
    try {
      setError('')
      const submitted = structuredClone(draft)
      await runtime.outbox.submit(
        model.id,
        operation,
        {
          text: submitted.text,
          ...(submitted.attachment_ids.length ? { attachment_ids: submitted.attachment_ids } : {})
        },
        submitted
      )
      model.settleDraft()
    } catch (error) {
      setError(String(error))
    }
  }
  const upload = async (file?: File) => {
    if (!file) return
    if (file.size > 8 * 1024 * 1024 || !['image/png', 'image/jpeg', 'image/webp', 'image/gif'].includes(file.type)) {
      setError('请选择 8 MiB 以内的 PNG、JPEG、WebP 或 GIF 图片。')
      return
    }
    setUploading(true)
    try {
      setError('')
      const body = new FormData()
      body.append('file', file)
      const result = await runtime.api.request<{ id: string }>(`${sessionPath(model.id)}/attachments`, {
        method: 'POST',
        body
      })
      model.edit({ attachment_ids: [...model.draft.get().attachment_ids, result.id] })
    } catch (error) {
      setError(String(error))
    } finally {
      setUploading(false)
    }
  }
  return (
    <form
      className="composer"
      onSubmit={event => {
        event.preventDefault()
        void send()
      }}
    >
      {blocksNewCommand(pending) && (
        <button
          className="pending-shortcut"
          type="button"
          onClick={() => document.querySelector('.receipt')?.scrollIntoView({ block: 'center', behavior: 'instant' })}
        >
          上一条操作待核对 · 查看回执 ↑
        </button>
      )}
      {!!state.detail?.pending_requests.length && (
        <button
          type="button"
          className="pending-shortcut"
          onClick={() =>
            document.getElementById('pending-requests')?.scrollIntoView({ block: 'start', behavior: 'instant' })
          }
        >
          查看 {state.detail.pending_requests.length} 个待处理请求 ↑
        </button>
      )}
      <div className="composer-top">
        <label>
          发送方式
          <select value={operation} onChange={event => setOperation(event.target.value as Operation)}>
            {(['send', 'queue', 'steer'] as Operation[]).map(value => (
              <option value={value} key={value}>
                {operationLabel[value]}
              </option>
            ))}
          </select>
        </label>
        <span className="muted">草稿自动保存于本机</span>
      </div>
      <textarea
        aria-label="消息草稿"
        placeholder={online ? '继续这段会话…' : '可以先写草稿，恢复连接后由你发送'}
        value={draft.text}
        onChange={event => {
          try {
            model.edit({ text: event.target.value })
            setError('')
          } catch {
            setError('本机存储已满，草稿未能保存。请复制文字后清理空间。')
          }
        }}
        rows={3}
        maxLength={200000}
      />
      {draft.attachment_ids.length > 0 && (
        <div className="attachment-list">
          {draft.attachment_ids.map((id, index) => (
            <button
              type="button"
              key={id}
              onClick={() => model.edit({ attachment_ids: draft.attachment_ids.filter(item => item !== id) })}
            >
              图片 {index + 1} ×
            </button>
          ))}
        </div>
      )}
      <div className="composer-actions">
        <label className={`upload-button ${uploadCapability?.status !== 'supported' ? 'disabled' : ''}`}>
          ＋ 图片
          <input
            aria-label="添加图片"
            type="file"
            accept="image/png,image/jpeg,image/webp,image/gif"
            disabled={
              !online ||
              uploadCapability?.status !== 'supported' ||
              uploading ||
              draft.attachment_ids.length >= 5 ||
              operation === 'steer'
            }
            onChange={event => {
              void upload(event.target.files?.[0])
              event.target.value = ''
            }}
          />
        </label>
        <button className="primary" type="submit" disabled={!canSend}>
          {uploading ? '上传中…' : operationLabel[operation]}
        </button>
      </div>
      <p className="composer-help">
        {!online
          ? '电脑或网络离线：不会自动发送草稿。'
          : capability?.status !== 'supported'
            ? localizedReason(capability?.reason) || '此来源不支持该操作。'
            : operation === 'queue'
              ? '明确排队下一轮，不会变成当前执行的引导消息。'
              : operation === 'steer'
                ? '引导当前执行；此操作不支持图片。'
                : '在电脑上继续原会话。'}{' '}
        {uploadCapability?.status !== 'supported'
          ? `图片：${localizedReason(uploadCapability?.reason) || '当前来源不可用'}`
          : ''}
      </p>
      {error && (
        <p className="danger-text" role="alert">
          {error}
        </p>
      )}
    </form>
  )
}
