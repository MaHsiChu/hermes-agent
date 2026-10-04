import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useStore } from '@nanostores/react'
import type { Runtime } from '../store/runtime'
import type { SessionModel } from '../store/session'
import type { Detail, Operation, Pending } from '../lib/protocol'
import { canAnswer, dateLabel, statusLabel } from '../lib/models'
import { sessionPath } from '../lib/api'
import { Composer, ReceiptCard, ReceiptHistory } from '../components/Composer'
import { PendingCard } from '../components/PendingCard'
import { Transcript } from '../components/Transcript'
import { captureReadingPosition, restoreReadingPosition, type ReadingPosition } from '../lib/reading-position'
import { localizedReason } from '../lib/reasons'
import { blocksNewCommand } from '../store/outbox'

export function Conversation({ runtime, model }: { runtime: Runtime; model: SessionModel }) {
  const state = useStore(model.state),
    live = useStore(model.live.state),
    connection = useStore(runtime.connection),
    pendingCommand = useStore(runtime.outbox.state)
  const [error, setError] = useState(''),
    [now, setNow] = useState(Date.now() / 1000)
  const body = useRef<HTMLDivElement>(null),
    reading = useRef<ReadingPosition | null>(null),
    positioned = useRef(false)
  useLayoutEffect(() => {
    if (state.loading || !state.detail || !body.current) return
    if (reading.current) {
      restoreReadingPosition(body.current, reading.current)
      reading.current = null
    } else if (!positioned.current) {
      positioned.current = true
      window.scrollTo({ top: document.documentElement.scrollHeight, behavior: 'instant' })
    }
  }, [state.messages, state.loading, state.detail])
  const more = () => {
    if (body.current) reading.current = captureReadingPosition(body.current)
    void model.more()
  }
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now() / 1000), 1000)
    return () => clearInterval(timer)
  }, [])
  const detail = state.detail
  const online = !!detail?.online && connection === '实时连接' && !state.error
  const reply = async (pending: Pending, payload: Record<string, unknown>) => {
    const fresh = await runtime.api.request<Detail>(sessionPath(model.id))
    const actual = fresh.pending_requests.find(value => value.id === pending.id)
    if (
      !actual ||
      !fresh.online ||
      !canAnswer(actual, fresh.capabilities[actual.method as Operation], Date.now() / 1000)
    ) {
      await model.refresh()
      throw new Error('请求已失效或不可远程回答，请查看最新状态。')
    }
    if (actual.method === 'approval' && !actual.params.choices?.includes(payload.choice))
      throw new Error('此选项已不再有效。')
    await runtime.outbox.submit(model.id, actual.method as Operation, payload)
    await model.refresh()
  }
  return (
    <main className="conversation">
      <header className="conversation-heading">
        <button className="back" onClick={() => runtime.open(null)}>
          ‹ 会话
        </button>
        <h1>{detail?.session.title || '加载会话…'}</h1>
        <div className="heading-meta">
          <span className="badge">{statusLabel[detail?.session.status || 'unknown'] || detail?.session.status}</span>
          <span>
            {detail?.session.engine} · {detail?.session.profile}
          </span>
        </div>
      </header>
      {detail && (
        <section className={`sync-strip ${!detail.online ? 'offline' : ''}`}>
          <strong>{detail.online ? '电脑已连接' : '电脑离线 · 显示中继已同步的历史'}</strong>
          <span>最后同步 {dateLabel(detail.sync.last_synced)}</span>
          {!detail.sync.complete && (
            <span>历史仍在同步{detail.sync.total ? ` · ${detail.sync.offset || 0} / ${detail.sync.total}` : ''}</span>
          )}
          {detail.sync.error && <span className="danger-text">{detail.sync.error}</span>}
        </section>
      )}
      <div className="conversation-body" ref={body}>
        {detail && (
          <details className="session-details">
            <summary>会话详情与可用操作</summary>
            <dl>
              <dt>来源</dt>
              <dd>{detail.session.backend_id}</dd>
              <dt>工作目录</dt>
              <dd>{detail.session.cwd || '未提供'}</dd>
              <dt>原会话 ID</dt>
              <dd>{detail.session.native_session_id}</dd>
              <dt>设备 ID</dt>
              <dd>{detail.session.device_id}</dd>
              <dt>最近更新</dt>
              <dd>{dateLabel(detail.session.updated_at)}</dd>
              <dt>归档</dt>
              <dd>{detail.session.archived ? '已归档' : '未归档'}</dd>
            </dl>
            {!!detail.session.source && <pre>{JSON.stringify(detail.session.source, null, 2)}</pre>}
            {Object.entries(detail.capabilities).map(([name, capability]) => (
              <p key={name}>
                <strong>
                  {(
                    {
                      history: '历史',
                      send: '继续会话',
                      queue: '排队',
                      steer: '引导',
                      interrupt: '停止',
                      approval: '审批',
                      clarify: '回答',
                      attachments: '图片'
                    } as Record<string, string>
                  )[name] || name}
                </strong>
                ：{{ supported: '支持', unavailable: '暂不可用', unsupported: '不支持' }[capability.status]}{' '}
                {localizedReason(capability.reason)}
              </p>
            ))}
          </details>
        )}
        {state.error && (
          <p className="error" role="alert">
            {state.error}
            <button onClick={() => void model.refresh()}>重新同步</button>
          </p>
        )}
        <ReceiptCard runtime={runtime} />
        <ReceiptHistory runtime={runtime} />
        <div id="pending-requests">
          {detail?.pending_requests.map(pending => (
            <PendingCard
              key={pending.id}
              pending={pending}
              capability={detail.capabilities[pending.method as Operation]}
              online={online}
              busy={blocksNewCommand(pendingCommand)}
              now={now}
              submit={payload => reply(pending, payload)}
            />
          ))}
        </div>
        {state.next && (
          <button className="load-more" disabled={state.loading} onClick={more}>
            加载更早消息（已加载 {state.messages.filter(row => !row.deleted).length} 条）
          </button>
        )}
        <Transcript session={model.id} messages={state.messages} />
        {(live.status || live.text || live.reasoning) && (
          <section className="live-output" aria-label="实时输出">
            <p className="muted" role="status">
              {live.status || '实时输出 · 等待写入会话记录'}
            </p>
            {live.reasoning && (
              <details className="output">
                <summary>思考过程</summary>
                <pre>{live.reasoning}</pre>
              </details>
            )}
            {live.text && (
              <Transcript
                session={model.id}
                messages={[live.text].map((text, index) => ({
                  id: `live-${index}`,
                  ordinal: index,
                  revision: 1,
                  role: 'assistant',
                  content: text
                }))}
              />
            )}
            {live.limited && <p className="muted">实时预览已达内存上限；完整输出写入后会显示在会话记录中。</p>}
          </section>
        )}
        {state.loading && (
          <p role="status" className="muted">
            正在同步会话…
          </p>
        )}
        {detail && (
          <div className="stop-row">
            <span className="muted">停止请求由原执行端处理</span>
            <button
              className="danger"
              disabled={
                !online || detail.capabilities.interrupt?.status !== 'supported' || blocksNewCommand(pendingCommand)
              }
              onClick={() => {
                void runtime.outbox.submit(model.id, 'interrupt', {}).catch(error => setError(String(error)))
              }}
            >
              请求停止
            </button>
          </div>
        )}
        {error && (
          <p role="alert" className="danger-text">
            {error}
          </p>
        )}
      </div>
      <Composer key={model.id} runtime={runtime} model={model} />
    </main>
  )
}
