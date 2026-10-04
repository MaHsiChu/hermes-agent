import type { Identity } from './protocol'

export class HttpError extends Error {
  constructor(
    public status: number,
    message: string
  ) {
    super(message)
  }
}
export class StaleAccountError extends Error {
  constructor() {
    super('账号已更改，已丢弃旧请求结果')
  }
}
export class Api {
  private controller = new AbortController()
  private active = true
  constructor(
    public csrf: string,
    private fetcher: typeof fetch = fetch
  ) {}
  close() {
    this.active = false
    this.controller.abort()
  }
  assertActive() {
    if (!this.active) throw new StaleAccountError()
  }
  async request<T>(path: string, options: RequestInit = {}): Promise<T> {
    this.assertActive()
    const headers = new Headers(options.headers)
    if (options.method && options.method !== 'GET') headers.set('X-CSRF-Token', this.csrf)
    if (options.body && !(options.body instanceof FormData)) headers.set('Content-Type', 'application/json')
    const fetcher = this.fetcher
    const response = await fetcher(path, {
      ...options,
      headers,
      signal: this.controller.signal,
      credentials: 'same-origin',
      cache: 'no-store'
    })
    this.assertActive()
    const data = await response.json()
    this.assertActive()
    if (!response.ok)
      throw new HttpError(
        response.status,
        typeof data.detail === 'string' ? data.detail : `请求失败 (${response.status})`
      )
    return data as T
  }
  post<T>(path: string, body: unknown) {
    return this.request<T>(path, { method: 'POST', body: JSON.stringify(body) })
  }
}
export async function identity(): Promise<Identity> {
  const response = await fetch('/api/remote/me', { credentials: 'same-origin', cache: 'no-store' })
  if (!response.ok) throw new HttpError(response.status, '无法确认登录状态')
  return response.json()
}
export const sessionPath = (id: string) => `/api/remote/sessions/${encodeURIComponent(id)}`
