import { useEffect, useState } from 'react'
import type { Runtime } from '../store/runtime'
import type { Pairing } from '../lib/protocol'

export function PairingPage({ runtime, id, done }: { runtime: Runtime; id: string; done: () => void }) {
  const [pairing, setPairing] = useState<Pairing | null>(null),
    [selected, setSelected] = useState<number[]>([]),
    [code, setCode] = useState(''),
    [error, setError] = useState(''),
    [busy, setBusy] = useState(false),
    [approved, setApproved] = useState(false)
  useEffect(() => {
    let active = true
    void runtime.api
      .request<Pairing>(`/api/remote/pairings/${encodeURIComponent(id)}`)
      .then(value => {
        if (active) setPairing(value)
      })
      .catch(error => {
        if (active) setError(String(error))
      })
    return () => {
      active = false
    }
  }, [id, runtime])
  const approve = async () => {
    if (!pairing || !selected.length || !code.trim()) return
    setBusy(true)
    try {
      setError('')
      await runtime.api.post(`/api/remote/pairings/${encodeURIComponent(id)}/approve`, {
        user_code: code.trim(),
        allowed_sources: selected.map(index => pairing.sources[index])
      })
      setApproved(true)
      sessionStorage.removeItem('hermes.remote.pairing')
      history.replaceState(null, '', '/')
      await runtime.list()
    } catch (error) {
      setError(String(error))
    } finally {
      setBusy(false)
    }
  }
  return (
    <main className="pairing-page">
      <p className="eyebrow">连接你的电脑</p>
      <h1>{approved ? '授权已确认' : '选择要共享的来源'}</h1>
      {approved ? (
        <>
          <p>回到电脑完成连接。你选择的来源会同步到此账号；执行仍发生在电脑上。</p>
          <button className="primary" onClick={done}>
            查看会话
          </button>
        </>
      ) : (
        <>
          <p>只连接你信任的电脑。共享后，此账号可查看所选来源的会话，并使用执行端支持的继续、停止与审批操作。</p>
          {pairing && (
            <form
              onSubmit={event => {
                event.preventDefault()
                void approve()
              }}
            >
              <section className="device-card">
                <h2>{pairing.name}</h2>
                <p className="muted">来源默认不选中，请逐项核对。</p>
                {pairing.sources.map((source, index) => (
                  <label className="pair-source" key={JSON.stringify(source)}>
                    <input
                      type="checkbox"
                      checked={selected.includes(index)}
                      onChange={event =>
                        setSelected(
                          event.target.checked ? [...selected, index] : selected.filter(value => value !== index)
                        )
                      }
                    />
                    <span>
                      <strong>
                        {source.engine} · {source.profile}
                      </strong>
                      <small>{source.backend_id}</small>
                    </span>
                  </label>
                ))}
              </section>
              <label className="code-label">
                电脑上显示的配对码
                <input
                  autoComplete="off"
                  autoCapitalize="characters"
                  required
                  value={code}
                  onChange={event => setCode(event.target.value)}
                  placeholder="输入配对码"
                />
              </label>
              <button
                className="primary"
                type="submit"
                disabled={busy || !selected.length || !code.trim() || pairing.expires_at <= Date.now() / 1000}
              >
                {busy ? '正在授权…' : `授权 ${selected.length} 个来源`}
              </button>
            </form>
          )}
          {!pairing && !error && <p role="status">正在读取配对请求…</p>}
          <button
            className="text-button"
            onClick={() => {
              sessionStorage.removeItem('hermes.remote.pairing')
              history.replaceState(null, '', '/')
              done()
            }}
          >
            取消配对
          </button>
        </>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </main>
  )
}
