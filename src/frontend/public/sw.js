// Naiad service worker: offline app shell + cached static assets, so the UI is
// installable as a home-screen app and opens instantly (even briefly offline).
//
// API requests (live data, auth) and cross-origin requests are never touched.
// Static assets carry content hashes in their filenames, so cache-first with a
// background refresh is safe; navigations are network-first so a deployment is
// picked up on the next online load.

const CACHE = 'naiad-static-v1'
// Cache key for the SPA entry document. Every navigation serves index.html
// regardless of path, so one shell entry covers all routes (incl. deep links).
const APP_SHELL = 'app-shell'

self.addEventListener('install', () => {
  self.skipWaiting()
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  )
})

self.addEventListener('fetch', (event) => {
  const { request } = event
  if (request.method !== 'GET') return
  const url = new URL(request.url)
  if (url.origin !== self.location.origin) return
  if (url.pathname.includes('/api/')) return

  if (request.mode === 'navigate') {
    event.respondWith(
      (async () => {
        try {
          const res = await fetch(request)
          if (res.ok) {
            const cache = await caches.open(CACHE)
            cache.put(APP_SHELL, res.clone())
          }
          return res
        } catch {
          const cached = await caches.match(APP_SHELL)
          return cached ?? Response.error()
        }
      })(),
    )
    return
  }

  event.respondWith(
    (async () => {
      const cache = await caches.open(CACHE)
      const cached = await cache.match(request)
      const refresh = fetch(request)
        .then((res) => {
          if (res.ok) cache.put(request, res.clone())
          return res
        })
        .catch(() => undefined)
      return cached ?? (await refresh) ?? Response.error()
    })(),
  )
})
