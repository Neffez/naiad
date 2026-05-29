import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { type CSSProperties, type ReactNode, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  type ConfigDoc,
  type EntityInfo,
  type SequenceConfig,
  exportConfig,
  getConfig,
  getEntities,
  importConfig,
  putConfig,
} from '../api/client'

const inputStyle: CSSProperties = {
  height: 36,
  padding: '0 10px',
  background: 'var(--n-card-elev)',
  border: '1px solid var(--n-line-strong)',
  borderRadius: 'var(--n-r-sm)',
  color: 'var(--n-fg)',
  fontSize: 14,
  fontFamily: 'var(--n-sans)',
  outline: 'none',
  minWidth: 0,
}

export default function Config() {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const { data } = useQuery({ queryKey: ['config'], queryFn: getConfig })
  const switches = useQuery({ queryKey: ['entities', 'switch'], queryFn: () => getEntities('switch') })
  const sensors = useQuery({ queryKey: ['entities', 'sensor'], queryFn: () => getEntities('sensor') })
  const binarySensors = useQuery({
    queryKey: ['entities', 'binary_sensor'],
    queryFn: () => getEntities('binary_sensor'),
  })

  const [draft, setDraft] = useState<ConfigDoc | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const [restart, setRestart] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (data) setDraft(structuredClone(data))
  }, [data])

  const saveMut = useMutation({
    mutationFn: (body: ConfigDoc) => putConfig(body),
    onSuccess: (resp) => {
      setError(null)
      setRestart(resp.restart_required)
      setSaved(true)
      setTimeout(() => setSaved(false), 2500)
      qc.invalidateQueries({ queryKey: ['config'] })
      qc.invalidateQueries({ queryKey: ['sequences'] })
      qc.invalidateQueries({ queryKey: ['status'] })
    },
    onError: (e: Error) => setError(e.message),
  })

  const importMut = useMutation({
    mutationFn: (text: string) => importConfig(text),
    onSuccess: (resp) => {
      setError(null)
      setRestart(resp.restart_required)
      setSaved(true)
      setTimeout(() => setSaved(false), 2500)
      qc.invalidateQueries({ queryKey: ['config'] })
      qc.invalidateQueries({ queryKey: ['sequences'] })
    },
    onError: (e: Error) => setError(e.message),
  })

  if (!draft) {
    return (
      <div style={{ padding: 20, color: 'var(--n-fg-muted)' }}>
        {t('config.loading', { defaultValue: 'Laden…' })}
      </div>
    )
  }

  const dirty = data != null && JSON.stringify(draft) !== JSON.stringify(data)

  function patch(mutator: (d: ConfigDoc) => void) {
    setDraft((prev) => {
      if (!prev) return prev
      const next = structuredClone(prev)
      mutator(next)
      return next
    })
  }

  async function handleExport() {
    try {
      const text = await exportConfig()
      const blob = new Blob([text], { type: 'application/x-yaml' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = 'naiad-config.yaml'
      a.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      setError((e as Error).message)
    }
  }

  function handleImportFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    file.text().then((text) => importMut.mutate(text))
    e.target.value = '' // allow re-selecting the same file
  }

  const zoneIds = Object.keys(draft.zones)

  return (
    <div style={{ maxWidth: 940, display: 'flex', flexDirection: 'column', gap: 22, paddingBottom: 88 }}>
      {/* Entity datalists for the pickers */}
      <EntityDatalist id="ents-switch" entities={switches.data?.entities} />
      <EntityDatalist id="ents-sensor" entities={sensors.data?.entities} />
      <EntityDatalist id="ents-binary_sensor" entities={binarySensors.data?.entities} />

      {/* HA connection */}
      <Section title={t('config.ha', { defaultValue: 'Home Assistant' })}>
        <Row label={t('config.haUrl', { defaultValue: 'WebSocket-URL' })}>
          <input
            style={{ ...inputStyle, width: 360 }}
            value={draft.ha.url}
            onChange={(e) => patch((d) => { d.ha.url = e.target.value })}
          />
        </Row>
        <Row label={t('config.notifyTargets', { defaultValue: 'Notify-Ziele' })} last align="start">
          <StringList
            values={draft.ha.notify_targets}
            placeholder="notify.mobile_app_…"
            onChange={(vals) => patch((d) => { d.ha.notify_targets = vals })}
          />
        </Row>
      </Section>

      {/* Sensors */}
      <Section title={t('config.sensors', { defaultValue: 'Sensoren' })}>
        {SENSOR_FIELDS.map((f, i) => (
          <Row key={f.key} label={t(`config.sensor.${f.key}`, { defaultValue: f.fallback })} last={i === SENSOR_FIELDS.length - 1}>
            <input
              style={{ ...inputStyle, width: 320 }}
              list={`ents-${f.domain}`}
              value={draft.sensors[f.key]}
              onChange={(e) => patch((d) => { d.sensors[f.key] = e.target.value })}
            />
          </Row>
        ))}
      </Section>

      {/* Zones */}
      <Section
        title={t('config.zones', { defaultValue: 'Zonen' })}
        action={
          <AddButton
            label={t('config.addZone', { defaultValue: 'Zone hinzufügen' })}
            existing={zoneIds}
            onAdd={(id) => patch((d) => { d.zones[id] = { label: id, switch: '', flow_lph: 0 } })}
          />
        }
      >
        {zoneIds.length === 0 && <Empty>{t('config.noZones', { defaultValue: 'Keine Zonen' })}</Empty>}
        {zoneIds.map((id, i) => {
          const z = draft.zones[id]
          return (
            <CardRow key={id} last={i === zoneIds.length - 1}>
              <IdTag id={id} />
              <Labeled label={t('config.label', { defaultValue: 'Bezeichnung' })}>
                <input style={{ ...inputStyle, width: 160 }} value={z.label}
                  onChange={(e) => patch((d) => { d.zones[id].label = e.target.value })} />
              </Labeled>
              <Labeled label={t('config.switch', { defaultValue: 'Switch' })}>
                <input style={{ ...inputStyle, width: 240 }} list="ents-switch" value={z.switch}
                  onChange={(e) => patch((d) => { d.zones[id].switch = e.target.value })} />
              </Labeled>
              <Labeled label={t('config.flowLph', { defaultValue: 'Durchfluss (L/h)' })}>
                <input type="number" style={{ ...inputStyle, width: 90, textAlign: 'right' }} value={z.flow_lph}
                  onChange={(e) => patch((d) => { d.zones[id].flow_lph = Number(e.target.value) })} />
              </Labeled>
              <DeleteButton onClick={() => patch((d) => { delete d.zones[id] })} />
            </CardRow>
          )
        })}
      </Section>

      {/* Sequences */}
      <Section
        title={t('config.sequences', { defaultValue: 'Sequenzen' })}
        action={
          <AddButton
            label={t('config.addSequence', { defaultValue: 'Sequenz hinzufügen' })}
            existing={Object.keys(draft.sequences)}
            onAdd={(id) => patch((d) => {
              d.sequences[id] = {
                label: id, zones: [], basis_min_per_zone: 30, range: [5, 240],
                watchdog_min: 60, schedule: { cron: '0 6 * * *' }, enabled: false, wind_blocks: false,
              }
            })}
          />
        }
      >
        {Object.keys(draft.sequences).length === 0 && (
          <Empty>{t('config.noSequences', { defaultValue: 'Keine Sequenzen' })}</Empty>
        )}
        {Object.entries(draft.sequences).map(([id, s], i, arr) => (
          <SequenceEditor
            key={id}
            id={id}
            seq={s}
            zoneIds={zoneIds}
            last={i === arr.length - 1}
            onChange={(mut) => patch((d) => mut(d.sequences[id]))}
            onDelete={() => patch((d) => { delete d.sequences[id] })}
          />
        ))}
      </Section>

      {/* Factors */}
      <Section title={t('config.factors', { defaultValue: 'Faktoren' })}>
        <Row label={t('config.tempBasisC', { defaultValue: 'Temp-Basis (°C)' })}>
          <Num value={draft.factors.temp.basis_c} onChange={(v) => patch((d) => { d.factors.temp.basis_c = v })} />
        </Row>
        <Row label={t('config.tempPctPerC', { defaultValue: '% pro °C' })}>
          <Num value={draft.factors.temp.pct_per_c} onChange={(v) => patch((d) => { d.factors.temp.pct_per_c = v })} />
        </Row>
        <Row label={t('config.tempMinPct', { defaultValue: 'Min %' })}>
          <Num value={draft.factors.temp.min_pct} onChange={(v) => patch((d) => { d.factors.temp.min_pct = v })} />
        </Row>
        <Row label={t('config.tempMaxPct', { defaultValue: 'Max %' })}>
          <Num value={draft.factors.temp.max_pct} onChange={(v) => patch((d) => { d.factors.temp.max_pct = v })} />
        </Row>
        <Row label={t('config.rainThreshold', { defaultValue: 'Regen-Schwelle (%)' })}>
          <Num value={draft.factors.rain.threshold_prob} onChange={(v) => patch((d) => { d.factors.rain.threshold_prob = v })} />
        </Row>
        <Row label={t('config.rainReduce', { defaultValue: 'Reduktion ab (mm)' })}>
          <Num value={draft.factors.rain.reduce_above_mm} onChange={(v) => patch((d) => { d.factors.rain.reduce_above_mm = v })} />
        </Row>
        <Row label={t('config.rainZero', { defaultValue: 'Null ab (mm)' })}>
          <Num value={draft.factors.rain.zero_above_mm} onChange={(v) => patch((d) => { d.factors.rain.zero_above_mm = v })} />
        </Row>
        <Row label={t('config.rainDecay', { defaultValue: 'Vorhersage-Decay' })} last>
          <Num step={0.1} value={draft.factors.rain.forecast_decay} onChange={(v) => patch((d) => { d.factors.rain.forecast_decay = v })} />
        </Row>
      </Section>

      {/* Advanced */}
      <Section title={t('config.advanced', { defaultValue: 'Erweitert' })}>
        <Row label={t('config.timezone', { defaultValue: 'Zeitzone' })}>
          <input style={{ ...inputStyle, width: 220 }} value={draft.timezone}
            onChange={(e) => patch((d) => { d.timezone = e.target.value })} />
        </Row>
        <Row label={t('config.authMode', { defaultValue: 'Auth-Modus' })}>
          <select style={{ ...inputStyle, width: 200 }} value={draft.auth.mode}
            onChange={(e) => patch((d) => { d.auth.mode = e.target.value as ConfigDoc['auth']['mode'] })}>
            <option value="password">password</option>
            <option value="forward_header">forward_header</option>
            <option value="none">none</option>
          </select>
        </Row>
        {draft.auth.mode === 'none' && (
          <div style={{ padding: '0 20px 14px' }}>
            <Banner tone="amber">
              {t('config.authNoneWarning', {
                defaultValue: 'Kein Login aktiv — jeder im Netzwerk kann Naiad bedienen. Für den dauerhaften Betrieb auf „password" umstellen (NAIAD_PASSWORD_HASH setzen) oder hinter einen Auth-Proxy stellen.',
              })}
            </Banner>
          </div>
        )}
        <Row label={t('config.frameAncestors', { defaultValue: 'frame-ancestors' })} last align="start">
          <StringList
            values={draft.auth.frame_ancestors}
            placeholder="'self'"
            onChange={(vals) => patch((d) => { d.auth.frame_ancestors = vals })}
          />
        </Row>
      </Section>

      {/* Sticky save bar */}
      <div style={{
        position: 'sticky', bottom: 0, marginTop: 4,
        display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap',
        padding: '14px 18px',
        background: 'var(--n-bg-elev)',
        border: '1px solid var(--n-line)',
        borderRadius: 'var(--n-r-lg)',
      }}>
        <button className="n-btn primary" disabled={!dirty || saveMut.isPending}
          style={{ height: 38, padding: '0 20px', fontSize: 13 }}
          onClick={() => saveMut.mutate(draft)}>
          {saveMut.isPending
            ? t('config.saving', { defaultValue: 'Speichern…' })
            : t('config.save', { defaultValue: 'Speichern' })}
        </button>
        <button className="n-btn" disabled={!dirty}
          style={{ height: 38, padding: '0 16px', fontSize: 13 }}
          onClick={() => data && setDraft(structuredClone(data))}>
          {t('config.reset', { defaultValue: 'Verwerfen' })}
        </button>
        <div style={{ flex: 1 }} />
        <button className="n-btn" style={{ height: 38, padding: '0 16px', fontSize: 13 }} onClick={handleExport}>
          {t('config.export', { defaultValue: 'Export' })}
        </button>
        <button className="n-btn" style={{ height: 38, padding: '0 16px', fontSize: 13 }}
          onClick={() => fileRef.current?.click()}>
          {t('config.import', { defaultValue: 'Import' })}
        </button>
        <input ref={fileRef} type="file" accept=".yaml,.yml,.json" style={{ display: 'none' }} onChange={handleImportFile} />

        {dirty && <Pill tone="muted">{t('config.unsaved', { defaultValue: 'Ungespeichert' })}</Pill>}
        {saved && <Pill tone="teal">✓ {t('config.saved', { defaultValue: 'Gespeichert' })}</Pill>}
      </div>

      {restart && (
        <Banner tone="amber">
          {t('config.restartRequired', {
            defaultValue: 'HA-Verbindung geändert — ein Neustart ist nötig, damit die neue Verbindung aktiv wird.',
          })}
        </Banner>
      )}
      {error && <Banner tone="danger">{error}</Banner>}
    </div>
  )
}

