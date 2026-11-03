import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import Button from '../../components/ui/Button.jsx'
import Card from '../../components/ui/Card.jsx'
import { getHistory } from '../../services/api.js'
import { apiError } from '../../utils/errors.js'
import { STATUS_LABEL, fmtDateTime, fmtMin } from '../../utils/format.js'

const STATUSES = Object.keys(STATUS_LABEL)

export default function History() {
  const [query, setQuery] = useState({ status: '', page: 1 })
  const [data, setData] = useState(null)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    try {
      const params = { page: query.page, per_page: 10 }
      if (query.status) params.status = query.status
      setData(await getHistory(params))
      setError('')
    } catch (e) {
      setError(apiError(e).message)
    }
  }, [query])

  useEffect(() => { load() }, [load])

  return (
    <>
      <h1>Queue history</h1>
      <Card
        title={`Tickets${data ? ` (${data.total})` : ''}`}
        action={
          <select aria-label="Filter by status" value={query.status} onChange={(e) => setQuery({ status: e.target.value, page: 1 })}>
            <option value="">All statuses</option>
            {STATUSES.map((s) => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}
          </select>
        }
      >
        {error && <div className="qp-alert" role="alert">{error}</div>}
        {!data ? <p className="qp-muted">Loading…</p> : data.tickets.length === 0 ? (
          <p className="qp-muted">{query.status ? 'No tickets with this status.' : 'You have not joined any queue yet.'}</p>
        ) : (
          <div className="qp-table-wrap">
            <table className="qp-table">
              <thead><tr><th>Ticket</th><th>Service</th><th>Status</th><th>Joined</th><th>Predicted wait</th><th>Actual wait</th><th>Service time</th></tr></thead>
              <tbody>
                {data.tickets.map((t) => (
                  <tr key={t.id}>
                    <td><Link to={`/customer/tickets/${t.id}`}>{t.queue_number}</Link></td>
                    <td>{t.service.name}</td>
                    <td><span className={`qp-badge qp-status qp-status--${t.status.toLowerCase()}`}>{STATUS_LABEL[t.status]}</span></td>
                    <td>{fmtDateTime(t.join_time)}</td>
                    <td>{fmtMin(t.predicted_waiting_time)}</td>
                    <td>{fmtMin(t.actual_waiting_time)}</td>
                    <td>{fmtMin(t.service_duration)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="qp-pager">
          <Button variant="ghost" disabled={query.page <= 1} onClick={() => setQuery({ ...query, page: query.page - 1 })}>Previous</Button>
          <span>Page {query.page} of {data?.pages || 1}</span>
          <Button variant="ghost" disabled={query.page >= (data?.pages || 1)} onClick={() => setQuery({ ...query, page: query.page + 1 })}>Next</Button>
        </div>
      </Card>
    </>
  )
}
