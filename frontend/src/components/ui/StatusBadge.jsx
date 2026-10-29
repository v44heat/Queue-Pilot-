const LABELS = { ok: 'Online', error: 'Unavailable', loading: 'Checking…' }

export default function StatusBadge({ status }) {
  return (
    <span className={`qp-badge qp-badge--${status}`} role="status">
      <span className="qp-badge__dot" aria-hidden="true" />
      {LABELS[status] ?? status}
    </span>
  )
}
