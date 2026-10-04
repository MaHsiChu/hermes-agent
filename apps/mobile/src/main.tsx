import { createRoot } from 'react-dom/client'
import { App } from './app/App'
import './styles.css'

createRoot(document.getElementById('root')!).render(<App />)
if (import.meta.env.PROD && 'serviceWorker' in navigator)
  void navigator.serviceWorker
    .register('/sw.js', { type: 'module' })
    .catch(error => console.warn('静态离线外壳不可用', error))
