import { useEffect, useRef, useState } from 'react'

/** Small circled "i" that reveals an explanatory tooltip on hover or tap. */
export function InfoTip({ text }: { text: string }) {
  const [open, setOpen] = useState(false)
  const wrapRef = useRef<HTMLSpanElement>(null)

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent | TouchEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('touchstart', onDown)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('touchstart', onDown)
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
        type="button"
        aria-label="info"
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
      {open && (
        <span
          role="tooltip"
          style={{
            position: 'absolute',
            top: 'calc(100% + 6px)',
            left: 0,
            zIndex: 1000,
            width: 240,
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
        </span>
      )}
    </span>
  )
}