// ── Field metadata ─────────────────────────────────────────────────────────────

const SENSOR_FIELDS: { key: keyof ConfigDoc['sensors']; domain: string; fallback: string }[] = [
  { key: 'rain', domain: 'binary_sensor', fallback: 'Regen' },
  { key: 'wind', domain: 'binary_sensor', fallback: 'Wind' },
  { key: 'season', domain: 'binary_sensor', fallback: 'Saison' },
  { key: 'temperature', domain: 'sensor', fallback: 'Temperatur' },
  { key: 'precipitation_prob_today', domain: 'sensor', fallback: 'Regenwahrscheinlichkeit heute' },
  { key: 'precipitation_prob_tomorrow', domain: 'sensor', fallback: 'Regenwahrscheinlichkeit morgen' },
  { key: 'precipitation_today', domain: 'sensor', fallback: 'Niederschlag heute' },
  { key: 'precipitation_tomorrow', domain: 'sensor', fallback: 'Niederschlag morgen' },
]

// ── Sequence editor ─────────────────────────────────────────────────────────────

function SequenceEditor({ id, seq, zoneIds, last, onChange, onDelete }: {
  id: string
  seq: SequenceConfig
  zoneIds: string[]
  last: boolean
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
        <Labeled label={t('config.label', { defaultValue: 'Bezeichnung' })}>
          <input style={{ ...inputStyle, width: 160 }} value={seq.label}
            onChange={(e) => onChange((s) => { s.label = e.target.value })} />
        </Labeled>
        <Check label={t('config.enabled', { defaultValue: 'Aktiv' })} checked={seq.enabled}
          onChange={(c) => onChange((s) => { s.enabled = c })} />
        <Check label={t('config.windBlocks', { defaultValue: 'Wind blockt' })} checked={seq.wind_blocks}
          onChange={(c) => onChange((s) => { s.wind_blocks = c })} />
        <div style={{ flex: 1 }} />
        <DeleteButton onClick={onDelete} />
      </div>

      <Labeled label={t('config.seqZones', { defaultValue: 'Zonen (Reihenfolge)' })} align="start">
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          {zoneIds.length === 0 && <span style={{ fontSize: 12, color: 'var(--n-fg-dim)' }}>—</span>}
          {zoneIds.map((zid) => {
            const active = seq.zones.includes(zid)
            return (
              <button key={zid} className={`n-chip${active ? ' active' : ''}`}
                style={{ cursor: 'pointer', opacity: active ? 1 : 0.55 }}
                onClick={() => onChange((s) => {
                  s.zones = active ? s.zones.filter((z) => z !== zid) : [...s.zones, zid]
                })}>
                {active ? `${seq.zones.indexOf(zid) + 1}. ` : ''}{zid}
              </button>
            )
          })}
        </div>
      </Labeled>

      <div style={{ display: 'flex', gap: 18, flexWrap: 'wrap' }}>
        <Labeled label={t('config.basisMin', { defaultValue: 'Basis (min/Zone)' })}>
          <Num value={seq.basis_min_per_zone} onChange={(v) => onChange((s) => { s.basis_min_per_zone = v })} />
        </Labeled>
        <Labeled label={t('config.watchdogMin', { defaultValue: 'Watchdog (min)' })}>
          <Num value={seq.watchdog_min} onChange={(v) => onChange((s) => { s.watchdog_min = v })} />
        </Labeled>
        <Labeled label={t('config.rangeMin', { defaultValue: 'Min' })}>
          <Num value={seq.range[0]} onChange={(v) => onChange((s) => { s.range = [v, s.range[1]] })} />
        </Labeled>
        <Labeled label={t('config.rangeMax', { defaultValue: 'Max' })}>
          <Num value={seq.range[1]} onChange={(v) => onChange((s) => { s.range = [s.range[0], v] })} />
        </Labeled>
        <Labeled label={t('config.cron', { defaultValue: 'Cron' })}>
          <input style={{ ...inputStyle, width: 130, fontFamily: 'var(--n-mono, monospace)' }} value={seq.schedule.cron}
            onChange={(e) => onChange((s) => { s.schedule.cron = e.target.value })} />
        </Labeled>
      </div>
    </div>
  )
}

