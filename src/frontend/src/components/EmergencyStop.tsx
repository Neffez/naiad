import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { IAlert } from './icons'

interface EmergencyStopProps {
  onFire: () => void
  /** Icon-only until armed — fits the narrow mobile header. */
  compact?: boolean
}

export function EmergencyStop({ onFire, compact = false }: EmergencyStopProps) {
  const { t } = useTranslation()
  const [armed, setArmed] = useState(false)

  const handleClick = useCallback(() => {
    if (armed) {
      onFire()
      setArmed(false)
    } else {
      setArmed(true)
    }
  }, [armed, onFire])

  useEffect(() => {
    if (!armed) return
    const timer = setTimeout(() => setArmed(false), 4000)
    return () => clearTimeout(timer)
  }, [armed])

  // Compact shows the label only once armed, so the unarmed control stays a small
  // square icon button in the mobile header.
  const showLabel = !compact || armed

  return (
    <button
      className="n-btn danger"
      onClick={handleClick}
      style={{
        height: 44,
        gap: showLabel ? 8 : 0,
        paddingLeft: showLabel ? 14 : 0,
        paddingRight: showLabel ? 14 : 0,
        width: showLabel ? undefined : 44,
        fontWeight: 600,
      }}
      title={t('emergency.title')}
      aria-label={t('emergency.label')}
    >
      <IAlert size={16} />
      {showLabel && <span>{armed ? t('emergency.confirm') : t('emergency.label')}</span>}
    </button>
  )
}
