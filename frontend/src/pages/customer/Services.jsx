import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import Button from '../../components/ui/Button.jsx'
import Card from '../../components/ui/Card.jsx'
import { useNotifications } from '../../context/NotificationContext.jsx'
import { useToast } from '../../context/ToastContext.jsx'
import usePolling from '../../hooks/usePolling.js'
import { getMyActive, getServices, joinQueue } from '../../services/api.js'
import { apiError } from '../../utils/errors.js'

export default function Services() {
  const navigate = useNavigate()
  const toast = useToast()
  const { refresh: refreshNotifications } = useNotifications()
  const [services, setServices] = useState(null)
  const [active, setActive] = useState([])
  const [busyId, setBusyId] = useState(null)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    try {
      const [s, a] = await Promise.all([getServices(), getMyActive()])
      setServices(s.services)
      setActive(a.tickets)
      setError('')
    } catch (e) {
      setError(apiError(e).message)
    }
  }, [])

  useEffect(() => { load() }, [load])
  usePolling(load, 15000, true)

  const join = async (service) => {
    setBusyId(service.id)
    try {
      const { ticket } = await joinQueue(service.id)
      toast.success(`You joined the queue: ${ticket.queue_number}`)
      refreshNotifications()
      navigate(`/customer/tickets/${ticket.id}`)
    } catch (e) {
      const { message } = apiError(e)
      toast.error(message)
      setError(message)
      load()
    } finally {
      setBusyId(null)
    }
  }

  return (
    <>
      <h1>Available services</h1>
      <p className="qp-muted">Choose a service to join its queue.</p>
      {error && <div className="qp-alert" role="alert">{error}</div>}
      {services === null ? <p className="qp-muted">Loading…</p> : services.length === 0 ? (
        <Card title="No services available"><p>There are no services open for queueing right now.</p></Card>
      ) : (
        <div className="qp-service-grid">
          {services.map((s) => {
            const mine = active.find((t) => t.service.id === s.id)
            const open = s.counters?.open ?? 0
            return (
              <Card key={s.id} title={s.name} className="qp-service">
                {s.description && <p className="qp-muted">{s.description}</p>}
                <ul className="qp-facts">
                  <li><strong>{s.waiting_count}</strong> waiting</li>
                  <li>{open > 0 ? <><strong>{open}</strong> counter{open > 1 ? 's' : ''} open</> : 'No counter open yet'}</li>
                </ul>
                {mine ? (
                  <Link className="qp-btn qp-btn--ghost qp-linkbtn" to={`/customer/tickets/${mine.id}`}>
                    You are in this queue ({mine.queue_number})
                  </Link>
                ) : (
                  <Button disabled={busyId !== null} onClick={() => join(s)} aria-label={`Join queue for ${s.name}`}>
                    {busyId === s.id ? 'Joining…' : 'Join Queue'}
                  </Button>
                )}
              </Card>
            )
          })}
        </div>
      )}
    </>
  )
}
