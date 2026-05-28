import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { getSettings, getSequences, updateSettings } from '../api/client'

export default function Settings() {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const { data: settings } = useQuery({ queryKey: ['settings'], queryFn: getSettings })
  const { data: sequences = [] } = useQuery({ queryKey: ['sequences'], queryFn: getSequences })
  const [saved, setSaved] = useState(false)

  const mut = useMutation({
    mutationFn: updateSettings,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['settings'] })
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    },
  })

  function saveSeqBasis(seqId: string, val: string) {
    const num = parseFloat(val)
    if (isNaN(num)) return
    mut.mutate({ sequences: { [seqId]: { basis_min_per_zone: num } } })
  }

  function savePaused(seqId: string, paused: boolean) {
    mut.mutate({ sequences: { [seqId]: { paused } } })
  }

  if (!settings) return <div className="p-4" style={{ color: 'var(--n-text-dim)' }}>Laden…</div>

  return (
    <div className="p-4 flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">{t('settings.title')}</h2>
        {saved && <span className="text-sm" style={{ color: 'var(--n-leaf-400)' }}>✓ Gespeichert</span>}
      </div>

      {/* Sequence overrides */}
      <section className="n-card p-4 flex flex-col gap-3">
        <h3 className="font-medium">Sequenzen</h3>
        {sequences.map(seq => {
          const ov = settings.sequences[seq.id]
          return (
            <div key={seq.id} className="flex items-center justify-between gap-4">
              <div className="flex-1">
                <p className="text-sm font-medium">{seq.label}</p>
              </div>
              <input
                type="number"
                defaultValue={ov?.basis_min_per_zone ?? seq.basis_min_per_zone}
                onBlur={e => saveSeqBasis(seq.id, e.target.value)}
                className="w-20 rounded px-2 py-1 text-sm text-right"
                style={{ background: 'var(--n-bg)', border: '1px solid var(--n-border)', color: 'var(--n-text)', fontVariantNumeric: 'tabular-nums' }}
              />
              <span className="text-sm" style={{ color: 'var(--n-text-dim)' }}>min</span>
              <label className="flex items-center gap-1 text-sm">
                <input
                  type="checkbox"
                  checked={ov?.paused ?? false}
                  onChange={e => savePaused(seq.id, e.target.checked)}
                />
                <span style={{ color: 'var(--n-text-dim)' }}>Pause</span>
              </label>
            </div>
          )
        })}
      </section>

      {/* Factor settings */}
      <section className="n-card p-4 flex flex-col gap-2">
        <h3 className="font-medium">{t('settings.factorTemp')}</h3>
        <FactorRow label="Basis °C" value={settings.factors.temp.basis_c} onSave={v => mut.mutate({ factors: { temp: { basis_c: v } } })} />
        <FactorRow label="% pro °C" value={settings.factors.temp.pct_per_c} onSave={v => mut.mutate({ factors: { temp: { pct_per_c: v } } })} />
        <FactorRow label="Min %" value={settings.factors.temp.min_pct} onSave={v => mut.mutate({ factors: { temp: { min_pct: v } } })} />
        <FactorRow label="Max %" value={settings.factors.temp.max_pct} onSave={v => mut.mutate({ factors: { temp: { max_pct: v } } })} />
      </section>

      <section className="n-card p-4 flex flex-col gap-2">
        <h3 className="font-medium">{t('settings.factorRain')}</h3>
        <FactorRow label="Schwelle Prob %" value={settings.factors.rain.threshold_prob} onSave={v => mut.mutate({ factors: { rain: { threshold_prob: v } } })} />
        <FactorRow label="Reduz. ab mm" value={settings.factors.rain.reduce_above_mm} onSave={v => mut.mutate({ factors: { rain: { reduce_above_mm: v } } })} />
        <FactorRow label="Null ab mm" value={settings.factors.rain.zero_above_mm} onSave={v => mut.mutate({ factors: { rain: { zero_above_mm: v } } })} />
        <FactorRow label="Forecast Decay" value={settings.factors.rain.forecast_decay} onSave={v => mut.mutate({ factors: { rain: { forecast_decay: v } } })} />
      </section>
    </div>
  )
}

function FactorRow({ label, value, onSave }: { label: string; value: number; onSave: (v: number) => void }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-sm" style={{ color: 'var(--n-text-dim)' }}>{label}</span>
      <input
        type="number"
        defaultValue={value}
        step="any"
        onBlur={e => onSave(parseFloat(e.target.value))}
        className="w-24 rounded px-2 py-1 text-sm text-right"
        style={{ background: 'var(--n-bg)', border: '1px solid var(--n-border)', color: 'var(--n-text)', fontVariantNumeric: 'tabular-nums' }}
      />
    </div>
  )
}
