import { expect, it } from 'vitest'
import { Api } from './api'

it('calls fetch without rebinding its native receiver to the API client', async () => {
  const receiverSensitiveFetch: typeof fetch = async function (this: unknown) {
    if (this !== undefined && this !== globalThis) throw new TypeError('Illegal invocation')
    return new Response(JSON.stringify({ ok: true }))
  }
  await expect(new Api('csrf', receiverSensitiveFetch).request('/api/remote/devices')).resolves.toEqual({ ok: true })
})
