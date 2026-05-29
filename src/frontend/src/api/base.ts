// Runtime base path detection.
//
// Naiad is served either at the server root (standalone container) or behind a
// Home Assistant ingress prefix (`/api/hassio_ingress/<token>/`). The ingress
// proxy strips that prefix before forwarding to the backend, but the browser
// still addresses everything *with* it — so the SPA must prepend the prefix to
// its own API/WebSocket calls and use it as the router basename.
//
// The prefix is the leading `/api/hassio_ingress/<token>` segment of the current
// path (route-independent, so it survives client-side navigation and deep links).
// Standalone paths never match → empty prefix → unchanged behaviour.

export const BASE_PATH: string = (() => {
  const match = window.location.pathname.match(/^(.*?\/api\/hassio_ingress\/[^/]+)/)
  return match ? match[1] : ''
})()

export const API_BASE = `${BASE_PATH}/api`

export function wsUrl(path: string): string {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${window.location.host}${BASE_PATH}${path}`
}
