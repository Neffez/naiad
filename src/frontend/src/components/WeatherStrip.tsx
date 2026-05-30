import { useTranslation } from 'react-i18next'
import type { SystemStatus } from '../api/client'
import { ICloud, IDrop, ISun, IWind } from './icons'

interface WeatherStripProps {
  sys: SystemStatus
  compact?: boolean
}

export function WeatherStrip({ sys, compact = false }: WeatherStripProps) {
  const { t } = useTranslation()
  const w = sys.weather
  const items = [
    { icon: <ISun size={14} />, label: t('weather.temp'), value: w.temp_c != null ? `${w.temp_c.toFixed(1)}°` : '—', title: t('weather.temp') },
    { icon: <IDrop size={14} />, label: t('weather.rain'), value: `${w.rain_24h_mm.toFixed(1)} mm`, title: t('weather.rain') },
    { icon: <IWind size={14} />, label: t('weather.wind'), value: w.wind_label === 'on' ? t('weather.windActive') : t('weather.windCalm'), title: t('weather.wind') },
    { icon: <ICloud size={14} />, label: t('weather.season'), value: w.season_active ? t('weather.seasonActive') : t('weather.seasonPaused'), title: t('weather.seasonHint') },
  ]

  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      gap: compact ? 14 : 18,
      padding: compact ? '0 6px' : '0 4px',
      flexWrap: 'wrap',
    }}>
      {items.map((it, i) => (
        <div key={i} title={it.title} style={{ display: 'flex', alignItems: 'center', gap: 7, color: 'var(--n-fg-soft)' }}>
          <span style={{ color: 'var(--n-fg-muted)' }}>{it.icon}</span>
          <span className="n-eyebrow" style={{ fontSize: 10 }}>{it.label}</span>
          <span className="mono" style={{ fontSize: 13, color: 'var(--n-fg)' }}>{it.value}</span>
        </div>
      ))}
    </div>
  )
}
