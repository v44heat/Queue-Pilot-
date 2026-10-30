import Card from '../components/ui/Card.jsx'
import { useAuth } from '../context/AuthContext.jsx'

// Honest placeholders: these dashboards are built in later phases.
export default function RoleHome({ title, note }) {
  const { user } = useAuth()
  return (
    <>
      <h1>{title}</h1>
      <p className="qp-muted">Signed in as {user.name} ({user.role}).</p>
      <Card title="Coming soon"><p>{note}</p></Card>
    </>
  )
}
