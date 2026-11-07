import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import {
  Activity, Bell, BarChart3, BrainCircuit, Clock, Cpu, Gauge, Home as HomeIcon, LayoutDashboard, FileDown, Layers, Lightbulb, LogIn, LogOut, Monitor,
  Settings, Ticket, User, UserPlus, Users,
} from 'lucide-react'
import { useAuth } from '../context/AuthContext.jsx'
import { useNotifications } from '../context/NotificationContext.jsx'
import { roleHome } from '../utils/roles.js'

const icon = (Cmp) => <Cmp size={18} aria-hidden="true" />

export default function AppLayout() {
  const { user, logout } = useAuth()
  const { unread } = useNotifications()
  const navigate = useNavigate()

  const onLogout = async () => {
    await logout()
    navigate('/login')
  }

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
          <NavLink to="/" end className="qp-nav">{icon(HomeIcon)} Home</NavLink>
          {!user && (
            <>
              <NavLink to="/login" className="qp-nav">{icon(LogIn)} Log in</NavLink>
              <NavLink to="/register" className="qp-nav">{icon(UserPlus)} Register</NavLink>
            </>
          )}
          {user && <NavLink to={roleHome(user.role)} end className="qp-nav">{icon(LayoutDashboard)} Dashboard</NavLink>}
          {user?.role === 'CUSTOMER' && (
            <>
              <NavLink to="/customer/services" className="qp-nav">{icon(Ticket)} Services</NavLink>
              <NavLink to="/customer/history" className="qp-nav">{icon(Clock)} History</NavLink>
              <NavLink to="/customer/notifications" className="qp-nav">
                {icon(Bell)} Notifications
                {unread > 0 && <span className="qp-count" aria-label={`${unread} unread notifications`}>{unread}</span>}
              </NavLink>
              <NavLink to="/customer/profile" className="qp-nav">{icon(User)} Profile</NavLink>
            </>
          )}
          {user?.role === 'ADMIN' && (
            <>
              <NavLink to="/admin/queue" className="qp-nav">{icon(Activity)} Live queue</NavLink>
              <NavLink to="/admin/analytics" className="qp-nav">{icon(BarChart3)} Analytics</NavLink>
              <NavLink to="/admin/recommendations" className="qp-nav">{icon(Lightbulb)} Recommendations</NavLink>
              <NavLink to="/admin/reports" className="qp-nav">{icon(FileDown)} Reports</NavLink>
              <NavLink to="/admin/services" className="qp-nav">{icon(Layers)} Services</NavLink>
              <NavLink to="/admin/counters" className="qp-nav">{icon(Monitor)} Counters</NavLink>
              <NavLink to="/admin/users" className="qp-nav">{icon(Users)} Users</NavLink>
              <NavLink to="/admin/ml" end className="qp-nav">{icon(BrainCircuit)} ML models</NavLink>
              <NavLink to="/admin/ml/training" className="qp-nav">{icon(Cpu)} ML training</NavLink>
              <NavLink to="/admin/settings" className="qp-nav">{icon(Settings)} Settings</NavLink>
            </>
          )}
        </nav>
        {user && (
          <div className="qp-userbox">
            <div><strong>{user.name}</strong><small>{user.role}</small></div>
            <button className="qp-nav qp-nav--button" onClick={onLogout}>{icon(LogOut)} Log out</button>
          </div>
        )}
      </aside>
      <div className="qp-main">
        <header className="qp-topbar"><span>Machine Learning-Based Smart Queue Management</span></header>
        <main className="qp-content"><Outlet /></main>
      </div>
    </div>
  )
}
