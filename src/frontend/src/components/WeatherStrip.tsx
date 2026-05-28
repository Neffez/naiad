import type { SystemStatus } from '../api/client'
import { ICloud, IDrop, ISun, IWind } from './icons'

interface WeatherStripProps {
  sys: SystemStatus
  compact?: boolean
}

export function WeatherStrip({ sys, compact = false }: WeatherStripProps) {
  const w = sys.weather
  const items = [
    { icon: <ISun size={14} />, value: w.temp_c != null ? `${w.temp_c.toFixed(1)}°` : '—' },
    { icon: <IDrop size={14} />, value: `${w.rain_24h_mm.toFixed(1)} mm` },
    { icon: <IWind size={14} />, value: w.wind_label === 'on' ? 'aktiv' : 'ruhig' },
    { icon: <ICloud size={14} />, value: w.season_active ? 'aktiv' : 'Pause' },
  ]

  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      gap: compact ? 14 : 18,
      padding: compact ? '0 6px' : '0 4px',
    }}>
      {items.map((it, i) => (
        <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 7, color: 'var(--n-fg-soft)' }}>
          <span style={{ color: 'var(--n-fg-muted)' }}>{it.icon}</span>
          <span className="mono" style={{ fontSize: 13, color: 'var(--n-fg)' }}>{it.value}</span>
        </div>
      ))}
    </div>
  )
}
