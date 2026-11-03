export const fmtTime = (iso) => (iso ? new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '-')
export const fmtDateTime = (iso) => (iso ? new Date(iso).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }) : '-')
export const fmtDate = (iso) => (iso ? new Date(iso).toLocaleDateString([], { dateStyle: 'medium' }) : '-')
export const fmtMin = (m) => (m == null ? '-' : `${Math.round(m * 10) / 10} min`)

export const ACTIVE = ['WAITING', 'CALLED', 'SERVING']
export const STATUS_LABEL = {
  WAITING: 'Waiting', CALLED: 'Called', SERVING: 'Being served', COMPLETED: 'Completed',
  CANCELLED: 'Cancelled', SKIPPED: 'Skipped', ABSENT: 'Absent',
}

// What to show as the estimated wait, using only data the backend returned.
export function estimateInfo(ticket) {
  if (ticket.status === 'CALLED') return { value: 'Your turn', note: ticket.counter ? `Please go to ${ticket.counter.name}.` : 'Please go to the counter.' }
  if (ticket.status === 'SERVING') return { value: 'Being served', note: '' }
  if (ticket.status === 'COMPLETED') return { value: fmtMin(ticket.actual_waiting_time), note: 'You waited this long.' }
  if (ticket.status !== 'WAITING') return { value: '-', note: '' }
  const est = ticket.estimated_wait
  if (est && est.minutes != null) {
    const note = est.source === 'machine_learning' ? 'Estimated by the prediction model.' : 'Basic estimate (prediction model not active).'
    return { value: est.minutes < 0.5 ? 'No wait expected' : `${Math.round(est.minutes)} minutes`, note }
  }
  if (est && est.source === 'unavailable') return { value: 'Not available', note: 'No counter is open for this service yet.' }
  if (ticket.predicted_waiting_time != null) return { value: `${Math.round(ticket.predicted_waiting_time)} minutes`, note: 'Estimate made when you joined.' }
  return { value: 'Not available', note: '' }
}
