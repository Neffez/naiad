// A small segmented toggle: a row of buttons where the active option is
// highlighted. Shared across the settings sections (factor modes, theme,
// language) so the styling and a11y semantics stay in one place.
export function ButtonGroup({ label, options }: {
  label: string
  options: { value: string; active: boolean; label: string; onClick: () => void }[]
}) {
  return (
    <div role="group" aria-label={label} style={{ display: 'flex', gap: 6 }}>
      {options.map((o) => (
        <button
          key={o.value}
          className={`n-btn${o.active ? ' primary' : ''}`}
          aria-pressed={o.active}
          style={{ height: 32, padding: '0 12px', fontSize: 12.5 }}
          onClick={o.onClick}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}
