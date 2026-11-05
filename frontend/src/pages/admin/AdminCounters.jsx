import { useCallback, useEffect, useState } from 'react'
import Button from '../../components/ui/Button.jsx'
import Card from '../../components/ui/Card.jsx'
import ConfirmDialog from '../../components/ui/ConfirmDialog.jsx'
import { useToast } from '../../context/ToastContext.jsx'
import {
  adminAssignStaff, adminCreateCounter, adminListCounters, adminListServices, adminUnassignStaff, adminUpdateCounter, listUsers,
} from '../../services/api.js'
import { apiError } from '../../utils/errors.js'

export default function AdminCounters() {
  const toast = useToast()
  const [counters, setCounters] = useState(null)
  const [services, setServices] = useState([])
  const [staff, setStaff] = useState([])
  const [error, setError] = useState('')
  const [form, setForm] = useState({ name: '', service_id: '' })
  const [formErrors, setFormErrors] = useState({})
  const [pick, setPick] = useState({}) // counter id -> chosen staff id
  const [confirm, setConfirm] = useState(null) // { title, message, label, run }
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    try { setCounters((await adminListCounters()).counters); setError('') } catch (e) { setError(apiError(e).message) }
  }, [])
  useEffect(() => {
    load()
    adminListServices().then((d) => setServices(d.services.filter((s) => s.status === 'ACTIVE'))).catch(() => {})
    listUsers({ role: 'STAFF', status: 'ACTIVE', per_page: 100 }).then((d) => setStaff(d.users)).catch(() => {})
  }, [load])

  const act = async (fn, okMessage) => {
    setError('')
    try { await fn(); if (okMessage) toast.success(okMessage); await load() } catch (e) { setError(apiError(e).message) }
  }

  const create = async (e) => {
    e.preventDefault()
    setFormErrors({})
    try {
      await adminCreateCounter({ name: form.name, ...(form.service_id ? { service_id: Number(form.service_id) } : {}) })
      toast.success('Counter created.')
      setForm({ name: '', service_id: '' })
      await load()
    } catch (err) {
      const { message, details } = apiError(err)
      setFormErrors({ ...details, _: message })
    }
  }

  const runConfirmed = async () => {
    setBusy(true)
    await act(confirm.run)
    setBusy(false)
    setConfirm(null)
  }

  return (
    <>
      <h1>Counters</h1>
      <p className="qp-muted">Create counters, assign them to a service, and assign staff. Staff open counters themselves; administrators cannot open them or serve customers.</p>
      {error && <div className="qp-alert" role="alert">{error}</div>}

      <Card title="Add counter">
        <form onSubmit={create} className="qp-form qp-form--inline" noValidate>
          {formErrors._ && <div className="qp-alert" role="alert">{formErrors._}</div>}
          <label>Name
            <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            {formErrors.name && <span className="qp-field-error">{formErrors.name}</span>}
          </label>
          <label>Service
            <select value={form.service_id} onChange={(e) => setForm({ ...form, service_id: e.target.value })}>
              <option value="">Not assigned yet</option>
              {services.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </label>
          <Button type="submit">Create counter</Button>
        </form>
      </Card>

      <Card title={`Counters${counters ? ` (${counters.length})` : ''}`}>
        {!counters ? <p className="qp-muted">Loading…</p> : counters.length === 0 ? <p className="qp-muted">No counters yet.</p> : (
          <div className="qp-table-wrap">
            <table className="qp-table">
              <thead><tr><th>Counter</th><th>Service</th><th>Status</th><th>Staff</th><th>Actions</th></tr></thead>
              <tbody>
                {counters.map((c) => {
                  const free = staff.filter((s) => !c.staff.some((x) => x.id === s.id))
                  return (
                    <tr key={c.id}>
                      <td>{c.name}<br /><small className="qp-muted">{c.availability}</small></td>
                      <td>
                        <select aria-label={`Service for ${c.name}`} value={c.service?.id ?? ''}
                          onChange={(e) => act(() => adminUpdateCounter(c.id, { service_id: e.target.value ? Number(e.target.value) : null }), 'Counter updated.')}>
                          <option value="">Not assigned</option>
                          {services.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                        </select>
                      </td>
                      <td>{c.status}</td>
                      <td>
                        <ul className="qp-chips">
                          {c.staff.map((s) => (
                            <li key={s.id}>{s.name}
                              <button type="button" aria-label={`Remove ${s.name} from ${c.name}`}
                                onClick={() => setConfirm({ title: `Remove ${s.name}?`, message: `${s.name} will no longer be able to operate ${c.name}.`, label: 'Remove',
                                  run: () => adminUnassignStaff(c.id, s.id) })}>×</button>
                            </li>
                          ))}
                          {c.staff.length === 0 && <li className="qp-muted">No staff</li>}
                        </ul>
                        <span className="qp-actions">
                          <select aria-label={`Staff to assign to ${c.name}`} value={pick[c.id] ?? ''} onChange={(e) => setPick({ ...pick, [c.id]: e.target.value })}>
                            <option value="">Choose staff…</option>
                            {free.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                          </select>
                          <Button variant="ghost" disabled={!pick[c.id]} aria-label={`Assign staff to ${c.name}`}
                            onClick={() => act(() => adminAssignStaff(c.id, Number(pick[c.id])), 'Staff assigned.').then(() => setPick({ ...pick, [c.id]: '' }))}>
                            Assign
                          </Button>
                        </span>
                      </td>
                      <td>
                        {c.status === 'INACTIVE' ? (
                          <Button variant="ghost" onClick={() => act(() => adminUpdateCounter(c.id, { status: 'CLOSED' }), 'Counter re-enabled.')} aria-label={`Re-enable ${c.name}`}>Re-enable</Button>
                        ) : (
                          <Button variant="ghost" aria-label={`Deactivate ${c.name}`}
                            onClick={() => setConfirm({ title: `Deactivate ${c.name}?`, message: 'The counter will be closed and staff cannot open it until you re-enable it.', label: 'Deactivate',
                              run: () => adminUpdateCounter(c.id, { status: 'INACTIVE' }) })}>
                            Deactivate
                          </Button>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <ConfirmDialog open={Boolean(confirm)} busy={busy} title={confirm?.title} message={confirm?.message}
        confirmLabel={confirm?.label} cancelLabel="Cancel" onConfirm={runConfirmed} onCancel={() => setConfirm(null)} />
    </>
  )
}
