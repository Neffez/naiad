import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { queryKeys } from '../api/queryKeys'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { type ConfigDoc, deleteHistory, getConfig, getHistory, type HistoryEntry } from '../api/client'
import { ConfirmActionDialog } from '../components/ConfirmActionDialog'
import { LoadError } from '../components/LoadError'
import { IClock, IPlay } from '../components/icons'
import { resolveSeqColor } from '../theme/sequenceColors'

const OLDER_THAN_DAYS = 30

function fmtDur(min: number | null): string {
  if (min == null) return '—'
  if (min < 60) return `${min.toFixed(0)} min`
  return `${(min / 60).toFixed(1)} h`
}

function fmtDate(iso: string, lng: string): string {
  return new Date(iso).toLocaleString(lng, {
    day: '2-digit', month: '2-digit',
    hour: '2-digit', minute: '2-digit',
  })
}

const COLS = [
  { key: 'zone', labelKey: 'history.zone', flex: 1.3 },
  { key: 'seq', labelKey: 'history.sequence', flex: 1 },
  { key: 'started', labelKey: 'history.started', flex: 1.2 },
  { key: 'dur', labelKey: 'history.duration', flex: 0.7 },
  { key: 'liters', labelKey: 'history.liters', flex: 0.7 },
  { key: 'trigger', labelKey: 'history.trigger', flex: 0.8 },
] as const

export default function History() {
  const { t, i18n } = useTranslation()
  const [page, setPage] = useState(1)
  const [confirm, setConfirm] = useState<null | 'all' | 'old'>(null)
  const qc = useQueryClient()

  const { data, isError } = useQuery({
    queryKey: queryKeys.historyPage(page),
    queryFn: () => getHistory({ page, per_page: 50 }),
  })
  // Fetched once for the whole table (sequence accent colors); passed down so each
  // row doesn't open its own ['config'] query subscription.
  const { data: config } = useQuery({ queryKey: queryKeys.config, queryFn: getConfig })

  const deleteMut = useMutation({
    mutationFn: (olderThanDays?: number) => deleteHistory(olderThanDays),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.history })
      setPage(1)
      setConfirm(null)
    },
  })

  const items = data?.items ?? []
  const totalLiters = items.reduce((a, r) => a + (r.liters ?? 0), 0)
  const avgDur = items.length > 0
    ? Math.round(items.reduce((a, r) => a + (r.duration_min ?? 0), 0) / items.length)
    : 0

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
      {/* Summary bar */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 24,
        marginBottom: 22, flexWrap: 'wrap',
      }}>
        <div style={{ display: 'flex', gap: 32, flexWrap: 'wrap', flex: 1 }}>
          <SummaryBlock
            label={t('history.last7days')}
            value={`${Math.round(totalLiters).toLocaleString(i18n.language)} L`}
          />
          <div className="n-vdivider" style={{ height: 44 }} />
          <SummaryBlock
            label={t('history.totalRuns')}
            value={String(data?.total ?? 0)}
          />
          <div className="n-vdivider" style={{ height: 44 }} />
          <SummaryBlock
            label={t('history.avgDuration')}
            value={`${avgDur} min`}
          />
        </div>

        {/* History maintenance actions — affect run history only, never
            settings or plans. */}
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          <button
            className="n-btn danger"
            onClick={() => setConfirm('old')}
            disabled={deleteMut.isPending}
            style={{ height: 36, padding: '0 14px', fontSize: 13 }}
          >
            {t('history.deleteOld')}
          </button>
          <button
            className="n-btn danger"
            onClick={() => setConfirm('all')}
            disabled={deleteMut.isPending}
            style={{ height: 36, padding: '0 14px', fontSize: 13 }}
          >
            {t('history.deleteAll')}
          </button>
        </div>
      </div>

      {/* Table header */}
      <div style={{
        display: 'flex', alignItems: 'center',
        padding: '12px 18px',
        borderBottom: '1px solid var(--n-line-bright)',
      }}>
        {COLS.map((c) => (
          <span key={c.key} className="n-eyebrow" style={{
            flex: c.flex, fontSize: 11, letterSpacing: '0.05em',
          }}>
            {t(c.labelKey)}
          </span>
        ))}
      </div>

      {/* Table rows */}
      {items.map((row) => (
        <HistoryRow key={row.id} row={row} config={config} />
      ))}

      {/* Empty / error state */}
      {items.length === 0 && (
        isError ? (
          <div style={{ padding: '24px 0' }}><LoadError /></div>
        ) : (
          <div style={{
            padding: '32px 0', textAlign: 'center',
            color: 'var(--n-fg-muted)', fontSize: 14,
          }}>
            {t('history.empty')}
          </div>
        )
      )}

      {/* Pagination */}
      {data && data.total > data.per_page && (
        <div style={{
          display: 'flex', justifyContent: 'center', alignItems: 'center',
          gap: 12, padding: '18px 0',
        }}>
          <button
            className="n-btn"
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page === 1}
            style={{ height: 36, padding: '0 14px', fontSize: 13 }}
          >
            ← {t('history.prev')}
          </button>
          <span className="mono" style={{ fontSize: 13, color: 'var(--n-fg-muted)' }}>
            {page} / {Math.ceil(data.total / data.per_page)}
          </span>
          <button
            className="n-btn"
            onClick={() => setPage((p) => p + 1)}
            disabled={page >= Math.ceil(data.total / data.per_page)}
            style={{ height: 36, padding: '0 14px', fontSize: 13 }}
          >
            {t('history.next')} →
          </button>
        </div>
      )}

      <ConfirmActionDialog
        open={confirm === 'old'}
        title={t('history.deleteOldTitle')}
        message={t('history.deleteOldMessage')}
        confirmLabel={t('history.deleteConfirm')}
        tone="danger"
        onConfirm={() => deleteMut.mutate(OLDER_THAN_DAYS)}
        onCancel={() => setConfirm(null)}
      />
      <ConfirmActionDialog
        open={confirm === 'all'}
        title={t('history.deleteAllTitle')}
        message={t('history.deleteAllMessage')}
        confirmLabel={t('history.deleteConfirm')}
        tone="danger"
        onConfirm={() => deleteMut.mutate(undefined)}
        onCancel={() => setConfirm(null)}
      />
    </div>
  )
}

