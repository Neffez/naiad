import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Outlet } from 'react-router-dom'
import { queryKeys } from '../../api/queryKeys'
import {
  type ConfigDoc,
  type EntityInfo,
  exportConfig,
  getConfig,
  getEntities,
  getServices,
  importConfig,
  putConfig,
} from '../../api/client'
import { ConfirmActionDialog } from '../../components/ConfirmActionDialog'
import { toast } from '../../components/Toast'
import { SubNav } from '../../components/config/SubNav'
import { Banner, Pill } from '../../components/config/primitives'
import { ConfigProvider } from './ConfigContext'
import { SECTIONS, type SectionId } from './sectionsMeta'

// The config slice a section edits, for per-section dirty markers in the
// sub-navigation. Dirty is computed per slice so the badge points at the
// section that changed.
function sectionSlice(d: ConfigDoc, id: SectionId): unknown {
  switch (id) {
    case 'zones': return d.zones
    case 'sequences': return { sequences: d.sequences, colors: d.sequence_colors_enabled }
    case 'notifications': return { notifications: d.notifications, targets: d.ha.notify_targets }
    case 'connection': return { url: d.ha.url, sensors: d.sensors }
    case 'integrations': return d.mqtt
    case 'advanced': return { timezone: d.timezone, auth: d.auth }
    default: return null
  }
}

export default function SettingsLayout() {
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

  // Memoized: the JSON round-trips only rerun when draft or data actually change
  // (setDraft always produces a fresh object), not on unrelated rerenders.
  const dirty = useMemo(
    () => draft != null && data != null && JSON.stringify(draft) !== JSON.stringify(data),
    [draft, data],
  )
  const dirtySections = useMemo(() => {
    const out = new Set<SectionId>()
    if (!draft || !data) return out
    // Derive the draft-backed sections from the metadata so a new section (or a
    // change to usesDraft) is picked up here without editing a parallel list.
    for (const s of SECTIONS) {
      if (!s.usesDraft) continue
      if (JSON.stringify(sectionSlice(draft, s.id)) !== JSON.stringify(sectionSlice(data, s.id))) {
        out.add(s.id)
      }
    }
    return out
  }, [draft, data])

  if (!draft) {
    return (
      <div style={{ padding: 20, color: 'var(--n-fg-muted)' }}>
        {t('config.loading')}
      </div>
    )
  }

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

  // HA entities grouped by domain, for the searchable entity pickers.
  const entitiesByDomain: Record<string, EntityInfo[] | undefined> = {
    switch: switches.data?.entities,
    sensor: sensors.data?.entities,
    binary_sensor: binarySensors.data?.entities,
  }

  const counts: Partial<Record<SectionId, number>> = {
    zones: Object.keys(draft.zones).length,
    sequences: Object.keys(draft.sequences).length,
  }

  return (
    <ConfigProvider value={{
      draft,
      patch,
      dirty,
      entitiesByDomain,
      notifyServices: notifyServices.data?.services,
      requestDelete: setPendingDelete,
      onExport: handleExport,
      onImportClick: () => fileRef.current?.click(),
    }}>
      <div className="n-settings-shell">
        <SubNav dirtySections={dirtySections} counts={counts} />

        <div className="n-settings-content" style={{ display: 'flex', flexDirection: 'column', gap: 18, minWidth: 0, paddingBottom: 88 }}>
          {restart && <Banner tone="amber">{t('config.restartRequired')}</Banner>}
          {error && <Banner tone="danger">{error}</Banner>}

          <Outlet />
        </div>
      </div>

      {/* Contextual save bar — appears only when the config draft has unsaved
          changes, so it never clutters the settings/system sections. */}
      {dirty && (
        <div className="n-save-bar" style={{
          position: 'sticky', bottom: 0, marginTop: 4,
          display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap',
          padding: '14px 18px',
          background: 'var(--n-bg-elev)',
          border: '1px solid var(--n-line)',
          borderRadius: 'var(--n-r-lg)',
          zIndex: 5,
        }}>
          <button className="n-btn primary" disabled={saveMut.isPending}
            style={{ height: 38, padding: '0 20px', fontSize: 13 }}
            onClick={() => saveMut.mutate(draft)}>
            {saveMut.isPending ? t('config.saving') : t('config.save')}
          </button>
          <button className="n-btn"
            style={{ height: 38, padding: '0 16px', fontSize: 13 }}
            onClick={() => data && setDraft(structuredClone(data))}>
            {t('config.reset')}
          </button>
          <div style={{ flex: 1 }} />
          <Pill tone="muted">{t('config.unsaved')}</Pill>
        </div>
      )}
      {saved && !dirty && (
        <div style={{ position: 'sticky', bottom: 0, marginTop: 4, display: 'flex', justifyContent: 'flex-end' }}>
          <Pill tone="teal">✓ {t('config.saved')}</Pill>
        </div>
      )}

      <input ref={fileRef} type="file" accept=".yaml,.yml,.json" aria-hidden="true" tabIndex={-1} style={{ display: 'none' }} onChange={handleImportFile} />

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
    </ConfigProvider>
  )
}
