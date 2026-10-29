import { RefreshCw } from 'lucide-react'
import Button from '../components/ui/Button.jsx'
import Card from '../components/ui/Card.jsx'
import StatusBadge from '../components/ui/StatusBadge.jsx'
import useHealth from '../hooks/useHealth.js'

export default function Home() {
  const { api, db, refresh } = useHealth()

  return (
    <>
      <h1>Welcome to QueuePilot</h1>
      <p className="qp-muted">
        Foundation build. Queue features arrive in later phases; below is the live system status.
      </p>
      <Card
        title="System status"
        action={
          <Button variant="ghost" onClick={refresh} aria-label="Refresh status">
            <RefreshCw size={16} aria-hidden="true" /> Refresh
          </Button>
        }
      >
        <ul className="qp-status-list">
          <li>
            <span>API server</span>
            <StatusBadge status={api.status} />
          </li>
          <li>
            <span>PostgreSQL database</span>
            <StatusBadge status={db.status} />
          </li>
        </ul>
      </Card>
    </>
  )
}
