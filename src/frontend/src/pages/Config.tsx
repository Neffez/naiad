import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { queryKeys } from '../api/queryKeys'
import {
  type ConfigDoc,
  type EntityInfo,
  exportConfig,
  getConfig,
  getEntities,
  getServices,
  importConfig,
  putConfig,
  testNotify,
} from '../api/client'
import { ConfirmActionDialog } from '../components/ConfirmActionDialog'
import { InfoTip } from '../components/InfoTip'
import { NumberField } from '../components/NumberField'
import { toast } from '../components/Toast'
import { NotifyTargetList, ReminderTime, SequenceEditor } from '../components/config/editors'
import { inputStyle } from '../components/config/formStyles'
import {
  AddButton,
  Banner,
  CardRow,
  Check,
  DeleteButton,
  Empty,
  EntityCombobox,
  IdTag,
  Labeled,
  Num,
  Pill,
  Row,
  Section,
  StringList,
} from '../components/config/primitives'

export default function Config() {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const { data } = useQuery({ queryKey: queryKeys.config, queryFn: getConfig })
  const switches = useQuery({ queryKey: queryKeys.entities('switch'), queryFn: () => getEntities('switch') })
  const sensors = useQuery({ queryKey: queryKeys.entities('sensor'), queryFn: () => getEntities('sensor') })
  const binarySensors = useQuery({
    queryKey: queryKeys.entities('binary_sensor'),
    queryFn: () => getEntities('binary_sensor'),
  })
  const notifyServices = useQuery({
    queryKey: queryKeys.services('notify'),
    queryFn: () => getServices('notify'),
  })

  const [draft, setDraft] = useState<ConfigDoc | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const [restart, setRestart] = useState(false)
  const [pendingDelete, setPendingDelete] = useState<{ type: 'zone' | 'sequence'; id: string } | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (data) setDraft(structuredClone(data))
  }, [data])

  const saveMut = useMutation({
    mutationFn: (body: ConfigDoc) => putConfig(body),
    onSuccess: (resp) => {
      setError(null)
      setRestart(resp.restart_required)
      setSaved(true)
      setTimeout(() => setSaved(false), 2500)
      qc.invalidateQueries({ queryKey: queryKeys.config })
      qc.invalidateQueries({ queryKey: queryKeys.sequences })
      qc.invalidateQueries({ queryKey: queryKeys.status })
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
      qc.invalidateQueries({ queryKey: queryKeys.config })
      qc.invalidateQueries({ queryKey: queryKeys.sequences })
    },
    onError: (e: Error) => setError(e.message),
  })

  if (!draft) {
    return (
      <div style={{ padding: 20, color: 'var(--n-fg-muted)' }}>
        {t('config.loading')}
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
      // Download — robust across browsers: the anchor must be in the DOM, and the
      // object URL must be revoked late (revoking immediately can abort the download).
      const blob = new Blob([text], { type: 'application/x-yaml' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = 'naiad-config.yaml'
      document.body.appendChild(a)
      a.click()
      a.remove()
      setTimeout(() => URL.revokeObjectURL(url), 10000)
      // The Home Assistant add-on serves the UI in a sandboxed iframe that often
      // blocks file downloads, so also copy the YAML to the clipboard — there is
      // always a way to get the config out.
      try {
        await navigator.clipboard.writeText(text)
        toast(t('config.exportedCopied'), 'success')
      } catch {
        toast(t('config.exported'), 'success')
      }
    } catch (e) {
      toast((e as Error).message, 'error')
    }
  }

  function handleImportFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    file.text().then((text) => importMut.mutate(text))
    e.target.value = '' // allow re-selecting the same file
  }

  async function handleTestNotify() {
    try {
      const r = await testNotify()
      toast(t('config.notifyTestOk', { count: r.sent }), 'success')
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), 'error')
    }
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
      <Section title={t('config.ha')}>
        <Row label={t('config.haUrl')} last>
          <input
            style={{ ...inputStyle, width: 360 }}
            value={draft.ha.url}
            onChange={(e) => patch((d) => { d.ha.url = e.target.value })}
          />
        </Row>
      </Section>

      {/* Sensors */}
      <Section title={t('config.sensors')}>
        {SENSOR_FIELDS.map((f, i) => (
          <Row
            key={f.key}
            label={
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 7 }}>
                {t(`config.sensor.${f.key}`, { defaultValue: f.fallback })}
                <InfoTip text={t(`config.sensorHelp.${f.infoKey}`)} />
              </span>
            }
            last={i === SENSOR_FIELDS.length - 1}
          >
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
        title={t('config.zones')}
        action={
          <AddButton
            label={t('config.addZone')}
            existing={zoneIds}
            onAdd={(id, name) => patch((d) => { d.zones[id] = { label: name, switch: '', flow_lph: 0 } })}
          />
        }
      >
        {zoneIds.length === 0 && <Empty>{t('config.noZones')}</Empty>}
        {zoneIds.map((id, i) => {
          const z = draft.zones[id]
          return (
            <CardRow key={id} last={i === zoneIds.length - 1}>
              <IdTag id={id} />
              <Labeled label={t('config.label')}>
                <input style={{ ...inputStyle, width: 160 }} value={z.label}
                  onChange={(e) => patch((d) => { d.zones[id].label = e.target.value })} />
              </Labeled>
              <Labeled label={t('config.switch')}>
                <EntityCombobox
                  value={z.switch}
                  onChange={(v) => patch((d) => { d.zones[id].switch = v })}
                  entities={entitiesByDomain.switch}
                  domain="switch"
                  width={240}
                />
              </Labeled>
              <Labeled label={t('config.flowLph')}>
                <NumberField value={z.flow_lph} width={90}
                  onChange={(v) => patch((d) => { d.zones[id].flow_lph = v })} />
              </Labeled>
              <DeleteButton onClick={() => setPendingDelete({ type: 'zone', id })} />
            </CardRow>
          )
        })}
      </Section>

      {/* Sequences */}
      <Section
        title={t('config.sequences')}
        action={
          <AddButton
            label={t('config.addSequence')}
            existing={Object.keys(draft.sequences)}
            onAdd={(id, name) => patch((d) => {
              d.sequences[id] = {
                label: name, zones: [], basis_min_per_zone: 30, range: [5, 240],
                watchdog_min: 60, schedule: { days: [], times: ['06:00'], cron: null }, enabled: false, wind_blocks: false,
                color: null,
              }
            })}
          />
        }
      >
        <Row label={t('config.sequenceColors')}>
          <Check
            label={t('config.sequenceColorsHint')}
            checked={draft.sequence_colors_enabled}
            onChange={(v) => patch((d) => { d.sequence_colors_enabled = v })}
          />
        </Row>
        {Object.keys(draft.sequences).length === 0 && (
          <Empty>{t('config.noSequences')}</Empty>
        )}
        {Object.entries(draft.sequences).map(([id, s], i, arr) => (
          <SequenceEditor
            key={id}
            id={id}
            seq={s}
            zoneIds={zoneIds}
            zones={draft.zones}
            last={i === arr.length - 1}
            colorsEnabled={draft.sequence_colors_enabled}
            onChange={(mut) => patch((d) => mut(d.sequences[id]))}
            onDelete={() => setPendingDelete({ type: 'sequence', id })}
          />
        ))}
      </Section>

      {/* MQTT statistics bridge — publishes tracked liters/durations to HA */}
      <Section title={t('config.mqtt')}>
        <Row label={t('config.mqttEnabled')}>
          <Check
              label={t('config.mqttEnabledHint')}
              checked={draft.mqtt.enabled}
              onChange={(v) => patch((d) => { d.mqtt.enabled = v })}
          />
        </Row>
        <Row label={t('config.mqttHost')}>
          <input
              style={{ ...inputStyle, width: 280 }}
              value={draft.mqtt.host}
              placeholder="core-mosquitto"
              onChange={(e) => patch((d) => { d.mqtt.host = e.target.value })}
          />
        </Row>
        <Row label={t('config.mqttPort')}>
          <Num value={draft.mqtt.port} onChange={(v) => patch((d) => { d.mqtt.port = v })} />
        </Row>
        <Row label={t('config.mqttUsername')}>
          <input
              style={{ ...inputStyle, width: 200 }}
              value={draft.mqtt.username}
              onChange={(e) => patch((d) => { d.mqtt.username = e.target.value })}
          />
        </Row>
        <Row label={t('config.mqttBaseTopic')} last>
          <input
              style={{ ...inputStyle, width: 200, fontFamily: 'var(--n-mono, monospace)' }}
              value={draft.mqtt.base_topic}
              onChange={(e) => patch((d) => { d.mqtt.base_topic = e.target.value })}
          />
        </Row>
      </Section>

      {/* Notifications (global) — per-recipient choices live on each notify target below */}
      <Section title={t('config.notifications')}>
        <Row label={t('config.notifyReminderTime')}>
          <ReminderTime
              value={draft.notifications.evening_reminder_cron}
              onChange={(cron) => patch((d) => { d.notifications.evening_reminder_cron = cron })}
          />
        </Row>
        <Row
            label={
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 7 }}>
                {t('config.notifyQueueMaxHours')}
                <InfoTip text={t('config.notifyQueueMaxHoursHelp')} />
              </span>
            }
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <input
                type="number" min={0} step={1}
                style={{ ...inputStyle, width: 120, fontVariantNumeric: 'tabular-nums' }}
                value={draft.notifications.queue_max_hours}
                onChange={(e) => patch((d) => {
                  const n = Number(e.target.value)
                  d.notifications.queue_max_hours = e.target.value === '' || Number.isNaN(n) ? 0 : Math.max(0, n)
                })}
            />
            <span style={{ color: 'var(--n-dim)', fontSize: 13 }}>{t('config.notifyQueueMaxHoursUnit')}</span>
          </div>
        </Row>
        <Row label={t('config.notifyTargets')} last align="start">
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, width: '100%' }}>
            <NotifyTargetList
                values={draft.ha.notify_targets}
                services={notifyServices.data?.services}
                dirty={dirty}
                onChange={(vals) => patch((d) => { d.ha.notify_targets = vals })}
            />
            <button
                className="n-btn"
                style={{ height: 32, padding: '0 12px', fontSize: 12.5, alignSelf: 'flex-start' }}
                disabled={dirty || draft.ha.notify_targets.length === 0}
                title={dirty ? t('config.saveFirst') : undefined}
                onClick={handleTestNotify}
            >
              {t('config.notifyTest')}
            </button>
          </div>
        </Row>
      </Section>

      {/* Factors are edited on the Settings page (FactorOverride layer), which
          always takes precedence over these base values at runtime. Editing them
          here too would be misleading, so the section lives only in Settings. */}

      {/* Advanced */}
      <Section title={t('config.advanced')}>
        <Row label={t('config.timezone')}>
          <input style={{ ...inputStyle, width: 220 }} value={draft.timezone}
            onChange={(e) => patch((d) => { d.timezone = e.target.value })} />
        </Row>
        <Row label={t('config.authMode')}>
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
              {t('config.authNoneWarning')}
            </Banner>
          </div>
        )}
        <Row label={t('config.frameAncestors')} last align="start">
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
            ? t('config.saving')
            : t('config.save')}
        </button>
        <button className="n-btn" disabled={!dirty}
          style={{ height: 38, padding: '0 16px', fontSize: 13 }}
          onClick={() => data && setDraft(structuredClone(data))}>
          {t('config.reset')}
        </button>
        <div style={{ flex: 1 }} />
        <button className="n-btn" style={{ height: 38, padding: '0 16px', fontSize: 13 }} onClick={handleExport}>
          {t('config.export')}
        </button>
        <button className="n-btn" style={{ height: 38, padding: '0 16px', fontSize: 13 }}
          onClick={() => fileRef.current?.click()}>
          {t('config.import')}
        </button>
        <input ref={fileRef} type="file" accept=".yaml,.yml,.json" style={{ display: 'none' }} onChange={handleImportFile} />

        {dirty && <Pill tone="muted">{t('config.unsaved')}</Pill>}
        {saved && <Pill tone="teal">✓ {t('config.saved')}</Pill>}
      </div>

      {restart && (
        <Banner tone="amber">
          {t('config.restartRequired')}
        </Banner>
      )}
      {error && <Banner tone="danger">{error}</Banner>}

      <ConfirmActionDialog
        open={pendingDelete != null}
        tone="danger"
        title={
          pendingDelete?.type === 'sequence'
            ? t('config.deleteSequenceTitle')
            : t('config.deleteZoneTitle')
        }
        message={
          pendingDelete?.type === 'sequence'
            ? t('config.deleteSequenceMsg', { name: draft.sequences[pendingDelete.id]?.label || pendingDelete?.id })
            : t('config.deleteZoneMsg', { name: pendingDelete ? draft.zones[pendingDelete.id]?.label || pendingDelete.id : '' })
        }
        confirmLabel={t('config.delete')}
        onCancel={() => setPendingDelete(null)}
        onConfirm={() => {
          if (!pendingDelete) return
          const { type, id } = pendingDelete
          patch((d) => {
            if (type === 'sequence') {
              delete d.sequences[id]
            } else {
              delete d.zones[id]
              // Drop the deleted zone from every sequence that referenced it —
              // otherwise the config can't be saved (dangling zone reference).
              for (const seq of Object.values(d.sequences)) {
                seq.zones = seq.zones.filter((z) => z !== id)
              }
            }
          })
          setPendingDelete(null)
        }}
      />
    </div>
  )
}

