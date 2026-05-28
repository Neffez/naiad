import type { ValveState } from '../api/client'

interface ValveGridProps {
  valves: ValveState[]
  cols?: number
  dense?: boolean
}

export function ValveGrid({ valves, cols = 4, dense = false }: ValveGridProps) {
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: `repeat(${cols}, 1fr)`,
        gap: dense ? 8 : 10,
      }}
    >
      {valves.map((v) => {
        const state = v.state === 'on' ? 'on' : 'off'
        return (
          <div
            key={v.id}
            className={`n-valve ${state}`}
            style={{ minHeight: dense ? 74 : 88, padding: dense ? '10px 11px' : '12px 12px 10px' }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
              <span className="led" />
              {state === 'on' && v.runtime_min != null && (
                <span className="mono" style={{ fontSize: 11, color: 'var(--n-teal-200)' }}>
                  {v.runtime_min.toFixed(0)} min
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
                {v.label}
              </span>
              <span className="n-eyebrow" style={{ fontSize: 9 }}>
                {state === 'on' ? 'Live' : 'Aus'}
              </span>
            </div>
          </div>
        )
      })}
    </div>
  )
}
