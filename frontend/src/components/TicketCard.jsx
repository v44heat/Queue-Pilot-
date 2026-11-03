import { Link } from 'react-router-dom'
import { STATUS_LABEL, estimateInfo } from '../utils/format.js'
import ProgressSteps from './ProgressSteps.jsx'

// The digital ticket. Every value comes from the backend ticket object.
export default function TicketCard({ ticket, to }) {
  const est = estimateInfo(ticket)
  const waiting = ticket.status === 'WAITING'
  return (
    <article className={`qp-ticket qp-ticket--${ticket.status.toLowerCase()}`} aria-label={`Ticket ${ticket.queue_number}`}>
      <div className="qp-ticket__label">QUEUE NUMBER</div>
      <div className="qp-ticket__number">{to ? <Link to={to}>{ticket.queue_number}</Link> : ticket.queue_number}</div>
      <dl className="qp-ticket__grid">
        <div><dt>SERVICE</dt><dd>{ticket.service.name}</dd></div>
        <div><dt>STATUS</dt><dd><span className={`qp-badge qp-status qp-status--${ticket.status.toLowerCase()}`}>{STATUS_LABEL[ticket.status] || ticket.status}</span></dd></div>
        {waiting && <div><dt>PEOPLE AHEAD</dt><dd>{ticket.people_ahead}</dd></div>}
        {waiting && <div><dt>POSITION</dt><dd>{ticket.position}</dd></div>}
        {ticket.counter && ticket.status !== 'WAITING' && <div><dt>COUNTER</dt><dd>{ticket.counter.name}</dd></div>}
        <div className="qp-ticket__wide"><dt>{ticket.status === 'COMPLETED' ? 'WAITED' : 'ESTIMATED WAIT'}</dt><dd>{est.value}</dd>{est.note && <small>{est.note}</small>}</div>
      </dl>
      <ProgressSteps status={ticket.status} />
    </article>
  )
}
