import { useState } from 'react'
import { useStore } from '@nanostores/react'
import type { Runtime } from '../store/runtime'
import { dateLabel, statusLabel } from '../lib/models'
import { ReceiptCard, ReceiptHistory } from '../components/Composer'

export function Catalog({ runtime }: { runtime: Runtime }) {
  const catalog = useStore(runtime.catalog)
  const [view, setView] = useState<'sessions' | 'devices'>('sessions'),
    [revoke, setRevoke] = useState<string | null>(null),
    [error, setError] = useState('')
  const remove = async (id: string) => {
    try {
      setError('')
      await runtime.api.request(`/api/remote/devices/${encodeURIComponent(id)}`, { method: 'DELETE' })
      setRevoke(null)
      await runtime.list()
      runtime.connect()
    } catch (error) {
      setError(String(error))
    }
  }
  return (
    <main className="catalog">
      <div className="page-heading">
        <div>
          <p className="eyebrow">WORK, WITH YOU</p>
          <h1>{view === 'sessions' ? '你的会话' : '已连接的电脑'}</h1>
          <p className="muted">原会话留在电脑上，随时查看与继续。</p>
        </div>
        <button aria-label="刷新列表" className="icon-button" onClick={() => void runtime.list()}>
          ↻
        </button>
      </div>
      <nav className="tabs" aria-label="工作区">
        <button aria-current={view === 'sessions' ? 'page' : undefined} onClick={() => setView('sessions')}>
          会话
        </button>
        <button aria-current={view === 'devices' ? 'page' : undefined} onClick={() => setView('devices')}>
          设备 <span>{catalog.devices.length}</span>
        </button>
      </nav>
      <ReceiptCard runtime={runtime} />
      <ReceiptHistory runtime={runtime} />
      {catalog.error && (
        <p className="error" role="alert">
          {catalog.error}
        </p>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {view === 'sessions' ? (
        <>
          <form
            className="search"
            onSubmit={event => {
              event.preventDefault()
              void runtime.list()
            }}
          >
            <span aria-hidden="true">⌕</span>
            <input
              aria-label="搜索会话"
              placeholder="搜索会话标题"
              value={catalog.filters.q}
              onChange={event => runtime.filter({ q: event.target.value })}
            />
          </form>
          <div className="filters">
            <label>
              来源
              <select value={catalog.filters.engine} onChange={event => runtime.filter({ engine: event.target.value })}>
                <option value="">全部来源</option>
                <option value="hermes">Hermes</option>
                <option value="codex">Codex</option>
                <option value="claude">Claude</option>
              </select>
            </label>
            <label>
              状态
              <select value={catalog.filters.status} onChange={event => runtime.filter({ status: event.target.value })}>
                <option value="">全部状态</option>
                {Object.entries(statusLabel).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <details className="advanced-filters">
            <summary>配置、设备与归档筛选</summary>
            <div className="filters">
              <label>
                配置
                <input
                  aria-label="配置筛选"
                  placeholder="输入 profile 名称"
                  value={catalog.filters.profile}
                  onChange={event => runtime.filter({ profile: event.target.value })}
                />
              </label>
              <label>
                设备
                <select
                  value={catalog.filters.device_id}
                  onChange={event => runtime.filter({ device_id: event.target.value })}
                >
                  <option value="">全部设备</option>
                  {catalog.devices.map(device => (
                    <option key={device.id} value={device.id}>
                      {device.name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                归档
                <select
                  value={catalog.filters.archived}
                  onChange={event => runtime.filter({ archived: event.target.value })}
                >
                  <option value="exclude">未归档</option>
                  <option value="only">仅归档</option>
                  <option value="include">全部</option>
                </select>
              </label>
            </div>
          </details>
          <div className="list-label">
            <span>
              {catalog.sessions.length} 段会话{catalog.next ? ' · 还有更多' : ''}
            </span>
            <span>按最近更新排序</span>
          </div>
          <div className="session-list">
            {catalog.sessions.map(session => (
              <button className="session-card" key={session.id} onClick={() => runtime.open(session.id)}>
                <div className="card-top">
                  <span className={`engine engine-${session.engine}`}>
                    {session.engine === 'hermes' ? 'H' : session.engine === 'codex' ? 'C' : 'A'}
                  </span>
                  <span className="source-label">
                    {session.engine} <span> / {session.profile}</span>
                  </span>
                  <span className="badge">{statusLabel[session.status || 'unknown'] || session.status}</span>
                </div>
                <h2>{session.title || '未命名会话'}</h2>
                <div className="card-footer">
                  <span className={session.online ? 'online-dot' : 'offline-dot'}>
                    {session.online ? '电脑在线' : '电脑离线'}
                  </span>
                  <time>{dateLabel(session.updated_at)}</time>
                  <span aria-hidden="true">↗</span>
                </div>
              </button>
            ))}
          </div>
          {!catalog.loading && !catalog.sessions.length && (
            <div className="empty">
              <div className="empty-mark">⌁</div>
              <h2>会话会在这里汇合</h2>
              <p>
                {catalog.devices.length
                  ? '没有符合筛选条件的会话。检查电脑上的来源共享与同步状态，或调整筛选。'
                  : '先在电脑上启动 Bridge 配对，再扫描或打开配对链接。只有你明确选择的来源会被同步。'}
              </p>
              <button onClick={() => setView('devices')}>查看设备</button>
            </div>
          )}
          {catalog.next && (
            <button className="load-more" disabled={catalog.loading} onClick={() => void runtime.list(true)}>
              加载更多会话
            </button>
          )}
        </>
      ) : (
        <div className="device-list">
          {catalog.devices.map(device => (
            <section className="device-card" key={device.id}>
              <div className="card-top">
                <span className="device-icon">▱</span>
                <h2>{device.name}</h2>
                <span className="badge">{device.online ? '已连接' : '离线'}</span>
              </div>
              <p className="muted">最后连接 {dateLabel(device.last_seen)}</p>
              <details>
                <summary>已授权来源（{device.backends.length}）</summary>
                {device.backends.map(source => (
                  <p key={JSON.stringify(source)}>
                    {source.engine} · {source.profile}
                    <br />
                    <small>{source.backend_id}</small>
                  </p>
                ))}
              </details>
              {revoke === device.id ? (
                <div className="revoke">
                  <p>撤销后，此电脑立即断开，已同步会话将无法访问。</p>
                  <button className="danger" onClick={() => void remove(device.id)}>
                    确认撤销此设备
                  </button>
                  <button onClick={() => setRevoke(null)}>取消</button>
                </div>
              ) : (
                <button className="text-button danger-text" onClick={() => setRevoke(device.id)}>
                  撤销授权
                </button>
              )}
            </section>
          ))}
          {!catalog.devices.length && (
            <div className="empty">
              <h2>尚未连接电脑</h2>
              <p>请在电脑端发起配对。在手机上核对设备名称、来源及配对码后，才能共享会话。</p>
            </div>
          )}
        </div>
      )}
      {catalog.loading && (
        <p className="loading" role="status">
          正在加载…
        </p>
      )}
      <footer className="page-footer">执行始终发生在你授权的电脑上</footer>
    </main>
  )
}
