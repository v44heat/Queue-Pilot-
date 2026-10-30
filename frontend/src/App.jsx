import { Routes, Route } from 'react-router-dom'
import ProtectedRoute from './components/ProtectedRoute.jsx'
import { AuthProvider } from './context/AuthContext.jsx'
import AppLayout from './layouts/AppLayout.jsx'
import AdminUsers from './pages/AdminUsers.jsx'
import Home from './pages/Home.jsx'
import Login from './pages/Login.jsx'
import NotFound from './pages/NotFound.jsx'
import Register from './pages/Register.jsx'
import RoleHome from './pages/RoleHome.jsx'

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route element={<AppLayout />}>
          <Route index element={<Home />} />
          <Route path="login" element={<Login />} />
          <Route path="register" element={<Register />} />
          <Route path="customer" element={
            <ProtectedRoute roles={['CUSTOMER']}>
              <RoleHome title="Customer dashboard" note="Joining queues and live tracking arrive in Phases 3 and 6." />
            </ProtectedRoute>} />
          <Route path="staff" element={
            <ProtectedRoute roles={['STAFF']}>
              <RoleHome title="Staff dashboard" note="Counter and customer-calling workflows arrive in Phase 4." />
            </ProtectedRoute>} />
          <Route path="admin" element={
            <ProtectedRoute roles={['ADMIN']}>
              <RoleHome title="Admin dashboard" note="Analytics and monitoring arrive in Phases 7 and 8. User management is available now under Users." />
            </ProtectedRoute>} />
          <Route path="admin/users" element={
            <ProtectedRoute roles={['ADMIN']}><AdminUsers /></ProtectedRoute>} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </AuthProvider>
  )
}
