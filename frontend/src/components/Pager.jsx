import Button from './ui/Button.jsx'

export default function Pager({ page, pages, onChange }) {
  const last = pages || 1
  return (
    <div className="qp-pager">
      <Button variant="ghost" disabled={page <= 1} onClick={() => onChange(page - 1)}>Previous</Button>
      <span>Page {page} of {last}</span>
      <Button variant="ghost" disabled={page >= last} onClick={() => onChange(page + 1)}>Next</Button>
    </div>
  )
}
