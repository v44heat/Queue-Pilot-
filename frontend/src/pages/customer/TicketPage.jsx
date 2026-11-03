import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import Button from '../../components/ui/Button.jsx'
import ConfirmDialog from '../../components/ui/ConfirmDialog.jsx'
import TicketCard from '../../components/TicketCard.jsx'
import { useNotifications } from '../../context/NotificationContext.jsx'
import { useToast } from '../../context/ToastContext.jsx'
import usePolling from '../../hooks/usePolling.js'
import { cancelTicket, getTicket } from '../../services/api.js'
import { apiError } from '../../utils/errors.js'
import { ACTIVE, fmtTime } from '../../utils/format.js'

const BANNERS = {
  CANCELLED: 'This ticket was cancelled.',
  SKIPPED: 'This ticket was skipped by staff. Join the queue again if you still need service.',
  ABSENT: 'You were not at the counter when called. Join the queue again if you still need service.',
  COMPLETED: 'Service completed. Thank you!',
}

export default function TicketPage() {
  const { id } = useParams()
  const toast = useToast()
  const { refresh: refreshNotifications } = useNotifications()
  const [ticket, setTicket] = useState(null)
  const [notFound, setNotFound] = useState(false)
  const [error, setError] = useState('')
  const [updatedAt, setUpdatedAt] = useState(null)
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    try {
      const d = await getTicket(id)
      setTicket(d.ticket)
      setUpdatedAt(new Date().toISOString())
      setError('')
    } catch (e) {
      const err = apiError(e)
      if (err.status === 404) setNotFound(true)
      else setError(err.message)
    }
  }, [id])

  useEffect(() => { load() }, [load])
  const live = Boolean(ticket) && ACTIVE.includes(ticket.status)
  usePolling(load, 10000, live) // stops by itself once the ticket is finished

  const doCancel = async () => {
    setBusy(true)
    try {
      await cancelTicket(id)
      toast.success('Ticket cancelled.')
      setConfirming(false)
      await load()
      refreshNotifications()
    } catch (e) {
      toast.error(apiError(e).message)
      setConfirming(false)
      await load()
    } finally {
      setBusy(false)
    }
  }

  if (notFound) {
    return (<><h1>Ticket not found</h1><p className="qp-muted">This ticket does not exist or is not yours.</p><Link to="/customer">Back to dashboard</Link></>)
  }
  if (!ticket) return error ? <div className="qp-alert" role="alert">{error}</div> : <p className="qp-muted">Loading…</p>

  return (
    <div className="qp-ticket-page">
      <h1>Your ticket</h1>
      {error && <div className="qp-alert" role="alert">{error}</div>}
      <TicketCard ticket={ticket} />
      {BANNERS[ticket.status] && <div className={`qp-note qp-note--${ticket.status.toLowerCase()}`}>{BANNERS[ticket.status]}</div>}
      <div className="qp-actions">
        {ticket.status === 'WAITING' && <Button variant="ghost" onClick={() => setConfirming(true)}>Cancel ticket</Button>}
        {!live && <Link className="qp-btn qp-btn--primary qp-linkbtn" to="/customer/services">Join a queue</Link>}
        <Link className="qp-btn qp-btn--ghost qp-linkbtn" to="/customer">Dashboard</Link>
      </div>
      {live && <p className="qp-muted qp-small">Updates automatically{updatedAt ? ` · last updated ${fmtTime(updatedAt)}` : ''}</p>}
      <ConfirmDialog
        open={confirming} busy={busy} title="Cancel this ticket?"
        message={`You will lose your place in the queue (${ticket.queue_number}). You can join again later but will get a new number.`}
        confirmLabel="Cancel ticket" cancelLabel="Keep my place" onConfirm={doCancel} onCancel={() => setConfirming(false)}
      />
    </div>
  )
}
