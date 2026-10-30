import { useState } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import Button from '../components/ui/Button.jsx'
import Card from '../components/ui/Card.jsx'
import { useAuth } from '../context/AuthContext.jsx'
import { apiError } from '../utils/errors.js'
import { roleHome } from '../utils/roles.js'

export default function Register() {
  const { user, register } = useAuth()
  const navigate = useNavigate()
  const [form, setForm] = useState({ name: '', email: '', phone: '', password: '', confirm: '' })
  const [errors, setErrors] = useState({})
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  if (user) return <Navigate to={roleHome(user.role)} replace />

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value })

  const onSubmit = async (e) => {
    e.preventDefault()
    setError('')
    if (form.password !== form.confirm) {
      setErrors({ confirm: 'Passwords do not match.' })
      return
    }
    setErrors({})
    setBusy(true)
    try {
      const { confirm, ...payload } = form
      const u = await register(payload)
      navigate(roleHome(u.role), { replace: true })
    } catch (err) {
      const { message, details } = apiError(err)
      setErrors(details)
      setError(message)
    } finally {
      setBusy(false)
    }
  }

  const field = (key, label, props = {}) => (
    <label>{label}
      <input value={form[key]} onChange={set(key)} {...props} />
      {errors[key] && <span className="qp-field-error">{errors[key]}</span>}
    </label>
  )

  return (
    <div className="qp-auth">
      <Card title="Create your account">
        <form onSubmit={onSubmit} className="qp-form" noValidate>
          {error && <div className="qp-alert" role="alert">{error}</div>}
          {field('name', 'Full name', { autoComplete: 'name' })}
          {field('email', 'Email', { type: 'email', autoComplete: 'email' })}
          {field('phone', 'Phone (optional)', { type: 'tel', autoComplete: 'tel' })}
          {field('password', 'Password', { type: 'password', autoComplete: 'new-password' })}
          <small className="qp-muted">At least 8 characters with a letter and a number.</small>
          {field('confirm', 'Confirm password', { type: 'password', autoComplete: 'new-password' })}
          <Button type="submit" disabled={busy}>{busy ? 'Creating…' : 'Register'}</Button>
          <p className="qp-muted">Already registered? <Link to="/login">Log in</Link></p>
        </form>
      </Card>
    </div>
  )
}
