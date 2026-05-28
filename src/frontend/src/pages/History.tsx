import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { getHistory } from '../api/client'

export default function History() {
  const { t } = useTranslation()
  const [page, setPage] = useState(1)

  const { data } = useQuery({
    queryKey: ['history', page],
    queryFn: () => getHistory({ page, per_page: 50 }),
  })

  function fmtDur(min: number | null) {
    if (min == null) return '—'
    if (min < 60) return `${min.toFixed(0)} min`
    return `${(min / 60).toFixed(1)} h`
  }

  return (
    <div className="p-4 flex flex-col gap-4">
      <h2 className="text-lg font-semibold">{t('history.title')}</h2>

      <div className="n-card overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr style={{ borderBottom: '1px solid var(--n-border)', color: 'var(--n-text-dim)' }}>
              <th className="text-left p-3">{t('history.zone')}</th>
              <th className="text-left p-3">{t('history.sequence')}</th>
              <th className="text-left p-3">{t('history.started')}</th>
              <th className="text-right p-3">{t('history.duration')}</th>
              <th className="text-right p-3">{t('history.liters')}</th>
              <th className="text-left p-3">{t('history.trigger')}</th>
            </tr>
          </thead>
          <tbody>
            {data?.items.map(row => (
              <tr key={row.id} style={{ borderBottom: '1px solid var(--n-border)', opacity: row.aborted ? 0.6 : 1 }}>
                <td className="p-3">{row.zone_label}</td>
                <td className="p-3" style={{ color: 'var(--n-text-dim)' }}>{row.sequence_label}</td>
                <td className="p-3" style={{ fontVariantNumeric: 'tabular-nums', color: 'var(--n-text-dim)' }}>
                  {new Date(row.started_at).toLocaleString()}
                </td>
                <td className="p-3 text-right" style={{ fontVariantNumeric: 'tabular-nums' }}>
                  {fmtDur(row.duration_min)}
                </td>
                <td className="p-3 text-right" style={{ fontVariantNumeric: 'tabular-nums' }}>
                  {row.liters != null ? `${row.liters.toFixed(0)} L` : '—'}
                </td>
                <td className="p-3" style={{ color: row.aborted ? 'var(--n-danger)' : 'var(--n-text-dim)' }}>
                  {row.aborted ? `⚠ ${row.abort_reason ?? 'aborted'}` : row.triggered_by}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {data && data.total > data.per_page && (
        <div className="flex justify-center gap-3 text-sm">
          <button
            onClick={() => setPage(p => Math.max(1, p - 1))}
            disabled={page === 1}
            className="px-3 py-1 rounded"
            style={{ background: 'var(--n-card)', border: '1px solid var(--n-border)' }}
          >← Zurück</button>
          <span style={{ color: 'var(--n-text-dim)' }}>{page} / {Math.ceil(data.total / data.per_page)}</span>
          <button
            onClick={() => setPage(p => p + 1)}
            disabled={page >= Math.ceil(data.total / data.per_page)}
            className="px-3 py-1 rounded"
            style={{ background: 'var(--n-card)', border: '1px solid var(--n-border)' }}
          >Weiter →</button>
        </div>
      )}
    </div>
  )
}
