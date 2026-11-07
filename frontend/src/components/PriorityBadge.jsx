const LABEL = { URGENT: 'Urgent', HIGH: 'High priority', MEDIUM: 'Medium priority', NONE: 'No action' }

export default function PriorityBadge({ priority }) {
  return <span className={`qp-badge qp-priority qp-priority--${priority.toLowerCase()}`}>{LABEL[priority] ?? priority}</span>
}
