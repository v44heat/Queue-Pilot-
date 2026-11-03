const STEPS = ['WAITING', 'CALLED', 'SERVING', 'COMPLETED']
const LABELS = { WAITING: 'Waiting', CALLED: 'Called', SERVING: 'Serving', COMPLETED: 'Done' }

export default function ProgressSteps({ status }) {
  const index = STEPS.indexOf(status) // -1 for cancelled/skipped/absent
  if (index === -1) return null
  return (
    <ol className="qp-steps" aria-label="Queue progress">
      {STEPS.map((s, i) => (
        <li key={s} className={i < index ? 'is-done' : i === index ? 'is-current' : ''} aria-current={i === index ? 'step' : undefined}>
          <span className="qp-steps__dot">{i < index ? '✓' : i + 1}</span>{LABELS[s]}
        </li>
      ))}
    </ol>
  )
}
