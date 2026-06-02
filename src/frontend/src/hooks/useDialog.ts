import { useEffect, useRef } from 'react'

const FOCUSABLE = 'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'

/**
 * Accessibility plumbing for modal dialogs. While the dialog is open it:
 *  - moves focus into the dialog (first focusable element, or the container),
 *  - traps Tab focus inside the dialog,
 *  - closes the dialog on Escape,
 *  - restores focus to the previously focused element on close.
 *
 * Returns a ref to attach to the dialog container; that element should carry
 * `role="dialog"`, `aria-modal="true"` and `tabIndex={-1}`.
 */
export function useDialog<T extends HTMLElement = HTMLDivElement>(
  open: boolean,
  onClose: () => void,
) {
  const ref = useRef<T>(null)

  useEffect(() => {
    if (!open) return
    const node = ref.current
    const previouslyFocused = document.activeElement as HTMLElement | null

    const focusables = (): HTMLElement[] =>
      node
        ? Array.from(node.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
            (el) => !el.hasAttribute('disabled') && el.getAttribute('aria-hidden') !== 'true',
          )
        : []

    // Move focus inside the dialog so screen readers and keyboard users land there.
    const initial = focusables()[0] ?? node
    initial?.focus()

    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        e.preventDefault()
        onClose()
        return
      }
      if (e.key !== 'Tab') return
      const items = focusables()
      if (items.length === 0) {
        e.preventDefault()
        return
      }
      const first = items[0]
      const last = items[items.length - 1]
      const activeEl = document.activeElement
      if (e.shiftKey && (activeEl === first || activeEl === node)) {
        e.preventDefault()
        last.focus()
      } else if (!e.shiftKey && activeEl === last) {
        e.preventDefault()
        first.focus()
      }
    }

    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      // Restore focus to whatever was focused before the dialog opened.
      previouslyFocused?.focus?.()
    }
  }, [open, onClose])

  return ref
}
