import { useCallback, useEffect, useState } from 'react'
import {
  Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis,
} from 'recharts'
import ChartCard from '../../components/ChartCard.jsx'
import StatCard from '../../components/StatCard.jsx'
import Button from '../../components/ui/Button.jsx'
import Card from '../../components/ui/Card.jsx'
import usePolling from '../../hooks/usePolling.js'
import {
  adminListServices, getCounterUtilization, getDailyVolume, getPredictionAccuracy, getQueueLength, getServicePerformance, getWaitingByHour,
} from '../../services/api.js'
import { apiError } from '../../utils/errors.js'
import { fmtMin, fmtNum, fmtPct } from '../../utils/format.js'

const H = 260
const Chart = ({ children }) => <ResponsiveContainer width="100%" height={H}>{children}</ResponsiveContainer>

export default function AdminAnalytics() {
  const [days, setDays] = useState(7)
  const [hours, setHours] = useState(24)
  const [serviceId, setServiceId] = useState('')
  const [services, setServices] = useState([])
  const [data, setData] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => { adminListServices().then((d) => setServices(d.services)).catch(() => {}) }, [])

  const load = useCallback(async () => {
    const filter = serviceId ? { service_id: serviceId } : {}
    try {
      const [queue, wait, volume, perf, util, acc] = await Promise.all([
        getQueueLength({ hours, ...filter }), getWaitingByHour({ days, ...filter }), getDailyVolume({ days, ...filter }),
        getServicePerformance({ days, ...filter }), getCounterUtilization({ days }), getPredictionAccuracy({ days, ...filter }),
      ])
      setData({ queue, wait, volume, perf, util, acc })
      setError('')
    } catch (e) {
      setError(apiError(e).message)
    }
  }, [days, hours, serviceId])
  useEffect(() => { load() }, [load])
  usePolling(load, 30000, true)

  const d = data
  const waitRows = d ? d.wait.hours.filter((h) => h.n > 0) : []
  const utilRows = d ? d.util.counters.map((c) => ({ ...c, pct: c.utilization == null ? null : Math.round(c.utilization * 1000) / 10 })) : []
  const unrecorded = utilRows.filter((c) => c.utilization == null)
  const acc = d?.acc
  const maxPoint = acc ? Math.max(10, ...acc.points.flatMap((p) => [p.predicted, p.actual])) : 10

  return (
    <>
      <h1>Analytics</h1>
      <p className="qp-muted">Every figure is computed from tickets, counter sessions and prediction logs in the database.</p>
      <div className="qp-filters">
        <label className="qp-inline-label">Period{' '}
          <select value={days} onChange={(e) => setDays(Number(e.target.value))} aria-label="Period">
            <option value={7}>Last 7 days</option><option value={14}>Last 14 days</option><option value={30}>Last 30 days</option>
          </select>
        </label>
        <label className="qp-inline-label">Queue length window{' '}
          <select value={hours} onChange={(e) => setHours(Number(e.target.value))} aria-label="Queue length window">
            <option value={24}>24 hours</option><option value={48}>48 hours</option><option value={72}>72 hours</option>
          </select>
        </label>
        <label className="qp-inline-label">Service{' '}
          <select value={serviceId} onChange={(e) => setServiceId(e.target.value)} aria-label="Service">
            <option value="">All services</option>
            {services.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
        </label>
        <Button variant="ghost" onClick={load}>Refresh</Button>
      </div>
      {error && <div className="qp-alert" role="alert">{error}</div>}
      {!d ? (!error && <p className="qp-muted">Loading…</p>) : (
        <>
          <ChartCard title="Queue length over time" note={`Customers waiting at each hour, and the highest number waiting at any moment within that hour. Busiest moment in this window: ${d.queue.peak}. Customers cancelled or skipped before leave times were recorded cannot be placed in time and are omitted.`}
            columns={[{ key: 'label', label: 'Time' }, { key: 'waiting', label: 'Waiting at that time' }, { key: 'peak', label: 'Highest within the hour' }]} rows={d.queue.points}>
            <Chart><LineChart data={d.queue.points}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="label" interval="preserveStartEnd" /><YAxis allowDecimals={false} /><Tooltip /><Legend /><Line type="stepAfter" dataKey="waiting" name="Waiting at the hour" stroke="#2563eb" dot={false} /><Line type="stepAfter" dataKey="peak" name="Highest within the hour" stroke="#f59e0b" strokeDasharray="4 4" dot={false} /></LineChart></Chart>
          </ChartCard>

          <ChartCard title="Average waiting time by hour" note="By the hour customers joined (local time), for customers whose wait has been measured."
            empty={waitRows.length === 0 ? 'No measured waiting times in this period yet.' : null}
            columns={[{ key: 'label', label: 'Hour' }, { key: 'avg_waiting', label: 'Average wait (min)' }, { key: 'n', label: 'Customers measured' }]} rows={waitRows}>
            <Chart><BarChart data={waitRows}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="label" /><YAxis /><Tooltip /><Bar dataKey="avg_waiting" name="Average wait (min)" fill="#2563eb" /></BarChart></Chart>
          </ChartCard>

          <ChartCard title="Customers per day" note={`Customers who joined each day and how their tickets ended. Totals: ${d.volume.totals.joined} joined, ${d.volume.totals.completed} completed, ${d.volume.totals.cancelled} cancelled, ${d.volume.totals.skipped} skipped, ${d.volume.totals.absent} absent.`}
            empty={d.volume.totals.joined === 0 ? 'Nobody joined a queue in this period.' : null}
            columns={[{ key: 'label', label: 'Day' }, { key: 'joined', label: 'Joined' }, { key: 'completed', label: 'Completed' }, { key: 'cancelled', label: 'Cancelled' }, { key: 'skipped', label: 'Skipped' }, { key: 'absent', label: 'Absent' }, { key: 'in_progress', label: 'In progress' }]} rows={d.volume.days}>
            <Chart><BarChart data={d.volume.days}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="label" /><YAxis allowDecimals={false} /><Tooltip /><Legend />
              <Bar dataKey="completed" name="Completed" stackId="a" fill="#16a34a" /><Bar dataKey="cancelled" name="Cancelled" stackId="a" fill="#94a3b8" />
              <Bar dataKey="skipped" name="Skipped" stackId="a" fill="#f59e0b" /><Bar dataKey="absent" name="Absent" stackId="a" fill="#dc2626" /><Bar dataKey="in_progress" name="In progress" stackId="a" fill="#2563eb" /></BarChart></Chart>
          </ChartCard>

          <ChartCard title="Service performance" note="Average waiting and service times per service, with completion statistics."
            empty={d.perf.services.every((s) => s.joined === 0) ? 'No tickets in this period.' : null}
            columns={[{ key: 'service', label: 'Service' }, { key: 'joined', label: 'Joined' }, { key: 'completed', label: 'Completed' }, { key: 'completion_rate', label: 'Completion rate', render: (r) => fmtPct(r.completion_rate) },
              { key: 'cancelled', label: 'Cancelled' }, { key: 'skipped', label: 'Skipped' }, { key: 'absent', label: 'Absent' },
              { key: 'avg_waiting', label: 'Avg wait', render: (r) => fmtMin(r.avg_waiting) }, { key: 'avg_service_duration', label: 'Avg service', render: (r) => fmtMin(r.avg_service_duration) }]} rows={d.perf.services}>
            <Chart><BarChart data={d.perf.services}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="service" /><YAxis /><Tooltip /><Legend />
              <Bar dataKey="avg_waiting" name="Average wait (min)" fill="#2563eb" /><Bar dataKey="avg_service_duration" name="Average service (min)" fill="#16a34a" /></BarChart></Chart>
          </ChartCard>

          <ChartCard title="Counter utilization" note="Time spent serving customers divided by time the counter was open."
            empty={utilRows.length === 0 ? 'No counters yet.' : null}
            columns={[{ key: 'counter', label: 'Counter' }, { key: 'service', label: 'Service' }, { key: 'open_minutes', label: 'Open (min)' }, { key: 'serving_minutes', label: 'Serving (min)' },
              { key: 'utilization', label: 'Utilization', render: (r) => fmtPct(r.utilization) }, { key: 'customers_served', label: 'Customers served' }]} rows={utilRows}>
            <Chart><BarChart data={utilRows}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="counter" /><YAxis unit="%" domain={[0, 100]} /><Tooltip /><Bar dataKey="pct" name="Utilization (%)" fill="#7c3aed" /></BarChart></Chart>
          </ChartCard>
          {unrecorded.length > 0 && utilRows.length > 0 && (
            <p className="qp-muted qp-small">No open time recorded in this period for: {unrecorded.map((c) => c.counter).join(', ')}. Utilization is unknown for them, not zero.</p>
          )}

          <Card title="Prediction accuracy">
            {acc.overall.n === 0 ? (
              <p className="qp-muted">No predictions with a measured outcome in this period yet. {acc.awaiting_outcome} awaiting an outcome.</p>
            ) : (
              <>
                <div className="qp-stats-grid">
                  <StatCard label="MAE" value={fmtMin(acc.overall.mae)} hint={`Average absolute error, ${acc.overall.n} predictions`} />
                  <StatCard label="RMSE" value={fmtMin(acc.overall.rmse)} hint="Penalises large misses" />
                  <StatCard label="R²" value={fmtNum(acc.overall.r2, 3)} hint={acc.overall.r2 == null ? 'Needs at least 10 predictions' : 'Closer to 1 is better'} />
                  <StatCard label="Awaiting outcome" value={acc.awaiting_outcome} hint="Predictions whose customer has not started service" />
                </div>
                <p className="qp-muted qp-small">{acc.note}</p>
              </>
            )}
          </Card>
          {acc.overall.n > 0 && (
            <>
              <ChartCard title="Prediction error trend" columns={[{ key: 'label', label: 'Day' }, { key: 'n', label: 'Predictions' }, { key: 'mae', label: 'MAE (min)' }, { key: 'bias', label: 'Bias (min)' }]} rows={acc.trend}>
                <Chart><LineChart data={acc.trend}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="label" /><YAxis /><Tooltip /><Legend />
                  <Line dataKey="mae" name="MAE (min)" stroke="#dc2626" /><Line dataKey="bias" name="Bias (min)" stroke="#2563eb" /></LineChart></Chart>
              </ChartCard>
              <ChartCard title="Predicted vs actual waiting time" note="Points on the diagonal are perfect predictions."
                columns={[{ key: 'source', label: 'Source' }, { key: 'predicted', label: 'Predicted (min)' }, { key: 'actual', label: 'Actual (min)' }]} rows={acc.points}>
                <Chart><ScatterChart><CartesianGrid strokeDasharray="3 3" /><XAxis type="number" dataKey="predicted" name="Predicted" unit=" min" domain={[0, maxPoint]} /><YAxis type="number" dataKey="actual" name="Actual" unit=" min" domain={[0, maxPoint]} /><Tooltip />
                  <ReferenceLine segment={[{ x: 0, y: 0 }, { x: maxPoint, y: maxPoint }]} stroke="#94a3b8" strokeDasharray="4 4" /><Scatter data={acc.points} fill="#2563eb" /></ScatterChart></Chart>
              </ChartCard>
            </>
          )}
        </>
      )}
    </>
  )
}