function SummaryBlock({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      <span className="n-eyebrow">{label}</span>
      <span className="mono" style={{ fontSize: 28, fontWeight: 500, letterSpacing: '-0.02em' }}>
        {value}
      </span>
    </div>
  )
}

function HistoryRow({ row, config }: { row: HistoryEntry; config: ConfigDoc | undefined }) {
  const { t, i18n } = useTranslation()
  const isManual = row.triggered_by === 'manual'
  const triggerLabel = isManual ? t('history.manual') : t('history.scheduled')
  const barColor = resolveSeqColor(config, row.sequence_id) ?? 'var(--n-fg-dim)'

  return (
    <div
      style={{
        display: 'flex', alignItems: 'center',
        padding: '13px 18px',
        borderBottom: '1px solid var(--n-line)',
        opacity: row.aborted ? 0.6 : 1,
      }}
    >
      <span style={{
        flex: COLS[0].flex, fontSize: 13.5, fontWeight: 500,
        display: 'flex', alignItems: 'center', gap: 10,
      }}>
        <span aria-hidden="true" style={{
          width: 4, height: 22, borderRadius: 2,
          background: barColor,
        }} />
        {row.zone_label}
      </span>
      <span style={{ flex: COLS[1].flex, fontSize: 13.5, color: 'var(--n-fg-soft)' }}>
        {row.sequence_label}
      </span>
      <span className="mono" style={{ flex: COLS[2].flex, fontSize: 13, color: 'var(--n-fg-soft)' }}>
        {fmtDate(row.started_at, i18n.language)}
      </span>
      <span className="mono" style={{ flex: COLS[3].flex, fontSize: 13, color: 'var(--n-fg-soft)' }}>
        {fmtDur(row.duration_min)}
      </span>
      <span className="mono" style={{ flex: COLS[4].flex, fontSize: 13, color: 'var(--n-teal-200)' }}>
        {row.liters != null ? `${row.liters.toFixed(0)} L` : '—'}
      </span>
      <span style={{ flex: COLS[5].flex, fontSize: 12.5 }}>
        {row.aborted ? (
          <span style={{
            display: 'inline-flex', alignItems: 'center', gap: 6,
            padding: '4px 10px', borderRadius: 999,
            border: '1px solid rgba(255,100,100,0.30)',
            background: 'rgba(255,100,100,0.08)',
            color: 'var(--n-danger)',
            fontSize: 11.5, fontWeight: 500,
          }}>
            ⚠ {row.abort_reason ? t(`abortReason.${row.abort_reason}`, { defaultValue: row.abort_reason }) : t('history.aborted')}
          </span>
        ) : (
          <span style={{
            display: 'inline-flex', alignItems: 'center', gap: 6,
            padding: '4px 10px', borderRadius: 999,
            border: '1px solid var(--n-line-strong)',
            background: isManual ? 'var(--n-paused-soft)' : 'rgba(255,255,255,0.02)',
            color: isManual ? 'var(--n-paused)' : 'var(--n-fg-muted)',
            fontSize: 11.5, fontWeight: 500,
          }}>
            {isManual ? <IPlay size={11} /> : <IClock size={11} />}
            {triggerLabel}
          </span>
        )}
      </span>
    </div>
  )
}
