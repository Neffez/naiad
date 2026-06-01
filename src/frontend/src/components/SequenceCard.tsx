import { useQuery } from '@tanstack/react-query'
import { queryKeys } from '../api/queryKeys'
import { useTranslation } from 'react-i18next'
import { getConfig, type SequenceState } from '../api/client'
import { formatSchedule } from '../lib/schedule'
import { resolveSeqColor } from '../theme/sequenceColors'
import { ICal, IPause, IPlay, IStop } from './icons'
import { StatusChip } from './StatusChip'

interface SequenceCardProps {
  seq: SequenceState
  size?: 'regular' | 'rich'
  onStart?: () => void
  onPause?: () => void
  onResume?: () => void
  onStop?: () => void
  onSchedule?: () => void
}

function runProgress(run: { elapsed_min: number; remaining_min: number } | null | undefined): number {
  if (!run) return 0
  const total = run.elapsed_min + run.remaining_min
  if (total <= 0) return 0
  return Math.min(100, (run.elapsed_min / total) * 100)
}

export function SequenceCard({ seq, size = 'regular', onStart, onPause, onResume, onStop, onSchedule }: SequenceCardProps) {
  const { data: config } = useQuery({ queryKey: queryKeys.config, queryFn: getConfig })
  const color = resolveSeqColor(config, seq.id)
  if (size === 'rich') {
    return (
      <SequenceCardRich seq={seq} color={color} onStart={onStart} onPause={onPause} onResume={onResume} onStop={onStop} onSchedule={onSchedule} />
    )
  }
  return (
    <SequenceCardRegular seq={seq} color={color} onStart={onStart} onPause={onPause} onResume={onResume} onStop={onStop} onSchedule={onSchedule} />
  )
}

type CardVariantProps = Omit<SequenceCardProps, 'size'> & { color: string | null }

function SequenceCardRegular({ seq, color, onStart, onPause, onResume, onStop, onSchedule }: CardVariantProps) {
  const { t, i18n } = useTranslation()
  const isRunning = seq.status === 'running'
  const isPaused = seq.status === 'paused'
  const isDisabled = seq.status === 'disabled' || !seq.enabled

  const progress = runProgress(seq.current_run)

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
      {color && (
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
      )}

      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12 }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ fontSize: 19, fontWeight: 600, letterSpacing: '-0.01em' }}>{seq.label}</span>
            <StatusChip status={seq.status} />
          </div>
          <div className="n-label" style={{ fontSize: 12 }}>
            {isRunning && seq.current_run && (
              <span>
                {t('status.running')} · {seq.zones.length}{' '}
                {seq.zones.length === 1 ? t('sequence.zone') : t('sequence.zones')}
              </span>
            )}
            {isPaused && seq.current_run && (
              <span>
                {t('status.paused')} · {seq.current_run.remaining_min.toFixed(0)} {t('sequence.minLeft')}
              </span>
            )}
            {seq.status === 'idle' && (
              <span>
                {seq.next_run_at
                  ? `${t('sequence.nextRun')} · ${new Date(seq.next_run_at).toLocaleString(i18n.language, { weekday: 'short', hour: '2-digit', minute: '2-digit' })}`
                  : formatSchedule(seq.schedule, t)}{' '}
                · {seq.zones.length} × {seq.basis_min_per_zone} min
              </span>
            )}
            {isDisabled && <span style={{ color: 'var(--n-fg-dim)' }}>{t('status.disabled')}</span>}
          </div>
        </div>
      </div>

      {isRunning && seq.current_run && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div className="n-progress" style={{ flex: 1 }}>
            <i style={{ width: `${progress}%` }} />
          </div>
          <span className="mono" style={{ fontSize: 13, color: 'var(--n-teal-200)', letterSpacing: '-0.01em', fontWeight: 500 }}>
            {seq.current_run.remaining_min.toFixed(0)} {t('sequence.minLeft')}
          </span>
        </div>
      )}

      <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
        <button
          className={`n-iconbtn${isRunning ? ' paused-state' : ' accent'}`}
          onClick={isRunning ? onPause : isPaused ? onResume : onStart}
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
          onClick={onStop}
          disabled={isDisabled || (!isRunning && !isPaused)}
          title={t('sequence.stop')}
          style={{
            width: 44,
            height: 44,
            flex: '0 0 44px',
            opacity: isDisabled || (!isRunning && !isPaused) ? 0.4 : 1,
            color: 'var(--n-fg-soft)',
          }}
        >
          <IStop size={15} />
        </button>
      </div>
    </div>
  )
}

function SequenceCardRich({ seq, color, onStart, onPause, onResume, onStop, onSchedule }: CardVariantProps) {
  const { t, i18n } = useTranslation()
  const isRunning = seq.status === 'running'
  const isPaused = seq.status === 'paused'
  const isDisabled = seq.status === 'disabled' || !seq.enabled

  const progress = runProgress(seq.current_run)

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
      {color && (
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
      )}

      {/* header */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 14 }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <span style={{ fontSize: 24, fontWeight: 600, letterSpacing: '-0.015em' }}>{seq.label}</span>
            <StatusChip status={seq.status} />
          </div>
          <span className="n-label" style={{ fontSize: 13 }}>
            {formatSchedule(seq.schedule, t)} · {seq.zones.length}{' '}
            {seq.zones.length === 1 ? t('sequence.zone') : t('sequence.zones')}
            {seq.basis_min_per_zone
              ? ` · ${t('sequence.regularPerZone', { min: seq.basis_min_per_zone })}`
              : ''}
          </span>
        </div>
      </div>

      {/* live progress */}
      {isRunning && seq.current_run && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between' }}>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
              <span className="n-bignum" style={{ fontSize: 38, color: 'var(--n-teal-200)' }}>
                {seq.current_run.remaining_min.toFixed(0)}
              </span>
              <span style={{ fontSize: 13, color: 'var(--n-fg-muted)' }}>{t('sequence.minLeft')}</span>
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
            <span style={{ fontSize: 12.5, color: 'var(--n-fg-muted)' }}>{t('sequence.remainingPaused')}</span>
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
                ? new Date(seq.next_run_at).toLocaleString(i18n.language, { weekday: 'short', hour: '2-digit', minute: '2-digit' })
                : formatSchedule(seq.schedule, t)}
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
          onClick={isRunning ? onPause : isPaused ? onResume : onStart}
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
          onClick={onStop}
          disabled={isDisabled || (!isRunning && !isPaused)}
          title={t('sequence.stop')}
          style={{ width: 44, height: 44, flex: '0 0 44px', opacity: isDisabled || (!isRunning && !isPaused) ? 0.4 : 1 }}
        >
          <IStop size={16} />
        </button>
      </div>
    </div>
  )
}