// ── Small reusable building blocks ──────────────────────────────────────────────

function Section({ title, action, children }: { title: string; action?: ReactNode; children: ReactNode }) {
  return (
    <div style={{
      display: 'flex', flexDirection: 'column',
      border: '1px solid var(--n-line)', borderRadius: 'var(--n-r-lg)', overflow: 'hidden',
    }}>
      <div style={{
        padding: '14px 20px', background: 'rgba(255,255,255,0.015)',
        borderBottom: '1px solid var(--n-line)',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12,
      }}>
        <span style={{ fontSize: 16, fontWeight: 600, letterSpacing: '-0.01em' }}>{title}</span>
        {action}
      </div>
      {children}
    </div>
  )
}

function Row({ label, children, last = false, align = 'center' }: {
  label: ReactNode; children: ReactNode; last?: boolean; align?: 'center' | 'start'
}) {
  return (
    <div style={{
      display: 'flex', alignItems: align === 'start' ? 'flex-start' : 'center',
      justifyContent: 'space-between', gap: 16,
      padding: '12px 20px', borderBottom: last ? 'none' : '1px solid var(--n-line)', minHeight: 52,
    }}>
      <span style={{ fontSize: 14, color: 'var(--n-fg-soft)', paddingTop: align === 'start' ? 6 : 0 }}>{label}</span>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>{children}</div>
    </div>
  )
}

