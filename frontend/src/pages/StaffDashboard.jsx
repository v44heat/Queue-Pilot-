import { useCallback, useEffect, useState } from 'react'
import Button from '../components/ui/Button.jsx'
import Card from '../components/ui/Card.jsx'
import {
  callNext, closeCounter, getCounterQueue, getStaffCounters, openCounter, ticketAction,
} from '../services/api.js'
import { apiError } from '../utils/errors.js'

const POLL_MS = 5000
const time = (iso) => (iso ? new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '-')

export default function StaffDashboard() {
  const [counters, setCounters] = useState(null) // null = loading
  const [selected, setSelected] = useState(null)
  const [view, setView] = useState(null) // { counter, waiting, stats }
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    getStaffCounters()
      .then((d) => {
        setCounters(d.counters)
        if (d.counters.length) setSelected(d.counters[0].id)
      })
      .catch((e) => { setError(apiError(e).message); setCounters([]) })
  }, [])

  const load = useCallback(async () => {
    if (selected == null) return
    try {
      setView(await getCounterQueue(selected))
    } catch (e) {
      setError(apiError(e).message)
    }
  }, [selected])

  // Live updates: refresh the queue every few seconds while this page is open.
  useEffect(() => {
    load()
    const id = setInterval(load, POLL_MS)
    return () => clearInterval(id)
  }, [load])

  const run = async (fn, confirmText) => {
    if (confirmText && !window.confirm(confirmText)) return
    setBusy(true)
    setError('')
    try {
      await fn()
    } catch (e) {
      setError(apiError(e).message)
    } finally {
      await load()
      setBusy(false)
    }
  }

  if (counters === null) return <p className="qp-muted">Loading…</p>
  if (counters.length === 0) {
    return (
      <>
        <h1>Staff dashboard</h1>
        {error && <div className="qp-alert" role="alert">{error}</div>}
        <Card title="No counters assigned">
          <p>You are not assigned to any counter yet. Ask an administrator to assign you to one.</p>
        </Card>
      </>
    )
  }

  const counter = view?.counter
  const current = counter?.current_ticket
  const open = counter?.status === 'OPEN'
  const waiting = view?.waiting ?? []
  const stats = view?.stats

  return (
    <>
      <h1>Staff dashboard</h1>
      {counters.length > 1 && (
        <label className="qp-inline-label">Counter{' '}
          <select value={selected ?? ''} onChange={(e) => { setView(null); setSelected(Number(e.target.value)) }}>
            {counters.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </label>
      )}
      {error && <div className="qp-alert" role="alert">{error}</div>}
      {!counter ? <p className="qp-muted">Loading counter…</p> : (
        <>
          <Card
            title={`${counter.name} · ${counter.service ? counter.service.name : 'No service'}`}
            action={
              <span className="qp-actions">
                <span className={`qp-badge qp-badge--${open ? 'ok' : 'loading'}`}>{counter.status}</span>
                {counter.status === 'CLOSED' && (
                  <Button disabled={busy} onClick={() => run(() => openCounter(counter.id))}>Open counter</Button>
                )}
                {open && (
                  <Button variant="ghost" disabled={busy || Boolean(current)} onClick={() => run(() => closeCounter(counter.id))}>
                    Close counter
                  </Button>
                )}
              </span>
            }
          >
            <div className="qp-stats">
              <div><strong>{stats?.waiting_for_service ?? 0}</strong><span>Waiting</span></div>
              <div><strong>{stats?.served_today ?? 0}</strong><span>Served today</span></div>
              <div>
                <strong>{stats?.avg_service_duration_today == null ? '-' : `${stats.avg_service_duration_today} min`}</strong>
                <span>Avg service time today</span>
              </div>
            </div>
            {counter.status === 'INACTIVE' && (
              <p className="qp-muted">This counter was deactivated by an administrator.</p>
            )}
          </Card>

          <Card title="Current customer">
            {current ? (
              <div className="qp-current">
                <div>
                  <div className="qp-bignumber">{current.queue_number}</div>
                  <div>{current.customer?.name}</div>
                  <div className="qp-muted">
                    {current.status === 'CALLED' ? `Called at ${time(current.called_time)}` : `Serving since ${time(current.service_start_time)}`}
                  </div>
                  <span className={`qp-badge qp-badge--${current.status === 'SERVING' ? 'ok' : 'loading'}`}>{current.status}</span>
                </div>
                <div className="qp-actions">
                  {current.status === 'CALLED' && (
                    <>
                      <Button disabled={busy} onClick={() => run(() => ticketAction(current.id, 'start'))}>Start service</Button>
                      <Button variant="ghost" disabled={busy}
                        onClick={() => run(() => ticketAction(current.id, 'absent'), `Mark ${current.queue_number} as absent?`)}>
                        Mark absent
                      </Button>
                      <Button variant="ghost" disabled={busy}
                        onClick={() => run(() => ticketAction(current.id, 'skip'), `Skip ${current.queue_number}?`)}>
                        Skip
                      </Button>
                    </>
                  )}
                  {current.status === 'SERVING' && (
                    <Button disabled={busy} onClick={() => run(() => ticketAction(current.id, 'complete'))}>Complete service</Button>
                  )}
                </div>
              </div>
            ) : (
              <div className="qp-current">
                <p className="qp-muted">{open ? 'No customer at this counter.' : 'Open the counter to start calling customers.'}</p>
                <Button disabled={busy || !open || waiting.length === 0} onClick={() => run(() => callNext(counter.id))}>
                  Call next customer
                </Button>
              </div>
            )}
          </Card>

          <Card title={`Waiting (${waiting.length})`}>
            {waiting.length === 0 ? <p className="qp-muted">Nobody is waiting.</p> : (
              <div className="qp-table-wrap">
                <table className="qp-table">
                  <thead><tr><th>#</th><th>Ticket</th><th>Customer</th><th>Joined</th></tr></thead>
                  <tbody>
                    {waiting.map((t) => (
                      <tr key={t.id}><td>{t.position}</td><td>{t.queue_number}</td><td>{t.customer?.name}</td><td>{time(t.join_time)}</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </>
      )}
    </>
  )
}
