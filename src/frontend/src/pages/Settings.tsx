import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { type ReactNode, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import {
  type ConfigDoc,
  type NotifyTarget,
  getConfig,
  getHealth,
  getServices,
  getSettings,
  getStatus,
  logout,
  putConfig,
  updateSettings,
} from '../api/client'
import { InfoTip } from '../components/InfoTip'
import { NotifyTargetList, ReminderTime } from './Config'

export default function Settings() {
  const { t, i18n } = useTranslation()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { data: settings } = useQuery({ queryKey: ['settings'], queryFn: getSettings })
  const { data: status } = useQuery({ queryKey: ['status'], queryFn: getStatus })
  const { data: health } = useQuery({ queryKey: ['health'], queryFn: getHealth })
  const [saved, setSaved] = useState(false)
  const [theme, setTheme] = useState<'dark' | 'light'>(
    () => (localStorage.getItem('naiad_theme') === 'light' ? 'light' : 'dark'),
  )

  function applyTheme(next: 'dark' | 'light') {
    setTheme(next)
    localStorage.setItem('naiad_theme', next)
    document.documentElement.setAttribute('data-theme', next)
  }

  const mut = useMutation({
    mutationFn: updateSettings,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['settings'] })
      qc.invalidateQueries({ queryKey: ['sequences'] })
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    },
  })

  if (!settings) return (
    <div style={{ padding: 20, color: 'var(--n-fg-muted)' }}>
      {t('settings.loading', { defaultValue: 'Laden…' })}
    </div>
  )

  return (
    <div style={{ maxWidth: 900, display: 'flex', flexDirection: 'column', gap: 22 }}>
      {saved && (
        <div style={{
          display: 'inline-flex', alignSelf: 'flex-start',
          alignItems: 'center', gap: 8,
          padding: '8px 16px', borderRadius: 999,
          background: 'var(--n-teal-glow)',
          border: '1px solid rgba(94,200,216,0.25)',
          color: 'var(--n-teal-200)', fontSize: 13, fontWeight: 500,
        }}>
          ✓ {t('settings.saved', { defaultValue: 'Gespeichert' })}
        </div>
      )}

      {/* Temperatur-Faktor */}
      <SettingsSection title={t('settings.factorTemp')}>
        <SettingsRow label={t('settings.basisC')} info={t('settings.help.basisC')}>
          <NumInput value={settings.factors.temp.basis_c} unit="°C" onBlur={(v) => mut.mutate({ factors: { temp: { basis_c: v } } })} />
        </SettingsRow>
        <SettingsRow label={t('settings.pctPerC')} info={t('settings.help.pctPerC')}>
          <NumInput value={settings.factors.temp.pct_per_c} unit="%" onBlur={(v) => mut.mutate({ factors: { temp: { pct_per_c: v } } })} />
        </SettingsRow>
        <SettingsRow label={t('settings.minPct')} info={t('settings.help.minPct')}>
          <NumInput value={settings.factors.temp.min_pct} unit="%" onBlur={(v) => mut.mutate({ factors: { temp: { min_pct: v } } })} />
        </SettingsRow>
        <SettingsRow label={t('settings.maxPct')} info={t('settings.help.maxPct')} last>
          <NumInput value={settings.factors.temp.max_pct} unit="%" onBlur={(v) => mut.mutate({ factors: { temp: { max_pct: v } } })} />
        </SettingsRow>
      </SettingsSection>

      {/* Regen-Faktor */}
      <SettingsSection title={t('settings.factorRain')}>
        <SettingsRow label={t('settings.thresholdProb')} info={t('settings.help.thresholdProb')}>
          <NumInput value={settings.factors.rain.threshold_prob} unit="%" onBlur={(v) => mut.mutate({ factors: { rain: { threshold_prob: v } } })} />
        </SettingsRow>
        <SettingsRow label={t('settings.reduceAbove')} info={t('settings.help.reduceAbove')}>
          <NumInput value={settings.factors.rain.reduce_above_mm} unit="mm" onBlur={(v) => mut.mutate({ factors: { rain: { reduce_above_mm: v } } })} />
        </SettingsRow>
        <SettingsRow label={t('settings.zeroAbove')} info={t('settings.help.zeroAbove')}>
          <NumInput value={settings.factors.rain.zero_above_mm} unit="mm" onBlur={(v) => mut.mutate({ factors: { rain: { zero_above_mm: v } } })} />
        </SettingsRow>
        <SettingsRow label={t('settings.forecastDecay')} info={t('settings.help.forecastDecay')} last>
          <NumInput value={settings.factors.rain.forecast_decay} unit="" width={60} step={0.1} onBlur={(v) => mut.mutate({ factors: { rain: { forecast_decay: v } } })} />
        </SettingsRow>
      </SettingsSection>

      {/* Benachrichtigungen */}
      <NotificationsSection />

      {/* System */}
      <SettingsSection title={t('settings.system', { defaultValue: 'System' })}>
        <SettingsRow label={t('settings.configuration', { defaultValue: 'Anlagen-Konfiguration' })}>
          <button
            className="n-btn"
            style={{ height: 32, padding: '0 14px', fontSize: 12.5 }}
            onClick={() => navigate('/config')}
          >
            {t('settings.editConfig', { defaultValue: 'Bearbeiten →' })}
          </button>
        </SettingsRow>
        <SettingsRow label={t('settings.theme', { defaultValue: 'Darstellung' })}>
          <div style={{ display: 'flex', gap: 6 }}>
            {(['dark', 'light'] as const).map((mode) => (
              <button
                key={mode}
                className={`n-btn${theme === mode ? ' primary' : ''}`}
                style={{ height: 32, padding: '0 12px', fontSize: 12.5 }}
                onClick={() => applyTheme(mode)}
              >
                {t(`settings.theme_${mode}`, { defaultValue: mode === 'dark' ? 'Dunkel' : 'Hell' })}
              </button>
            ))}
          </div>
        </SettingsRow>
        <SettingsRow label={t('settings.version')}>
          <span className="mono" style={{ fontSize: 13, color: 'var(--n-fg-muted)' }}>
            v{health?.version ?? '—'}
          </span>
        </SettingsRow>
        <SettingsRow label={t('settings.haIntegration')}>
          {status?.ha_connected ? (
            <span style={{
              display: 'inline-flex', alignItems: 'center', gap: 6,
              padding: '4px 10px', borderRadius: 999,
              border: '1px solid rgba(94,200,216,0.30)',
              background: 'var(--n-teal-glow)',
              color: 'var(--n-teal-200)',
              fontSize: 12, fontWeight: 500,
            }}>
              <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--n-teal-300)' }} />
              {t('settings.connected', { defaultValue: 'Verbunden' })}
            </span>
          ) : (
            <span style={{
              display: 'inline-flex', alignItems: 'center', gap: 6,
              padding: '4px 10px', borderRadius: 999,
              border: '1px solid var(--n-line-strong)',
              color: 'var(--n-fg-muted)',
              fontSize: 12, fontWeight: 500,
            }}>
              <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--n-fg-dim)' }} />
              {t('settings.disconnected', { defaultValue: 'Getrennt' })}
            </span>
          )}
        </SettingsRow>
        <SettingsRow label={t('settings.language')} last>
          <div style={{ display: 'flex', gap: 6 }}>
            {(['de', 'en'] as const).map((lng) => (
              <button
                key={lng}
                className={`n-btn${i18n.language?.startsWith(lng) ? ' primary' : ''}`}
                style={{ height: 32, padding: '0 12px', fontSize: 12.5 }}
                onClick={() => {
                  i18n.changeLanguage(lng)
                  localStorage.setItem('naiad_lang', lng)
                }}
              >
                {lng.toUpperCase()}
              </button>
            ))}
          </div>
        </SettingsRow>
      </SettingsSection>

      <button
        className="n-btn"
        onClick={logout}
        style={{ alignSelf: 'flex-start', height: 38, padding: '0 18px', fontSize: 13 }}
      >
        {t('settings.logout')}
      </button>
    </div>
  )
}

