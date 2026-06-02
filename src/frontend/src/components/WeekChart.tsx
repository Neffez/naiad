interface DayData {
  day: string
  liters: number
  today?: boolean
}

interface WeekChartProps {
  data: DayData[]
  height?: number
  /** Accessible name prefix for the chart, e.g. the surrounding card's heading. */
  label?: string
}

export function WeekChart({ data, height = 130, label }: WeekChartProps) {
  const maxTotal = Math.max(...data.map((d) => d.liters), 1)
  const niceMax = Math.ceil(maxTotal / 100) * 100 || 100

  // Text alternative for screen readers: the chart is otherwise purely visual.
  const summary = data.map((d) => `${d.day}: ${d.liters} L`).join(', ')
  const ariaLabel = label ? `${label} — ${summary}` : summary

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div role="img" aria-label={ariaLabel} style={{ display: 'flex', alignItems: 'flex-end', gap: 8, height, paddingTop: 6 }}>
        {data.map((d, i) => {
          const barH = (d.liters / niceMax) * (height - 18)
          return (
            <div
              key={i}
              style={{
                flex: 1,
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                gap: 6,
                height: '100%',
              }}
            >
              <div
                style={{
                  height: '100%',
                  display: 'flex',
                  flexDirection: 'column',
                  justifyContent: 'flex-end',
                  width: '100%',
                  minHeight: 4,
                }}
              >
                <div
                  style={{
                    height: Math.max(barH, 3),
                    borderRadius: 4,
                    overflow: 'hidden',
                    border: d.today ? '1px solid rgba(94,200,216,0.55)' : '1px solid var(--n-line)',
                    background: d.today
                      ? 'linear-gradient(180deg, var(--n-teal-500), var(--n-teal-700))'
                      : 'rgba(255,255,255,0.04)',
                    opacity: d.today ? 0.95 : 0.7,
                  }}
                />
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 1, height: 28 }}>
                <span
                  className="n-eyebrow"
                  style={{ fontSize: 9.5, color: d.today ? 'var(--n-teal-300)' : 'var(--n-fg-muted)' }}
                >
                  {d.day}
                </span>
                <span className="mono" style={{ fontSize: 10.5, color: d.today ? 'var(--n-fg)' : 'var(--n-fg-muted)' }}>
                  {d.liters} L
                </span>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
