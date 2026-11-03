import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import Card from '../../components/ui/Card.jsx'
import TicketCard from '../../components/TicketCard.jsx'
import { useAuth } from '../../context/AuthContext.jsx'
import usePolling from '../../hooks/usePolling.js'
import { getHistory, getMyActive } from '../../services/api.js'
import { apiError } from '../../utils/errors.js'
import { STATUS_LABEL, fmtDateTime } from '../../utils/format.js'

export default function CustomerDashboard() {
  const { user } = useAuth()
  const [active, setActive] = useState(null)
  const [recent, setRecent] = useState([])
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    try {
      const [a, h] = await Promise.all([getMyActive(), getHistory({ per_page: 3 })])
      setActive(a.tickets)
      setRecent(h.tickets)
      setError('')
    } catch (e) {
      setError(apiError(e).message)
    }
  }, [])

  useEffect(() => { load() }, [load])
  usePolling(load, 10000, true)

  return (
    <>
      <h1>Hello, {user.name.split(' ')[0]}</h1>
      <p className="qp-muted">Your queue tickets update automatically.</p>
      {error && <div className="qp-alert" role="alert">{error}</div>}

      {active === null ? <p className="qp-muted">Loading…</p> : active.length === 0 ? (
        <Card title="No active ticket">
          <p>You are not in any queue right now.</p>
          <Link className="qp-btn qp-btn--primary qp-linkbtn" to="/customer/services">Join a queue</Link>
        </Card>
      ) : (
        <div className="qp-ticket-list">
          {active.map((t) => <TicketCard key={t.id} ticket={t} to={`/customer/tickets/${t.id}`} />)}
        </div>
      )}

      <Card title="Recent tickets" action={<Link to="/customer/history">View all</Link>}>
        {recent.length === 0 ? <p className="qp-muted">No tickets yet.</p> : (
          <ul className="qp-simple-list">
            {recent.map((t) => (
              <li key={t.id}>
                <Link to={`/customer/tickets/${t.id}`}>{t.queue_number}</Link>
                <span>{t.service.name}</span>
                <span className={`qp-badge qp-status qp-status--${t.status.toLowerCase()}`}>{STATUS_LABEL[t.status]}</span>
                <small className="qp-muted">{fmtDateTime(t.join_time)}</small>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </>
  )
}
