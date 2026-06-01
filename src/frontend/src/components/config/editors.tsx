import { type CSSProperties, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  NOTIFICATION_CATEGORIES,
  type ConfigDoc,
  type NotifyTarget,
  type ScheduleSummary,
  type SequenceColorKey,
  type SequenceConfig,
  testNotify,
} from '../../api/client'
import {
  MAX_TIMES,
  WEEKDAYS,
  dailyCronToTime,
  isDaily,
  isWeekdays,
  isWeekend,
  timeToDailyCron,
  weekdayShort,
} from '../../lib/schedule'
import { SEQUENCE_COLOR_KEYS, SEQUENCE_PALETTE } from '../../theme/sequenceColors'
import { toast } from '../Toast'
import { inputStyle } from './formStyles'
import {
  Check,
  DeleteButton,
  EntityCombobox,
  IdTag,
  Labeled,
  Num,
} from './primitives'

// ── Sequence editor ─────────────────────────────────────────────────────────────

export function SequenceEditor({ id, seq, zoneIds, zones, last, colorsEnabled, onChange, onDelete }: {
  id: string
  seq: SequenceConfig
  zoneIds: string[]
  zones: ConfigDoc['zones']
  last: boolean
  colorsEnabled: boolean
  onChange: (mut: (s: SequenceConfig) => void) => void
  onDelete: () => void
}) {
  const { t } = useTranslation()
  return (
    <div style={{
      display: 'flex', flexDirection: 'column', gap: 12,
      padding: '16px 20px',
      borderBottom: last ? 'none' : '1px solid var(--n-line)',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <IdTag id={id} />
        <Labeled label={t('config.label')}>
          <input style={{ ...inputStyle, width: 160 }} value={seq.label}
            onChange={(e) => onChange((s) => { s.label = e.target.value })} />
        </Labeled>
        <Check label={t('config.enabled')} checked={seq.enabled}
          onChange={(c) => onChange((s) => { s.enabled = c })} />
        <Check label={t('config.windBlocks')} checked={seq.wind_blocks}
          onChange={(c) => onChange((s) => { s.wind_blocks = c })} />
        <div style={{ flex: 1 }} />
        <DeleteButton onClick={onDelete} />
      </div>

      <Labeled label={t('config.seqZones')} align="start">
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {zoneIds.length === 0 ? (
            <span style={{ fontSize: 12, color: 'var(--n-paused)' }}>
              {t('config.seqNoZonesDefined')}
            </span>
          ) : seq.zones.length === 0 ? (
            <span style={{ fontSize: 12, color: 'var(--n-paused)' }}>
              {t('config.seqNoZonesAssigned')}
            </span>
          ) : null}
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {zoneIds.map((zid) => {
              const active = seq.zones.includes(zid)
              return (
                <button key={zid} className={`n-chip${active ? ' active' : ''}`}
                  style={{ cursor: 'pointer', opacity: active ? 1 : 0.55 }}
                  onClick={() => onChange((s) => {
                    s.zones = active ? s.zones.filter((z) => z !== zid) : [...s.zones, zid]
                  })}>
                  {active ? `${seq.zones.indexOf(zid) + 1}. ` : ''}{zones[zid]?.label || zid}
                </button>
              )
            })}
          </div>
        </div>
      </Labeled>

      {colorsEnabled && (
        <Labeled label={t('config.color')} align="start">
          <ColorPicker value={seq.color} onChange={(c) => onChange((s) => { s.color = c })} />
        </Labeled>
      )}

      <div style={{ display: 'flex', gap: 18, flexWrap: 'wrap' }}>
        <Labeled label={t('config.basisMin')}>
          <Num value={seq.basis_min_per_zone} onChange={(v) => onChange((s) => { s.basis_min_per_zone = v })} />
        </Labeled>
        <Labeled label={t('config.watchdogMin')}>
          <Num value={seq.watchdog_min} onChange={(v) => onChange((s) => { s.watchdog_min = v })} />
        </Labeled>
        <Labeled label={t('config.rangeMin')}>
          <Num value={seq.range[0]} onChange={(v) => onChange((s) => { s.range = [v, s.range[1]] })} />
        </Labeled>
        <Labeled label={t('config.rangeMax')}>
          <Num value={seq.range[1]} onChange={(v) => onChange((s) => { s.range = [s.range[0], v] })} />
        </Labeled>
      </div>

      <Labeled label={t('config.schedule')} align="start">
        <SchedulePicker
          value={seq.schedule}
          onChange={(next) => onChange((s) => { s.schedule = next })}
        />
      </Labeled>
    </div>
  )
}

// Friendly schedule editor: weekday chips + up to five clock times, with a raw
// cron escape hatch for expressions the picker can't represent. Internally the
// backend turns this into one cron trigger per time (see ScheduleConfig).
export function SchedulePicker({ value, onChange }: {
  value: ScheduleSummary
  onChange: (next: ScheduleSummary) => void
}) {
  const { t } = useTranslation()
  const [showAdvanced, setShowAdvanced] = useState(!!value.cron)
  const advancedActive = !!value.cron
  const dimmed: CSSProperties = advancedActive ? { opacity: 0.45, pointerEvents: 'none' } : {}
  const labelStyle: CSSProperties = { fontSize: 11, color: 'var(--n-fg-muted)', letterSpacing: '0.02em' }

  const setDays = (days: number[]) => onChange({ ...value, days })
  const toggleDay = (d: number) => {
    const next = value.days.includes(d)
      ? value.days.filter((x) => x !== d)
      : [...value.days, d].sort((a, b) => a - b)
    // All seven selected means "every day" — store the canonical empty form.
    setDays(next.length === 7 ? [] : next)
  }
  const setTimes = (times: string[]) => onChange({ ...value, times })

  const presets: { label: string; active: boolean; days: number[] }[] = [
    { label: t('schedule.daily'), active: isDaily(value.days), days: [] },
    { label: t('schedule.weekdays'), active: isWeekdays(value.days), days: [1, 2, 3, 4, 5] },
    { label: t('schedule.weekend'), active: isWeekend(value.days), days: [6, 7] },
  ]

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {/* Weekdays */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6, ...dimmed }}>
        <span style={labelStyle}>{t('schedule.days')}</span>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          {presets.map((p) => (
            <button key={p.label} className={`n-chip${p.active ? ' active' : ''}`}
              style={{ cursor: 'pointer', opacity: p.active ? 1 : 0.6 }}
              onClick={() => setDays(p.days)}>{p.label}</button>
          ))}
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          {WEEKDAYS.map((d) => {
            const active = value.days.includes(d)
            return (
              <button key={d} className={`n-chip${active ? ' active' : ''}`}
                style={{ cursor: 'pointer', opacity: active ? 1 : 0.55, minWidth: 42, textAlign: 'center' }}
                onClick={() => toggleDay(d)}>{weekdayShort(d, t)}</button>
            )
          })}
        </div>
      </div>

      {/* Times */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6, ...dimmed }}>
        <span style={labelStyle}>{t('schedule.times')}</span>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
          {value.times.length === 0 && (
            <span style={{ fontSize: 12, color: 'var(--n-paused)' }}>
              {t('schedule.noTimes')}
            </span>
          )}
          {value.times.map((tm, i) => (
            <span key={i} style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
              <input type="time" value={tm} style={{ ...inputStyle, width: 120, fontVariantNumeric: 'tabular-nums' }}
                onChange={(e) => setTimes(value.times.map((x, j) => (j === i ? e.target.value : x)))} />
              <button className="n-btn" title={t('config.delete')} aria-label={t('config.delete')}
                style={{ height: 30, width: 30, padding: 0, fontSize: 13, color: 'var(--n-danger)' }}
                onClick={() => setTimes(value.times.filter((_, j) => j !== i))}>✕</button>
            </span>
          ))}
          {value.times.length < MAX_TIMES && (
            <button className="n-btn" style={{ height: 34, padding: '0 12px', fontSize: 12.5 }}
              onClick={() => setTimes([...value.times, '06:00'])}>
              + {t('schedule.addTime')}
            </button>
          )}
        </div>
      </div>

      {/* Advanced cron escape hatch */}
      {!showAdvanced ? (
        <button className="n-btn" style={{ height: 28, padding: '0 10px', fontSize: 12, alignSelf: 'flex-start' }}
          onClick={() => setShowAdvanced(true)}>{t('schedule.advanced')}</button>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <span style={labelStyle}>{t('schedule.advanced')}</span>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
            <input style={{ ...inputStyle, width: 160, fontFamily: 'var(--n-mono, monospace)' }}
              placeholder="*/30 * * * *" value={value.cron ?? ''}
              onChange={(e) => onChange({ ...value, cron: e.target.value })} />
            <button className="n-btn" style={{ height: 32, padding: '0 10px', fontSize: 12 }}
              onClick={() => { onChange({ ...value, cron: null }); setShowAdvanced(false) }}>
              {t('schedule.usePicker')}
            </button>
          </div>
          {advancedActive && (
            <span style={{ fontSize: 11, color: 'var(--n-paused)' }}>
              {t('schedule.advancedActive')}
            </span>
          )}
        </div>
      )}
    </div>
  )
}

