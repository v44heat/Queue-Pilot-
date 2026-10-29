import { NavLink, Outlet } from 'react-router-dom'
import { Gauge, Home as HomeIcon } from 'lucide-react'

export default function AppLayout() {
  return (
    <div className="qp-shell">
      <aside className="qp-sidebar" aria-label="Main navigation">
        <div className="qp-brand">
          <Gauge size={26} aria-hidden="true" />
          <div>
            <strong>QueuePilot</strong>
            <small>Smarter Queues. Less Waiting.</small>
          </div>
        </div>
        <nav>
          <NavLink to="/" end className="qp-nav">
            <HomeIcon size={18} aria-hidden="true" /> Home
          </NavLink>
        </nav>
      </aside>
      <div className="qp-main">
        <header className="qp-topbar">
          <span>Machine Learning-Based Smart Queue Management</span>
        </header>
        <main className="qp-content">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