function CardRow({ children, last }: { children: ReactNode; last: boolean }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'flex-end', gap: 12, flexWrap: 'wrap',
      padding: '14px 20px', borderBottom: last ? 'none' : '1px solid var(--n-line)',
    }}>
      {children}
    </div>
  )
}

function Labeled({ label, children, align = 'center' }: { label: string; children: ReactNode; align?: 'center' | 'start' }) {
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: 4, alignItems: align === 'start' ? 'flex-start' : undefined }}>
      <span style={{ fontSize: 11, color: 'var(--n-fg-muted)', letterSpacing: '0.02em' }}>{label}</span>
      {children}
    </label>
  )
}

function IdTag({ id }: { id: string }) {
  return (
    <span className="mono" style={{
      fontSize: 12, color: 'var(--n-teal-200)',
      background: 'var(--n-teal-glow)', border: '1px solid rgba(94,200,216,0.25)',
      padding: '4px 8px', borderRadius: 'var(--n-r-sm)', alignSelf: 'flex-end',
    }}>{id}</span>
  )
}

function Num({ value, step = 1, onChange }: { value: number; step?: number; onChange: (v: number) => void }) {
  const [local, setLocal] = useState(String(value))
  useEffect(() => { setLocal(String(value)) }, [value])
  return (
    <input type="number" step={step} value={local}
      style={{ ...inputStyle, width: 90, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}
      onChange={(e) => setLocal(e.target.value)}
      onBlur={(e) => { const n = parseFloat(e.target.value); if (!isNaN(n)) onChange(n) }}
    />
  )
}

function Check({ label, checked, onChange }: { label: string; checked: boolean; onChange: (c: boolean) => void }) {
  return (
    <label style={{ display: 'flex', alignItems: 'center', gap: 7, cursor: 'pointer', fontSize: 13, color: 'var(--n-fg-muted)', userSelect: 'none' }}>
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)}
        style={{ width: 16, height: 16, accentColor: 'var(--n-teal-400)', cursor: 'pointer' }} />
      {label}
    </label>
  )
}

