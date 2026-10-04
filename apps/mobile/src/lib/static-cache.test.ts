import { expect, it, vi } from 'vitest'
import { staticPath } from '../../public/sw.js'

it('never intercepts authenticated APIs, OIDC, attachments or query-bearing assets', () => {
  for (const path of [
    '/api/remote/me',
    '/auth/callback?code=private',
    '/api/remote/sessions/s/attachments/a',
    '/assets/index.js?token=private'
  ]) {
    const event = new Event('fetch')
    const respondWith = vi.fn()
    Object.defineProperties(event, {
      request: { value: new Request(new URL(path, location.href)) },
      respondWith: { value: respondWith }
    })
    window.dispatchEvent(event)
    expect(respondWith).not.toHaveBeenCalled()
  }
  expect(staticPath('/assets/index-AbC123.js')).toBe(true)
  expect(staticPath('/api/remote/attachments/image.js')).toBe(false)
})
