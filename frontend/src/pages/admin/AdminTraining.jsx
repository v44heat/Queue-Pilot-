import { useState } from 'react'
import { Link } from 'react-router-dom'
import ModelTable from '../../components/ModelTable.jsx'
import Button from '../../components/ui/Button.jsx'
import Card from '../../components/ui/Card.jsx'
import { useToast } from '../../context/ToastContext.jsx'
import { mlTrain } from '../../services/api.js'
import { apiError } from '../../utils/errors.js'

export default function AdminTraining() {
  const toast = useToast()
  const [form, setForm] = useState({ source: 'synthetic', rows: 6000, seed: 42, activate_best: false })
  const [errors, setErrors] = useState({})
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState(null)

  const submit = async (e) => {
    e.preventDefault()
    setErrors({})
    setResult(null)
    setBusy(true)
    try {
      const payload = { source: form.source, seed: Number(form.seed), activate_best: form.activate_best }
      if (form.source !== 'historical') payload.rows = Number(form.rows)
      const d = await mlTrain(payload)
      setResult(d.models)
      toast.success('Training finished.')
    } catch (err) {
      const { message, details } = apiError(err)
      setErrors({ ...details, _: message })
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <h1>ML training</h1>
      <p className="qp-muted">Trains Linear Regression, Random Forest and Gradient Boosting, then compares them on days they never saw.</p>
      <Card title="Train new models">
        <form onSubmit={submit} className="qp-form" noValidate>
          {errors._ && <div className="qp-alert" role="alert">{errors._}</div>}
          <label>Training data
            <select value={form.source} onChange={(e) => setForm({ ...form, source: e.target.value })}>
              <option value="synthetic">Synthetic (generated, for development and demonstration)</option>
              <option value="historical">Historical (this system&rsquo;s completed tickets)</option>
              <option value="mixed">Mixed (synthetic + historical)</option>
            </select>
          </label>
          {form.source !== 'historical' && (
            <label>Synthetic rows (500 to 50,000)
              <input type="number" min={500} max={50000} value={form.rows} onChange={(e) => setForm({ ...form, rows: e.target.value })} />
              {errors.rows && <span className="qp-field-error">{errors.rows}</span>}
            </label>
          )}
          <label>Random seed
            <input type="number" min={0} value={form.seed} onChange={(e) => setForm({ ...form, seed: e.target.value })} />
            {errors.seed && <span className="qp-field-error">{errors.seed}</span>}
          </label>
          <label className="qp-check"><input type="checkbox" checked={form.activate_best} onChange={(e) => setForm({ ...form, activate_best: e.target.checked })} /> Activate the selected model afterwards</label>
          <p className="qp-muted qp-small">Synthetic scores demonstrate that the pipeline works; they say nothing about real-world accuracy. Historical training needs at least 200 completed tickets over 5 days.</p>
          <Button type="submit" disabled={busy}>{busy ? 'Training… this can take up to a minute' : 'Start training'}</Button>
        </form>
      </Card>
      {result && (
        <Card title="Results" action={<Link to="/admin/ml">Open model comparison</Link>}>
          <ModelTable models={result} />
          <p className="qp-muted qp-small">The model marked Selected had the lowest validation MAE among eligible models. Activate a model from the comparison page.</p>
        </Card>
      )}
    </>
  )
}