// Accent-color picker for a sequence card's left bar: a row of palette swatches
// plus a "default" (neutral) option. Stores a color key (or null for default).
export function ColorPicker({ value, onChange }: {
  value: SequenceColorKey | null
  onChange: (c: SequenceColorKey | null) => void
}) {
  const { t } = useTranslation()
  const swatch = (key: SequenceColorKey | null, bg: string, selected: boolean) => (
    <button
      key={key ?? 'default'}
      type="button"
      title={key ?? t('config.colorDefault')}
      aria-label={key ?? t('config.colorDefault')}
      onClick={() => onChange(key)}
      style={{
        width: 26, height: 26, borderRadius: '50%', cursor: 'pointer',
        background: bg,
        border: selected ? '2px solid var(--n-fg)' : '2px solid var(--n-line-strong)',
        boxShadow: selected ? '0 0 0 2px var(--n-bg)' : 'none',
        padding: 0,
      }}
    />
  )
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
      {swatch(null, 'var(--n-card-elev)', value == null)}
      {SEQUENCE_COLOR_KEYS.map((key) => swatch(key, SEQUENCE_PALETTE[key], value === key))}
    </div>
  )
}

// Evening-reminder time: a daily clock-time picker that reads/writes the stored
// "M H * * *" cron, with a raw cron fallback for non-daily expressions.
export function ReminderTime({ value, onChange }: { value: string; onChange: (cron: string) => void }) {
  const { t } = useTranslation()
  const time = dailyCronToTime(value)
  const [advanced, setAdvanced] = useState(time === null)

  if (advanced) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
        <input style={{ ...inputStyle, width: 160, fontFamily: 'var(--n-mono, monospace)' }}
          value={value} onChange={(e) => onChange(e.target.value)} />
        {dailyCronToTime(value) !== null && (
          <button className="n-btn" style={{ height: 32, padding: '0 10px', fontSize: 12 }}
            onClick={() => setAdvanced(false)}>{t('schedule.usePicker')}</button>
        )}
      </div>
    )
  }
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
      <input type="time" style={{ ...inputStyle, width: 120, fontVariantNumeric: 'tabular-nums' }}
        value={time ?? '21:00'} onChange={(e) => onChange(timeToDailyCron(e.target.value))} />
      <button className="n-btn" style={{ height: 32, padding: '0 10px', fontSize: 12 }}
        onClick={() => setAdvanced(true)}>{t('schedule.advanced')}</button>
    </div>
  )
}

