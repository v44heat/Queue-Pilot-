import { useCallback, useEffect, useState } from 'react'
import Pager from '../components/Pager.jsx'
import SortHeader from '../components/SortHeader.jsx'
import Button from '../components/ui/Button.jsx'
import Card from '../components/ui/Card.jsx'
import ConfirmDialog from '../components/ui/ConfirmDialog.jsx'
import { useAuth } from '../context/AuthContext.jsx'
import { useToast } from '../context/ToastContext.jsx'
import { createUser, listUsers, updateUser } from '../services/api.js'
import { apiError } from '../utils/errors.js'
import { fmtDate } from '../utils/format.js'

const ROLES = ['CUSTOMER', 'STAFF', 'ADMIN']
const EMPTY = { name: '', email: '', phone: '', password: '', role: 'STAFF' }

export default function AdminUsers() {
  const { user: me } = useAuth()
  const toast = useToast()
  const [query, setQuery] = useState({ search: '', role: '', status: '', sort: 'created', order: 'desc', page: 1 })
  const [searchInput, setSearchInput] = useState('')
  const [data, setData] = useState({ users: [], total: 0, pages: 1 })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState(EMPTY)
  const [formErrors, setFormErrors] = useState({})
  const [pending, setPending] = useState(null) // { user, patch, title, message, label }
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const params = { page: query.page, per_page: 10, sort: query.sort, order: query.order }
      for (const k of ['search', 'role', 'status']) if (query[k]) params[k] = query[k]
      setData(await listUsers(params))
    } catch (err) {
      setError(apiError(err).message)
    } finally {
      setLoading(false)
    }
  }, [query])

  useEffect(() => { load() }, [load])

  const confirmChange = async () => {
    setBusy(true)
    try {
      await updateUser(pending.user.id, pending.patch)
      toast.success('User updated.')
      await load()
    } catch (err) {
      setError(apiError(err).message)
    } finally {
      setBusy(false)
      setPending(null)
    }
  }

  const onCreate = async (e) => {
    e.preventDefault()
    setFormErrors({})
    try {
      await createUser(form)
      toast.success('User created.')
      setForm(EMPTY)
      setShowForm(false)
      setQuery({ ...query, page: 1 })
      await load()
    } catch (err) {
      const { message, details } = apiError(err)
      setFormErrors({ ...details, _: message })
    }
  }

  const sortProps = { sort: query.sort, order: query.order, onSort: (sort, order) => setQuery({ ...query, sort, order, page: 1 }) }

  return (
    <>
      <h1>User management</h1>
      <p className="qp-muted">Create staff and admin accounts, change roles, and activate or deactivate users. Assign staff to counters under Counters.</p>

      <Card
        title={`Users (${data.total})`}
        action={<Button onClick={() => setShowForm((s) => !s)}>{showForm ? 'Cancel' : 'Add user'}</Button>}
      >
        {showForm && (
          <form onSubmit={onCreate} className="qp-form qp-form--inline" aria-label="Create user">
            {formErrors._ && <div className="qp-alert" role="alert">{formErrors._}</div>}
            {['name', 'email', 'phone', 'password'].map((k) => (
              <label key={k}>{k[0].toUpperCase() + k.slice(1)}
                <input type={k === 'password' ? 'password' : 'text'} value={form[k]}
                  onChange={(e) => setForm({ ...form, [k]: e.target.value })} />
                {formErrors[k] && <span className="qp-field-error">{formErrors[k]}</span>}
              </label>
            ))}
            <label>Role
              <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
                {ROLES.map((r) => <option key={r}>{r}</option>)}
              </select>
            </label>
            <Button type="submit">Create</Button>
          </form>
        )}

        <form className="qp-filters" onSubmit={(e) => { e.preventDefault(); setQuery({ ...query, search: searchInput, page: 1 }) }}>
          <input placeholder="Search name or email" aria-label="Search users" value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)} />
          <select aria-label="Filter by role" value={query.role} onChange={(e) => setQuery({ ...query, role: e.target.value, page: 1 })}>
            <option value="">All roles</option>
            {ROLES.map((r) => <option key={r}>{r}</option>)}
          </select>
          <select aria-label="Filter by status" value={query.status} onChange={(e) => setQuery({ ...query, status: e.target.value, page: 1 })}>
            <option value="">All statuses</option>
            <option>ACTIVE</option>
            <option>INACTIVE</option>
          </select>
          <Button type="submit" variant="ghost">Search</Button>
        </form>

        {error && <div className="qp-alert" role="alert">{error}</div>}
        {loading ? <p className="qp-muted">Loading…</p> : data.users.length === 0 ? (
          <p className="qp-muted">No users match your filters.</p>
        ) : (
          <div className="qp-table-wrap">
            <table className="qp-table">
              <thead>
                <tr>
                  <SortHeader label="Name" sortKey="name" {...sortProps} />
                  <SortHeader label="Email" sortKey="email" {...sortProps} />
                  <SortHeader label="Role" sortKey="role" {...sortProps} />
                  <SortHeader label="Status" sortKey="status" {...sortProps} />
                  <SortHeader label="Joined" sortKey="created" {...sortProps} />
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {data.users.map((u) => {
                  const self = u.id === me.id
                  return (
                    <tr key={u.id}>
                      <td>{u.name}{self && ' (you)'}</td>
                      <td>{u.email}</td>
                      <td>
                        <select aria-label={`Role for ${u.email}`} value={u.role} disabled={self}
                          onChange={(e) => setPending({ user: u, patch: { role: e.target.value }, title: 'Change role?', message: `${u.email} will become ${e.target.value}. Their permissions change immediately.`, label: 'Change role' })}>
                          {ROLES.map((r) => <option key={r}>{r}</option>)}
                        </select>
                      </td>
                      <td>{u.status}</td>
                      <td>{fmtDate(u.created_at)}</td>
                      <td>
                        <Button variant="ghost" disabled={self}
                          onClick={() => {
                            const off = u.status === 'ACTIVE'
                            setPending({ user: u, patch: { status: off ? 'INACTIVE' : 'ACTIVE' }, label: off ? 'Deactivate' : 'Activate',
                              title: `${off ? 'Deactivate' : 'Activate'} ${u.email}?`,
                              message: off ? 'They will be signed out of every session and unable to log in.' : 'They will be able to log in again.' })
                          }}>
                          {u.status === 'ACTIVE' ? 'Deactivate' : 'Activate'}
                        </Button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
        <Pager page={query.page} pages={data.pages} onChange={(page) => setQuery({ ...query, page })} />
      </Card>
      <ConfirmDialog open={Boolean(pending)} busy={busy} title={pending?.title} message={pending?.message}
        confirmLabel={pending?.label} cancelLabel="Cancel" onConfirm={confirmChange} onCancel={() => setPending(null)} />
    </>
  )
}
