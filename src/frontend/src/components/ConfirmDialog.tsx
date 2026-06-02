import { useCallback, useEffect, useId, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useDialog } from '../hooks/useDialog'
import { IGauge, IPlay, IX } from './icons'

// 1 min, then 5-minute increments up to 90. A manual run may need just a minute
// (e.g. flushing a line), so the leftmost stop is 1 min, then 5, 10, 15, …
const DURATION_STEPS = [1, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 85, 90]

/** Index of the step closest to a given duration (snaps off-grid defaults). */
function nearestStepIdx(value: number): number {
  let best = 0
  let bestDist = Infinity
  DURATION_STEPS.forEach((step, i) => {
    const dist = Math.abs(step - value)
    if (dist < bestDist) {
      bestDist = dist
      best = i
    }
  })
  return best
}

interface ConfirmDialogProps {
  open: boolean
  title: string
  subtitle?: string
  color?: string
  zones: number
  defaultDuration: number
  onConfirm: (durationMin: number) => void
  onCancel: () => void
}

export function ConfirmDialog({
  open,
  title,
  subtitle,
  color = 'var(--n-teal-500)',
  zones,
  defaultDuration,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const { t } = useTranslation()
  const [duration, setDuration] = useState(defaultDuration)
  const backdropRef = useRef<HTMLDivElement>(null)
  const dialogRef = useDialog<HTMLDivElement>(open, onCancel)
  const titleId = useId()

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (open) setDuration(defaultDuration)
  }, [open, defaultDuration])

  const handleBackdropClick = useCallback(
    (e: React.MouseEvent) => {
      if (e.target === backdropRef.current) onCancel()
    },
    [onCancel],
  )

  if (!open) return null

  const estLiters = Math.round(zones * duration * 7.7)
  // Non-linear steps: 1 min on the far left, then 5-minute increments. The slider
  // index maps to a discrete duration so dragging snaps to these values.
  const sliderIdx = nearestStepIdx(duration)
  const pct = (sliderIdx / (DURATION_STEPS.length - 1)) * 100

  return (
    <div className="n-backdrop" ref={backdropRef} onClick={handleBackdropClick}>
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className="n-dialog"
        style={{
          position: 'absolute',
          left: '50%',
          top: '50%',
          transform: 'translate(-50%, -50%)',
          width: 'min(460px, calc(100% - 32px))',
          padding: 24,
          display: 'flex',
          flexDirection: 'column',
          gap: 18,
        }}
      >
        {/* header */}
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 14 }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <span className="n-eyebrow">{t('confirm.startNow')}</span>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span aria-hidden="true" style={{ width: 4, height: 28, background: color, borderRadius: 2 }} />
              <span id={titleId} style={{ fontSize: 28, fontWeight: 600, letterSpacing: '-0.02em' }}>{title}</span>
            </div>
            {subtitle && <span className="n-label" style={{ fontSize: 12.5 }}>{subtitle}</span>}
          </div>
          <button className="n-iconbtn" style={{ width: 40, height: 40 }} onClick={onCancel} aria-label={t('a11y.close')}>
            <IX size={16} />
          </button>
        </div>

        <div className="n-divider" />

        {/* summary grid */}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(3, 1fr)',
            padding: '10px 0',
            borderRadius: 12,
            background: 'rgba(255,255,255,0.015)',
            border: '1px solid var(--n-line)',
          }}
        >
          <SummaryStat label={t('confirm.zones')} value={zones} />
          <SummaryStat label={t('confirm.perZone')} value={duration} unit="min" highlight={duration !== defaultDuration} />
          <SummaryStat label={t('confirm.water')} value={estLiters} unit="L" mono />
        </div>

        {/* slider */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
            <span className="n-eyebrow">{t('confirm.durationOverride')}</span>
            <button
              onClick={() => setDuration(defaultDuration)}
              style={{
                background: 'transparent',
                border: 0,
                padding: 0,
                cursor: 'pointer',
                color: 'var(--n-fg-muted)',
                fontSize: 11.5,
                textDecoration: duration !== defaultDuration ? 'underline' : 'none',
              }}
            >
              {t('confirm.resetTo', { min: defaultDuration })}
            </button>
          </div>
          <input
            type="range"
            min="0"
            max={DURATION_STEPS.length - 1}
            step="1"
            value={sliderIdx}
            onChange={(e) => setDuration(DURATION_STEPS[+e.target.value])}
            className="n-slider"
            aria-label={t('a11y.durationSlider')}
            aria-valuetext={`${duration} min`}
            style={{ '--p': `${pct}%` } as React.CSSProperties}
          />
          <div style={{ display: 'flex', justifyContent: 'space-between', color: 'var(--n-fg-muted)', fontSize: 11 }}>
            <span className="mono">{DURATION_STEPS[0]} min</span>
            <span className="mono" style={{ color: 'var(--n-fg)' }}>{duration} min</span>
            <span className="mono">{DURATION_STEPS[DURATION_STEPS.length - 1]} min</span>
          </div>
        </div>

        {/* hint */}
        <div
          style={{
            display: 'flex',
            alignItems: 'flex-start',
            gap: 10,
            padding: '10px 12px',
            background: 'var(--n-teal-glow)',
            border: '1px solid rgba(94,200,216,0.20)',
            borderRadius: 10,
            color: 'var(--n-fg-soft)',
          }}
        >
          <span style={{ color: 'var(--n-teal-300)', marginTop: 1 }}>
            <IGauge size={16} />
          </span>
          <div style={{ fontSize: 12.5, lineHeight: 1.5 }}>{t('confirm.factorHint')}</div>
        </div>

        {/* actions */}
        <div style={{ display: 'flex', gap: 10, marginTop: 4 }}>
          <button className="n-btn ghost lg" style={{ flex: 1 }} onClick={onCancel}>
            {t('confirm.cancel')}
          </button>
          <button className="n-btn primary lg" style={{ flex: 1.4 }} onClick={() => onConfirm(duration)}>
            <IPlay size={14} />
            {t('confirm.start')}
          </button>
        </div>
      </div>
    </div>
  )
}

function SummaryStat({
  label,
  value,
  unit,
  mono,
  highlight,
}: {
  label: string
  value: number
  unit?: string
  mono?: boolean
  highlight?: boolean
}) {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: 4,
        borderRight: '1px solid var(--n-line)',
        padding: '4px 8px',
      }}
    >
      <span className="n-eyebrow" style={{ fontSize: 9.5 }}>{label}</span>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 3 }}>
        <span
          className={mono ? 'mono' : 'n-bignum'}
          style={{
            fontSize: mono ? 18 : 24,
            fontWeight: mono ? 500 : 400,
            color: highlight ? 'var(--n-teal-200)' : 'var(--n-fg)',
          }}
        >
          {value}
        </span>
        {unit && <span style={{ fontSize: 11, color: 'var(--n-fg-muted)' }}>{unit}</span>}
      </div>
    </div>
  )
}
