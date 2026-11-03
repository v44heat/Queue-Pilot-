import { useState } from 'react'
import Button from '../../components/ui/Button.jsx'
import Card from '../../components/ui/Card.jsx'
import { useAuth } from '../../context/AuthContext.jsx'
import { useToast } from '../../context/ToastContext.jsx'
import { changePassword, updateProfile } from '../../services/api.js'
import { apiError } from '../../utils/errors.js'
import { fmtDate } from '../../utils/format.js'

export default function Profile() {
  const { user, setUser } = useAuth()
  const toast = useToast()
  const [form, setForm] = useState({ name: user.name, phone: user.phone || '' })
  const [errors, setErrors] = useState({})
  const [busy, setBusy] = useState(false)
  const [pw, setPw] = useState({ current: '', next: '', confirm: '' })
  const [pwErrors, setPwErrors] = useState({})

  const saveProfile = async (e) => {
    e.preventDefault()
    setErrors({})
    setBusy(true)
    try {
      const d = await updateProfile({ name: form.name, phone: form.phone })
      setUser(d.user)
      toast.success('Profile updated.')
    } catch (err) {
      setErrors(apiError(err).details)
      toast.error(apiError(err).message)
    } finally {
      setBusy(false)
    }
  }

  const savePassword = async (e) => {
    e.preventDefault()
    if (pw.next !== pw.confirm) { setPwErrors({ confirm: 'Passwords do not match.' }); return }
    setPwErrors({})
    try {
      await changePassword(pw.current, pw.next)
      setPw({ current: '', next: '', confirm: '' })
      toast.success('Password changed.')
    } catch (err) {
      const { message, details } = apiError(err)
      setPwErrors({ current: details.current_password, next: details.new_password, _: details.current_password || details.new_password ? '' : message })
    }
  }

  return (
    <>
      <h1>My profile</h1>
      <Card title="Account">
        <dl className="qp-profile">
          <div><dt>Email</dt><dd>{user.email}</dd></div>
          <div><dt>Role</dt><dd>{user.role}</dd></div>
          <div><dt>Member since</dt><dd>{fmtDate(user.created_at)}</dd></div>
        </dl>
        <form onSubmit={saveProfile} className="qp-form" noValidate>
          <label>Full name
            <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            {errors.name && <span className="qp-field-error">{errors.name}</span>}
          </label>
          <label>Phone (optional)
            <input type="tel" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} />
            {errors.phone && <span className="qp-field-error">{errors.phone}</span>}
          </label>
          <Button type="submit" disabled={busy}>Save changes</Button>
        </form>
      </Card>
      <Card title="Change password">
        <form onSubmit={savePassword} className="qp-form" noValidate>
          {pwErrors._ && <div className="qp-alert" role="alert">{pwErrors._}</div>}
          <label>Current password
            <input type="password" autoComplete="current-password" value={pw.current} onChange={(e) => setPw({ ...pw, current: e.target.value })} />
            {pwErrors.current && <span className="qp-field-error">{pwErrors.current}</span>}
          </label>
          <label>New password
            <input type="password" autoComplete="new-password" value={pw.next} onChange={(e) => setPw({ ...pw, next: e.target.value })} />
            {pwErrors.next && <span className="qp-field-error">{pwErrors.next}</span>}
          </label>
          <label>Confirm new password
            <input type="password" autoComplete="new-password" value={pw.confirm} onChange={(e) => setPw({ ...pw, confirm: e.target.value })} />
            {pwErrors.confirm && <span className="qp-field-error">{pwErrors.confirm}</span>}
          </label>
          <Button type="submit">Change password</Button>
        </form>
      </Card>
    </>
  )
}
