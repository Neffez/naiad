import { useTranslation } from 'react-i18next'
import type { ValveState } from '../api/client'
import { IPlay, IStop } from './icons'
import { SortableGrid } from './SortableGrid'

interface ValveGridProps {
  valves: ValveState[]
  cols?: number
  dense?: boolean
  /** When provided, valve cards become drag-and-drop sortable; called with the new ID order. */
  onReorder?: (ids: string[]) => void
  /** Start this zone as a standalone single-zone run (opens a duration dialog). */
  onStartZone?: (zoneId: string) => void
  /** Stop a standalone single-zone run. */
  onStopZone?: (zoneId: string) => void
}

function ValveCell({
  valve,
  dense,
  onStartZone,
  onStopZone,
}: {
  valve: ValveState
  dense: boolean
  onStartZone?: (zoneId: string) => void
  onStopZone?: (zoneId: string) => void
}) {
  const { t } = useTranslation()
  const state = valve.state === 'on' ? 'on' : 'off'

  // A small action button (start / stop) sits in the top-right of the cell. It
  // stops pointer/click propagation so it never triggers a drag or reorder.
  const stop = (e: React.SyntheticEvent) => e.stopPropagation()
  const canStart = onStartZone && state === 'off'
  const canStop = onStopZone && valve.single_run

  return (
    <div
      className={`n-valve ${state}`}
      style={{ minHeight: dense ? 74 : 88, padding: dense ? '10px 11px' : '12px 12px 10px' }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <span className="led" />
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {state === 'on' && valve.runtime_min != null && (
            <span className="mono" style={{ fontSize: 11, color: 'var(--n-teal-200)' }}>
              {valve.total_min != null
                ? `${valve.runtime_min.toFixed(0)} / ${valve.total_min.toFixed(0)} min`
                : `${valve.runtime_min.toFixed(0)} min`}
            </span>
          )}
          {canStop ? (
            <button
              className="n-iconbtn"
              style={{ width: 26, height: 26 }}
              title={t('valve.stop')}
              aria-label={t('valve.stop')}
              onPointerDown={stop}
              onClick={(e) => { stop(e); onStopZone(valve.zone_id) }}
            >
              <IStop size={12} />
            </button>
          ) : canStart ? (
            <button
              className="n-iconbtn"
              style={{ width: 26, height: 26 }}
              title={t('valve.start')}
              aria-label={t('valve.start')}
              onPointerDown={stop}
              onClick={(e) => { stop(e); onStartZone(valve.zone_id) }}
            >
              <IPlay size={12} />
            </button>
          ) : null}
        </div>
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

export function ValveGrid({
  valves,
  cols = 4,
  dense = false,
  onReorder,
  onStartZone,
  onStopZone,
}: ValveGridProps) {
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
        renderItem={(v) => (
          <ValveCell valve={v} dense={dense} onStartZone={onStartZone} onStopZone={onStopZone} />
        )}
        style={gridStyle}
      />
    )
  }

  return (
    <div style={gridStyle}>
      {valves.map((v) => (
        <ValveCell
          key={v.id}
          valve={v}
          dense={dense}
          onStartZone={onStartZone}
          onStopZone={onStopZone}
        />
      ))}
    </div>
  )
}
