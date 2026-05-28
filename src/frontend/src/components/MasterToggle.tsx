import { useTranslation } from 'react-i18next'

interface MasterToggleProps {
  on: boolean
  onToggle: () => void
  compact?: boolean
}

export function MasterToggle({ on, onToggle, compact = false }: MasterToggleProps) {
  const { t } = useTranslation()
  return (
    <button
      className={`n-master${on ? '' : ' off'}`}
      onClick={onToggle}
      style={{ height: compact ? 40 : 44 }}
    >
      <span className="knob" style={compact ? { width: 28, height: 28 } : undefined} />
      <span style={{ display: 'flex', flexDirection: 'column', lineHeight: 1.1, alignItems: 'flex-start' }}>
        <span className="n-eyebrow" style={{ fontSize: 9.5 }}>{t('master.system')}</span>
        <span style={{ fontSize: 13, fontWeight: 500, color: on ? 'var(--n-fg)' : 'var(--n-fg-muted)' }}>
          {on ? t('master.on') : t('master.off')}
        </span>
      </span>
    </button>
  )
}
