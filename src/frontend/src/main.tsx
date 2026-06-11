import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.tsx'
import { BASE_PATH } from './api/base'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)

// PWA: cache the app shell so Naiad is installable and opens instantly. The
// scope-aware path keeps the registration working behind an ingress prefix.
// Registration failure is fine — the app simply runs without offline support.
if (import.meta.env.PROD && 'serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register(`${BASE_PATH}/sw.js`).catch(() => undefined)
  })
}
