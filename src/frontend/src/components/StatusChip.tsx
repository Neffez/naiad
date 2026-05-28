import { useTranslation } from 'react-i18next'

interface StatusChipProps {
  status: string
}

export function StatusChip({ status }: StatusChipProps) {
  const { t } = useTranslation()
  const label = t(`status.${status}` as never) || status
  return (
    <span className={`n-chip ${status}`}>
      <span className="n-chip-dot" />
      {label}
    </span>
  )
}
