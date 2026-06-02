import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

// Lightweight, app-wide toast notifications. Fire from anywhere with `toast(...)`
// (event-based, like the existing `naiad:unauthorized` pattern); <Toaster/> is
// mounted once in App and renders the stack.

export type ToastLevel = 'error' | 'success' | 'info'

interface ToastItem {
  id: number
  message: string
  level: ToastLevel
}

const EVENT = 'naiad:toast'

// eslint-disable-next-line react-refresh/only-export-components
export function toast(message: string, level: ToastLevel = 'error'): void {
  window.dispatchEvent(new CustomEvent<{ message: string; level: ToastLevel }>(EVENT, {
    detail: { message, level },
  }))
}

const ACCENT: Record<ToastLevel, string> = {
  error: 'var(--n-danger)',
  success: 'var(--n-leaf-400)',
  info: 'var(--n-teal-400)',
}

const TTL_MS = 6000

export function Toaster() {
  const { t } = useTranslation()
  const [items, setItems] = useState<ToastItem[]>([])

  useEffect(() => {
    let nextId = 1
    const onToast = (e: Event) => {
      const detail = (e as CustomEvent<{ message: string; level: ToastLevel }>).detail
      if (!detail?.message) return
      const id = nextId++
      setItems((prev) => [...prev, { id, message: detail.message, level: detail.level }])
      window.setTimeout(() => setItems((prev) => prev.filter((item) => item.id !== id)), TTL_MS)
    }
    window.addEventListener(EVENT, onToast)
    return () => window.removeEventListener(EVENT, onToast)
  }, [])

  function dismiss(id: number) {
    setItems((prev) => prev.filter((item) => item.id !== id))
  }

  if (items.length === 0) return null

  return (
    <div
      role="region"
      aria-label={t('a11y.notificationsRegion')}
      style={{
        position: 'fixed',
        left: '50%',
        bottom: 'calc(env(safe-area-inset-bottom, 0px) + 84px)',
        transform: 'translateX(-50%)',
        zIndex: 2000,
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
        width: 'min(440px, calc(100vw - 32px))',
        pointerEvents: 'none',
      }}
    >
      {items.map((item) => (
        <div
          key={item.id}
          // Errors interrupt; success/info wait for a pause in speech.
          role={item.level === 'error' ? 'alert' : 'status'}
          aria-live={item.level === 'error' ? 'assertive' : 'polite'}
          className="n-card"
          style={{
            pointerEvents: 'auto',
            display: 'flex',
            alignItems: 'flex-start',
            gap: 10,
            padding: '12px 14px',
            borderLeft: `3px solid ${ACCENT[item.level]}`,
            boxShadow: '0 8px 24px rgba(0,0,0,0.45)',
            animation: 'n-fade-in 160ms var(--n-ease)',
          }}
        >
          <span style={{ flex: 1, fontSize: 13.5, lineHeight: 1.45, color: 'var(--n-fg)' }}>
            {item.message}
          </span>
          <button
            type="button"
            onClick={() => dismiss(item.id)}
            aria-label={t('a11y.dismissNotification')}
            style={{
              background: 'transparent',
              border: 0,
              // Roomy hit target (the whole-card tap-to-dismiss is gone); the
              // negative margin keeps the glyph visually aligned with the text.
              padding: '4px 8px',
              margin: '-4px -8px -4px 0',
              cursor: 'pointer',
              color: 'var(--n-fg-muted)',
              fontSize: 16,
              lineHeight: 1,
              display: 'inline-flex',
              alignItems: 'center',
            }}
          >
            ×
          </button>
        </div>
      ))}
    </div>
  )
}
