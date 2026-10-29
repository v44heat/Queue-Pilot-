export default function Card({ title, action, children, className = '' }) {
  return (
    <section className={`qp-card ${className}`}>
      {(title || action) && (
        <header className="qp-card__header">
          <h2>{title}</h2>
          {action}
        </header>
      )}
      <div className="qp-card__body">{children}</div>
    </section>
  )
}
