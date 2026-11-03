import { Routes, Route } from 'react-router-dom'
import ProtectedRoute from './components/ProtectedRoute.jsx'
import { AuthProvider } from './context/AuthContext.jsx'
import { NotificationProvider } from './context/NotificationContext.jsx'
import { ToastProvider } from './context/ToastContext.jsx'
import AppLayout from './layouts/AppLayout.jsx'
import AdminUsers from './pages/AdminUsers.jsx'
import Home from './pages/Home.jsx'
import Login from './pages/Login.jsx'
import NotFound from './pages/NotFound.jsx'
import Register from './pages/Register.jsx'
import RoleHome from './pages/RoleHome.jsx'
import StaffDashboard from './pages/StaffDashboard.jsx'
import CustomerDashboard from './pages/customer/CustomerDashboard.jsx'
import History from './pages/customer/History.jsx'
import Notifications from './pages/customer/Notifications.jsx'
import Profile from './pages/customer/Profile.jsx'
import Services from './pages/customer/Services.jsx'
import TicketPage from './pages/customer/TicketPage.jsx'

const customer = (el) => <ProtectedRoute roles={['CUSTOMER']}>{el}</ProtectedRoute>

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
              <Route path="admin" element={
                <ProtectedRoute roles={['ADMIN']}>
                  <RoleHome title="Admin dashboard" note="Analytics and monitoring arrive in Phases 7 and 8. User management is available now under Users." />
                </ProtectedRoute>} />
              <Route path="admin/users" element={
                <ProtectedRoute roles={['ADMIN']}><AdminUsers /></ProtectedRoute>} />
              <Route path="*" element={<NotFound />} />
            </Route>
          </Routes>
        </NotificationProvider>
      </ToastProvider>
    </AuthProvider>
  )
}
