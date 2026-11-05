import { useEffect, useState } from 'react'
import Button from '../../components/ui/Button.jsx'
import Card from '../../components/ui/Card.jsx'
import { useToast } from '../../context/ToastContext.jsx'
import { getSettings, updateSettings } from '../../services/api.js'
import { apiError } from '../../utils/errors.js'

export default function AdminSettings() {
  const toast = useToast()
  const [settings, setSettings] = useState(null)
  const [form, setForm] = useState({})
  const [resets, setResets] = useState({})
  const [errors, setErrors] = useState({})
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const adopt = (list) => { setSettings(list); setForm(Object.fromEntries(list.map((s) => [s.key, String(s.value)]))); setResets({}) }
  useEffect(() => { getSettings().then((d) => adopt(d.settings)).catch((e) => setError(apiError(e).message)) }, [])

  if (!settings) return error ? <div className="qp-alert" role="alert">{error}</div> : <p className="qp-muted">Loading…</p>

  const save = async (e) => {
    e.preventDefault()
    const changes = {}
    for (const s of settings) {
      if (resets[s.key]) { if (!s.is_default) changes[s.key] = null } else if (form[s.key].trim() === '' || Number(form[s.key]) !== s.value) {
        changes[s.key] = form[s.key].trim() === '' ? '' : Number(form[s.key])
      }
    }
    if (Object.keys(changes).length === 0) { toast.info('No changes to save.'); return }
    setErrors({})
    setError('')
    setBusy(true)
    try {
      adopt((await updateSettings(changes)).settings)
      toast.success('Settings saved.')
    } catch (err) {
      const { message, details } = apiError(err)
      setErrors(details)
      setError(message)
    } finally {
      setBusy(false)
    }
  }

  const groups = [...new Set(settings.map((s) => s.group))]
  return (
    <>
      <h1>System settings</h1>
      <p className="qp-muted">Changes apply immediately to dashboards and customer notifications. All changes are saved together or not at all.</p>
      {error && <div className="qp-alert" role="alert">{error}</div>}
      <form onSubmit={save} noValidate>
        {groups.map((g) => (
          <Card key={g} title={g}>
            <div className="qp-form">
              {settings.filter((s) => s.group === g).map((s) => (
                <div key={s.key} className="qp-setting">
                  <label>{s.label}
                    <input type="number" step={s.type === 'int' ? 1 : 'any'} value={resets[s.key] ? String(s.default) : form[s.key]}
                      onChange={(e) => { setForm({ ...form, [s.key]: e.target.value }); setResets({ ...resets, [s.key]: false }) }} />
                    {errors[s.key] && <span className="qp-field-error">{errors[s.key]}</span>}
                  </label>
                  <small className="qp-muted">{s.description} Default {s.default}; allowed {s.min} to {s.max}.</small>
                  <Button type="button" variant="ghost" disabled={s.is_default && !resets[s.key]} onClick={() => setResets({ ...resets, [s.key]: true })}
                    aria-label={`Reset ${s.label} to default`}>Reset to default</Button>
                </div>
              ))}
            </div>
          </Card>
        ))}
        <Button type="submit" disabled={busy}>{busy ? 'Saving…' : 'Save settings'}</Button>
      </form>
    </>
  )
}
