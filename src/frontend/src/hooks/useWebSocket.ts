import { useEffect, useRef } from 'react'

type WsMessage = { type: string; data?: unknown }
type MessageHandler = (msg: WsMessage) => void

export function useWebSocket(onMessage: MessageHandler) {
  const wsRef = useRef<WebSocket | null>(null)
  const handlerRef = useRef(onMessage)
  handlerRef.current = onMessage

  useEffect(() => {
    let reconnectTimer: ReturnType<typeof setTimeout>

    function connect() {
      const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
      const ws = new WebSocket(`${proto}://${window.location.host}/api/ws`)
      wsRef.current = ws

      ws.onopen = () => {
        const token = localStorage.getItem('naiad_token') ?? ''
        ws.send(JSON.stringify({ type: 'auth', token }))
      }

      ws.onmessage = (ev) => {
        try {
          handlerRef.current(JSON.parse(ev.data))
        } catch { /* ignore */ }
      }

      ws.onclose = () => {
        reconnectTimer = setTimeout(connect, 3000)
      }
    }

    connect()

    return () => {
      clearTimeout(reconnectTimer)
      wsRef.current?.close()
    }
  }, [])

  return wsRef
}
