import { useCallback, useEffect, useState } from 'react'
import Button from '../../components/ui/Button.jsx'
import Card from '../../components/ui/Card.jsx'
import ConfirmDialog from '../../components/ui/ConfirmDialog.jsx'
import { useToast } from '../../context/ToastContext.jsx'
import { adminCreateService, adminListServices, adminUpdateService } from '../../services/api.js'
import { apiError } from '../../utils/errors.js'

const EMPTY = { name: '', prefix: '', description: '', default_service_duration: 10 }

export default function AdminServices() {
  const toast = useToast()
  const [services, setServices] = useState(null)
  const [error, setError] = useState('')
  const [editing, setEditing] = useState(null) // null = closed, 'new' or a service
  const [form, setForm] = useState(EMPTY)
  const [errors, setErrors] = useState({})
  const [confirm, setConfirm] = useState(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    try { setServices((await adminListServices()).services); setError('') } catch (e) { setError(apiError(e).message) }
  }, [])
  useEffect(() => { load() }, [load])

  const open = (service) => {
    setErrors({})
    setEditing(service || 'new')
    setForm(service ? { name: service.name, prefix: service.prefix, description: service.description || '', default_service_duration: service.default_service_duration } : EMPTY)
  }

  const save = async (e) => {
    e.preventDefault()
    setErrors({})
    const payload = { ...form, default_service_duration: Number(form.default_service_duration) }
    try {
      if (editing === 'new') await adminCreateService(payload)
      else await adminUpdateService(editing.id, payload)
      toast.success(editing === 'new' ? 'Service created.' : 'Service updated.')
      setEditing(null)
      await load()
    } catch (err) {
      const { message, details } = apiError(err)
      setErrors({ ...details, _: message })
    }
  }

  const toggle = async () => {
    setBusy(true)
    try {
      await adminUpdateService(confirm.id, { status: confirm.status === 'ACTIVE' ? 'INACTIVE' : 'ACTIVE' })
      toast.success(confirm.status === 'ACTIVE' ? 'Service deactivated.' : 'Service activated.')
      await load()
    } catch (err) {
      setError(apiError(err).message)
    } finally {
      setBusy(false)
      setConfirm(null)
    }
  }

  const field = (key, label, props = {}) => (
    <label>{label}
      <input value={form[key]} onChange={(e) => setForm({ ...form, [key]: e.target.value })} {...props} />
      {errors[key] && <span className="qp-field-error">{errors[key]}</span>}
    </label>
  )

  return (
    <>
      <h1>Services</h1>
      <p className="qp-muted">Services customers can queue for. Services are deactivated, never deleted, so ticket history stays intact.</p>
      {error && <div className="qp-alert" role="alert">{error}</div>}
      <Card title={`Services${services ? ` (${services.length})` : ''}`} action={<Button onClick={() => (editing ? setEditing(null) : open())}>{editing ? 'Cancel' : 'Add service'}</Button>}>
        {editing && (
          <form onSubmit={save} className="qp-form qp-form--inline" aria-label={editing === 'new' ? 'Create service' : 'Edit service'} noValidate>
            {errors._ && <div className="qp-alert" role="alert">{errors._}</div>}
            {field('name', 'Name')}
            {field('prefix', 'Ticket prefix', { maxLength: 6, disabled: editing !== 'new' && editing.total_tickets > 0, title: 'Locked once tickets exist' })}
            {field('default_service_duration', 'Typical service time (min)', { type: 'number', min: 1, max: 240 })}
            {field('description', 'Description')}
            <Button type="submit">{editing === 'new' ? 'Create service' : 'Save changes'}</Button>
          </form>
        )}
        {!services ? <p className="qp-muted">Loading…</p> : services.length === 0 ? <p className="qp-muted">No services yet. Add one to get started.</p> : (
          <div className="qp-table-wrap">
            <table className="qp-table">
              <thead><tr><th>Name</th><th>Prefix</th><th>Typical time</th><th>Status</th><th>Waiting</th><th>Counters</th><th>Tickets ever</th><th>Actions</th></tr></thead>
              <tbody>
                {services.map((s) => (
                  <tr key={s.id}>
                    <td>{s.name}</td><td>{s.prefix}</td><td>{s.default_service_duration} min</td>
                    <td><span className={`qp-badge qp-status qp-status--${s.status === 'ACTIVE' ? 'completed' : 'cancelled'}`}>{s.status}</span></td>
                    <td>{s.waiting_count}</td><td>{s.open_counters} open / {s.counters}</td><td>{s.total_tickets}</td>
                    <td className="qp-actions">
                      <Button variant="ghost" onClick={() => open(s)} aria-label={`Edit ${s.name}`}>Edit</Button>
                      <Button variant="ghost" onClick={() => setConfirm(s)} aria-label={`${s.status === 'ACTIVE' ? 'Deactivate' : 'Activate'} ${s.name}`}>
                        {s.status === 'ACTIVE' ? 'Deactivate' : 'Activate'}
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <ConfirmDialog
        open={Boolean(confirm)} busy={busy} onConfirm={toggle} onCancel={() => setConfirm(null)}
        title={confirm?.status === 'ACTIVE' ? `Deactivate ${confirm?.name}?` : `Activate ${confirm?.name}?`}
        message={confirm?.status === 'ACTIVE'
          ? 'Customers will no longer see this service or be able to join it. This is refused while anyone is still in its queue.'
          : 'Customers will be able to see and join this service again.'}
        confirmLabel={confirm?.status === 'ACTIVE' ? 'Deactivate' : 'Activate'} cancelLabel="Cancel"
      />
    </>
  )
}