// Notification targets + reminder time, mirroring the Config page's notification
// settings so they can be managed here too. Edits the full config document via a
// local draft and saves with putConfig.
function NotificationsSection() {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const { data: config } = useQuery({ queryKey: ['config'], queryFn: getConfig })
  const notifyServices = useQuery({ queryKey: ['services', 'notify'], queryFn: () => getServices('notify') })

  const [targets, setTargets] = useState<NotifyTarget[] | null>(null)
  const [reminderCron, setReminderCron] = useState<string | null>(null)

  useEffect(() => {
    if (config) {
      setTargets(structuredClone(config.ha.notify_targets))
      setReminderCron(config.notifications.evening_reminder_cron)
    }
  }, [config])

  const saveMut = useMutation({
    mutationFn: (body: ConfigDoc) => putConfig(body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['config'] })
    },
  })

  if (!config || targets === null || reminderCron === null) {
    return (
      <SettingsSection title={t('config.notifications', { defaultValue: 'Benachrichtigungen' })}>
        <div style={{ padding: '16px 20px', fontSize: 13, color: 'var(--n-fg-dim)' }}>
          {t('settings.loading', { defaultValue: 'Laden…' })}
        </div>
      </SettingsSection>
    )
  }

  const dirty =
    JSON.stringify(targets) !== JSON.stringify(config.ha.notify_targets) ||
    reminderCron !== config.notifications.evening_reminder_cron

  function save() {
    if (!config || targets === null || reminderCron === null) return
    saveMut.mutate({
      ...config,
      ha: { ...config.ha, notify_targets: targets },
      notifications: { ...config.notifications, evening_reminder_cron: reminderCron },
    })
  }

  return (
    <SettingsSection title={t('config.notifications', { defaultValue: 'Benachrichtigungen' })}>
      <SettingsRow label={t('config.notifyTargets', { defaultValue: 'Notify-Ziele' })} align="start">
        <NotifyTargetList
          values={targets}
          services={notifyServices.data?.services}
          dirty={dirty}
          onChange={setTargets}
        />
      </SettingsRow>
      <SettingsRow label={t('config.notifyReminderTime', { defaultValue: 'Erinnerungszeit' })}>
        <ReminderTime value={reminderCron} onChange={setReminderCron} />
      </SettingsRow>
      <SettingsRow label="" last>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <button
            className="n-btn primary"
            disabled={!dirty || saveMut.isPending}
            style={{ height: 34, padding: '0 16px', fontSize: 13 }}
            onClick={save}
          >
            {saveMut.isPending
              ? t('config.saving', { defaultValue: 'Speichern…' })
              : t('config.save', { defaultValue: 'Speichern' })}
          </button>
          {dirty && (
            <span style={{ fontSize: 12, color: 'var(--n-fg-muted)' }}>
              {t('config.unsaved', { defaultValue: 'Ungespeichert' })}
            </span>
          )}
        </div>
      </SettingsRow>
    </SettingsSection>
  )
}

function SettingsSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div style={{
      display: 'flex', flexDirection: 'column', gap: 0,
      border: '1px solid var(--n-line)',
      borderRadius: 'var(--n-r-lg)',
      overflow: 'hidden',
    }}>
      <div style={{
        padding: '14px 20px',
        background: 'rgba(255,255,255,0.015)',
        borderBottom: '1px solid var(--n-line)',
      }}>
        <span style={{ fontSize: 16, fontWeight: 600, letterSpacing: '-0.01em' }}>{title}</span>
      </div>
      {children}
    </div>
  )
}

function SettingsRow({ label, children, last = false, info, align = 'center' }: {
  label: ReactNode; children: ReactNode; last?: boolean; info?: string; align?: 'center' | 'start'
}) {
  return (
    <div style={{
      display: 'flex', alignItems: align === 'start' ? 'flex-start' : 'center', justifyContent: 'space-between',
      padding: '12px 20px',
      borderBottom: last ? 'none' : '1px solid var(--n-line)',
      minHeight: 52, gap: 16,
    }}>
      <span style={{ fontSize: 14, color: 'var(--n-fg-soft)', display: 'inline-flex', alignItems: 'center', gap: 7, paddingTop: align === 'start' ? 6 : 0 }}>
        {label}
        {info && <InfoTip text={info} />}
      </span>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        {children}
      </div>
    </div>
  )
}

function NumInput({ value, unit, width = 72, step = 1, onBlur }: {
  value: number; unit: string; width?: number; step?: number
  onBlur: (v: number) => void
}) {
  const [localVal, setLocalVal] = useState(String(value))

  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 0,
      background: 'var(--n-card-elev)',
      border: '1px solid var(--n-line-strong)',
      borderRadius: 'var(--n-r-sm)',
      overflow: 'hidden', height: 36,
    }}>
      <input
        type="number"
        value={localVal}
        step={step}
        onChange={(e) => setLocalVal(e.target.value)}
        onBlur={(e) => {
          const num = parseFloat(e.target.value)
          if (!isNaN(num)) onBlur(num)
        }}
        style={{
          width, height: '100%', padding: '0 10px',
          background: 'transparent', border: 'none',
          color: 'var(--n-fg)', fontSize: 14,
          fontFamily: 'var(--n-sans)',
          fontVariantNumeric: 'tabular-nums',
          textAlign: 'right', outline: 'none',
        }}
      />
      {unit && (
        <span style={{
          padding: '0 8px', color: 'var(--n-fg-muted)', fontSize: 12,
          borderLeft: '1px solid var(--n-line)',
          height: '100%', display: 'flex', alignItems: 'center',
          background: 'rgba(255,255,255,0.015)',
        }}>
          {unit}
        </span>
      )}
    </div>
  )
}
