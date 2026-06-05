import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { getHealth, getStatus, logout } from '../../../api/client'
import { queryKeys } from '../../../api/queryKeys'
import { ButtonGroup } from '../../../components/config/ButtonGroup'
import { Row, Section } from '../../../components/config/primitives'
import { useConfig } from '../ConfigContext'

export default function SystemSection() {
  const { t, i18n } = useTranslation()
  const { onExport, onImportClick } = useConfig()
  const { data: status } = useQuery({ queryKey: queryKeys.status, queryFn: getStatus })
  const { data: health } = useQuery({ queryKey: queryKeys.health, queryFn: getHealth })
  const [theme, setTheme] = useState<'dark' | 'light'>(
    () => (localStorage.getItem('naiad_theme') === 'light' ? 'light' : 'dark'),
  )

  function applyTheme(next: 'dark' | 'light') {
    setTheme(next)
    localStorage.setItem('naiad_theme', next)
    document.documentElement.setAttribute('data-theme', next)
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
      <Section title={t('settings.system')}>
        <Row label={t('settings.theme')}>
          <ButtonGroup
            label={t('settings.theme')}
            options={(['dark', 'light'] as const).map((mode) => ({
              value: mode,
              active: theme === mode,
              label: t(`settings.theme_${mode}`, { defaultValue: mode === 'dark' ? 'Dark' : 'Light' }),
              onClick: () => applyTheme(mode),
            }))}
          />
        </Row>
        <Row label={t('settings.language')}>
          <ButtonGroup
            label={t('settings.language')}
            options={(['de', 'en'] as const).map((lng) => ({
              value: lng,
              active: i18n.language?.startsWith(lng) ?? false,
              label: lng.toUpperCase(),
              onClick: () => {
                i18n.changeLanguage(lng)
                localStorage.setItem('naiad_lang', lng)
              },
            }))}
          />
        </Row>
        <Row label={t('settings.version')}>
          <span className="mono" style={{ fontSize: 13, color: 'var(--n-fg-muted)' }}>
            v{health?.version ?? '—'}
          </span>
        </Row>
        <Row label={t('settings.haIntegration')} last>
          {status?.ha_connected ? (
            <span style={{
              display: 'inline-flex', alignItems: 'center', gap: 6,
              padding: '4px 10px', borderRadius: 999,
              border: '1px solid rgba(94,200,216,0.30)',
              background: 'var(--n-teal-glow)', color: 'var(--n-teal-200)',
              fontSize: 12, fontWeight: 500,
            }}>
              <span aria-hidden="true" style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--n-teal-300)' }} />
              {t('settings.connected')}
            </span>
          ) : (
            <span style={{
              display: 'inline-flex', alignItems: 'center', gap: 6,
              padding: '4px 10px', borderRadius: 999,
              border: '1px solid var(--n-line-strong)', color: 'var(--n-fg-muted)',
              fontSize: 12, fontWeight: 500,
            }}>
              <span aria-hidden="true" style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--n-fg-dim)' }} />
              {t('settings.disconnected')}
            </span>
          )}
        </Row>
      </Section>

      <Section title={t('settings.configBackup')}>
        <Row label={t('settings.configBackupLabel')} last>
          <div style={{ display: 'flex', gap: 6 }}>
            <button className="n-btn" style={{ height: 32, padding: '0 14px', fontSize: 12.5 }} onClick={onExport}>
              {t('config.export')}
            </button>
            <button className="n-btn" style={{ height: 32, padding: '0 14px', fontSize: 12.5 }} onClick={onImportClick}>
              {t('config.import')}
            </button>
          </div>
        </Row>
      </Section>

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
