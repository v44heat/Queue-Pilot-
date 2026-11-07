import { lazy, Suspense } from 'react'
import { Routes, Route } from 'react-router-dom'
import ProtectedRoute from './components/ProtectedRoute.jsx'
import { AuthProvider } from './context/AuthContext.jsx'
import { NotificationProvider } from './context/NotificationContext.jsx'
import { ToastProvider } from './context/ToastContext.jsx'
import AppLayout from './layouts/AppLayout.jsx'
import AdminUsers from './pages/AdminUsers.jsx'
import AdminCounters from './pages/admin/AdminCounters.jsx'
import AdminDashboard from './pages/admin/AdminDashboard.jsx'
import AdminModels from './pages/admin/AdminModels.jsx'
import AdminRecommendations from './pages/admin/AdminRecommendations.jsx'
import AdminReports from './pages/admin/AdminReports.jsx'
import AdminServices from './pages/admin/AdminServices.jsx'
import AdminSettings from './pages/admin/AdminSettings.jsx'
import AdminTraining from './pages/admin/AdminTraining.jsx'
import LiveQueue from './pages/admin/LiveQueue.jsx'
import Home from './pages/Home.jsx'
import Login from './pages/Login.jsx'
import NotFound from './pages/NotFound.jsx'
import Register from './pages/Register.jsx'
import StaffDashboard from './pages/StaffDashboard.jsx'
import CustomerDashboard from './pages/customer/CustomerDashboard.jsx'
import History from './pages/customer/History.jsx'
import Notifications from './pages/customer/Notifications.jsx'
import Profile from './pages/customer/Profile.jsx'
import Services from './pages/customer/Services.jsx'
import TicketPage from './pages/customer/TicketPage.jsx'

// The charting library is large and only administrators use it, so load it on demand.
const AdminAnalytics = lazy(() => import('./pages/admin/AdminAnalytics.jsx'))

const customer = (el) => <ProtectedRoute roles={['CUSTOMER']}>{el}</ProtectedRoute>
const admin = (el) => <ProtectedRoute roles={['ADMIN']}>{el}</ProtectedRoute>

export default function App() {
  return (
    <AuthProvider>
      <ToastProvider>
        <NotificationProvider>
          <Routes>
            <Route element={<AppLayout />}>
              <Route index element={<Home />} />
              <Route path="login" element={<Login />} />
              <Route path="register" element={<Register />} />
              <Route path="customer" element={customer(<CustomerDashboard />)} />
              <Route path="customer/services" element={customer(<Services />)} />
              <Route path="customer/tickets/:id" element={customer(<TicketPage />)} />
              <Route path="customer/history" element={customer(<History />)} />
              <Route path="customer/notifications" element={customer(<Notifications />)} />
              <Route path="customer/profile" element={customer(<Profile />)} />
              <Route path="staff" element={
                <ProtectedRoute roles={['STAFF']}><StaffDashboard /></ProtectedRoute>} />
              <Route path="admin" element={admin(<AdminDashboard />)} />
              <Route path="admin/queue" element={admin(<LiveQueue />)} />
              <Route path="admin/analytics" element={admin(<Suspense fallback={<p className="qp-muted">Loading…</p>}><AdminAnalytics /></Suspense>)} />
              <Route path="admin/recommendations" element={admin(<AdminRecommendations />)} />
              <Route path="admin/reports" element={admin(<AdminReports />)} />
              <Route path="admin/services" element={admin(<AdminServices />)} />
              <Route path="admin/counters" element={admin(<AdminCounters />)} />
              <Route path="admin/users" element={admin(<AdminUsers />)} />
              <Route path="admin/ml" element={admin(<AdminModels />)} />
              <Route path="admin/ml/training" element={admin(<AdminTraining />)} />
              <Route path="admin/settings" element={admin(<AdminSettings />)} />
              <Route path="*" element={<NotFound />} />
            </Route>
          </Routes>
        </NotificationProvider>
      </ToastProvider>
    </AuthProvider>
  )
}
