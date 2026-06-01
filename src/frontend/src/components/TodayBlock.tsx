import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { TFunction } from 'i18next'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { type NextRun, type SystemStatus, getSettings, skipRun, updateSettings } from '../api/client'
import { ConfirmActionDialog } from './ConfirmActionDialog'
import { InfoTip } from './InfoTip'
import { NumberField } from './NumberField'
import { toast } from './Toast'
import { IClock, IX } from './icons'

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

function formatClock(isoDate: string, lng: string): string {
  return new Date(isoDate).toLocaleString(lng, { hour: '2-digit', minute: '2-digit' })
}

/** Day heading shared by all runs in the block (they're all on the same day). */
function formatDayLabel(isoDate: string, t: TFunction, lng: string): string {
  const d = new Date(isoDate)
  const now = new Date()
  const isToday = d.toDateString() === now.toDateString()
  const tomorrow = new Date(now)
  tomorrow.setDate(tomorrow.getDate() + 1)
  const isTomorrow = d.toDateString() === tomorrow.toDateString()
  if (isToday) return t('today.today')
  if (isTomorrow) return t('today.tomorrow')
  return d.toLocaleString(lng, { weekday: 'long', day: '2-digit', month: '2-digit' })
}

function useSkip() {
  const qc = useQueryClient()
  const { t } = useTranslation()
  return useMutation({
    mutationFn: (run: NextRun) =>
      skipRun({ sequence_id: run.sequence_id, scheduled_at: run.scheduled_at, plan_id: run.plan_id }),
    onSuccess: (_d, run) => {
      toast(t('today.skipped', { name: run.sequence_label }), 'success')
      qc.invalidateQueries({ queryKey: ['status'] })
      qc.invalidateQueries({ queryKey: ['sequences'] })
    },
    onError: (e) => toast(e instanceof Error ? e.message : String(e), 'error'),
  })
}

type BreakdownItem = { label: string; delta: string; positive: boolean; tip?: string }

/**
 * Adjustment factor block: a clickable auto/manual mode chip and the combined
 * percentage. In auto mode the percentage reflects the automatic temp/rain
 * calculation and is read-only. In manual mode the breakdown is hidden and the
 * percentage becomes click-to-edit, clamped to the configured min/max bounds.
 */
function AdjustmentSection({ sys, breakdown, compact = false }: {
  sys: SystemStatus
  breakdown: BreakdownItem[]
  compact?: boolean
}) {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const f = sys.today_factor
  const { data: settings } = useQuery({ queryKey: ['settings'], queryFn: getSettings })
  const [editing, setEditing] = useState(false)

  const mut = useMutation({
    mutationFn: (factors: { manual_mode?: boolean; manual_pct?: number }) =>
      updateSettings({ factors }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['status'] })
      qc.invalidateQueries({ queryKey: ['settings'] })
      qc.invalidateQueries({ queryKey: ['sequences'] })
    },
    onError: (e) => toast(e instanceof Error ? e.message : String(e), 'error'),
  })

  const manual = f.manual
  const minPct = settings?.factors.temp.min_pct ?? 0
  const maxPct = settings?.factors.temp.max_pct ?? 200

  const toggleMode = () => {
    setEditing(false)
    // Switching to auto discards the manual value; switching to manual seeds it
    // with the current (automatic) percentage so editing starts from there.
    if (manual) mut.mutate({ manual_mode: false })
    else mut.mutate({ manual_mode: true, manual_pct: f.combined_pct })
  }

  const commitPct = (v: number) => {
    setEditing(false)
    mut.mutate({ manual_pct: v })
  }

  const bigSize = compact ? 28 : 42
  const unitSize = compact ? 12 : 16

  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10 }}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: compact ? 6 : 6 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {!compact && <span className="n-eyebrow">{t('today.adjustment')}</span>}
          <button
            type="button"
            onClick={toggleMode}
            disabled={mut.isPending}
            title={t('today.toggleMode')}
            style={{
              background: 'none', border: 'none', padding: 0, cursor: 'pointer',
              fontSize: 10,
              color: manual ? 'var(--n-leaf-300)' : 'var(--n-teal-300)',
              display: 'inline-flex', alignItems: 'center', gap: 4,
            }}
          >
            <span style={{ width: 5, height: 5, borderRadius: '50%', background: 'currentColor' }} />
            {manual ? t('today.manual') : t('today.auto')}
          </button>
        </div>
        {!manual && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
            {breakdown.map((b, i) => (
              <div key={i} style={{ display: 'flex', alignItems: 'center', gap: compact ? 8 : 10, fontSize: compact ? 11.5 : 12.5 }}>
                <span style={{ color: 'var(--n-fg-soft)', minWidth: compact ? 70 : 80, display: 'inline-flex', alignItems: 'center', gap: compact ? 4 : 5 }}>
                  {b.label}
                  {b.tip && <InfoTip text={b.tip} />}
                </span>
                <span className="mono" style={{ color: !b.positive ? 'var(--n-paused)' : 'var(--n-leaf-300)', fontWeight: 500 }}>
                  {b.delta}
                </span>
              </div>
            ))}
          </div>
        )}
        {manual && (
          <span style={{ fontSize: compact ? 11 : 12, color: 'var(--n-fg-muted)' }}>
            {t('today.manualHint', { min: minPct, max: maxPct })}
          </span>
        )}
      </div>

      {manual && editing ? (
        <NumberField
          value={f.combined_pct}
          unit="%"
          min={minPct}
          max={maxPct}
          step={1}
          width={64}
          autoFocus
          aria-label={t('today.adjustment')}
          onChange={commitPct}
        />
      ) : (
        <button
          type="button"
          onClick={manual ? () => setEditing(true) : undefined}
          disabled={!manual}
          title={manual ? t('today.editPct') : undefined}
          style={{
            background: 'none', border: 'none', padding: 0,
            display: 'flex', alignItems: 'baseline', gap: 2,
            cursor: manual ? 'pointer' : 'default',
          }}
        >
          <span className="n-bignum" style={{ fontSize: bigSize, color: 'var(--n-teal-200)', letterSpacing: '-0.03em', lineHeight: 1 }}>
            {f.combined_pct}
          </span>
          <span style={{ fontSize: unitSize, color: 'var(--n-fg-muted)' }}>%</span>
        </button>
      )}
    </div>
  )
}

