const CACHE = 'hermes-remote-shell-__BUILD__'
// Only the generic, data-free SPA shell and fingerprinted build assets are cached.
export const staticPath = path =>
  ['/index.html', '/icon.svg', '/manifest.webmanifest'].includes(path) ||
  /^\/assets\/[a-zA-Z0-9_-]+\.(js|css)$/.test(path)
const assets = /* BUILD_ASSETS */ []
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE).then(cache => cache.addAll(['/index.html', '/icon.svg', '/manifest.webmanifest', ...assets]))
  )
})
self.addEventListener('activate', event => {
  event.waitUntil(
    caches
      .keys()
      .then(keys =>
        Promise.all(
          keys.filter(key => key.startsWith('hermes-remote-shell-') && key !== CACHE).map(key => caches.delete(key))
        )
      )
      .then(() => self.clients.claim())
  )
})
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url)
  if (
    event.request.method === 'GET' &&
    url.origin === self.location.origin &&
    event.request.mode === 'navigate' &&
    url.pathname === '/' &&
    !url.search
  ) {
    event.respondWith(fetch(event.request).catch(() => caches.match('/index.html')))
    return
  }
  if (event.request.method !== 'GET' || url.origin !== self.location.origin || url.search || !staticPath(url.pathname))
    return
  event.respondWith(
    caches.open(CACHE).then(async cache => {
      const cached = await cache.match(event.request)
      if (cached) return cached
      const response = await fetch(event.request)
      if (response.ok && !response.headers.get('Cache-Control')?.includes('no-store'))
        await cache.put(event.request, response.clone())
      return response
    })
  )
})
