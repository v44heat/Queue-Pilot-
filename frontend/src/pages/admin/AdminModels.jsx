import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import ModelTable from '../../components/ModelTable.jsx'
import Pager from '../../components/Pager.jsx'
import Card from '../../components/ui/Card.jsx'
import ConfirmDialog from '../../components/ui/ConfirmDialog.jsx'
import { useToast } from '../../context/ToastContext.jsx'
import { mlActivate, mlListModels, mlPerformance, mlPredictionLogs } from '../../services/api.js'
import { apiError } from '../../utils/errors.js'
import { fmtDateTime } from '../../utils/format.js'

const n = (v) => (v == null ? '-' : Number(v).toFixed(2))

export default function AdminModels() {
  const toast = useToast()
  const [models, setModels] = useState(null)
  const [perf, setPerf] = useState(null)
  const [logs, setLogs] = useState(null)
  const [logPage, setLogPage] = useState(1)
  const [onlyMeasured, setOnlyMeasured] = useState(true)
  const [error, setError] = useState('')
  const [confirm, setConfirm] = useState(null)
  const [busy, setBusy] = useState(false)

  const loadModels = useCallback(async () => {
    try { setModels((await mlListModels()).models); setPerf(await mlPerformance()); setError('') } catch (e) { setError(apiError(e).message) }
  }, [])
  const loadLogs = useCallback(async () => {
    try {
      const params = { page: logPage, per_page: 10 }
      if (onlyMeasured) params.with_actual = 'true'
      setLogs(await mlPredictionLogs(params))
    } catch (e) { setError(apiError(e).message) }
  }, [logPage, onlyMeasured])
  useEffect(() => { loadModels() }, [loadModels])
  useEffect(() => { loadLogs() }, [loadLogs])

  const runs = useMemo(() => {
    const byRun = new Map()
    for (const m of models || []) byRun.set(m.run_id, [...(byRun.get(m.run_id) || []), m])
    return [...byRun.values()]
  }, [models])

  const activate = async () => {
    setBusy(true)
    try {
      await mlActivate(confirm.id)
      toast.success(`${confirm.model_name} ${confirm.version} is now active.`)
      await loadModels()
    } catch (e) { setError(apiError(e).message) } finally { setBusy(false); setConfirm(null) }
  }

  const active = (models || []).find((m) => m.is_active)
  const synthetic = (models || []).some((m) => m.data_source === 'synthetic')

  return (
    <>
      <h1>ML model comparison</h1>
      <p className="qp-muted">Metrics are measured on held-out days no model was trained or selected on. Lower MAE and RMSE (minutes) are better; R² closer to 1 is better.</p>
      {error && <div className="qp-alert" role="alert">{error}</div>}
      {synthetic && <div className="qp-note">Some models were trained on <strong>synthetic</strong> data: their scores demonstrate the pipeline, not real-world accuracy.</div>}

      <Card title="Active model" action={<Link to="/admin/ml/training">Train new models</Link>}>
        {!models ? <p className="qp-muted">Loading…</p> : active
          ? <p><strong>{active.model_name} {active.version}</strong> serves predictions (trained {fmtDateTime(active.training_date)} on {active.data_source} data).</p>
          : <p className="qp-muted">No model is active. Predictions use the basic rule-based estimate until you activate one.</p>}
      </Card>

      {models && runs.length === 0 && <Card title="Trained models"><p className="qp-muted">No models trained yet. Use <Link to="/admin/ml/training">ML training</Link> to create some.</p></Card>}
      {runs.slice(0, 3).map((run) => {
        const d = run[0]
        return (
          <Card key={d.run_id} title={`Run ${fmtDateTime(d.training_date)} · ${d.data_source} · ${d.rows} usable rows`}>
            <p className="qp-muted qp-small">{d.split?.strategy}: {d.split?.n_train} train / {d.split?.n_validation} validation / {d.split?.n_test} test.</p>
            <ModelTable models={run} busy={busy} onActivate={setConfirm} />
          </Card>
        )
      })}
      {runs.length > 3 && <p className="qp-muted">Showing the 3 most recent of {runs.length} training runs.</p>}

      <Card title="Live accuracy of predictions made by the system">
        {!perf || perf.groups.length === 0 ? (
          <p className="qp-muted">No measured outcomes yet. Accuracy appears here once customers whose waiting time was predicted have started service. {perf ? `${perf.predictions_awaiting_outcome} prediction(s) are awaiting an outcome.` : ''}</p>
        ) : (
          <div className="qp-table-wrap">
            <table className="qp-table">
              <thead><tr><th>Source</th><th>Model</th><th>Predictions measured</th><th>MAE (min)</th><th>RMSE (min)</th><th>R²</th></tr></thead>
              <tbody>
                {perf.groups.map((g) => (
                  <tr key={`${g.source}-${g.model_version_id}`}><td>{g.source}</td><td>{g.model ?? '-'}</td><td>{g.n}</td><td>{n(g.mae)}</td><td>{n(g.rmse)}</td><td>{n(g.r2)}</td></tr>
                ))}
              </tbody>
            </table>
            <p className="qp-muted qp-small">MAE and RMSE appear from the first measured prediction; R² needs at least 10. {perf.predictions_awaiting_outcome} still awaiting an outcome.</p>
          </div>
        )}
      </Card>

      <Card title="Prediction errors" action={
        <label className="qp-check"><input type="checkbox" checked={onlyMeasured} onChange={(e) => { setOnlyMeasured(e.target.checked); setLogPage(1) }} /> Only measured outcomes</label>}>
        {!logs ? <p className="qp-muted">Loading…</p> : logs.logs.length === 0 ? <p className="qp-muted">No predictions to show.</p> : (
          <div className="qp-table-wrap">
            <table className="qp-table">
              <thead><tr><th>Ticket</th><th>Source</th><th>Predicted</th><th>Actual</th><th>Error (pred. − actual)</th><th>When</th></tr></thead>
              <tbody>
                {logs.logs.map((l) => (
                  <tr key={l.id}>
                    <td>{l.queue_number}</td><td>{l.model ?? l.source}</td><td>{n(l.prediction)} min</td>
                    <td>{l.actual_value == null ? 'pending' : `${n(l.actual_value)} min`}</td>
                    <td>{l.prediction_error == null ? '-' : `${l.prediction_error > 0 ? '+' : ''}${n(l.prediction_error)}`}</td>
                    <td>{fmtDateTime(l.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <Pager page={logPage} pages={logs?.pages} onChange={setLogPage} />
      </Card>

      <ConfirmDialog open={Boolean(confirm)} busy={busy} onConfirm={activate} onCancel={() => setConfirm(null)}
        title={`Activate ${confirm?.model_name} ${confirm?.version}?`}
        message="New predictions for customers will use this model immediately. Existing predictions are not changed."
        confirmLabel="Activate" cancelLabel="Cancel" />
    </>
  )
}
