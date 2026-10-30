import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { Gauge, Home as HomeIcon, LogIn, LogOut, UserPlus, Users, LayoutDashboard } from 'lucide-react'
import { useAuth } from '../context/AuthContext.jsx'
import { roleHome } from '../utils/roles.js'

export default function AppLayout() {
  const { user, logout } = useAuth()
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
          <NavLink to="/" end className="qp-nav"><HomeIcon size={18} aria-hidden="true" /> Home</NavLink>
          {!user && (
            <>
              <NavLink to="/login" className="qp-nav"><LogIn size={18} aria-hidden="true" /> Log in</NavLink>
              <NavLink to="/register" className="qp-nav"><UserPlus size={18} aria-hidden="true" /> Register</NavLink>
            </>
          )}
          {user && (
            <NavLink to={roleHome(user.role)} end className="qp-nav">
              <LayoutDashboard size={18} aria-hidden="true" /> Dashboard
            </NavLink>
          )}
          {user?.role === 'ADMIN' && (
            <NavLink to="/admin/users" className="qp-nav"><Users size={18} aria-hidden="true" /> Users</NavLink>
          )}
        </nav>
        {user && (
          <div className="qp-userbox">
            <div><strong>{user.name}</strong><small>{user.role}</small></div>
            <button className="qp-nav qp-nav--button" onClick={onLogout}>
              <LogOut size={18} aria-hidden="true" /> Log out
            </button>
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
