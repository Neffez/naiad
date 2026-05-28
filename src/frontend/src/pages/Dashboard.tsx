import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import {
  getSequences,
  getStatus,
  pauseSequence,
  setMaster,
  startSequence,
  stopSequence,
  type SequenceState,
  type SystemStatus,
} from '../api/client'
import { useWebSocket } from '../hooks/useWebSocket'

// ── Helpers ───────────────────────────────────────────────────────────────────

function ledClass(status: string) {
  return `n-led n-led-${status === 'running' ? 'running' : status === 'paused' ? 'paused' : status === 'disabled' ? 'disabled' : 'idle'}`
}
function chipClass(status: string) {
  const map: Record<string, string> = { running: 'n-chip-running', idle: 'n-chip-idle', paused: 'n-chip-paused', disabled: 'n-chip-disabled' }
  return `n-chip ${map[status] ?? 'n-chip-disabled'}`
}
function statusLabel(status: string, t: (k: string) => string) {
  return t(`status.${status}` as never) || status
}

// ── Weather strip ─────────────────────────────────────────────────────────────

function WeatherStrip({ sys }: { sys: SystemStatus }) {
  const { t } = useTranslation()
  const w = sys.weather
  const f = sys.today_factor
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 20, flexWrap: 'wrap' }}>
      {w.temp_c != null && (
        <span className="n-num" style={{ color: 'var(--n-text-2)', fontSize: 13 }}>
          🌡 <strong style={{ color: 'var(--n-text)' }}>{w.temp_c.toFixed(1)}°C</strong>
        </span>
      )}
      <span className="n-num" style={{ color: 'var(--n-text-2)', fontSize: 13 }}>
        🌧 <strong style={{ color: 'var(--n-text)' }}>{w.rain_24h_mm.toFixed(1)} mm</strong>
      </span>
      {w.wind_label === 'on' && (
        <span style={{ color: 'var(--n-paused)', fontSize: 13, fontWeight: 600 }}>💨 {t('weather.windOn')}</span>
      )}
      {!w.season_active && (
        <span style={{ color: 'var(--n-paused)', fontSize: 13, fontWeight: 600 }}>❄ {t('weather.seasonOff')}</span>
      )}
      <span style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, color: 'var(--n-text-2)' }}>
        {t('sequence.factor')}:&nbsp;
        <strong className="n-num" style={{ color: 'var(--n-teal-300)', fontSize: 16 }}>
          {f.combined_pct} %
        </strong>
        {f.wind_blocking_sequences.length > 0 && (
          <span style={{ color: 'var(--n-paused)', fontSize: 11 }}>
            (Wind sperrt: {f.wind_blocking_sequences.join(', ')})
          </span>
        )}
      </span>
    </div>
  )
}

// ── Header ────────────────────────────────────────────────────────────────────

