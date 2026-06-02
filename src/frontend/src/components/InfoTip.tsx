import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'

/** Small circled "i" that reveals an explanatory tooltip on hover or tap. */
export function InfoTip({ text }: { text: string }) {
  const { t } = useTranslation()
  const tooltipId = useId()
  const [open, setOpen] = useState(false)
  const wrapRef = useRef<HTMLSpanElement>(null)
  const btnRef = useRef<HTMLButtonElement>(null)
  // Position of the popup, computed from the button's viewport rect. The popup is
  // portalled to <body> so an ancestor's `overflow: hidden` (e.g. the settings
  // section card) can't clip it.
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null)

  const TOOLTIP_WIDTH = 240

  function reposition() {
    const el = btnRef.current
    if (!el) return
    const rect = el.getBoundingClientRect()
    // Anchor under the icon, but clamp to the viewport so the tooltip never
    // overflows the right edge on narrow screens.
    const left = Math.min(rect.left, window.innerWidth - TOOLTIP_WIDTH - 8)
    setPos({ top: rect.bottom + 6, left: Math.max(8, left) })
  }

  useLayoutEffect(() => {
    if (open) reposition()
  }, [open])

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent | TouchEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false)
    }
    const onScroll = () => reposition()
    document.addEventListener('mousedown', onDown)
    document.addEventListener('touchstart', onDown)
    window.addEventListener('scroll', onScroll, true)
    window.addEventListener('resize', onScroll)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('touchstart', onDown)
      window.removeEventListener('scroll', onScroll, true)
      window.removeEventListener('resize', onScroll)
    }
  }, [open])

  return (
    <span
      ref={wrapRef}
      style={{ position: 'relative', display: 'inline-flex', alignItems: 'center' }}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <button
        ref={btnRef}
        type="button"
        aria-label={t('a11y.moreInfo')}
        aria-expanded={open}
        aria-describedby={open ? tooltipId : undefined}
        onFocus={() => setOpen(true)}
        onKeyDown={(e) => { if (e.key === 'Escape') setOpen(false) }}
        onClick={(e) => {
          e.preventDefault()
          setOpen((o) => !o)
        }}
        style={{
          width: 16,
          height: 16,
          borderRadius: '50%',
          border: '1px solid var(--n-line-strong)',
          background: 'transparent',
          color: 'var(--n-fg-muted)',
          fontSize: 10.5,
          fontWeight: 600,
          fontStyle: 'italic',
          lineHeight: 1,
          cursor: 'pointer',
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
          padding: 0,
          fontFamily: 'var(--n-serif, Georgia, serif)',
        }}
      >
        i
      </button>
      {open && pos && createPortal(
        <span
          role="tooltip"
          id={tooltipId}
          style={{
            position: 'fixed',
            top: pos.top,
            left: pos.left,
            zIndex: 1000,
            width: TOOLTIP_WIDTH,
            padding: '8px 10px',
            borderRadius: 'var(--n-r-sm)',
            background: 'var(--n-bg-elev)',
            border: '1px solid var(--n-line-strong)',
            boxShadow: '0 6px 20px rgba(0,0,0,0.35)',
            color: 'var(--n-fg-soft)',
            fontSize: 12,
            lineHeight: 1.45,
            fontWeight: 400,
            whiteSpace: 'normal',
          }}
        >
          {text}
        </span>,
        document.body,
      )}
    </span>
  )
}
