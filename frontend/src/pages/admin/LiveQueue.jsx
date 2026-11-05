import { useCallback, useEffect, useState } from 'react'
import Pager from '../../components/Pager.jsx'
import SortHeader from '../../components/SortHeader.jsx'
import Button from '../../components/ui/Button.jsx'
import Card from '../../components/ui/Card.jsx'
import usePolling from '../../hooks/usePolling.js'
import { adminListServices, getAdminQueue } from '../../services/api.js'
import { apiError } from '../../utils/errors.js'
import { STATUS_LABEL, fmtTime } from '../../utils/format.js'

const STATUS_OPTIONS = [['ACTIVE', 'In queue now'], ['ALL', 'All tickets'], ...Object.entries(STATUS_LABEL)]

function estimate(t) {
  const e = t.estimated_wait
  if (t.status !== 'WAITING' || !e) return '-'
  if (e.minutes == null) return 'No counter open'
  return `${Math.round(e.minutes)} min${e.source === 'fallback' ? ' (basic)' : ''}`
}

export default function LiveQueue() {
  const [query, setQuery] = useState({ status: 'ACTIVE', service_id: '', search: '', sort: '', order: 'asc', page: 1 })
  const [searchInput, setSearchInput] = useState('')
  const [services, setServices] = useState([])
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [updated, setUpdated] = useState(null)

  useEffect(() => { adminListServices().then((d) => setServices(d.services)).catch(() => {}) }, [])

  const load = useCallback(async () => {
    try {
      const params = { status: query.status, page: query.page, per_page: 20 }
      for (const k of ['service_id', 'search', 'sort']) if (query[k]) params[k] = query[k]
      if (query.sort) params.order = query.order
      setData(await getAdminQueue(params))
      setUpdated(new Date().toISOString())
      setError('')
    } catch (e) {
      setError(apiError(e).message)
    }
  }, [query])
  useEffect(() => { load() }, [load])
  usePolling(load, 5000, true)

  const set = (patch) => setQuery({ ...query, ...patch, page: 'page' in patch ? patch.page : 1 })
  const sortProps = { sort: query.sort, order: query.order, onSort: (sort, order) => set({ sort, order }) }

  return (
    <>
      <h1>Live queue monitor</h1>
      <p className="qp-muted">Updates every 5 seconds{updated ? ` · last updated ${fmtTime(updated)}` : ''}. Estimates use the same model as customers see.</p>
      <Card title={`Tickets${data ? ` (${data.total})` : ''}`}>
        <form className="qp-filters" onSubmit={(e) => { e.preventDefault(); set({ search: searchInput }) }}>
          <input placeholder="Search ticket, name or email" aria-label="Search tickets" value={searchInput} onChange={(e) => setSearchInput(e.target.value)} />
          <select aria-label="Filter by status" value={query.status} onChange={(e) => set({ status: e.target.value })}>
            {STATUS_OPTIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
          <select aria-label="Filter by service" value={query.service_id} onChange={(e) => set({ service_id: e.target.value })}>
            <option value="">All services</option>
            {services.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
          <Button type="submit" variant="ghost">Search</Button>
        </form>
        {error && <div className="qp-alert" role="alert">{error}</div>}
        {!data ? <p className="qp-muted">Loading…</p> : data.tickets.length === 0 ? (
          <p className="qp-muted">No tickets match. {query.status === 'ACTIVE' && !query.search ? 'Nobody is in a queue right now.' : ''}</p>
        ) : (
          <div className="qp-table-wrap">
            <table className="qp-table">
              <thead>
                <tr>
                  <SortHeader label="Queue Number" sortKey="number" {...sortProps} />
                  <SortHeader label="Service" sortKey="service" {...sortProps} />
                  <SortHeader label="Customer" sortKey="customer" {...sortProps} />
                  <th>Position</th><th>Estimated Wait</th>
                  <SortHeader label="Status" sortKey="status" {...sortProps} />
                  <th>Counter</th>
                </tr>
              </thead>
              <tbody>
                {data.tickets.map((t) => (
                  <tr key={t.id}>
                    <td>{t.queue_number}</td><td>{t.service.name}</td>
                    <td>{t.customer.name}<br /><small className="qp-muted">{t.customer.email}</small></td>
                    <td>{t.position ?? '-'}</td><td>{estimate(t)}</td>
                    <td><span className={`qp-badge qp-status qp-status--${t.status.toLowerCase()}`}>{STATUS_LABEL[t.status]}</span></td>
                    <td>{t.counter?.name ?? '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <Pager page={query.page} pages={data?.pages} onChange={(page) => setQuery({ ...query, page })} />
      </Card>
    </>
  )
}
