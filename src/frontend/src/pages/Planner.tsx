import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { type FormEvent, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { createPlan, deletePlan, getPlans, getSequences, type CreatePlanRequest } from '../api/client'

export default function Planner() {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const { data: plans = [] } = useQuery({ queryKey: ['plans'], queryFn: getPlans })
  const { data: sequences = [] } = useQuery({ queryKey: ['sequences'], queryFn: getSequences })

  const [seqId, setSeqId] = useState('')
  const [mode, setMode] = useState<'in_hours' | 'at_datetime'>('in_hours')
  const [value, setValue] = useState('4')
  const [durMin, setDurMin] = useState('')
  const [error, setError] = useState('')

  const createMut = useMutation({
    mutationFn: (body: CreatePlanRequest) => createPlan(body),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['plans'] }); setError('') },
    onError: (e: Error) => setError(e.message),
  })

  const deleteMut = useMutation({
    mutationFn: deletePlan,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['plans'] }),
  })

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!seqId) return
    const req: CreatePlanRequest = {
      sequence_id: seqId,
      mode,
      value: mode === 'in_hours' ? parseFloat(value) : value,
    }
    if (durMin) req.duration_min = parseInt(durMin)
    createMut.mutate(req)
  }

  return (
    <div className="p-4 flex flex-col gap-4">
      <h2 className="text-lg font-semibold">{t('planner.title')}</h2>

      <form onSubmit={submit} className="n-card p-4 flex flex-col gap-3">
        <select
          value={seqId}
          onChange={e => setSeqId(e.target.value)}
          className="rounded-lg px-3 py-2"
          style={{ background: 'var(--n-bg)', border: '1px solid var(--n-border)', color: 'var(--n-text)' }}
        >
          <option value="">— Sequenz wählen —</option>
          {sequences.filter(s => s.enabled).map(s => (
            <option key={s.id} value={s.id}>{s.label}</option>
          ))}
        </select>

        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => setMode('in_hours')}
            className="flex-1 rounded-lg py-1.5 text-sm"
            style={{
              background: mode === 'in_hours' ? 'var(--n-teal-600)' : 'var(--n-card)',
              color: mode === 'in_hours' ? '#fff' : 'var(--n-text-dim)',
              border: '1px solid var(--n-border)',
            }}
          >
            {t('planner.inHours')}
          </button>
          <button
            type="button"
            onClick={() => setMode('at_datetime')}
            className="flex-1 rounded-lg py-1.5 text-sm"
            style={{
              background: mode === 'at_datetime' ? 'var(--n-teal-600)' : 'var(--n-card)',
              color: mode === 'at_datetime' ? '#fff' : 'var(--n-text-dim)',
              border: '1px solid var(--n-border)',
            }}
          >
            {t('planner.atTime')}
          </button>
        </div>

        {mode === 'in_hours' ? (
          <input
            type="number"
            value={value}
            onChange={e => setValue(e.target.value)}
            placeholder="Stunden ab jetzt"
            min={0.1}
            step={0.5}
            className="rounded-lg px-3 py-2"
            style={{ background: 'var(--n-bg)', border: '1px solid var(--n-border)', color: 'var(--n-text)' }}
          />
        ) : (
          <input
            type="datetime-local"
            value={value}
            onChange={e => setValue(e.target.value)}
            className="rounded-lg px-3 py-2"
            style={{ background: 'var(--n-bg)', border: '1px solid var(--n-border)', color: 'var(--n-text)' }}
          />
        )}

        <input
          type="number"
          value={durMin}
          onChange={e => setDurMin(e.target.value)}
          placeholder="Dauer (min) — leer = Konfig-Standard"
          className="rounded-lg px-3 py-2"
          style={{ background: 'var(--n-bg)', border: '1px solid var(--n-border)', color: 'var(--n-text)' }}
        />

        {error && <p className="text-sm" style={{ color: 'var(--n-danger)' }}>{error}</p>}

        <button
          type="submit"
          className="rounded-lg py-2 font-medium"
          style={{ background: 'var(--n-teal-600)', color: '#fff' }}
        >
          {t('planner.schedule')}
        </button>
      </form>

      {plans.length === 0 ? (
        <p className="text-sm text-center" style={{ color: 'var(--n-text-dim)' }}>{t('planner.noPlans')}</p>
      ) : (
        <div className="n-card flex flex-col divide-y" style={{ borderColor: 'var(--n-border)' }}>
          {plans.map(plan => {
            const seq = sequences.find(s => s.id === plan.sequence_id)
            return (
              <div key={plan.id} className="flex items-center justify-between p-4">
                <div>
                  <p className="font-medium">{seq?.label ?? plan.sequence_id}</p>
                  <p className="text-sm" style={{ color: 'var(--n-text-dim)' }}>
                    {new Date(plan.scheduled_at).toLocaleString()}
                    {plan.duration_min ? ` · ${plan.duration_min} min` : ''}
                  </p>
                </div>
                <button
                  onClick={() => deleteMut.mutate(plan.id)}
                  className="rounded px-2 py-1 text-sm"
                  style={{ color: 'var(--n-danger)', border: '1px solid var(--n-danger)' }}
                >
                  ✕
                </button>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
