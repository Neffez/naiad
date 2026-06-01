import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { queryKeys } from '../api/queryKeys'
import { type FormEvent, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router-dom'
import { createPlan, deletePlan, getConfig, getPlans, getSequences, getValves, type CreatePlanRequest } from '../api/client'
import { IChevDown, IX } from '../components/icons'
import { NumberField } from '../components/NumberField'
import { resolveSeqColor } from '../theme/sequenceColors'

type Target = 'sequence' | 'zone'

export default function Planner() {
  const { t, i18n } = useTranslation()
  const qc = useQueryClient()
  const { data: plans = [] } = useQuery({ queryKey: queryKeys.plans, queryFn: getPlans })
  const { data: sequences = [] } = useQuery({ queryKey: queryKeys.sequences, queryFn: getSequences })
  const { data: valves = [] } = useQuery({ queryKey: queryKeys.valves, queryFn: getValves })
  const { data: config } = useQuery({ queryKey: queryKeys.config, queryFn: getConfig })

  // Preselect the target when arriving from a card's "schedule" button (?seq=… / ?zone=…).
  const [searchParams] = useSearchParams()
  const [target, setTarget] = useState<Target>(searchParams.get('zone') ? 'zone' : 'sequence')
  const [seqId, setSeqId] = useState(searchParams.get('seq') ?? '')
  const [zoneId, setZoneId] = useState(searchParams.get('zone') ?? '')
  const [mode, setMode] = useState<'in_hours' | 'at_datetime'>('in_hours')
  const [hoursValue, setHoursValue] = useState('4')
  const [dateValue, setDateValue] = useState('')
  const [timeValue, setTimeValue] = useState('')
  const [durMin, setDurMin] = useState('')
  const [error, setError] = useState('')

  const createMut = useMutation({
    mutationFn: (body: CreatePlanRequest) => createPlan(body),
    onSuccess: () => { qc.invalidateQueries({ queryKey: queryKeys.plans }); setError('') },
    onError: (e: Error) => setError(e.message),
  })

  const deleteMut = useMutation({
    mutationFn: deletePlan,
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.plans }),
  })

  function submit(e: FormEvent) {
    e.preventDefault()
    const value = mode === 'in_hours' ? parseFloat(hoursValue) : `${dateValue}T${timeValue}`
    if (target === 'zone') {
      if (!zoneId) return
      // A single-zone plan needs an explicit duration — there is no per-zone default.
      if (!durMin) {
        setError(t('planner.zoneDurationRequired'))
        return
      }
      createMut.mutate({ zone_id: zoneId, mode, value, duration_min: parseInt(durMin) })
      return
    }
    if (!seqId) return
    const req: CreatePlanRequest = { sequence_id: seqId, mode, value }
    if (durMin) req.duration_min = parseInt(durMin)
    createMut.mutate(req)
  }

  return (
    <div style={{ maxWidth: 900, display: 'flex', flexDirection: 'column', gap: 22 }}>
      <form onSubmit={submit} style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        {/* Target toggle: a whole sequence or a single zone */}
        <div style={{
          display: 'grid', gridTemplateColumns: '1fr 1fr',
          background: 'var(--n-card)',
          border: '1px solid var(--n-line-strong)',
          borderRadius: 'var(--n-r-md)',
          overflow: 'hidden', height: 48,
        }}>
          {([
            { id: 'sequence' as const, label: t('planner.targetSequence') },
            { id: 'zone' as const, label: t('planner.targetZone') },
          ]).map((opt) => (
            <button
              key={opt.id}
              type="button"
              onClick={() => { setTarget(opt.id); setError('') }}
              style={{
                background: target === opt.id
                  ? 'linear-gradient(180deg, var(--n-teal-500), var(--n-teal-600))'
                  : 'transparent',
                border: 'none',
                color: target === opt.id ? 'var(--n-on-accent)' : 'var(--n-fg-muted)',
                fontSize: 14,
                fontWeight: target === opt.id ? 600 : 400,
                fontFamily: 'var(--n-sans)',
                cursor: 'pointer',
                transition: 'all 160ms var(--n-ease)',
                borderRadius: target === opt.id ? 'var(--n-r-sm)' : 0,
                margin: target === opt.id ? 4 : 0,
              }}
            >
              {opt.label}
            </button>
          ))}
        </div>

        {/* Sequence / zone select */}
        <div style={{ position: 'relative' }}>
          {target === 'sequence' ? (
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
              <option value="">{t('planner.selectSequence')}</option>
              {sequences.filter((s) => s.enabled).map((s) => (
                <option key={s.id} value={s.id}>{s.label}</option>
              ))}
            </select>
          ) : (
            <select
              value={zoneId}
              onChange={(e) => setZoneId(e.target.value)}
              style={{
                width: '100%', height: 52, padding: '0 18px',
                background: 'var(--n-card)',
                border: '1px solid var(--n-line-strong)',
                borderRadius: 'var(--n-r-md)',
                color: zoneId ? 'var(--n-fg)' : 'var(--n-fg-muted)',
                fontSize: 15, fontFamily: 'var(--n-sans)',
                appearance: 'none', cursor: 'pointer', outline: 'none',
              }}
            >
              <option value="">{t('planner.selectZone')}</option>
              {valves.map((v) => (
                <option key={v.zone_id} value={v.zone_id}>{v.label}</option>
              ))}
            </select>
          )}
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
                color: mode === opt.id ? 'var(--n-on-accent)' : 'var(--n-fg-muted)',
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
          <NumberField
            value={hoursValue}
            allowEmpty
            onChange={setHoursValue}
            min={1} max={72}
            unit="h"
            size="lg"
            fullWidth
            placeholder={t('planner.hoursPlaceholder')}
          />
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
        <NumberField
          value={durMin}
          allowEmpty
          onChange={setDurMin}
          min={1} max={120}
          unit="min"
          size="lg"
          fullWidth
          placeholder={target === 'zone'
            ? t('planner.durationPlaceholderZone')
            : t('planner.durationPlaceholder')}
        />

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
                  background: resolveSeqColor(config, p.sequence_id ?? '') ?? 'var(--n-fg-dim)',
                }} />
                <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                  <span style={{ fontSize: 15, fontWeight: 600 }}>
                    {p.label}
                    {p.target_type === 'zone' && (
                      <span className="n-chip" style={{ marginLeft: 8, fontSize: 10 }}>
                        {t('planner.zoneTag')}
                      </span>
                    )}
                  </span>
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
                title={t('planner.remove')}
                aria-label={t('planner.remove')}
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
