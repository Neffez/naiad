import { useEffect, useRef } from 'react'
import { wsUrl } from '../api/base'
import { clearToken } from '../api/client'

type WsMessage = { type: string; data?: unknown }
type MessageHandler = (msg: WsMessage) => void

interface UseWebSocketOptions {
  /** Called when the server rejects the token. Defaults to clearing the token
   *  and reloading so the login screen is shown. */
  onAuthFailed?: () => void
}

const MAX_BACKOFF_MS = 30_000

export function useWebSocket(onMessage: MessageHandler, options?: UseWebSocketOptions) {
  const wsRef = useRef<WebSocket | null>(null)
  const handlerRef = useRef(onMessage)
  const authFailedRef = useRef(options?.onAuthFailed)

  // Keep the latest callbacks in refs without re-opening the socket on every
  // render (assigning .current during render is disallowed by react-hooks/refs).
  useEffect(() => {
    handlerRef.current = onMessage
    authFailedRef.current = options?.onAuthFailed
  })

  useEffect(() => {
    let unmounted = false
    let stopped = false // set on auth failure — never reconnect after this
    let attempt = 0
    let reconnectTimer: ReturnType<typeof setTimeout> | undefined

    function scheduleReconnect() {
      if (unmounted || stopped) return
      // Exponential backoff so a persistently failing connection can't turn into
      // a 3-second reconnect storm against the backend.
      const delay = Math.min(1000 * 2 ** attempt, MAX_BACKOFF_MS)
      attempt += 1
      reconnectTimer = setTimeout(connect, delay)
    }

    function connect() {
      if (unmounted || stopped) return
      const ws = new WebSocket(wsUrl('/api/ws'))
      wsRef.current = ws

      ws.onopen = () => {
        const token = localStorage.getItem('naiad_token') ?? ''
        ws.send(JSON.stringify({ type: 'auth', token }))
      }

      ws.onmessage = (ev) => {
        let msg: WsMessage
        try {
          msg = JSON.parse(ev.data)
        } catch {
          return
        }

        if (msg.type === 'auth_ok') {
          attempt = 0 // healthy connection — reset backoff
          return
        }
        if (msg.type === 'auth_failed') {
          // Token invalid/expired: stop reconnecting and surface re-login instead
          // of looping forever against a backend that will keep rejecting us.
          stopped = true
          if (reconnectTimer) clearTimeout(reconnectTimer)
          clearToken()
          if (authFailedRef.current) authFailedRef.current()
          else window.location.reload()
          return
        }

        handlerRef.current(msg)
      }

      ws.onclose = () => {
        scheduleReconnect()
      }
    }

    connect()

    return () => {
      unmounted = true
      if (reconnectTimer) clearTimeout(reconnectTimer)
      const ws = wsRef.current
      if (ws) {
        // Detach handlers before closing so a late onclose can't schedule a
        // reconnect after the component has unmounted.
        ws.onopen = null
        ws.onmessage = null
        ws.onclose = null
        ws.onerror = null
        ws.close()
      }
    }
  }, [])

  return wsRef
}
