import Card from './ui/Card.jsx'

// A chart plus the same numbers as a table (for screen readers, keyboard users and exact values).
export default function ChartCard({ title, note, columns, rows, empty, children }) {
  return (
    <Card title={title}>
      {note && <p className="qp-muted qp-small">{note}</p>}
      {empty ? <p className="qp-muted">{empty}</p> : (
        <>
          <div className="qp-chart" role="img" aria-label={`${title} chart`}>{children}</div>
          <details className="qp-data">
            <summary>View data table</summary>
            <div className="qp-table-wrap">
              <table className="qp-table" aria-label={`${title} data`}>
                <thead><tr>{columns.map((c) => <th key={c.key}>{c.label}</th>)}</tr></thead>
                <tbody>
                  {rows.map((r, i) => (
                    <tr key={i}>{columns.map((c) => <td key={c.key}>{c.render ? c.render(r) : (r[c.key] ?? '-')}</td>)}</tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        </>
      )}
    </Card>
  )
}
