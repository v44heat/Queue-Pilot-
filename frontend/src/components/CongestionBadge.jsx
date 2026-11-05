export default function CongestionBadge({ level }) {
  return <span className={`qp-badge qp-level qp-level--${level.toLowerCase()}`}>{level}</span>
}
