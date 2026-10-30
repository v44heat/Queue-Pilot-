import { Link } from 'react-router-dom'

export default function Forbidden() {
  return (
    <>
      <h1>Access denied</h1>
      <p className="qp-muted">You do not have permission to view this page.</p>
      <Link to="/">Back to home</Link>
    </>
  )
}