function Header({ sys, onMaster }: { sys?: SystemStatus; onMaster: () => void }) {
  const { t } = useTranslation()
  const masterOn = sys?.master_on ?? true

  return (
    <div style={{
      background: 'var(--n-surface)',
      borderBottom: '1px solid var(--n-border)',
      padding: '14px 20px',
      display: 'flex',
      flexDirection: 'column',
      gap: 10,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        {/* Logo */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 20 }}>🌊</span>
          <span style={{ fontSize: 17, fontWeight: 700, color: 'var(--n-teal-300)', letterSpacing: '-0.3px' }}>
            Naiad
          </span>
        </div>

        <div style={{ flex: 1 }} />

        {/* HA disconnect badge */}
        {sys && !sys.ha_connected && (
          <span style={{ fontSize: 11, color: 'var(--n-danger)', border: '1px solid rgba(196,90,90,0.4)', borderRadius: 6, padding: '2px 8px' }}>
            HA offline
          </span>
        )}

        {/* Master toggle */}
        <button
          className="n-btn"
          onClick={onMaster}
          style={{
            background: masterOn ? 'var(--n-teal-700)' : 'rgba(255,255,255,0.04)',
            color: masterOn ? 'var(--n-teal-300)' : 'var(--n-text-3)',
            border: masterOn ? '1px solid var(--n-teal-600)' : '1px solid var(--n-border-hi)',
            minWidth: 110,
          }}
        >
          <span style={{
            width: 8, height: 8, borderRadius: '50%',
            background: masterOn ? 'var(--n-teal-300)' : 'var(--n-text-3)',
            boxShadow: masterOn ? '0 0 6px var(--n-teal-300)' : 'none',
            animation: masterOn ? 'n-pulse-led 2s ease-in-out infinite' : 'none',
          }} />
          {masterOn ? t('master.on') : t('master.off')}
        </button>
      </div>

      {/* Weather strip */}
      {sys && <WeatherStrip sys={sys} />}
    </div>
  )
}

// ── Sequence card ─────────────────────────────────────────────────────────────

function SequenceCard({ seq, onStart, onStop, onPause }: {
  seq: SequenceState
  onStart: () => void
  onStop: () => void
  onPause: () => void
}) {
  const { t } = useTranslation()
  const isRunning = seq.status === 'running'
  const isPaused  = seq.status === 'paused'
  const isDisabled = seq.status === 'disabled' || !seq.enabled

  const progress = seq.current_run
    ? Math.min(100, (seq.current_run.elapsed_min / (seq.current_run.elapsed_min + seq.current_run.remaining_min)) * 100)
    : 0

  return (
    <div
      className={`n-card n-fade-in${isRunning ? ' n-card-running' : ''}`}
      style={{ padding: '16px 18px', display: 'flex', flexDirection: 'column', gap: 10, opacity: isDisabled ? 0.45 : 1 }}
    >
      {/* Title row */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span className={ledClass(seq.status)} />
          <span style={{ fontWeight: 600, fontSize: 14, color: 'var(--n-text)' }}>{seq.label}</span>
        </div>
        <span className={chipClass(seq.status)}>{statusLabel(seq.status, t)}</span>
      </div>

      {/* Progress bar (running only) */}
      {isRunning && seq.current_run && (
        <div>
          <div className="n-progress">
            <div className="n-progress-fill" style={{ width: `${progress}%` }} />
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 4, fontSize: 11, color: 'var(--n-text-2)' }}>
            <span className="n-num">{seq.current_run.elapsed_min.toFixed(0)} min vergangen</span>
            <span className="n-num" style={{ color: 'var(--n-teal-300)' }}>
              noch {seq.current_run.remaining_min.toFixed(0)} min
            </span>
          </div>
        </div>
      )}

      {/* Zone list */}
      <div style={{ fontSize: 12, color: 'var(--n-text-3)', display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        {seq.zones.map((z, i) => (
          <span key={z.id} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            {i > 0 && <span>→</span>}
            <span style={{ color: z.valve_state === 'on' ? 'var(--n-teal-300)' : 'var(--n-text-3)' }}>
              {z.label}
            </span>
          </span>
        ))}
      </div>

      {/* Meta row */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 12 }}>
        <span style={{ color: 'var(--n-text-3)' }}>
          {seq.basis_min_per_zone} min/Zone
        </span>
        {seq.factor_note && (
          <span style={{ color: 'var(--n-paused)', fontSize: 11 }}>{seq.factor_note}</span>
        )}
        {!seq.factor_note && (
          <span className="n-num" style={{ color: 'var(--n-text-3)' }}>
            {seq.factor_pct} %
          </span>
        )}
      </div>

      {/* Actions */}
      {!isDisabled && (
        <div style={{ display: 'flex', gap: 6, marginTop: 2 }}>
          {!isRunning && !isPaused && (
            <button className="n-btn n-btn-primary" style={{ flex: 1 }} onClick={onStart}>
              ▶ {t('sequence.start')}
            </button>
          )}
          {isPaused && (
            <button className="n-btn n-btn-primary" style={{ flex: 1 }} onClick={onStart}>
              ▶ {t('sequence.resume')}
            </button>
          )}
          {isRunning && (
            <>
              <button className="n-btn n-btn-amber" style={{ flex: 1 }} onClick={onPause}>
                ⏸ {t('sequence.pause')}
              </button>
              <button className="n-btn n-btn-danger" style={{ flex: 1 }} onClick={onStop}>
                ⏹ {t('sequence.stop')}
              </button>
            </>
          )}
        </div>
      )}
    </div>
  )
}

// ── Main dashboard ────────────────────────────────────────────────────────────

export default function Dashboard() {
  const qc = useQueryClient()

  const { data: status } = useQuery<SystemStatus>({
    queryKey: ['status'],
    queryFn: getStatus,
    refetchInterval: 30_000,
  })
  const { data: sequences = [] } = useQuery<SequenceState[]>({
    queryKey: ['sequences'],
    queryFn: getSequences,
    refetchInterval: 15_000,
  })

  const masterMut = useMutation({
    mutationFn: (on: boolean) => setMaster(on),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['status'] }),
  })

  useWebSocket((msg) => {
    if (['status_snapshot', 'sequence_changed', 'run_tick'].includes(msg.type)) {
      qc.invalidateQueries({ queryKey: ['sequences'] })
      qc.invalidateQueries({ queryKey: ['status'] })
    }
  })

  async function handleStart(id: string) {
    try {
      await startSequence(id)
      qc.invalidateQueries({ queryKey: ['sequences'] })
    } catch (e) {
      alert(e instanceof Error ? e.message : String(e))
    }
  }

  async function handleStop(id: string) {
    await stopSequence(id)
    qc.invalidateQueries({ queryKey: ['sequences'] })
  }

  async function handlePause(id: string) {
    await pauseSequence(id)
    qc.invalidateQueries({ queryKey: ['sequences'] })
  }

  // Next run block (from status or first upcoming sequence)
  const nextRun = status?.next_run

  return (
    <div style={{ display: 'flex', flexDirection: 'column', minHeight: '100vh' }}>
      <Header sys={status} onMaster={() => masterMut.mutate(!(status?.master_on ?? true))} />

      <div style={{ padding: '20px', maxWidth: 1200, margin: '0 auto', width: '100%', display: 'flex', flexDirection: 'column', gap: 16 }}>

        {/* Next run banner */}
        {nextRun && (
          <div className="n-card" style={{
            padding: '14px 18px',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            borderColor: 'var(--n-teal-700)',
            background: 'rgba(26,122,138,0.08)',
          }}>
            <div>
              <div style={{ fontSize: 11, color: 'var(--n-text-3)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 3 }}>
                Nächster Lauf
              </div>
              <div style={{ fontSize: 16, fontWeight: 600, color: 'var(--n-teal-300)' }}>{nextRun.sequence_label}</div>
            </div>
            <div style={{ textAlign: 'right' }}>
              <div className="n-num" style={{ fontSize: 14, color: 'var(--n-text)' }}>
                {new Date(nextRun.scheduled_at).toLocaleString('de', { weekday: 'short', hour: '2-digit', minute: '2-digit' })}
              </div>
              <div style={{ fontSize: 12, color: 'var(--n-text-2)', marginTop: 2 }}>
                {nextRun.duration_min} min/Zone
              </div>
            </div>
          </div>
        )}

        {/* Sequence grid */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))',
          gap: 12,
        }}>
          {sequences.map(seq => (
            <SequenceCard
              key={seq.id}
              seq={seq}
              onStart={() => handleStart(seq.id)}
              onStop={() => handleStop(seq.id)}
              onPause={() => handlePause(seq.id)}
            />
          ))}
        </div>

        {/* Liter summary */}
        {status && (
          <div style={{ display: 'flex', gap: 12 }}>
            {[
              { label: 'Heute', value: status.liters_today },
              { label: 'Diese Woche', value: status.liters_week },
            ].map(({ label, value }) => (
              <div key={label} className="n-card" style={{ flex: 1, padding: '12px 16px' }}>
                <div style={{ fontSize: 11, color: 'var(--n-text-3)', marginBottom: 4 }}>{label}</div>
                <div className="n-num" style={{ fontSize: 22, fontWeight: 600, color: 'var(--n-teal-300)' }}>
                  {value.toFixed(0)} <span style={{ fontSize: 13, fontWeight: 400, color: 'var(--n-text-2)' }}>L</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
