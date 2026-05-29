import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { type FormEvent, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router-dom'
import { createPlan, deletePlan, getPlans, getSequences, type CreatePlanRequest } from '../api/client'
import { IChevDown, IX } from '../components/icons'
import { seqColor } from '../theme/sequenceColors'

export default function Planner() {
  const { t, i18n } = useTranslation()
  const qc = useQueryClient()
  const { data: plans = [] } = useQuery({ queryKey: ['plans'], queryFn: getPlans })
  const { data: sequences = [] } = useQuery({ queryKey: ['sequences'], queryFn: getSequences })

  // Preselect the sequence when arriving from a card's "schedule" button (?seq=…).
  const [searchParams] = useSearchParams()
  const [seqId, setSeqId] = useState(searchParams.get('seq') ?? '')
  const [mode, setMode] = useState<'in_hours' | 'at_datetime'>('in_hours')
  const [hoursValue, setHoursValue] = useState('4')
  const [dateValue, setDateValue] = useState('')
  const [timeValue, setTimeValue] = useState('')
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

  function submit(e: FormEvent) {
    e.preventDefault()
    if (!seqId) return
    const req: CreatePlanRequest = {
      sequence_id: seqId,
      mode,
      value: mode === 'in_hours' ? parseFloat(hoursValue) : `${dateValue}T${timeValue}`,
    }
    if (durMin) req.duration_min = parseInt(durMin)
    createMut.mutate(req)
  }

  const inputStyle: React.CSSProperties = {
    flex: 1, height: '100%', padding: '0 18px',
    background: 'transparent', border: 'none',
    color: 'var(--n-fg)', fontSize: 15,
    fontFamily: 'var(--n-sans)', outline: 'none',
    fontVariantNumeric: 'tabular-nums',
  }

  const fieldStyle: React.CSSProperties = {
    display: 'flex', alignItems: 'center', gap: 0,
    background: 'var(--n-card)',
    border: '1px solid var(--n-line-strong)',
    borderRadius: 'var(--n-r-md)',
    height: 52, overflow: 'hidden',
  }

  return (
    <div style={{ maxWidth: 900, display: 'flex', flexDirection: 'column', gap: 22 }}>
      <form onSubmit={submit} style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        {/* Sequence select */}
        <div style={{ position: 'relative' }}>
          <select
            value={seqId}
            onChange={(e) => setSeqId(e.target.value)}
            style={{
              width: '100%', height: 52, padding: '0 18px',
              background: 'var(--n-card)',
              border: '1px solid var(--n-line-strong)',
              borderRadius: 'var(--n-r-md)',
              color: seqId ? 'var(--n-fg)' : 'var(--n-fg-muted)',
              fontSize: 15, fontFamily: 'var(--n-sans)',
              appearance: 'none', cursor: 'pointer', outline: 'none',
            }}
          >
            <option value="">{t('planner.selectSequence', { defaultValue: '— Sequenz wählen —' })}</option>
            {sequences.filter((s) => s.enabled).map((s) => (
              <option key={s.id} value={s.id}>{s.label}</option>
            ))}
          </select>
          <span style={{
            position: 'absolute', right: 18, top: '50%', transform: 'translateY(-50%)',
            color: 'var(--n-fg-muted)', pointerEvents: 'none',
          }}>
            <IChevDown size={18} />
          </span>
        </div>

        {/* Mode toggle */}
        <div style={{
          display: 'grid', gridTemplateColumns: '1fr 1fr',
          background: 'var(--n-card)',
          border: '1px solid var(--n-line-strong)',
          borderRadius: 'var(--n-r-md)',
          overflow: 'hidden', height: 48,
        }}>
          {([
            { id: 'in_hours' as const, label: t('planner.inHours') },
            { id: 'at_datetime' as const, label: t('planner.atTime') },
          ]).map((opt) => (
            <button
              key={opt.id}
              type="button"
              onClick={() => setMode(opt.id)}
              style={{
                background: mode === opt.id
                  ? 'linear-gradient(180deg, var(--n-teal-500), var(--n-teal-600))'
                  : 'transparent',
                border: 'none',
                color: mode === opt.id ? '#04181c' : 'var(--n-fg-muted)',
                fontSize: 14,
                fontWeight: mode === opt.id ? 600 : 400,
                fontFamily: 'var(--n-sans)',
                cursor: 'pointer',
                transition: 'all 160ms var(--n-ease)',
                borderRadius: mode === opt.id ? 'var(--n-r-sm)' : 0,
                margin: mode === opt.id ? 4 : 0,
              }}
            >
              {opt.label}
            </button>
          ))}
        </div>

        {/* Conditional inputs */}
        {mode === 'in_hours' ? (
          <div style={fieldStyle}>
            <input
              type="number"
              value={hoursValue}
              onChange={(e) => setHoursValue(e.target.value)}
              min="1" max="72"
              placeholder={t('planner.hoursPlaceholder', { defaultValue: 'Stunden' })}
              style={inputStyle}
            />
            <span style={{
              padding: '0 14px', color: 'var(--n-fg-muted)', fontSize: 13,
              borderLeft: '1px solid var(--n-line)',
              height: '100%', display: 'flex', alignItems: 'center',
              background: 'rgba(255,255,255,0.015)',
            }}>h</span>
          </div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <input
              type="date"
              value={dateValue}
              onChange={(e) => setDateValue(e.target.value)}
              style={{
                height: 52, padding: '0 18px',
                background: 'var(--n-card)',
                border: '1px solid var(--n-line-strong)',
                borderRadius: 'var(--n-r-md)',
                color: 'var(--n-fg)', fontSize: 15,
                fontFamily: 'var(--n-sans)', outline: 'none',
                colorScheme: 'dark',
              }}
            />
            <input
              type="time"
              value={timeValue}
              onChange={(e) => setTimeValue(e.target.value)}
              style={{
                height: 52, padding: '0 18px',
                background: 'var(--n-card)',
                border: '1px solid var(--n-line-strong)',
                borderRadius: 'var(--n-r-md)',
                color: 'var(--n-fg)', fontSize: 15,
                fontFamily: 'var(--n-sans)', outline: 'none',
                colorScheme: 'dark',
              }}
            />
          </div>
        )}

        {/* Duration override */}
        <div style={fieldStyle}>
          <input
            type="number"
            value={durMin}
            onChange={(e) => setDurMin(e.target.value)}
            min="1" max="120"
            placeholder={t('planner.durationPlaceholder', { defaultValue: 'Dauer (min) — leer = Konfig-Standard' })}
            style={{ ...inputStyle, color: durMin ? 'var(--n-fg)' : 'var(--n-fg-muted)' }}
          />
          <span style={{
            padding: '0 14px', color: 'var(--n-fg-muted)', fontSize: 13,
            borderLeft: '1px solid var(--n-line)',
            height: '100%', display: 'flex', alignItems: 'center',
            background: 'rgba(255,255,255,0.015)',
          }}>min</span>
        </div>

        {error && <p style={{ color: 'var(--n-danger)', fontSize: 13 }}>{error}</p>}

        {/* Submit */}
        <button
          type="submit"
          className="n-btn primary lg"
          style={{ width: '100%', height: 52, fontSize: 15 }}
        >
          {t('planner.schedule')}
        </button>
      </form>

      {/* Planned runs */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12, marginTop: 8 }}>
        {plans.length === 0 ? (
          <span style={{
            color: 'var(--n-fg-muted)', fontSize: 14,
            textAlign: 'center', padding: '16px 0',
          }}>
            {t('planner.noPlans')}
          </span>
        ) : (
          plans.map((p) => (
            <div key={p.id} className="n-card" style={{
              padding: '14px 18px',
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              gap: 14,
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <span style={{
                  width: 4, height: 28, borderRadius: 2,
                  background: seqColor(p.sequence_id),
                }} />
                <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                  <span style={{ fontSize: 15, fontWeight: 600 }}>{p.sequence_label}</span>
                  <span className="n-label" style={{ fontSize: 12 }}>
                    {new Date(p.scheduled_at).toLocaleString(i18n.language, {
                      weekday: 'short', day: '2-digit', month: '2-digit',
                      hour: '2-digit', minute: '2-digit',
                    })}
                    {p.duration_min ? ` · ${p.duration_min} min` : ''}
                  </span>
                </div>
              </div>
              <button
                className="n-iconbtn"
                onClick={() => deleteMut.mutate(p.id)}
                style={{ width: 36, height: 36 }}
                title={t('planner.remove', { defaultValue: 'Entfernen' })}
              >
                <IX size={15} />
              </button>
            </div>
          ))
        )}
      </div>
    </div>
  )
}
