import { useState } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'
import Button from '../components/ui/Button.jsx'
import Card from '../components/ui/Card.jsx'
import { useAuth } from '../context/AuthContext.jsx'
import { apiError } from '../utils/errors.js'
import { roleHome } from '../utils/roles.js'

export default function Login() {
  const { user, login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [form, setForm] = useState({ email: '', password: '' })
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  if (user) return <Navigate to={roleHome(user.role)} replace />

  const onSubmit = async (e) => {
    e.preventDefault()
    setError('')
    setBusy(true)
    try {
      const u = await login(form.email, form.password)
      navigate(location.state?.from || roleHome(u.role), { replace: true })
    } catch (err) {
      setError(apiError(err).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="qp-auth">
      <Card title="Log in">
        <form onSubmit={onSubmit} className="qp-form" noValidate>
          {error && <div className="qp-alert" role="alert">{error}</div>}
          <label>Email
            <input type="email" autoComplete="email" required value={form.email}
              onChange={(e) => setForm({ ...form, email: e.target.value })} />
          </label>
          <label>Password
            <input type="password" autoComplete="current-password" required value={form.password}
              onChange={(e) => setForm({ ...form, password: e.target.value })} />
          </label>
          <Button type="submit" disabled={busy}>{busy ? 'Signing in…' : 'Log in'}</Button>
          <p className="qp-muted">No account? <Link to="/register">Register</Link></p>
        </form>
      </Card>
    </div>
  )
}
