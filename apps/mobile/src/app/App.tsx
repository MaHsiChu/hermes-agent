import { useEffect, useState } from 'react'
import { useStore } from '@nanostores/react'
import { $auth, bootstrap, logout, pairingId, type Runtime } from '../store/runtime'
import { Catalog } from './Catalog'
import { Conversation } from './Conversation'
import { PairingPage } from './Pairing'

function Workspace({ runtime }: { runtime: Runtime }) {
  const selected = useStore(runtime.selected),
    connection = useStore(runtime.connection)
  const [pairing, setPairing] = useState(pairingId)
  useEffect(() => {
    const foreground = () => {
      if (document.visibilityState === 'visible') runtime.connect()
    }
    const online = () => runtime.connect()
    const offline = () => runtime.connection.set('网络离线 · 草稿仅保存在本机')
    document.addEventListener('visibilitychange', foreground)
    window.addEventListener('online', online)
    window.addEventListener('offline', offline)
    return () => {
      document.removeEventListener('visibilitychange', foreground)
      window.removeEventListener('online', online)
      window.removeEventListener('offline', offline)
    }
  }, [runtime])
  return (
    <>
      <header className="app-header">
        <a
          className="brand"
          href="/"
          onClick={event => {
            event.preventDefault()
            runtime.open(null)
            setPairing(null)
          }}
        >
          <span className="brand-mark">h</span>
          <span>
            hermes<small>远程会话</small>
          </span>
        </a>
        <div className="account">
          <span>{runtime.user.name}</span>
          <button className="text-button" onClick={() => void logout()}>
            退出
          </button>
        </div>
      </header>
      <div className={`connection ${connection === '实时连接' ? 'connected' : ''}`} role="status">
        <span />
        {connection}
      </div>
      {pairing ? (
        <PairingPage runtime={runtime} id={pairing} done={() => setPairing(null)} />
      ) : selected ? (
        <Conversation key={selected.id} runtime={runtime} model={selected} />
      ) : (
        <Catalog runtime={runtime} />
      )}
    </>
  )
}
export function App() {
  const auth = useStore($auth)
  useEffect(() => {
    pairingId()
    void bootstrap()
  }, [])
  if (auth.runtime) return <Workspace key={auth.runtime.user.id} runtime={auth.runtime} />
  return (
    <main className="login">
      <div className="login-brand">
        <span className="brand-mark">h</span> hermes <span>remote</span>
      </div>
      <div className="login-illustration" aria-hidden="true">
        <div className="computer-shape">
          <span>你的电脑</span>
          <i />
        </div>
        <div className="connection-line">··········</div>
        <div className="phone-shape">
          <i />
          <span>随你而行</span>
        </div>
      </div>
      <p className="eyebrow">会话连续，工作随行</p>
      <h1>
        离开电脑，
        <br />
        继续你的思路。
      </h1>
      <p className="login-description">
        在手机上查看 Hermes、Codex 和 Claude 的原始会话。确认进展、回复问题，把执行留给你的电脑。
      </p>
      <div className="login-actions">
        {auth.loading ? (
          <p role="status">正在确认登录状态…</p>
        ) : auth.loginUrl ? (
          <a className="primary button" href={auth.loginUrl}>
            安全登录 <span>↗</span>
          </a>
        ) : (
          <p className="muted">登录服务尚未配置。请联系部署者完成身份提供方设置。</p>
        )}
        {auth.error && (
          <p className="error" role="alert">
            {auth.error}
          </p>
        )}
        {!auth.loading && (
          <button className="text-button" onClick={() => void bootstrap()}>
            重新检查连接
          </button>
        )}
      </div>
      <div className="login-note">
        <span>✓</span>
        <p>登录后，仍需在电脑上发起配对，并由你明确选择共享来源。</p>
      </div>
      <footer>你的账号 · 你的电脑 · 原来的会话</footer>
    </main>
  )
}
