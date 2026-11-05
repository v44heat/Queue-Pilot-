import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import CongestionBadge from '../../components/CongestionBadge.jsx'
import StatCard from '../../components/StatCard.jsx'
import Card from '../../components/ui/Card.jsx'
import usePolling from '../../hooks/usePolling.js'
import { getAdminDashboard } from '../../services/api.js'
import { apiError } from '../../utils/errors.js'
import { fmtMin } from '../../utils/format.js'

export default function AdminDashboard() {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    try { setData(await getAdminDashboard()); setError('') } catch (e) { setError(apiError(e).message) }
  }, [])
  useEffect(() => { load() }, [load])
  usePolling(load, 5000, true)

  if (!data) return error ? <div className="qp-alert" role="alert">{error}</div> : <p className="qp-muted">Loading…</p>
  const s = data.summary
  const t = s.congestion.thresholds

  return (
    <>
      <h1>Admin dashboard</h1>
      <p className="qp-muted">Live figures from the database, refreshed every few seconds. &ldquo;Today&rdquo; is the local calendar day.</p>
      {error && <div className="qp-alert" role="alert">{error}</div>}

      <div className="qp-stats-grid">
        <StatCard label="Customers served today" value={s.served_today} />
        <StatCard label="Customers waiting" value={s.waiting} />
        <StatCard label="Being served" value={s.being_served} hint={s.called ? `${s.called} called, on the way` : undefined} />
        <StatCard label="Average waiting time" value={fmtMin(s.avg_waiting_time)} hint="Customers whose service started today" />
        <StatCard label="Average service duration" value={fmtMin(s.avg_service_duration)} hint="Services completed today" />
        <StatCard label="Active counters" value={`${s.active_counters} / ${s.total_counters}`} hint={`${s.busy_counters} busy`} />
        <div className="qp-stat">
          <span className="qp-stat__label">Congestion level</span>
          <strong className="qp-stat__value"><CongestionBadge level={s.congestion.level} /></strong>
          <small className="qp-muted">Worst service. Moderate from {t.moderate}, high from {t.high}, critical from {t.critical} waiting.</small>
        </div>
      </div>

      <Card title="Services" action={<Link to="/admin/queue">Open live queue</Link>}>
        {data.services.length === 0 ? <p className="qp-muted">No active services.</p> : (
          <div className="qp-table-wrap">
            <table className="qp-table">
              <thead><tr><th>Service</th><th>Waiting</th><th>Called</th><th>Serving</th><th>Counters open / busy</th><th>Congestion</th></tr></thead>
              <tbody>
                {data.services.map((r) => (
                  <tr key={r.id}>
                    <td>{r.name}</td><td>{r.waiting}</td><td>{r.called}</td><td>{r.serving}</td>
                    <td>{r.counters.open} / {r.counters.busy}</td><td><CongestionBadge level={r.congestion} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card title="Counters" action={<Link to="/admin/counters">Manage counters</Link>}>
        {data.counters.length === 0 ? <p className="qp-muted">No counters yet.</p> : (
          <div className="qp-table-wrap">
            <table className="qp-table">
              <thead><tr><th>Counter</th><th>Service</th><th>Status</th><th>Availability</th><th>Current customer</th><th>Staff</th></tr></thead>
              <tbody>
                {data.counters.map((c) => (
                  <tr key={c.id}>
                    <td>{c.name}</td><td>{c.service?.name ?? '-'}</td><td>{c.status}</td><td>{c.availability}</td>
                    <td>{c.current_ticket ? `${c.current_ticket.queue_number} (${c.current_ticket.customer?.name})` : '-'}</td>
                    <td>{c.staff.length ? c.staff.map((x) => x.name).join(', ') : '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  )
}