function StringList({ values, placeholder, onChange }: {
  values: string[]; placeholder?: string; onChange: (vals: string[]) => void
}) {
  const { t } = useTranslation()
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      {values.map((v, i) => (
        <div key={i} style={{ display: 'flex', gap: 6 }}>
          <input style={{ ...inputStyle, width: 300 }} value={v} placeholder={placeholder}
            onChange={(e) => onChange(values.map((x, j) => (j === i ? e.target.value : x)))} />
          <DeleteButton onClick={() => onChange(values.filter((_, j) => j !== i))} />
        </div>
      ))}
      <button className="n-btn" style={{ height: 32, padding: '0 12px', fontSize: 12.5, alignSelf: 'flex-start' }}
        onClick={() => onChange([...values, ''])}>
        + {t('config.addEntry', { defaultValue: 'Hinzufügen' })}
      </button>
    </div>
  )
}

function AddButton({ label, existing, onAdd }: { label: string; existing: string[]; onAdd: (id: string) => void }) {
  const { t } = useTranslation()
  const [adding, setAdding] = useState(false)
  const [id, setId] = useState('')
  const valid = /^[a-z0-9_]+$/.test(id) && !existing.includes(id)
  if (!adding) {
    return (
      <button className="n-btn" style={{ height: 32, padding: '0 12px', fontSize: 12.5 }} onClick={() => setAdding(true)}>
        + {label}
      </button>
    )
  }
  return (
    <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
      <input autoFocus style={{ ...inputStyle, width: 150, height: 32 }} value={id} placeholder="id_snake_case"
        onChange={(e) => setId(e.target.value)}
        onKeyDown={(e) => { if (e.key === 'Enter' && valid) { onAdd(id); setId(''); setAdding(false) } }} />
      <button className="n-btn primary" disabled={!valid} style={{ height: 32, padding: '0 12px', fontSize: 12.5 }}
        onClick={() => { onAdd(id); setId(''); setAdding(false) }}>
        {t('config.add', { defaultValue: 'OK' })}
      </button>
      <button className="n-btn" style={{ height: 32, padding: '0 10px', fontSize: 12.5 }}
        onClick={() => { setId(''); setAdding(false) }}>✕</button>
    </div>
  )
}