// ── Field metadata ─────────────────────────────────────────────────────────────

const SENSOR_FIELDS: { key: keyof ConfigDoc['sensors']; domain: string; fallback: string; infoKey: string }[] = [
  { key: 'rain', domain: 'binary_sensor', fallback: 'Regen', infoKey: 'rain' },
  { key: 'wind', domain: 'binary_sensor', fallback: 'Wind', infoKey: 'wind' },
  { key: 'season', domain: 'binary_sensor', fallback: 'Saison', infoKey: 'season' },
  { key: 'temperature', domain: 'sensor', fallback: 'Temperatur', infoKey: 'temperature' },
  { key: 'temperature_max', domain: 'sensor', fallback: 'Max-Temperatur (Prognose)', infoKey: 'temperature_max' },
  { key: 'precipitation_prob_today', domain: 'sensor', fallback: 'Regenwahrscheinlichkeit heute', infoKey: 'precipitation_prob_today' },
  { key: 'precipitation_prob_tomorrow', domain: 'sensor', fallback: 'Regenwahrscheinlichkeit morgen', infoKey: 'precipitation_prob_tomorrow' },
  { key: 'precipitation_today', domain: 'sensor', fallback: 'Niederschlag heute', infoKey: 'precipitation_today' },
  { key: 'precipitation_tomorrow', domain: 'sensor', fallback: 'Niederschlag morgen', infoKey: 'precipitation_tomorrow' },
]

