import { useQuery, useQueryClient } from '@tanstack/react-query'
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

const STATUS_COLOR: Record<string, string> = {
  running: 'var(--n-teal-300)',
  idle: 'var(--n-leaf-400)',
  paused: 'var(--n-paused)',
  disabled: 'var(--n-text-dim)',
}

function StatusDot({ status }: { status: string }) {
  const color = STATUS_COLOR[status] ?? 'var(--n-text-dim)'
  return (
    <span
      className={status === 'running' ? 'n-pulse' : ''}
      style={{ display: 'inline-block', width: 8, height: 8, borderRadius: '50%', background: color, marginRight: 6 }}
    />
  )
}

function SequenceCard({ seq, onStart, onStop, onPause }: {
  seq: SequenceState
  onStart: () => void
  onStop: () => void
  onPause: () => void
}) {
  const { t } = useTranslation()
  const isRunning = seq.status === 'running'
  const isPaused = seq.status === 'paused'

  return (
    <div
      className="n-card p-4 flex flex-col gap-2"
      style={isRunning ? { borderColor: 'var(--n-teal-600)', boxShadow: '0 0 16px rgba(94,200,216,0.15)' } : undefined}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center">
          <StatusDot status={seq.status} />
          <span className="font-medium">{seq.label}</span>
        </div>
        <span className="text-xs" style={{ color: STATUS_COLOR[seq.status] }}>
          {t(`status.${seq.status}`)}
        </span>
      </div>

      {seq.factor_note && (
        <p className="text-xs" style={{ color: 'var(--n-paused)' }}>{seq.factor_note}</p>
      )}

      <div className="text-xs" style={{ color: 'var(--n-text-dim)' }}>
        {seq.zones.map(z => z.label).join(' → ')}
      </div>

      <div className="flex gap-2 mt-1">
        {!isRunning && !isPaused && seq.enabled && (
          <button
            onClick={onStart}
            className="flex-1 rounded-lg py-1.5 text-sm font-medium"
            style={{ background: 'var(--n-teal-600)', color: '#fff' }}
          >
            ▶ {t('sequence.start')}
          </button>
        )}
        {isRunning && (
          <>
            <button
              onClick={onPause}
              className="flex-1 rounded-lg py-1.5 text-sm"
              style={{ border: '1px solid var(--n-paused)', color: 'var(--n-paused)' }}
            >
              ⏸ {t('sequence.pause')}
            </button>
            <button
              onClick={onStop}
              className="flex-1 rounded-lg py-1.5 text-sm"
              style={{ border: '1px solid var(--n-danger)', color: 'var(--n-danger)' }}
            >
              ⏹ {t('sequence.stop')}
            </button>
          </>
        )}
        {isPaused && (
          <button
            onClick={onStart}
            className="flex-1 rounded-lg py-1.5 text-sm"
            style={{ border: '1px solid var(--n-leaf-400)', color: 'var(--n-leaf-400)' }}
          >
            ▶ {t('sequence.resume')}
          </button>
        )}
      </div>
    </div>
  )
}

export default function Dashboard() {
  const { t } = useTranslation()
  const qc = useQueryClient()

  const { data: status } = useQuery<SystemStatus>({
    queryKey: ['status'],
    queryFn: getStatus,
    refetchInterval: 30_000,
  })
  const { data: sequences = [] } = useQuery<SequenceState[]>({
    queryKey: ['sequences'],
    queryFn: getSequences,
    refetchInterval: 10_000,
  })

  useWebSocket((msg) => {
    if (msg.type === 'status_snapshot' || msg.type === 'sequence_changed') {
      qc.invalidateQueries({ queryKey: ['sequences'] })
      qc.invalidateQueries({ queryKey: ['status'] })
    }
    if (msg.type === 'valve_changed') {
      qc.invalidateQueries({ queryKey: ['valves'] })
    }
  })

  async function handleMaster() {
    if (!status) return
    await setMaster(!status.master_on)
    qc.invalidateQueries({ queryKey: ['status'] })
  }

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

  const masterOn = status?.master_on ?? true

  return (
    <div className="p-4 flex flex-col gap-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold" style={{ color: 'var(--n-teal-300)' }}>Naiad</h1>
        <button
          onClick={handleMaster}
          className="rounded-full px-4 py-1.5 text-sm font-medium transition-colors"
          style={{
            background: masterOn ? 'var(--n-teal-600)' : 'var(--n-card)',
            color: masterOn ? '#fff' : 'var(--n-text-dim)',
            border: masterOn ? 'none' : '1px solid var(--n-border)',
          }}
        >
          {masterOn ? t('master.on') : t('master.off')}
        </button>
      </div>

      {/* Weather strip */}
      {status && (
        <div className="n-card px-4 py-2 flex gap-6 text-sm" style={{ color: 'var(--n-text-dim)' }}>
          {status.weather.temp_c != null && <span>🌡 {status.weather.temp_c.toFixed(1)} °C</span>}
          <span>🌧 {status.weather.rain_24h_mm.toFixed(1)} mm</span>
          {status.weather.wind_label === 'on' && <span style={{ color: 'var(--n-paused)' }}>💨 {t('weather.windOn')}</span>}
          {!status.weather.season_active && <span style={{ color: 'var(--n-paused)' }}>❄ {t('weather.seasonOff')}</span>}
          <span className="ml-auto">
            {t('sequence.factor')}: <strong style={{ color: 'var(--n-teal-300)', fontVariantNumeric: 'tabular-nums' }}>
              {status.today_factor.combined_pct} %
            </strong>
          </span>
        </div>
      )}

      {/* Next run */}
      {status?.next_run && (
        <div className="n-card px-4 py-3" style={{ borderColor: 'var(--n-teal-600)' }}>
          <p className="text-xs" style={{ color: 'var(--n-text-dim)' }}>{t('sequence.nextRun')}</p>
          <p className="font-medium" style={{ color: 'var(--n-teal-300)' }}>
            {status.next_run.sequence_label}
          </p>
          <p className="text-sm" style={{ color: 'var(--n-text-dim)' }}>
            {new Date(status.next_run.scheduled_at).toLocaleString()} · {status.next_run.duration_min} min
          </p>
        </div>
      )}

      {/* Sequence grid */}
      <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))' }}>
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

      {/* HA disconnected warning */}
      {status && !status.ha_connected && (
        <div className="n-card px-4 py-2 text-sm" style={{ borderColor: 'var(--n-danger)', color: 'var(--n-danger)' }}>
          ⚠ {t('errors.notConnected')}
        </div>
      )}
    </div>
  )
}
