export default function StatCard({ label, value, hint }) {
  return (
    <div className="qp-stat">
      <span className="qp-stat__label">{label}</span>
      <strong className="qp-stat__value">{value}</strong>
      {hint && <small className="qp-muted">{hint}</small>}
    </div>
  )
}
