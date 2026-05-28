import { useTranslation } from 'react-i18next'
import type { SequenceState } from '../api/client'
import { ICal, IClock, IPause, IPlay } from './icons'
import { StatusChip } from './StatusChip'

interface SequenceCardProps {
  seq: SequenceState
  size?: 'regular' | 'rich'
  onStart?: () => void
  onPause?: () => void
  onSchedule?: () => void
}

const SEQUENCE_COLORS: Record<string, string> = {
  beete: '#7fc8a8',
  rasen: '#7fc8a8',
  hochbeet: '#c8a87f',
  hecke: '#a87fc8',
  topf: '#8a9ea6',
}

function seqColor(id: string): string {
  for (const [key, color] of Object.entries(SEQUENCE_COLORS)) {
    if (id.toLowerCase().includes(key)) return color
  }
  return 'var(--n-teal-500)'
}

export function SequenceCard({ seq, size = 'regular', onStart, onPause, onSchedule }: SequenceCardProps) {
  if (size === 'rich') {
    return <SequenceCardRich seq={seq} onStart={onStart} onPause={onPause} onSchedule={onSchedule} />
  }
  return <SequenceCardRegular seq={seq} onStart={onStart} onPause={onPause} onSchedule={onSchedule} />
}

function SequenceCardRegular({ seq, onStart, onPause, onSchedule }: Omit<SequenceCardProps, 'size'>) {
  const { t } = useTranslation()
  const isRunning = seq.status === 'running'
  const isPaused = seq.status === 'paused'
  const isDisabled = seq.status === 'disabled' || !seq.enabled

  const progress = seq.current_run
    ? Math.min(100, (seq.current_run.elapsed_min / (seq.current_run.elapsed_min + seq.current_run.remaining_min)) * 100)
    : 0
  const color = seqColor(seq.id)

  return (
    <div
      className={`n-card${isRunning ? ' n-live-glow' : ''}`}
      style={{
        padding: '16px 18px',
        opacity: isDisabled ? 0.55 : 1,
        display: 'flex',
        flexDirection: 'column',
        gap: 12,
        position: 'relative',
        overflow: 'hidden',
      }}
    >
      <span
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          bottom: 0,
          width: 3,
          background: color,
          opacity: isDisabled ? 0.3 : 0.85,
        }}
      />

      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12 }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ fontSize: 19, fontWeight: 600, letterSpacing: '-0.01em' }}>{seq.label}</span>
            <StatusChip status={seq.status} />
          </div>
          <div className="n-label" style={{ fontSize: 12 }}>
            {isRunning && seq.current_run && (
              <span>
                {t('sequence.running', { defaultValue: 'Läuft' })} · {seq.zones.length}{' '}
                {seq.zones.length === 1 ? t('sequence.zone') : t('sequence.zones')}
              </span>
            )}
            {isPaused && seq.current_run && (
              <span>
                {t('status.paused')} · {seq.current_run.remaining_min.toFixed(0)} min Rest
              </span>
            )}
            {seq.status === 'idle' && (
              <span>
                {seq.next_run_at
                  ? `${t('sequence.nextRun')} · ${new Date(seq.next_run_at).toLocaleString('de', { weekday: 'short', hour: '2-digit', minute: '2-digit' })}`
                  : seq.schedule_label}{' '}
                · {seq.zones.length} × {seq.basis_min_per_zone} min
              </span>
            )}
            {isDisabled && <span style={{ color: 'var(--n-fg-dim)' }}>{t('status.disabled')}</span>}
          </div>
        </div>

        {!isDisabled && (
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 2, flex: '0 0 auto' }}>
            <span
              className="mono"
              style={{
                fontSize: 18,
                fontWeight: 500,
                letterSpacing: '-0.02em',
                color:
                  seq.factor_pct === 0
                    ? 'var(--n-paused)'
                    : seq.factor_pct > 100
                      ? 'var(--n-teal-200)'
                      : 'var(--n-fg)',
              }}
            >
              {seq.factor_pct}%
            </span>
            <span className="n-eyebrow" style={{ fontSize: 9 }}>
              {seq.factor_note || t('sequence.factor')}
            </span>
          </div>
        )}
      </div>

      {isRunning && seq.current_run && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div className="n-progress" style={{ flex: 1 }}>
            <i style={{ width: `${progress}%` }} />
          </div>
          <span className="mono" style={{ fontSize: 13, color: 'var(--n-teal-200)', letterSpacing: '-0.01em', fontWeight: 500 }}>
            {seq.current_run.remaining_min.toFixed(0)} min Rest
          </span>
        </div>
      )}

      <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
        <button
          className={`n-iconbtn${isRunning ? ' paused-state' : ' accent'}`}
          onClick={isRunning ? onPause : onStart}
          disabled={isDisabled}
          style={{ width: 44, height: 44, opacity: isDisabled ? 0.4 : 1 }}
          title={isRunning ? t('sequence.pause') : t('sequence.start')}
        >
          {isRunning ? <IPause size={18} /> : <IPlay size={16} />}
        </button>
        <button
          className="n-iconbtn"
          onClick={onSchedule}
          disabled={isDisabled}
          style={{ width: 44, height: 44, opacity: isDisabled ? 0.4 : 1 }}
          title={t('planner.schedule')}
        >
          <ICal size={17} />
        </button>
        <button
          className="n-iconbtn"
          disabled={isDisabled || !isRunning}
          style={{
            flex: 1,
            height: 44,
            opacity: isDisabled ? 0.4 : 1,
            gap: 8,
            fontSize: 12.5,
            color: 'var(--n-fg-soft)',
            paddingLeft: 12,
            justifyContent: 'flex-start',
          }}
        >
          <IClock size={15} />
        </button>
      </div>
    </div>
  )
}

