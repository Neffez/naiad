import type { TFunction } from 'i18next'
import { useTranslation } from 'react-i18next'
import type { SystemStatus } from '../api/client'

interface TodayBlockProps {
  sys: SystemStatus
  dense?: boolean
}

/** Format a signed percentage delta, e.g. 12 → "+12 %", -5 → "-5 %", 0 → "0 %". */
function fmtDelta(pct: number): string {
  if (pct === 0) return '0 %'
  return `${pct > 0 ? '+' : ''}${pct} %`
}

function formatRelative(isoDate: string, t: TFunction): string {
  const diff = new Date(isoDate).getTime() - Date.now()
  if (diff < 0) return t('time.now')
  const mins = Math.floor(diff / 60_000)
  if (mins < 60) return t('time.inMin', { n: mins })
  const h = Math.floor(mins / 60)
  const m = mins % 60
  return m > 0 ? t('time.inHM', { h, m }) : t('time.inH', { h })
}

function formatWhen(isoDate: string, t: TFunction, lng: string): string {
  const d = new Date(isoDate)
  const now = new Date()
  const isToday = d.toDateString() === now.toDateString()
  const tomorrow = new Date(now)
  tomorrow.setDate(tomorrow.getDate() + 1)
  const isTomorrow = d.toDateString() === tomorrow.toDateString()

  const time = d.toLocaleString(lng, { hour: '2-digit', minute: '2-digit' })
  if (isToday) return t('time.todayAt', { time })
  if (isTomorrow) return t('time.tomorrowAt', { time })
  return d.toLocaleString(lng, { weekday: 'short', hour: '2-digit', minute: '2-digit' })
}

export function TodayBlock({ sys, dense = false }: TodayBlockProps) {
  const { t, i18n } = useTranslation()
  const f = sys.today_factor

  // temp_pct and rain_pct are signed deltas from neutral (0 = no adjustment).
  const breakdown = [
    { label: t('weather.temp'), delta: fmtDelta(f.temp_pct), positive: f.temp_pct >= 0 },
    { label: t('weather.rain'), delta: fmtDelta(f.rain_pct), positive: f.rain_pct >= 0 },
  ]

  if (f.wind_blocking_sequences.length > 0) {
    breakdown.push({
      label: t('weather.wind'),
      delta: t('today.blocked', { seqs: f.wind_blocking_sequences.join(', ') }),
      positive: false,
    })
  }

  if (dense) {
    return <DenseTodayBlock sys={sys} breakdown={breakdown} />
  }

  return (
    <div
      className="n-card"
      style={{
        padding: '22px 24px',
        display: 'flex',
        flexDirection: 'column',
        gap: 16,
        position: 'relative',
        overflow: 'hidden',
        flex: 1,
      }}
    >
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span className="n-eyebrow">{t('today.title')}</span>
      </div>

      {/* Next run — hero card */}
      {sys.next_run ? (
        <div
          style={{
            padding: '14px 16px',
            borderRadius: 12,
            background: 'var(--n-teal-glow)',
            border: '1px solid rgba(94,200,216,0.15)',
            display: 'flex',
            flexDirection: 'column',
            gap: 6,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span style={{ fontSize: 22, fontWeight: 600, letterSpacing: '-0.015em' }}>
              {sys.next_run.sequence_label}
            </span>
            <span className="mono" style={{ fontSize: 13, color: 'var(--n-teal-300)', fontWeight: 500 }}>
              {formatRelative(sys.next_run.scheduled_at, t)}
            </span>
          </div>
          <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between' }}>
            <span className="mono" style={{ fontSize: 18, color: 'var(--n-teal-200)', fontWeight: 500 }}>
              {formatWhen(sys.next_run.scheduled_at, t, i18n.language)}
            </span>
            <span className="mono" style={{ fontSize: 14, color: 'var(--n-fg-soft)' }}>
              {sys.next_run.duration_min} min
            </span>
          </div>
        </div>
      ) : (
        <div style={{ padding: '14px 16px', borderRadius: 12, background: 'rgba(255,255,255,0.02)', border: '1px solid var(--n-line)' }}>
          <span style={{ fontSize: 14, color: 'var(--n-fg-muted)' }}>{t('today.noRun')}</span>
        </div>
      )}

      {/* After next — secondary */}
      {sys.after_next && (
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            padding: '10px 14px',
            background: 'rgba(255,255,255,0.018)',
            border: '1px solid var(--n-line)',
            borderRadius: 10,
          }}
        >
          <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <span className="n-eyebrow" style={{ fontSize: 9.5 }}>{t('today.after')}</span>
            <span style={{ fontSize: 16, fontWeight: 500 }}>{sys.after_next.sequence_label}</span>
          </div>
          <span className="mono" style={{ fontSize: 13, color: 'var(--n-fg-muted)' }}>
            {formatWhen(sys.after_next.scheduled_at, t, i18n.language)} · {sys.after_next.duration_min} min
          </span>
        </div>
      )}

      {/* Spacer to push adjustment to bottom */}
      <div style={{ flex: 1 }} />
      <div className="n-divider" />

      {/* Adjustment factor — compact / tertiary */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span className="n-eyebrow">{t('today.adjustment')}</span>
            <span
              style={{
                fontSize: 10,
                color: 'var(--n-teal-300)',
                display: 'inline-flex',
                alignItems: 'center',
                gap: 4,
              }}
            >
              <span style={{ width: 5, height: 5, borderRadius: '50%', background: 'var(--n-teal-300)' }} />
              {t('today.auto')}
            </span>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
            {breakdown.map((b, i) => (
              <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 12.5 }}>
                <span style={{ color: 'var(--n-fg-soft)', minWidth: 80 }}>{b.label}</span>
                <span
                  className="mono"
                  style={{
                    color: !b.positive ? 'var(--n-paused)' : 'var(--n-leaf-300)',
                    fontWeight: 500,
                  }}
                >
                  {b.delta}
                </span>
              </div>
            ))}
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 2 }}>
          <span
            className="n-bignum"
            style={{
              fontSize: 42,
              color: 'var(--n-teal-200)',
              letterSpacing: '-0.03em',
              lineHeight: 1,
            }}
          >
            {f.combined_pct}
          </span>
          <span style={{ fontSize: 16, color: 'var(--n-fg-muted)' }}>%</span>
        </div>
      </div>
    </div>
  )
}