export function TodayBlock({ sys, dense = false }: TodayBlockProps) {
  const { t, i18n } = useTranslation()
  const skip = useSkip()
  const { data: settings } = useQuery({ queryKey: ['settings'], queryFn: getSettings })
  // A run pending skip confirmation — guards against an accidental tap.
  const [pendingSkip, setPendingSkip] = useState<NextRun | null>(null)
  const f = sys.today_factor
  const runs = sys.upcoming_runs ?? []

  const tempTip = settings
    ? t('today.tempTip', { input: f.temp_input_c != null ? `${f.temp_input_c.toFixed(1)} °C` : '–', basis: settings.factors.temp.basis_c, pct: settings.factors.temp.pct_per_c, min: settings.factors.temp.min_pct, max: settings.factors.temp.max_pct })
    : undefined

  const rainTip = settings
    ? t('today.rainTip', { prob: f.rain_prob_pct != null ? `${Math.round(f.rain_prob_pct)} %` : '–', mm: f.rain_mm != null ? `${f.rain_mm.toFixed(1)} mm` : '–', threshold: settings.factors.rain.threshold_prob, reduce: settings.factors.rain.reduce_above_mm, zero: settings.factors.rain.zero_above_mm, decay: settings.factors.rain.forecast_decay })
    : undefined

  // Shared confirmation dialog for skipping a future run (both layouts).
  const skipDialog = pendingSkip && (
    <ConfirmActionDialog
      open={!!pendingSkip}
      title={t('confirmSkip.title')}
      message={t('confirmSkip.message', { name: pendingSkip.sequence_label, time: formatClock(pendingSkip.scheduled_at, i18n.language) })}
      confirmLabel={t('today.skip')}
      onConfirm={() => {
        skip.mutate(pendingSkip)
        setPendingSkip(null)
      }}
      onCancel={() => setPendingSkip(null)}
    />
  )

  // temp_pct and rain_pct are signed deltas from neutral (0 = no adjustment).
  const breakdown: { label: string; delta: string; positive: boolean; tip?: string }[] = [
    { label: t('weather.temp'), delta: fmtDelta(f.temp_pct), positive: f.temp_pct >= 0, tip: tempTip },
    { label: t('weather.rain'), delta: fmtDelta(f.rain_pct), positive: f.rain_pct >= 0, tip: rainTip },
  ]

  if (f.wind_blocking_sequences.length > 0) {
    breakdown.push({
      label: t('weather.wind'),
      delta: t('today.blocked', { seqs: f.wind_blocking_sequences.join(', ') }),
      positive: false,
    })
  }

  if (dense) {
    return (
      <>
        <DenseTodayBlock sys={sys} breakdown={breakdown} onSkip={setPendingSkip} />
        {skipDialog}
      </>
    )
  }

  const dayLabel = runs.length > 0 ? formatDayLabel(runs[0].scheduled_at, t, i18n.language) : null

  return (
    <>
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
        {dayLabel && (
          <span className="n-eyebrow" style={{ fontSize: 9.5, color: 'var(--n-teal-300)' }}>{dayLabel}</span>
        )}
      </div>

      {/* Upcoming runs of the day */}
      {runs.length > 0 ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {runs.map((run, i) => (
            <RunRow
              key={`${run.sequence_id}-${run.scheduled_at}`}
              run={run}
              hero={i === 0}
              t={t}
              lng={i18n.language}
              onSkip={() => setPendingSkip(run)}
              skipping={skip.isPending}
            />
          ))}
        </div>
      ) : (
        <div style={{ padding: '14px 16px', borderRadius: 12, background: 'rgba(255,255,255,0.02)', border: '1px solid var(--n-line)' }}>
          <span style={{ fontSize: 14, color: 'var(--n-fg-muted)' }}>{t('today.noRun')}</span>
        </div>
      )}

      {/* Spacer to push adjustment to bottom */}
      <div style={{ flex: 1 }} />
      <div className="n-divider" />

      {/* Adjustment factor — compact / tertiary */}
      <AdjustmentSection sys={sys} breakdown={breakdown} />
    </div>
    {skipDialog}
    </>
  )
}

