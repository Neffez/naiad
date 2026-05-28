import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { IAlert } from './icons'

interface EmergencyStopProps {
  onFire: () => void
}

export function EmergencyStop({ onFire }: EmergencyStopProps) {
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

  return (
    <button
      className="n-btn danger"
      onClick={handleClick}
      style={{ height: 44, gap: 8, paddingLeft: 14, paddingRight: 14, fontWeight: 600 }}
      title={t('emergency.title')}
    >
      <IAlert size={16} />
      <span>{armed ? t('emergency.confirm') : t('emergency.label')}</span>
    </button>
  )
}