function DeleteButton({ onClick }: { onClick: () => void }) {
  const { t } = useTranslation()
  return (
    <button className="n-btn" title={t('config.delete', { defaultValue: 'Löschen' })}
      style={{ height: 36, width: 36, padding: 0, fontSize: 15, color: 'var(--n-danger)' }}
      onClick={onClick}>✕</button>
  )
}

function EntityDatalist({ id, entities }: { id: string; entities?: EntityInfo[] }) {
  return (
    <datalist id={id}>
      {(entities ?? []).map((e) => (
        <option key={e.entity_id} value={e.entity_id}>
          {e.friendly_name ? `${e.friendly_name} (${e.entity_id})` : e.entity_id}
        </option>
      ))}
    </datalist>
  )
}

function Empty({ children }: { children: ReactNode }) {
  return <div style={{ padding: '16px 20px', fontSize: 13, color: 'var(--n-fg-dim)' }}>{children}</div>
}

function Pill({ tone, children }: { tone: 'teal' | 'muted'; children: ReactNode }) {
  const teal = tone === 'teal'
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 6, padding: '6px 12px', borderRadius: 999,
      fontSize: 12.5, fontWeight: 500,
      background: teal ? 'var(--n-teal-glow)' : 'transparent',
      border: `1px solid ${teal ? 'rgba(94,200,216,0.25)' : 'var(--n-line-strong)'}`,
      color: teal ? 'var(--n-teal-200)' : 'var(--n-fg-muted)',
    }}>{children}</span>
  )
}

function Banner({ tone, children }: { tone: 'amber' | 'danger'; children: ReactNode }) {
  const amber = tone === 'amber'
  return (
    <div style={{
      padding: '12px 16px', borderRadius: 'var(--n-r-md, 12px)', fontSize: 13,
      background: amber ? 'rgba(217,166,72,0.10)' : 'rgba(196,90,90,0.10)',
      border: `1px solid ${amber ? 'var(--n-paused)' : 'var(--n-danger)'}`,
      color: amber ? 'var(--n-paused)' : 'var(--n-danger)',
    }}>{children}</div>
  )
}