function RunRow({
  run,
  hero,
  t,
  lng,
  onSkip,
  skipping,
}: {
  run: NextRun
  hero: boolean
  t: TFunction
  lng: string
  onSkip: () => void
  skipping: boolean
}) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 10,
        padding: hero ? '14px 16px' : '10px 14px',
        borderRadius: hero ? 12 : 10,
        background: hero ? 'var(--n-teal-glow)' : 'rgba(255,255,255,0.018)',
        border: hero ? '1px solid rgba(94,200,216,0.15)' : '1px solid var(--n-line)',
      }}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: hero ? 4 : 2, minWidth: 0 }}>
        <span style={{ fontSize: hero ? 20 : 15, fontWeight: 600, letterSpacing: '-0.015em', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {run.sequence_label}
        </span>
        <span className="mono" style={{ fontSize: hero ? 14 : 12.5, color: 'var(--n-teal-200)', fontWeight: 500 }}>
          {formatClock(run.scheduled_at, lng)} · {run.duration_min} min
          {hero && <span style={{ color: 'var(--n-fg-soft)' }}> · {formatRelative(run.scheduled_at, t)}</span>}
        </span>
      </div>
      <button
        className="n-btn ghost"
        onClick={onSkip}
        disabled={skipping}
        title={t('today.skip')}
        style={{
          display: 'inline-flex', alignItems: 'center', gap: 6,
          height: 32, padding: '0 10px', fontSize: 12, flex: '0 0 auto',
          color: 'var(--n-fg-muted)',
        }}
      >
        <IX size={13} />
        <span>{t('today.skip')}</span>
      </button>
    </div>
  )
}

function DenseTodayBlock({
  sys,
  breakdown,
  onSkip,
}: {
  sys: SystemStatus
  breakdown: { label: string; delta: string; positive: boolean; tip?: string }[]
  onSkip: (run: NextRun) => void
}) {
  const { t, i18n } = useTranslation()
  const runs = sys.upcoming_runs ?? []
  const dayLabel = runs.length > 0 ? formatDayLabel(runs[0].scheduled_at, t, i18n.language) : null

  return (
    <div className="n-card" style={{ padding: '16px 18px', display: 'flex', flexDirection: 'column', gap: 12 }}>
      {runs.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
            <span className="n-eyebrow" style={{ fontSize: 9.5 }}>{t('today.title')}</span>
            {dayLabel && <span className="n-eyebrow" style={{ fontSize: 9, color: 'var(--n-teal-300)' }}>{dayLabel}</span>}
          </div>
          {runs.map((run, i) => (
            <div
              key={`${run.sequence_id}-${run.scheduled_at}`}
              style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8,
                padding: '8px 10px', borderRadius: 8,
                background: i === 0 ? 'var(--n-teal-glow)' : 'rgba(255,255,255,0.018)',
                border: i === 0 ? '1px solid rgba(94,200,216,0.15)' : '1px solid var(--n-line)',
              }}
            >
              <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: 14, fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{run.sequence_label}</div>
                <span className="mono" style={{ fontSize: 11.5, color: 'var(--n-teal-200)' }}>
                  {formatClock(run.scheduled_at, i18n.language)} · {run.duration_min} min
                </span>
              </div>
              <button
                className="n-iconbtn"
                onClick={() => onSkip(run)}
                title={t('today.skip')}
                style={{ width: 32, height: 32, flex: '0 0 32px', color: 'var(--n-fg-muted)' }}
              >
                <IX size={14} />
              </button>
            </div>
          ))}
        </div>
      )}
      {runs.length === 0 && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12.5, color: 'var(--n-fg-muted)' }}>
          <IClock size={13} /> {t('today.noRun')}
        </div>
      )}

      <div className="n-divider" />

      {/* Adjustment — inline */}
      <AdjustmentSection sys={sys} breakdown={breakdown} compact />
    </div>
  )
}