// Per-recipient notify targets: each is an HA notify.* service plus which
// categories it wants, whether to deliver quietly, and a platform hint.
export function NotifyTargetList({ values, services, dirty, onChange }: {
  values: NotifyTarget[]; services?: string[]; dirty: boolean; onChange: (vals: NotifyTarget[]) => void
}) {
  const { t } = useTranslation()
  const [testStates, setTestStates] = useState<Record<number, 'pending' | 'ok' | 'error'>>({})
  const options = (services ?? []).map((s) => ({ value: s, label: s }))
  const update = (i: number, mut: (tg: NotifyTarget) => NotifyTarget) =>
    onChange(values.map((x, j) => (j === i ? mut(x) : x)))

  async function handleTestTarget(i: number, service: string) {
    setTestStates((prev) => ({ ...prev, [i]: 'pending' }))
    try {
      const r = await testNotify(service)
      setTestStates((prev) => ({ ...prev, [i]: 'ok' }))
      setTimeout(() => setTestStates((prev) => { const n = { ...prev }; delete n[i]; return n }), 2500)
      toast(t('config.notifyTestOk', { count: r.sent }), 'success')
    } catch (e) {
      setTestStates((prev) => { const n = { ...prev }; delete n[i]; return n })
      toast(e instanceof Error ? e.message : String(e), 'error')
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10, width: '100%' }}>
      {values.map((tg, i) => (
        <div key={i} style={{
          display: 'flex', flexDirection: 'column', gap: 8,
          padding: '12px', border: '1px solid var(--n-line)', borderRadius: 'var(--n-r-md)',
        }}>
          <div style={{ display: 'flex', gap: 6, alignItems: 'flex-start' }}>
            <EntityCombobox
              value={tg.service}
              onChange={(nv) => update(i, (x) => ({ ...x, service: nv }))}
              options={options}
              hint={t('config.entityType.notify')}
              width={300}
            />
            <button
              className="n-btn"
              title={dirty ? t('config.saveFirst') : t('config.notifyTestThis')}
              aria-label={t('config.notifyTestThis')}
              style={{ height: 36, width: 36, padding: 0, fontSize: 15, color: testStates[i] === 'ok' ? 'var(--n-teal-400)' : 'var(--n-fg-muted)' }}
              disabled={dirty || !tg.service || testStates[i] === 'pending'}
              onClick={() => handleTestTarget(i, tg.service)}
            >
              {testStates[i] === 'ok' ? '✓' : '✉'}
            </button>
            <DeleteButton onClick={() => onChange(values.filter((_, j) => j !== i))} />
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {NOTIFICATION_CATEGORIES.map((cat) => {
              const on = tg.categories.includes(cat)
              return (
                <button key={cat} type="button" className={`n-chip${on ? ' active' : ''}`}
                  style={{ cursor: 'pointer', opacity: on ? 1 : 0.55 }}
                  onClick={() => update(i, (x) => ({
                    ...x,
                    categories: on ? x.categories.filter((c) => c !== cat) : [...x.categories, cat],
                  }))}>
                  {t(`config.notifyCat.${cat}`, { defaultValue: cat })}
                </button>
              )
            })}
          </div>
          <div style={{ display: 'flex', gap: 16, alignItems: 'center', flexWrap: 'wrap' }}>
            <Check label={t('config.notifyQuiet')} checked={tg.quiet}
              onChange={(c) => update(i, (x) => ({ ...x, quiet: c }))} />
            <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12.5, color: 'var(--n-fg-muted)' }}>
              {t('config.notifyPlatform')}
              <select value={tg.platform}
                onChange={(e) => update(i, (x) => ({ ...x, platform: e.target.value as NotifyTarget['platform'] }))}
                style={{ ...inputStyle, height: 30, width: 110 }}>
                <option value="auto">{t('config.platformAuto')}</option>
                <option value="ios">iOS</option>
                <option value="android">Android</option>
              </select>
            </label>
          </div>
        </div>
      ))}
      <button className="n-btn" style={{ height: 32, padding: '0 12px', fontSize: 12.5, alignSelf: 'flex-start' }}
        onClick={() => onChange([...values, { service: '', categories: [...NOTIFICATION_CATEGORIES], quiet: false, platform: 'auto' }])}>
        + {t('config.addEntry')}
      </button>
    </div>
  )
}
