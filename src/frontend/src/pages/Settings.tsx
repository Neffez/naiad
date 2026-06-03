import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { queryKeys } from '../api/queryKeys'
import { type ReactNode, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import {
  getHealth,
  getSettings,
  getStatus,
  logout,
  updateSettings,
} from '../api/client'
import { InfoTip } from '../components/InfoTip'
import { NumberField } from '../components/NumberField'

export default function Settings() {
  const { t, i18n } = useTranslation()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { data: settings } = useQuery({ queryKey: queryKeys.settings, queryFn: getSettings })
  const { data: status } = useQuery({ queryKey: queryKeys.status, queryFn: getStatus })
  const { data: health } = useQuery({ queryKey: queryKeys.health, queryFn: getHealth })
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
      qc.invalidateQueries({ queryKey: queryKeys.settings })
      qc.invalidateQueries({ queryKey: queryKeys.sequences })
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    },
  })

  if (!settings) return (
    <div style={{ padding: 20, color: 'var(--n-fg-muted)' }}>
      {t('settings.loading')}
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
          border: '1px solid var(--n-glow-border)',
          color: 'var(--n-teal-200)', fontSize: 13, fontWeight: 500,
        }}>
          ✓ {t('settings.saved')}
        </div>
      )}

      {/* Temperatur-Faktor */}
      <SettingsSection title={t('settings.factorTemp')}>
        <SettingsRow label={t('settings.basisC')} info={t('settings.help.basisC')}>
          <NumInput label={t('settings.basisC')} value={settings.factors.temp.basis_c} unit="°C" onBlur={(v) => mut.mutate({ factors: { temp: { basis_c: v } } })} />
        </SettingsRow>
        <SettingsRow label={t('settings.pctPerC')} info={t('settings.help.pctPerC')}>
          <NumInput label={t('settings.pctPerC')} value={settings.factors.temp.pct_per_c} unit="%" onBlur={(v) => mut.mutate({ factors: { temp: { pct_per_c: v } } })} />
        </SettingsRow>
        <SettingsRow label={t('settings.minPct')} info={t('settings.help.minPct')}>
          <NumInput label={t('settings.minPct')} value={settings.factors.temp.min_pct} unit="%" onBlur={(v) => mut.mutate({ factors: { temp: { min_pct: v } } })} />
        </SettingsRow>
        <SettingsRow label={t('settings.maxPct')} info={t('settings.help.maxPct')} last>
          <NumInput label={t('settings.maxPct')} value={settings.factors.temp.max_pct} unit="%" onBlur={(v) => mut.mutate({ factors: { temp: { max_pct: v } } })} />
        </SettingsRow>
      </SettingsSection>

      {/* Regen-Faktor */}
      <SettingsSection title={t('settings.factorRain')}>
        <SettingsRow label={t('settings.thresholdProb')} info={t('settings.help.thresholdProb')}>
          <NumInput label={t('settings.thresholdProb')} value={settings.factors.rain.threshold_prob} unit="%" onBlur={(v) => mut.mutate({ factors: { rain: { threshold_prob: v } } })} />
        </SettingsRow>
        <SettingsRow label={t('settings.reduceAbove')} info={t('settings.help.reduceAbove')}>
          <NumInput label={t('settings.reduceAbove')} value={settings.factors.rain.reduce_above_mm} unit="mm" onBlur={(v) => mut.mutate({ factors: { rain: { reduce_above_mm: v } } })} />
        </SettingsRow>
        <SettingsRow label={t('settings.zeroAbove')} info={t('settings.help.zeroAbove')}>
          <NumInput label={t('settings.zeroAbove')} value={settings.factors.rain.zero_above_mm} unit="mm" onBlur={(v) => mut.mutate({ factors: { rain: { zero_above_mm: v } } })} />
        </SettingsRow>
        <SettingsRow label={t('settings.forecastDecay')} info={t('settings.help.forecastDecay')}>
          <NumInput label={t('settings.forecastDecay')} value={settings.factors.rain.forecast_decay} unit="" width={60} step={0.1} onBlur={(v) => mut.mutate({ factors: { rain: { forecast_decay: v } } })} />
        </SettingsRow>
        <SettingsRow label={t('settings.peakTomorrow')} info={t('settings.help.peakTomorrow')}>
          <div role="group" aria-label={t('settings.peakTomorrow')} style={{ display: 'flex', gap: 6 }}>
            {([false, true] as const).map((val) => (
              <button
                key={String(val)}
                className={`n-btn${settings.factors.rain.peak_tomorrow === val ? ' primary' : ''}`}
                aria-pressed={settings.factors.rain.peak_tomorrow === val}
                style={{ height: 32, padding: '0 12px', fontSize: 12.5 }}
                onClick={() => mut.mutate({ factors: { rain: { peak_tomorrow: val } } })}
              >
                {val ? t('settings.peakTomorrow_both') : t('settings.peakTomorrow_today')}
              </button>
            ))}
          </div>
        </SettingsRow>
        <SettingsRow label={t('settings.confirmRainSensor')} info={t('settings.help.confirmRainSensor')} last>
          <div role="group" aria-label={t('settings.confirmRainSensor')} style={{ display: 'flex', gap: 6 }}>
            {([false, true] as const).map((val) => (
              <button
                key={String(val)}
                className={`n-btn${settings.factors.rain.confirm_with_rain_sensor === val ? ' primary' : ''}`}
                aria-pressed={settings.factors.rain.confirm_with_rain_sensor === val}
                style={{ height: 32, padding: '0 12px', fontSize: 12.5 }}
                onClick={() => mut.mutate({ factors: { rain: { confirm_with_rain_sensor: val } } })}
              >
                {val ? t('settings.confirmRainSensor_on') : t('settings.confirmRainSensor_off')}
              </button>
            ))}
          </div>
        </SettingsRow>
      </SettingsSection>

      {/* System */}
      <SettingsSection title={t('settings.system')}>
        <SettingsRow label={t('settings.configuration')}>
          <button
            className="n-btn"
            style={{ height: 32, padding: '0 14px', fontSize: 12.5 }}
            onClick={() => navigate('/config')}
          >
            {t('settings.editConfig')}
          </button>
        </SettingsRow>
        <SettingsRow label={t('settings.theme')}>
          <div role="group" aria-label={t('settings.theme')} style={{ display: 'flex', gap: 6 }}>
            {(['dark', 'light'] as const).map((mode) => (
              <button
                key={mode}
                className={`n-btn${theme === mode ? ' primary' : ''}`}
                aria-pressed={theme === mode}
                style={{ height: 32, padding: '0 12px', fontSize: 12.5 }}
                onClick={() => applyTheme(mode)}
              >
                {t(`settings.theme_${mode}`, { defaultValue: mode === 'dark' ? 'Dark' : 'Light' })}
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
              <span aria-hidden="true" style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--n-teal-300)' }} />
              {t('settings.connected')}
            </span>
          ) : (
            <span style={{
              display: 'inline-flex', alignItems: 'center', gap: 6,
              padding: '4px 10px', borderRadius: 999,
              border: '1px solid var(--n-line-strong)',
              color: 'var(--n-fg-muted)',
              fontSize: 12, fontWeight: 500,
            }}>
              <span aria-hidden="true" style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--n-fg-dim)' }} />
              {t('settings.disconnected')}
            </span>
          )}
        </SettingsRow>
        <SettingsRow label={t('settings.language')} last>
          <div role="group" aria-label={t('settings.language')} style={{ display: 'flex', gap: 6 }}>
            {(['de', 'en'] as const).map((lng) => (
              <button
                key={lng}
                className={`n-btn${i18n.language?.startsWith(lng) ? ' primary' : ''}`}
                aria-pressed={i18n.language?.startsWith(lng)}
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
        background: 'var(--n-surface-overlay)',
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

function NumInput({ value, unit, width = 72, step = 1, label, onBlur }: {
  value: number; unit: string; width?: number; step?: number; label: string
  onBlur: (v: number) => void
}) {
  return (
    <NumberField value={value} unit={unit} width={width} step={step} aria-label={label} onChange={onBlur} />
  )
}
