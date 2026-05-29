import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { type CSSProperties, type ReactNode, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
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

  // HA entities grouped by domain, for the searchable entity pickers.
  const entitiesByDomain: Record<string, EntityInfo[] | undefined> = {
    switch: switches.data?.entities,
    sensor: sensors.data?.entities,
    binary_sensor: binarySensors.data?.entities,
  }

  return (
    <div className="config-page" style={{ maxWidth: 940, display: 'flex', flexDirection: 'column', gap: 22, paddingBottom: 88 }}>

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
            <EntityCombobox
              value={draft.sensors[f.key]}
              onChange={(v) => patch((d) => { d.sensors[f.key] = v })}
              entities={entitiesByDomain[f.domain]}
              domain={f.domain}
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
            onAdd={(id, name) => patch((d) => { d.zones[id] = { label: name, switch: '', flow_lph: 0 } })}
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
                <EntityCombobox
                  value={z.switch}
                  onChange={(v) => patch((d) => { d.zones[id].switch = v })}
                  entities={entitiesByDomain.switch}
                  domain="switch"
                  width={240}
                />
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
            onAdd={(id, name) => patch((d) => {
              d.sequences[id] = {
                label: name, zones: [], basis_min_per_zone: 30, range: [5, 240],
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
            zones={draft.zones}
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

function SequenceEditor({ id, seq, zoneIds, zones, last, onChange, onDelete }: {
  id: string
  seq: SequenceConfig
  zoneIds: string[]
  zones: ConfigDoc['zones']
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
                {active ? `${seq.zones.indexOf(zid) + 1}. ` : ''}{zones[zid]?.label || zid}
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
    <div className="n-cfg-row" style={{
      display: 'flex', alignItems: align === 'start' ? 'flex-start' : 'center',
      justifyContent: 'space-between', gap: 16,
      padding: '12px 20px', borderBottom: last ? 'none' : '1px solid var(--n-line)', minHeight: 52,
    }}>
      <span style={{ fontSize: 14, color: 'var(--n-fg-soft)', paddingTop: align === 'start' ? 6 : 0 }}>{label}</span>
      <div className="n-cfg-control" style={{ display: 'flex', alignItems: 'center', gap: 10 }}>{children}</div>
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

// Derive an internal snake_case id from a human name. Umlauts/diacritics are
// stripped (NFKD), everything non-alphanumeric collapses to single underscores.
function slugify(name: string): string {
  return name
    .normalize('NFKD')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
}

// Ensure the generated id doesn't collide with an existing one.
function uniqueId(base: string, existing: string[]): string {
  const root = base || 'item'
  if (!existing.includes(root)) return root
  let n = 2
  while (existing.includes(`${root}_${n}`)) n++
  return `${root}_${n}`
}

function AddButton({ label, existing, onAdd }: {
  label: string; existing: string[]; onAdd: (id: string, name: string) => void
}) {
  const { t } = useTranslation()
  const [adding, setAdding] = useState(false)
  const [name, setName] = useState('')
  // The user types a name; the id is generated for them. Valid as long as the
  // name yields a non-empty slug.
  const valid = slugify(name).length > 0
  function submit() {
    if (!valid) return
    onAdd(uniqueId(slugify(name), existing), name.trim())
    setName('')
    setAdding(false)
  }
  if (!adding) {
    return (
      <button className="n-btn" style={{ height: 32, padding: '0 12px', fontSize: 12.5 }} onClick={() => setAdding(true)}>
        + {label}
      </button>
    )
  }
  return (
    <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
      <input autoFocus style={{ ...inputStyle, width: 180, height: 32 }} value={name}
        placeholder={t('config.namePlaceholder', { defaultValue: 'Bezeichnung' })}
        onChange={(e) => setName(e.target.value)}
        onKeyDown={(e) => { if (e.key === 'Enter') submit() }} />
      <button className="n-btn primary" disabled={!valid} style={{ height: 32, padding: '0 12px', fontSize: 12.5 }}
        onClick={submit}>
        {t('config.add', { defaultValue: 'OK' })}
      </button>
      <button className="n-btn" style={{ height: 32, padding: '0 10px', fontSize: 12.5 }}
        onClick={() => { setName(''); setAdding(false) }}>✕</button>
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

// Searchable entity picker populated from Home Assistant. Filters by friendly
// name or entity_id as you type, shows a type hint, and still accepts a pasted /
// typed entity_id that isn't in the list. The dropdown is portalled to <body> so
// the Section's `overflow: hidden` can't clip it.
function EntityCombobox({ value, onChange, entities, domain, width = 320 }: {
  value: string
  onChange: (v: string) => void
  entities?: EntityInfo[]
  domain: string
  width?: number
}) {
  const { t } = useTranslation()
  const wrapRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const [rect, setRect] = useState<DOMRect | null>(null)

  const list = entities ?? []
  const q = query.trim().toLowerCase()
  const matches = (
    q
      ? list.filter(
          (e) =>
            e.entity_id.toLowerCase().includes(q) ||
            (e.friendly_name?.toLowerCase().includes(q) ?? false),
        )
      : list
  ).slice(0, 50)

  function reposition() {
    if (inputRef.current) setRect(inputRef.current.getBoundingClientRect())
  }

  useEffect(() => {
    if (!open) return
    const onScroll = () => reposition()
    const onDown = (e: MouseEvent) => {
      const target = e.target as Node
      if (wrapRef.current?.contains(target)) return
      if (document.getElementById('entity-combobox-pop')?.contains(target)) return
      setOpen(false)
    }
    window.addEventListener('scroll', onScroll, true)
    window.addEventListener('resize', onScroll)
    document.addEventListener('mousedown', onDown)
    return () => {
      window.removeEventListener('scroll', onScroll, true)
      window.removeEventListener('resize', onScroll)
      document.removeEventListener('mousedown', onDown)
    }
  }, [open])

  function choose(e: EntityInfo) {
    onChange(e.entity_id)
    setQuery('')
    setOpen(false)
  }

  // Commit free text only if it looks like an entity id (so an abandoned search
  // term doesn't overwrite the saved value).
  function commitFreeText() {
    if (query && query.includes('.') && query !== value) onChange(query)
    setOpen(false)
  }

  const looksLikeId = q.includes('.')

  return (
    <div ref={wrapRef} style={{ width, maxWidth: '100%', display: 'flex', flexDirection: 'column', gap: 3 }}>
      <input
        ref={inputRef}
        style={{ ...inputStyle, width: '100%' }}
        value={open ? query : value}
        placeholder={
          open && value ? value : t('config.entitySearch', { defaultValue: 'Suchen oder Entity-ID…' })
        }
        onFocus={() => { setQuery(''); setActive(0); reposition(); setOpen(true) }}
        onChange={(e) => { setQuery(e.target.value); setActive(0); if (!open) { reposition(); setOpen(true) } }}
        onBlur={() => { if (open) commitFreeText() }}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown') { e.preventDefault(); setOpen(true); setActive((a) => Math.min(a + 1, matches.length - 1)) }
          else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)) }
          else if (e.key === 'Enter') {
            if (open && matches[active]) { e.preventDefault(); choose(matches[active]) }
            else if (looksLikeId) { e.preventDefault(); commitFreeText() }
          } else if (e.key === 'Escape') { setQuery(''); setOpen(false) }
        }}
      />
      <span style={{ fontSize: 10.5, color: 'var(--n-fg-dim)', letterSpacing: '0.02em' }}>
        {t('config.expects', { defaultValue: 'Erwartet' })}:{' '}
        {t(`config.entityType.${domain}`, { defaultValue: domain })}
      </span>
      {open && rect && createPortal(
        <div
          id="entity-combobox-pop"
          className="n-card"
          style={{
            position: 'fixed', top: rect.bottom + 4, left: rect.left, width: rect.width,
            maxHeight: 260, overflowY: 'auto', padding: 4, zIndex: 1000,
          }}
        >
          {matches.length === 0 ? (
            <div style={{ padding: '8px 10px', fontSize: 12.5, color: 'var(--n-fg-muted)' }}>
              {t('config.noEntities', { defaultValue: 'Keine passenden Entitäten' })}
            </div>
          ) : (
            matches.map((e, i) => (
              <button
                key={e.entity_id}
                type="button"
                onMouseEnter={() => setActive(i)}
                onMouseDown={(ev) => { ev.preventDefault(); choose(e) }}
                style={{
                  display: 'block', width: '100%', textAlign: 'left', padding: '7px 10px',
                  background: i === active ? 'var(--n-teal-glow)' : 'transparent',
                  border: 0, borderRadius: 6, cursor: 'pointer',
                }}
              >
                <div style={{ fontSize: 13, color: 'var(--n-fg)' }}>{e.friendly_name || e.entity_id}</div>
                {e.friendly_name && (
                  <div className="mono" style={{ fontSize: 11, color: 'var(--n-fg-muted)' }}>{e.entity_id}</div>
                )}
              </button>
            ))
          )}
        </div>,
        document.body,
      )}
    </div>
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
