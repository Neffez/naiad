import { useCallback, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { IAlert, IX } from './icons'

interface ConfirmActionDialogProps {
  open: boolean
  title: string
  message?: string
  confirmLabel: string
  cancelLabel?: string
  tone?: 'danger' | 'default'
  onConfirm: () => void
  onCancel: () => void
}

/** Lightweight yes/no confirmation, used to guard destructive/irreversible
 * actions (stopping a running sequence, skipping a scheduled run). */
export function ConfirmActionDialog({
  open,
  title,
  message,
  confirmLabel,
  cancelLabel,
  tone = 'default',
  onConfirm,
  onCancel,
}: ConfirmActionDialogProps) {
  const { t } = useTranslation()
  const backdropRef = useRef<HTMLDivElement>(null)

  const handleBackdropClick = useCallback(
    (e: React.MouseEvent) => {
      if (e.target === backdropRef.current) onCancel()
    },
    [onCancel],
  )

  if (!open) return null

  const accent = tone === 'danger' ? 'var(--n-danger)' : 'var(--n-teal-400)'

  return (
    <div className="n-backdrop" ref={backdropRef} onClick={handleBackdropClick}>
      <div
        className="n-dialog"
        style={{
          position: 'absolute',
          left: '50%',
          top: '50%',
          transform: 'translate(-50%, -50%)',
          width: 'min(420px, calc(100% - 32px))',
          padding: 24,
          display: 'flex',
          flexDirection: 'column',
          gap: 18,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 14 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, minWidth: 0 }}>
            <span
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
                width: 34,
                height: 34,
                borderRadius: '50%',
                flex: '0 0 auto',
                color: accent,
                background: tone === 'danger' ? 'var(--n-danger-soft)' : 'var(--n-teal-glow)',
              }}
            >
              <IAlert size={18} />
            </span>
            <span style={{ fontSize: 20, fontWeight: 600, letterSpacing: '-0.015em' }}>{title}</span>
          </div>
          <button className="n-iconbtn" style={{ width: 36, height: 36, flex: '0 0 36px' }} onClick={onCancel}>
            <IX size={15} />
          </button>
        </div>

        {message && (
          <p style={{ margin: 0, fontSize: 14, lineHeight: 1.5, color: 'var(--n-fg-soft)' }}>{message}</p>
        )}

        <div style={{ display: 'flex', gap: 10, marginTop: 4 }}>
          <button className="n-btn ghost lg" style={{ flex: 1 }} onClick={onCancel}>
            {cancelLabel ?? t('confirm.cancel')}
          </button>
          <button
            className={`n-btn lg${tone === 'danger' ? ' danger' : ' primary'}`}
            style={{ flex: 1.2 }}
            onClick={onConfirm}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
