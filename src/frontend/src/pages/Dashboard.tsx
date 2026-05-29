import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import {
  getSequences,
  getStatus,
  getValves,
  pauseSequence,
  setMaster,
  startSequence,
  stopSequence,
  type SequenceState,
  type SystemStatus,
} from '../api/client'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { EmergencyStop } from '../components/EmergencyStop'
import { ILogo } from '../components/icons'
import { MasterToggle } from '../components/MasterToggle'
import { SequenceCard } from '../components/SequenceCard'
import { TodayBlock } from '../components/TodayBlock'
import { ValveGrid } from '../components/ValveGrid'
import { WeatherStrip } from '../components/WeatherStrip'
import { WeekChart } from '../components/WeekChart'
import { useWebSocket } from '../hooks/useWebSocket'

export default function Dashboard() {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const navigate = useNavigate()

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
  const { data: valves = [] } = useQuery({
    queryKey: ['valves'],
    queryFn: getValves,
    refetchInterval: 15_000,
  })

  const masterMut = useMutation({
    mutationFn: (on: boolean) => setMaster(on),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['status'] }),
  })

  useWebSocket((msg) => {
    if (['status_snapshot', 'sequence_changed', 'run_tick', 'valve_changed', 'factor_updated'].includes(msg.type)) {
      qc.invalidateQueries({ queryKey: ['sequences'] })
      qc.invalidateQueries({ queryKey: ['status'] })
      qc.invalidateQueries({ queryKey: ['valves'] })
    }
  })

  const [confirmSeq, setConfirmSeq] = useState<SequenceState | null>(null)

  async function handleStart(seq: SequenceState, durationMin?: number) {
    try {
      await startSequence(seq.id, durationMin)
      qc.invalidateQueries({ queryKey: ['sequences'] })
    } catch (e) {
      alert(e instanceof Error ? e.message : String(e))
    }
  }

  async function handleStop(id: string) {
    try {
      await stopSequence(id)
    } catch (e) {
      alert(e instanceof Error ? e.message : String(e))
    } finally {
      qc.invalidateQueries({ queryKey: ['sequences'] })
    }
  }

  async function handlePause(id: string) {
    try {
      await pauseSequence(id)
    } catch (e) {
      alert(e instanceof Error ? e.message : String(e))
    } finally {
      qc.invalidateQueries({ queryKey: ['sequences'] })
    }
  }

  async function handleEmergency() {
    // Master off is the authoritative kill; stop every running sequence even if
    // some individual stop calls fail (e.g. a sequence already ended → 409).
    await masterMut.mutateAsync(false)
    await Promise.allSettled(
      sequences.filter((s) => s.status === 'running').map((seq) => stopSequence(seq.id)),
    )
    qc.invalidateQueries({ queryKey: ['sequences'] })
  }

  const masterOn = status?.master_on ?? true

  const weekData = buildWeekData(status, t('weekdaysShort', { returnObjects: true }) as string[])
  const running = sequences.filter((s) => s.status === 'running').length
  const idle = sequences.filter((s) => s.status === 'idle').length

  return (
    <div style={{ display: 'flex', flexDirection: 'column', minHeight: '100vh' }}>
      {/* header */}
      <header
        className="n-wavebed"
        style={{
          padding: '0 24px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          borderBottom: '1px solid var(--n-line)',
          height: 88,
          flex: '0 0 88px',
          gap: 24,
          position: 'relative',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 28, minWidth: 0 }}>
          <div className="mobile-only" style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <ILogo size={24} />
            <span style={{ fontSize: 17, fontWeight: 500, color: 'var(--n-fg)' }}>Naiad</span>
          </div>

          <div className="desktop-only" style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <span className="n-eyebrow">{t('nav.dashboard')}</span>
            <span style={{ fontSize: 22, fontWeight: 500, letterSpacing: '-0.01em' }}>{t('dashboard.title')}</span>
          </div>

          <div className="desktop-only">
            <div className="n-vdivider" style={{ height: 40 }} />
          </div>

          {status && (
            <div className="desktop-only">
              <WeatherStrip sys={status} />
            </div>
          )}
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          <div className="desktop-only" style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
            <div className="n-vdivider" style={{ height: 40 }} />
            <MasterToggle on={masterOn} onToggle={() => masterMut.mutate(!masterOn)} />
            <EmergencyStop onFire={handleEmergency} />
          </div>

          <div className="mobile-only" style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <MasterToggle on={masterOn} onToggle={() => masterMut.mutate(!masterOn)} compact />
            <EmergencyStop onFire={handleEmergency} compact />
          </div>
        </div>
      </header>

      {/* mobile-only: weather + master below header */}
      {status && (
        <div className="mobile-only" style={{ padding: '12px 20px', display: 'flex', flexDirection: 'column', gap: 10 }}>
          <WeatherStrip sys={status} compact />
        </div>
      )}

      {/* TABLET: 3-column grid */}
      <main className="desktop-only" style={{
        flex: 1,
        padding: '22px 36px 28px',
        display: 'grid',
        gridTemplateColumns: '360px 1fr 440px',
        gap: 22,
        minHeight: 0,
      }}>
        {/* col 1: Today block — fills full height */}
        <div style={{ display: 'flex', flexDirection: 'column', minHeight: 0 }}>
          {status && <TodayBlock sys={status} />}
        </div>

        {/* col 2: Sequences */}
        <section style={{ display: 'flex', flexDirection: 'column', gap: 12, minHeight: 0 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', padding: '0 2px' }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              <span className="n-eyebrow">{t('dashboard.sequences')}</span>
              <span style={{ fontSize: 16, fontWeight: 500 }}>{sequences.length} {t('dashboard.configured')}</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, fontSize: 12.5 }}>
              {running > 0 && (
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: 'var(--n-teal-200)' }}>
                  <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--n-teal-300)' }} />
                  {running} {t('dashboard.running')}
                </span>
              )}
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: 'var(--n-fg-muted)' }}>
                <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--n-fg-dim)' }} />
                {idle} {t('dashboard.ready')}
              </span>
            </div>
          </div>
          <div style={{
            display: 'grid',
            gridTemplateColumns: '1fr 1fr',
            gap: 14,
            alignContent: 'start',
          }}>
            {sequences.map((seq) => (
              <SequenceCard
                key={seq.id}
                seq={seq}
                size="rich"
                onStart={() => setConfirmSeq(seq)}
                onPause={() => (seq.status === 'running' ? handlePause(seq.id) : handleStart(seq))}
                onStop={() => handleStop(seq.id)}
                onSchedule={() => navigate(`/planner?seq=${seq.id}`)}
              />
            ))}
          </div>
        </section>

        {/* col 3: Valves + Chart */}
        <section style={{ display: 'flex', flexDirection: 'column', gap: 18, minHeight: 0 }}>
          {valves.length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                  <span className="n-eyebrow">{t('dashboard.valvesLive')}</span>
                  <span style={{ fontSize: 16, fontWeight: 500 }}>{valves.length} {t('sequence.zones')}</span>
                </div>
                {valves.some((v) => v.state === 'on') && (
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8, color: 'var(--n-teal-200)', fontSize: 12.5 }}>
                    <span className="n-drop" />
                    {valves.filter((v) => v.state === 'on').length} {t('dashboard.live')}
                  </span>
                )}
              </div>
              <ValveGrid valves={valves} cols={2} />
            </div>
          )}

          <div className="n-card" style={{ padding: '16px 18px', display: 'flex', flexDirection: 'column', gap: 12, flex: 1, minHeight: 0 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                <span className="n-eyebrow">{t('dashboard.usage7d')}</span>
                <span className="mono" style={{ fontSize: 22, fontWeight: 500 }}>
                  {status?.liters_week.toFixed(0) ?? '—'} L
                </span>
              </div>
            </div>
            <WeekChart data={weekData} height={150} />
          </div>
        </section>
      </main>

      {/* MOBILE: stacked layout */}
      <main
        className="mobile-only"
        style={{
          flex: 1,
          overflowY: 'auto',
          padding: '0 20px 20px',
          display: 'flex',
          flexDirection: 'column',
          gap: 14,
        }}
      >
        {status && <TodayBlock sys={status} dense />}

        <section style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', padding: '0 2px' }}>
            <span className="n-eyebrow">{t('dashboard.sequences')}</span>
            <span className="n-label" style={{ fontSize: 11 }}>
              {running > 0 && <span style={{ color: 'var(--n-teal-200)' }}>{running} {t('dashboard.running')} · </span>}
              {idle} {t('dashboard.ready')}
            </span>
          </div>
          {sequences.map((seq) => (
            <SequenceCard
              key={seq.id}
              seq={seq}
              onStart={() => setConfirmSeq(seq)}
              onPause={() => (seq.status === 'running' ? handlePause(seq.id) : handleStart(seq))}
              onStop={() => handleStop(seq.id)}
              onSchedule={() => navigate(`/planner?seq=${seq.id}`)}
            />
          ))}
        </section>

        {valves.length > 0 && (
          <section style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', padding: '0 2px' }}>
              <span className="n-eyebrow">{t('dashboard.valves')}</span>
              {valves.some((v) => v.state === 'on') && (
                <span className="n-label" style={{ fontSize: 11, color: 'var(--n-teal-200)' }}>
                  {valves.filter((v) => v.state === 'on').length} {t('dashboard.live')}
                </span>
              )}
            </div>
            <ValveGrid valves={valves} cols={2} />
          </section>
        )}

        <div className="n-card" style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 10 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end' }}>
            <div>
              <span className="n-eyebrow">{t('dashboard.usage')}</span>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, marginTop: 4 }}>
                <span className="n-bignum" style={{ fontSize: 26 }}>{status?.liters_week.toFixed(0) ?? '—'} L</span>
                <span style={{ fontSize: 12, color: 'var(--n-fg-muted)' }}>{t('dashboard.thisWeek')}</span>
              </div>
            </div>
            <div style={{ textAlign: 'right' }}>
              <span className="mono" style={{ fontSize: 14, color: 'var(--n-teal-200)' }}>
                {status?.liters_today.toFixed(0) ?? '—'} L
              </span>
              <div className="n-label" style={{ fontSize: 11 }}>{t('dashboard.today')}</div>
            </div>
          </div>
          <WeekChart data={weekData} height={100} />
        </div>
      </main>

      {/* Confirm dialog */}
      {confirmSeq && (
        <ConfirmDialog
          open={!!confirmSeq}
          title={confirmSeq.label}
          subtitle={`${confirmSeq.schedule_label} · ${confirmSeq.zones.length} × ${confirmSeq.basis_min_per_zone} min`}
          zones={confirmSeq.zones.length}
          defaultDuration={confirmSeq.basis_min_per_zone}
          onConfirm={(dur) => {
            handleStart(confirmSeq, dur)
            setConfirmSeq(null)
          }}
          onCancel={() => setConfirmSeq(null)}
        />
      )}
    </div>
  )
}

function buildWeekData(status: SystemStatus | undefined, days: string[]) {
  // Real per-day liters from the backend (Mon..Sun of the current local week).
  const series = status?.week_series ?? []
  const todayIdx = new Date().getDay()
  const adjustedIdx = todayIdx === 0 ? 6 : todayIdx - 1

  return days.map((day, i) => ({
    day,
    liters: series[i] ?? 0,
    today: i === adjustedIdx,
  }))
}