function DenseTodayBlock({ sys, breakdown }: { sys: SystemStatus; breakdown: { label: string; delta: string; positive: boolean }[] }) {
  const { t, i18n } = useTranslation()
  const f = sys.today_factor

  return (
    <div className="n-card" style={{ padding: '16px 18px', display: 'flex', flexDirection: 'column', gap: 12 }}>
      {/* Next run — compact hero */}
      {sys.next_run && (
        <div
          style={{
            padding: '10px 12px',
            borderRadius: 10,
            background: 'var(--n-teal-glow)',
            border: '1px solid rgba(94,200,216,0.15)',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
          }}
        >
          <div>
            <div style={{ fontSize: 16, fontWeight: 600 }}>{sys.next_run.sequence_label}</div>
            <span className="mono" style={{ fontSize: 12, color: 'var(--n-teal-200)' }}>
              {formatWhen(sys.next_run.scheduled_at, t, i18n.language)} · {sys.next_run.duration_min} min
            </span>
          </div>
          <span className="mono" style={{ fontSize: 12, color: 'var(--n-teal-300)', fontWeight: 500 }}>
            {formatRelative(sys.next_run.scheduled_at, t)}
          </span>
        </div>
      )}

      {/* After next */}
      {sys.after_next && (
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12.5, opacity: 0.7, padding: '0 2px' }}>
          <span style={{ color: 'var(--n-fg-soft)' }}>{sys.after_next.sequence_label}</span>
          <span className="mono" style={{ color: 'var(--n-fg-muted)' }}>
            {formatWhen(sys.after_next.scheduled_at, t, i18n.language)} · {sys.after_next.duration_min} min
          </span>
        </div>
      )}

      <div className="n-divider" />

      {/* Adjustment — inline */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
          {breakdown.map((b, i) => (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 11.5 }}>
              <span style={{ color: 'var(--n-fg-soft)', minWidth: 70 }}>{b.label}</span>
              <span className="mono" style={{ color: !b.positive ? 'var(--n-paused)' : 'var(--n-leaf-300)' }}>
                {b.delta}
              </span>
            </div>
          ))}
        </div>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 2 }}>
          <span className="n-bignum" style={{ fontSize: 28, color: 'var(--n-teal-200)', lineHeight: 1 }}>
            {f.combined_pct}
          </span>
          <span style={{ fontSize: 12, color: 'var(--n-fg-muted)' }}>%</span>
        </div>
      </div>
    </div>
  )
}
