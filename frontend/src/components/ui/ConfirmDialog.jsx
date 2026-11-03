import { useEffect, useRef } from 'react'
import Button from './Button.jsx'

export default function ConfirmDialog({ open, title, message, confirmLabel = 'Confirm', cancelLabel = 'Keep', busy = false, onConfirm, onCancel }) {
  const cancelRef = useRef(null)
  useEffect(() => {
    if (!open) return undefined
    cancelRef.current?.focus()
    const onKey = (e) => { if (e.key === 'Escape') onCancel() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onCancel])
  if (!open) return null
  return (
    <div className="qp-overlay" onClick={onCancel}>
      <div className="qp-dialog" role="dialog" aria-modal="true" aria-labelledby="qp-dialog-title" onClick={(e) => e.stopPropagation()}>
        <h2 id="qp-dialog-title">{title}</h2>
        <p>{message}</p>
        <div className="qp-actions">
          <button ref={cancelRef} className="qp-btn qp-btn--ghost" onClick={onCancel} disabled={busy}>{cancelLabel}</button>
          <Button onClick={onConfirm} disabled={busy}>{busy ? 'Working…' : confirmLabel}</Button>
        </div>
      </div>
    </div>
  )
}
