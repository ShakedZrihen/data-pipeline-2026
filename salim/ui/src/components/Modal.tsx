import { useEffect, useRef, type ReactNode } from 'react'

interface ModalProps {
  label: string
  onClose: () => void
  children: ReactNode
}

/**
 * Native `<dialog>`, so Escape, focus trapping and the backdrop come from the
 * browser rather than from hand-written key handlers.
 */
export function Modal({ label, onClose, children }: ModalProps) {
  const ref = useRef<HTMLDialogElement>(null)

  useEffect(() => {
    const dialog = ref.current
    if (!dialog || dialog.open) return
    dialog.showModal()
    return () => dialog.close()
  }, [])

  return (
    <dialog
      className="modal"
      aria-label={label}
      ref={ref}
      onClose={onClose}
      // A click landing on the dialog itself is a click on the backdrop; the
      // panel inside stops its own clicks from reaching here.
      onClick={(event) => {
        if (event.target === ref.current) onClose()
      }}
    >
      <div className="modal__panel" onClick={(event) => event.stopPropagation()}>
        <button type="button" className="modal__close" onClick={onClose} aria-label="סגור">
          ×
        </button>
        {children}
      </div>
    </dialog>
  )
}
