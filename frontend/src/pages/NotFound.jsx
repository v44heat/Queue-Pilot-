import { Link } from 'react-router-dom'

export default function NotFound() {
  return (
    <>
      <h1>Page not found</h1>
      <p className="qp-muted">The page you requested does not exist.</p>
      <Link to="/">Back to home</Link>
    </>
  )
}
