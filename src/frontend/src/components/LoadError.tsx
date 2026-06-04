import { useTranslation } from 'react-i18next'

/**
 * Inline error indicator shown when a data query fails. Uses ``role="alert"`` so
 * screen readers announce it, and the danger token so it reads as an error in
 * both themes. ``compact`` trims the padding for dense layouts.
 */
export function LoadError({ compact = false }: { compact?: boolean }) {
  const { t } = useTranslation()
  return (
    <div
      role="alert"
      style={{
        padding: compact ? '10px 14px' : '14px 16px',
        borderRadius: 'var(--n-r-md)',
        background: 'var(--n-danger-soft)',
        border: '1px solid var(--n-danger)',
        color: 'var(--n-danger)',
        fontSize: 13,
      }}
    >
      {t('common.loadError')}
    </div>
  )
}
