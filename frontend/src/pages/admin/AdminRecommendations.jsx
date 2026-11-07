import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import PriorityBadge from '../../components/PriorityBadge.jsx'
import Card from '../../components/ui/Card.jsx'
import usePolling from '../../hooks/usePolling.js'
import { getRecommendations } from '../../services/api.js'
import { apiError } from '../../utils/errors.js'
import { fmtMin, fmtTime } from '../../utils/format.js'

export default function AdminRecommendations() {
  const [recs, setRecs] = useState(null)
  const [error, setError] = useState('')
  const [updated, setUpdated] = useState(null)

  const load = useCallback(async () => {
    try { setRecs((await getRecommendations()).recommendations); setUpdated(new Date().toISOString()); setError('') } catch (e) { setError(apiError(e).message) }
  }, [])
  useEffect(() => { load() }, [load])
  usePolling(load, 15000, true)

  return (
    <>
      <h1>Counter recommendations</h1>
      <p className="qp-muted">
        Advice based on the live queue, estimated waits, recent arrivals, service times and staff availability, using the thresholds in{' '}
        <Link to="/admin/settings">Settings</Link>. It is advisory: nothing is opened automatically, and no reduction in waiting time is promised.
        {updated ? ` Updated ${fmtTime(updated)}.` : ''}
      </p>
      {error && <div className="qp-alert" role="alert">{error}</div>}
      {!recs ? (!error && <p className="qp-muted">Loading…</p>) : recs.length === 0 ? (
        <Card title="No active services"><p className="qp-muted">Create a service first; recommendations appear for each active service.</p></Card>
      ) : recs.map((r) => (
        <Card key={r.service.id} title={r.service.name} action={<PriorityBadge priority={r.priority} />}>
          <p className="qp-headline">{r.headline}</p>
          <h3 className="qp-subhead">Why</h3>
          <ul className="qp-reasons">{r.reasons.map((x, i) => <li key={i}>{x}</li>)}</ul>
          {r.action !== 'NONE' && (
            <p>
              {r.candidate_counters.length > 0
                ? <>Counters you could open: <strong>{r.candidate_counters.map((c) => c.name).join(', ')}</strong>. Staff open counters themselves; you can see assignments under <Link to="/admin/counters">Counters</Link>.</>
                : <>No staffed closed counter exists for this service. Assign staff under <Link to="/admin/counters">Counters</Link>.</>}
            </p>
          )}
          <details className="qp-data">
            <summary>Data behind this advice</summary>
            <ul className="qp-facts">
              <li>Waiting: <strong>{r.data.waiting}</strong> ({r.data.congestion} congestion)</li>
              <li>Estimated wait for a new customer: <strong>{r.data.estimated_wait == null ? 'not available (no open counter)' : fmtMin(r.data.estimated_wait)}</strong>{r.data.estimated_wait != null ? ` (${r.data.estimate_source.replace('_', ' ')})` : ''}</li>
              <li>Arrivals: <strong>{r.data.arrival_rate_per_hour}</strong> per hour over the last {r.data.arrival_window_minutes} minutes</li>
              <li>Recent average service time: <strong>{fmtMin(r.data.avg_service_minutes)}</strong></li>
              <li>Counters: <strong>{r.data.counters.open}</strong> open, {r.data.counters.busy} busy, {r.data.counters.available} available; {r.data.staff_on_open_counters} staff on open counters</li>
              {r.data.offered_load != null && <li>Offered load per open counter: <strong>{r.data.offered_load}</strong> (1 or more means arrivals outpace service)</li>}
            </ul>
          </details>
        </Card>
      ))}
    </>
  )
}
