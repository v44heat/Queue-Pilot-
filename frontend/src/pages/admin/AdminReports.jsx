import { useState } from 'react'
import Button from '../../components/ui/Button.jsx'
import Card from '../../components/ui/Card.jsx'
import { useToast } from '../../context/ToastContext.jsx'
import { downloadReport } from '../../services/api.js'
import { saveBlob, todayLocal } from '../../utils/download.js'
import { apiError } from '../../utils/errors.js'

function ReportCard({ title, description, name, fields, initial = {}, toParams }) {
  const toast = useToast()
  const [values, setValues] = useState(initial)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const download = async () => {
    setBusy(true)
    setError('')
    try {
      const { blob, filename } = await downloadReport(name, toParams(values))
      saveBlob(blob, filename)
      toast.success(`Downloaded ${filename}`)
    } catch (e) {
      setError(apiError(e).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card title={title}>
      <p className="qp-muted">{description}</p>
      {error && <div className="qp-alert" role="alert">{error}</div>}
      <div className="qp-actions">
        {fields.map((f) => (
          <label key={f.key} className="qp-inline-label">{f.label}
            <input type={f.type} value={values[f.key] ?? ''} onChange={(e) => setValues({ ...values, [f.key]: e.target.value })} aria-label={`${title}: ${f.label}`} />
          </label>
        ))}
        <Button onClick={download} disabled={busy} aria-label={`Download ${title} CSV`}>{busy ? 'Preparing…' : 'Download CSV'}</Button>
      </div>
    </Card>
  )
}

export default function AdminReports() {
  const today = todayLocal()
  const monthStart = `${today.slice(0, 8)}01`
  const dateOnly = (v) => (v.date ? { date: v.date } : {})
  const range = (v) => ({ ...(v.from ? { from: v.from } : {}), ...(v.to ? { to: v.to } : {}) })
  return (
    <>
      <h1>Reports</h1>
      <p className="qp-muted">CSV files built from the same database figures as the analytics. Opens in Excel or any spreadsheet. Dates are local calendar days.</p>
      <ReportCard title="Daily report" name="daily" description="Per service for one day: tickets joined, completed, cancelled, skipped, absent, waiting and service times."
        fields={[{ key: 'date', label: 'Date', type: 'date' }]} initial={{ date: today }} toParams={dateOnly} />
      <ReportCard title="Weekly report" name="weekly" description="One row per day and service for the Monday-to-Sunday week that contains the date."
        fields={[{ key: 'date', label: 'Any date in the week', type: 'date' }]} initial={{ date: today }} toParams={dateOnly} />
      <ReportCard title="Monthly report" name="monthly" description="One row per day and service for the month."
        fields={[{ key: 'month', label: 'Month', type: 'month' }]} initial={{ month: today.slice(0, 7) }} toParams={(v) => (v.month ? { month: v.month } : {})} />
      <ReportCard title="Service performance" name="services" description="One row per service over a period (default: the last 30 days)."
        fields={[{ key: 'from', label: 'From', type: 'date' }, { key: 'to', label: 'To', type: 'date' }]} initial={{ from: monthStart, to: today }} toParams={range} />
      <ReportCard title="Counter performance" name="counters" description="Open time, serving time, utilization and customers served per counter."
        fields={[{ key: 'from', label: 'From', type: 'date' }, { key: 'to', label: 'To', type: 'date' }]} initial={{ from: monthStart, to: today }} toParams={range} />
      <ReportCard title="ML model performance" name="models" description="Every trained model with its held-out metrics and the baseline it was compared with."
        fields={[]} toParams={() => ({})} />
    </>
  )
}
