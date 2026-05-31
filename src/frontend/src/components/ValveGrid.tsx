import { useTranslation } from 'react-i18next'
import type { ValveState } from '../api/client'
import { SortableGrid } from './SortableGrid'

interface ValveGridProps {
  valves: ValveState[]
  cols?: number
  dense?: boolean
  /** When provided, valve cards become drag-and-drop sortable; called with the new ID order. */
  onReorder?: (ids: string[]) => void
}

function ValveCell({ valve, dense }: { valve: ValveState; dense: boolean }) {
  const { t } = useTranslation()
  const state = valve.state === 'on' ? 'on' : 'off'
  return (
    <div
      className={`n-valve ${state}`}
      style={{ minHeight: dense ? 74 : 88, padding: dense ? '10px 11px' : '12px 12px 10px' }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <span className="led" />
        {state === 'on' && valve.runtime_min != null && (
          <span className="mono" style={{ fontSize: 11, color: 'var(--n-teal-200)' }}>
            {valve.runtime_min.toFixed(0)} min
          </span>
        )}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        <span
          style={{
            fontSize: 12,
            fontWeight: 500,
            lineHeight: 1.2,
            color: state === 'on' ? 'var(--n-teal-200)' : 'var(--n-fg-soft)',
          }}
        >
          {valve.label}
        </span>
        <span className="n-eyebrow" style={{ fontSize: 9 }}>
          {state === 'on' ? t('valve.live') : t('valve.off')}
        </span>
      </div>
    </div>
  )
}

export function ValveGrid({ valves, cols = 4, dense = false, onReorder }: ValveGridProps) {
  const gridStyle = {
    display: 'grid',
    gridTemplateColumns: `repeat(${cols}, 1fr)`,
    gap: dense ? 8 : 10,
  } as const

  if (onReorder) {
    return (
      <SortableGrid
        items={valves}
        onReorder={onReorder}
        renderItem={(v) => <ValveCell valve={v} dense={dense} />}
        style={gridStyle}
      />
    )
  }

  return (
    <div style={gridStyle}>
      {valves.map((v) => (
        <ValveCell key={v.id} valve={v} dense={dense} />
      ))}
    </div>
  )
}
