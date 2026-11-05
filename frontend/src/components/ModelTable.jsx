import Button from './ui/Button.jsx'

const n = (v, d = 3) => (v == null ? '-' : Number(v).toFixed(d))

// Held-out metrics for each trained model of one run, plus the rule-based baseline for comparison.
export default function ModelTable({ models, onActivate, busy }) {
  const baseline = models[0]?.baseline
  return (
    <div className="qp-table-wrap">
      <table className="qp-table">
        <thead>
          <tr><th>Model</th><th>Ver.</th><th>Val MAE</th><th>Test MAE</th><th>Test RMSE</th><th>Test R²</th><th>Status</th>{onActivate && <th />}</tr>
        </thead>
        <tbody>
          {models.map((m) => (
            <tr key={m.id} className={m.is_active ? 'is-active-row' : ''}>
              <td>{m.model_name}</td>
              <td>{m.version}</td>
              <td>{n(m.validation?.mae)}</td>
              <td>{n(m.mae)}</td>
              <td>{n(m.rmse)}</td>
              <td>{n(m.r2)}</td>
              <td>
                {m.is_active && <span className="qp-badge qp-status qp-status--completed">Active</span>}{' '}
                {m.selected_in_run && <span className="qp-badge qp-status qp-status--waiting">Selected</span>}{' '}
                {!m.eligible && <span className="qp-badge qp-status qp-status--cancelled">Ineligible</span>}
              </td>
              {onActivate && (
                <td>
                  <Button variant="ghost" disabled={busy || m.is_active || !m.eligible} onClick={() => onActivate(m)}
                    aria-label={`Activate ${m.model_name} ${m.version}`}>Activate</Button>
                </td>
              )}
            </tr>
          ))}
          {baseline && (
            <tr className="qp-baseline-row">
              <td>Rule-based baseline</td><td>-</td><td>{n(baseline.validation?.mae)}</td><td>{n(baseline.test?.mae)}</td>
              <td>{n(baseline.test?.rmse)}</td><td>{n(baseline.test?.r2)}</td><td>Not a trained model</td>{onActivate && <td />}
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}
