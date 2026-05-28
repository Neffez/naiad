interface StatBlockProps {
  label: string
  value: string | number
  unit?: string
  tone?: string
}

export function StatBlock({ label, value, unit, tone }: StatBlockProps) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      <span className="n-eyebrow">{label}</span>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 3 }}>
        <span className="n-bignum" style={{ fontSize: 24, color: tone || 'var(--n-fg)' }}>
          {value}
        </span>
        {unit && <span style={{ fontSize: 12, color: 'var(--n-fg-muted)' }}>{unit}</span>}
      </div>
    </div>
  )
}
