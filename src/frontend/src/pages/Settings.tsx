import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { type ReactNode, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { getHealth, getSequences, getSettings, getStatus, logout, updateSettings } from '../api/client'
import { seqColor } from '../theme/sequenceColors'

export default function Settings() {
  const { t, i18n } = useTranslation()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { data: settings } = useQuery({ queryKey: ['settings'], queryFn: getSettings })
  const { data: sequences = [] } = useQuery({ queryKey: ['sequences'], queryFn: getSequences })
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

  function saveSeqBasis(seqId: string, val: string) {
    const num = parseFloat(val)
    if (isNaN(num)) return
    mut.mutate({ sequences: { [seqId]: { basis_min_per_zone: num } } })
  }

  function savePaused(seqId: string, paused: boolean) {
    mut.mutate({ sequences: { [seqId]: { paused } } })
  }

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

      {/* Sequenzen */}
      <SettingsSection title={t('settings.sequences', { defaultValue: 'Sequenzen' })}>
        {sequences.map((seq, i) => {
          const ov = settings.sequences[seq.id]
          return (
            <SettingsRow
              key={seq.id}
              label={
                <span style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <span style={{ width: 4, height: 22, borderRadius: 2, background: seqColor(seq.id) }} />
                  <span style={{ fontWeight: 500, color: 'var(--n-fg)' }}>{seq.label}</span>
                </span>
              }
              last={i === sequences.length - 1}
            >
              <NumInput
                value={ov?.basis_min_per_zone ?? seq.basis_min_per_zone}
                unit="min"
                onBlur={(v) => saveSeqBasis(seq.id, String(v))}
              />
              <CheckToggle
                label={t('settings.pause', { defaultValue: 'Pause' })}
                checked={ov?.paused ?? false}
                onChange={(checked) => savePaused(seq.id, checked)}
              />
            </SettingsRow>
          )
        })}
      </SettingsSection>

      {/* Temperatur-Faktor */}
      <SettingsSection title={t('settings.factorTemp')}>
        <SettingsRow label={t('settings.basisC')}>
          <NumInput value={settings.factors.temp.basis_c} unit="°C" onBlur={(v) => mut.mutate({ factors: { temp: { basis_c: v } } })} />
        </SettingsRow>
        <SettingsRow label={t('settings.pctPerC')}>
          <NumInput value={settings.factors.temp.pct_per_c} unit="%" onBlur={(v) => mut.mutate({ factors: { temp: { pct_per_c: v } } })} />
        </SettingsRow>
        <SettingsRow label={t('settings.minPct')}>
          <NumInput value={settings.factors.temp.min_pct} unit="%" onBlur={(v) => mut.mutate({ factors: { temp: { min_pct: v } } })} />
        </SettingsRow>
        <SettingsRow label={t('settings.maxPct')} last>
          <NumInput value={settings.factors.temp.max_pct} unit="%" onBlur={(v) => mut.mutate({ factors: { temp: { max_pct: v } } })} />
        </SettingsRow>
      </SettingsSection>

      {/* Regen-Faktor */}
      <SettingsSection title={t('settings.factorRain')}>
        <SettingsRow label={t('settings.thresholdProb')}>
          <NumInput value={settings.factors.rain.threshold_prob} unit="%" onBlur={(v) => mut.mutate({ factors: { rain: { threshold_prob: v } } })} />
        </SettingsRow>
        <SettingsRow label={t('settings.reduceAbove')}>
          <NumInput value={settings.factors.rain.reduce_above_mm} unit="mm" onBlur={(v) => mut.mutate({ factors: { rain: { reduce_above_mm: v } } })} />
        </SettingsRow>
        <SettingsRow label={t('settings.zeroAbove')}>
          <NumInput value={settings.factors.rain.zero_above_mm} unit="mm" onBlur={(v) => mut.mutate({ factors: { rain: { zero_above_mm: v } } })} />
        </SettingsRow>
        <SettingsRow label={t('settings.forecastDecay')} last>
          <NumInput value={settings.factors.rain.forecast_decay} unit="" width={60} step={0.1} onBlur={(v) => mut.mutate({ factors: { rain: { forecast_decay: v } } })} />
        </SettingsRow>
      </SettingsSection>

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

function SettingsRow({ label, children, last = false }: {
  label: ReactNode; children: ReactNode; last?: boolean
}) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      padding: '12px 20px',
      borderBottom: last ? 'none' : '1px solid var(--n-line)',
      minHeight: 52,
    }}>
      <span style={{ fontSize: 14, color: 'var(--n-fg-soft)' }}>{label}</span>
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

function CheckToggle({ label, checked, onChange }: {
  label: string; checked: boolean; onChange: (checked: boolean) => void
}) {
  return (
    <label style={{
      display: 'flex', alignItems: 'center', gap: 8,
      cursor: 'pointer', fontSize: 13, color: 'var(--n-fg-muted)',
      userSelect: 'none',
    }}>
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        style={{
          width: 16, height: 16,
          accentColor: 'var(--n-teal-400)',
          cursor: 'pointer',
        }}
      />
      {label}
    </label>
  )
}