function SequenceCardRich({ seq, onStart, onPause, onSchedule }: Omit<SequenceCardProps, 'size'>) {
  const { t } = useTranslation()
  const isRunning = seq.status === 'running'
  const isPaused = seq.status === 'paused'
  const isDisabled = seq.status === 'disabled' || !seq.enabled
  const color = seqColor(seq.id)

  const progress = seq.current_run
    ? Math.min(100, (seq.current_run.elapsed_min / (seq.current_run.elapsed_min + seq.current_run.remaining_min)) * 100)
    : 0

  return (
    <div
      className={`n-card${isRunning ? ' n-live-glow' : ''}`}
      style={{
        padding: '16px 20px 14px',
        opacity: isDisabled ? 0.55 : 1,
        display: 'flex',
        flexDirection: 'column',
        gap: 10,
        position: 'relative',
        overflow: 'hidden',
        height: '100%',
        lineHeight: '1',
      }}
    >
      <span
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          bottom: 0,
          width: 4,
          background: color,
          opacity: isDisabled ? 0.3 : 0.9,
        }}
      />

      {/* header */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 14 }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <span style={{ fontSize: 24, fontWeight: 600, letterSpacing: '-0.015em' }}>{seq.label}</span>
            <StatusChip status={seq.status} />
          </div>
          <span className="n-label" style={{ fontSize: 13 }}>
            {seq.schedule_label} · {seq.zones.length}{' '}
            {seq.zones.length === 1 ? t('sequence.zone') : t('sequence.zones')}
            {seq.basis_min_per_zone ? ` · regulär ${seq.basis_min_per_zone} min/Zone` : ''}
          </span>
        </div>
        {!isDisabled && (
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 2, flex: '0 0 auto' }}>
            <span
              className="n-bignum"
              style={{
                fontSize: 40,
                lineHeight: 1,
                letterSpacing: '-0.02em',
                color:
                  seq.factor_pct === 0
                    ? 'var(--n-paused)'
                    : seq.factor_pct > 100
                      ? 'var(--n-teal-200)'
                      : 'var(--n-fg)',
              }}
            >
              {seq.factor_pct}%
            </span>
            <span className="n-eyebrow" style={{ fontSize: 9.5 }}>
              {seq.factor_note || t('sequence.factor')}
            </span>
          </div>
        )}
      </div>

      {/* live progress */}
      {isRunning && seq.current_run && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between' }}>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
              <span className="n-bignum" style={{ fontSize: 38, color: 'var(--n-teal-200)' }}>
                {seq.current_run.remaining_min.toFixed(0)}
              </span>
              <span style={{ fontSize: 13, color: 'var(--n-fg-muted)' }}>min Rest</span>
            </div>
            <span className="mono" style={{ fontSize: 12, color: 'var(--n-fg-muted)' }}>
              {seq.current_run.elapsed_min.toFixed(0)} /{' '}
              {(seq.current_run.elapsed_min + seq.current_run.remaining_min).toFixed(0)} min
            </span>
          </div>
          <div className="n-progress" style={{ height: 6 }}>
            <i style={{ width: `${progress}%` }} />
          </div>
          <div className="n-ripple-line" />
        </div>
      )}

      {/* paused state */}
      {isPaused && seq.current_run && (
        <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
            <span className="mono" style={{ fontSize: 24, fontWeight: 500, color: 'var(--n-paused)' }}>
              {seq.current_run.remaining_min.toFixed(0)} min
            </span>
            <span style={{ fontSize: 12.5, color: 'var(--n-fg-muted)' }}>Rest, pausiert</span>
          </div>
        </div>
      )}

      {/* idle: next run box */}
      {seq.status === 'idle' && (
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'baseline',
            padding: '10px 12px',
            background: 'rgba(255,255,255,0.018)',
            border: '1px solid var(--n-line)',
            borderRadius: 10,
          }}
        >
          <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <span className="n-eyebrow" style={{ fontSize: 9.5 }}>
              {t('sequence.nextRun')}
            </span>
            <span
              className="mono"
              style={{ fontSize: 15, color: seq.factor_pct === 0 ? 'var(--n-paused)' : 'var(--n-fg)', fontWeight: 500 }}
            >
              {seq.next_run_at
                ? new Date(seq.next_run_at).toLocaleString('de', { weekday: 'short', hour: '2-digit', minute: '2-digit' })
                : seq.schedule_label}
            </span>
          </div>
        </div>
      )}

      {/* disabled state */}
      {isDisabled && (
        <div
          style={{
            padding: '12px 12px',
            borderRadius: 10,
            border: '1px dashed var(--n-line-strong)',
            fontSize: 13,
            color: 'var(--n-fg-dim)',
          }}
        >
          {t('status.disabled')}
        </div>
      )}

      {/* zone breakdown */}
      {!isDisabled && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
          <span className="n-eyebrow" style={{ fontSize: 9.5 }}>
            {t('sequence.zones')}
          </span>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {seq.zones.map((z, i) => (
              <div
                key={z.id}
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  padding: '4px 0',
                  borderBottom: i < seq.zones.length - 1 ? '1px dashed var(--n-line)' : 'none',
                  fontSize: 12.5,
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
                  <span
                    style={{
                      width: 6,
                      height: 6,
                      borderRadius: '50%',
                      background: z.valve_state === 'on' ? 'var(--n-teal-300)' : 'var(--n-fg-dim)',
                      boxShadow: z.valve_state === 'on' ? '0 0 0 3px rgba(94,200,216,0.18)' : 'none',
                      flex: '0 0 auto',
                    }}
                  />
                  <span
                    style={{
                      color: z.valve_state === 'on' ? 'var(--n-teal-200)' : 'var(--n-fg-soft)',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {z.label}
                  </span>
                </div>
                <span className="mono" style={{ color: 'var(--n-fg-muted)', fontSize: 12 }}>
                  {Math.round(seq.basis_min_per_zone * (seq.factor_pct / 100))} min
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div style={{ flex: 1 }} />

      {/* actions */}
      <div style={{ display: 'flex', gap: 8 }}>
        <button
          className={`n-btn ${isRunning ? '' : 'primary'}`}
          onClick={isRunning ? onPause : onStart}
          disabled={isDisabled}
          style={{ flex: 1, height: 44, minWidth: 0, padding: '0 12px', fontSize: 13, opacity: isDisabled ? 0.4 : 1, whiteSpace: 'nowrap' }}
        >
          {isRunning ? <IPause size={16} /> : <IPlay size={14} />}
          <span>{isRunning ? t('sequence.pause') : isPaused ? t('sequence.resume') : t('sequence.start')}</span>
        </button>
        <button
          className="n-btn"
          onClick={onSchedule}
          disabled={isDisabled}
          style={{ flex: 1, height: 44, minWidth: 0, padding: '0 12px', fontSize: 13, opacity: isDisabled ? 0.4 : 1, whiteSpace: 'nowrap' }}
        >
          <ICal size={15} />
          <span>{t('planner.schedule')}</span>
        </button>
        <button
          className="n-iconbtn"
          disabled={isDisabled}
          style={{ width: 44, height: 44, flex: '0 0 44px', opacity: isDisabled ? 0.4 : 1 }}
        >
          <IClock size={16} />
        </button>
      </div>
    </div>
  )
}
