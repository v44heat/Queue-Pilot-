import axios from 'axios'
import { tokenStore } from '../utils/tokenStore.js'

// Empty base URL => same-origin requests, handled by the Vite dev proxy.
const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '',
  timeout: 10000,
})

api.interceptors.request.use((config) => {
  const token = tokenStore.get()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// An expired/revoked token on a protected call logs the user out client-side.
api.interceptors.response.use(
  (r) => r,
  (error) => {
    const url = error.config?.url || ''
    if (error.response?.status === 401 && !url.startsWith('/api/auth/login')) {
      window.dispatchEvent(new Event('qp:unauthorized'))
    }
    return Promise.reject(error)
  },
)

const data = (r) => r.data

export const getHealth = () => api.get('/api/health').then(data)
export const getDbHealth = () => api.get('/api/health/db').then(data)

export const loginRequest = (email, password) => api.post('/api/auth/login', { email, password }).then(data)
export const registerRequest = (payload) => api.post('/api/auth/register', payload).then(data)
export const logoutRequest = () => api.post('/api/auth/logout').then(data)
export const getMe = () => api.get('/api/auth/me').then(data)

export const listUsers = (params) => api.get('/api/users', { params }).then(data)
export const createUser = (payload) => api.post('/api/users', payload).then(data)
export const updateUser = (id, payload) => api.patch(`/api/users/${id}`, payload).then(data)

// ---- staff ----
export const getStaffCounters = () => api.get('/api/staff/counters').then(data)
export const getCounterQueue = (id) => api.get(`/api/staff/counters/${id}/queue`).then(data)
export const openCounter = (id) => api.post(`/api/staff/counters/${id}/open`).then(data)
export const closeCounter = (id) => api.post(`/api/staff/counters/${id}/close`).then(data)
export const callNext = (id) => api.post(`/api/staff/counters/${id}/call-next`).then(data)
// action: 'start' | 'complete' | 'skip' | 'absent'
export const ticketAction = (ticketId, action) => api.post(`/api/staff/tickets/${ticketId}/${action}`).then(data)

// ---- customer ----
export const getServices = () => api.get('/api/services').then(data)
export const joinQueue = (serviceId) => api.post('/api/queue/join', { service_id: serviceId }).then(data)
export const getMyActive = () => api.get('/api/queue/my-active').then(data)
export const getTicket = (id) => api.get(`/api/queue/tickets/${id}`).then(data)
export const cancelTicket = (id) => api.post(`/api/queue/tickets/${id}/cancel`).then(data)
export const getHistory = (params) => api.get('/api/queue/history', { params }).then(data)

// ---- notifications ----
export const getNotifications = (params) => api.get('/api/notifications', { params }).then(data)
export const getUnreadCount = () => api.get('/api/notifications/unread-count').then(data)
export const markNotificationRead = (id) => api.post(`/api/notifications/${id}/read`).then(data)
export const markAllNotificationsRead = () => api.post('/api/notifications/read-all').then(data)

// ---- profile ----
export const updateProfile = (payload) => api.patch('/api/auth/me', payload).then(data)
export const changePassword = (current_password, new_password) =>
  api.post('/api/auth/change-password', { current_password, new_password }).then(data)

// ---- admin ----
export const getAdminDashboard = () => api.get('/api/admin/dashboard').then(data)
export const getAdminQueue = (params) => api.get('/api/admin/queue', { params }).then(data)
export const adminListServices = () => api.get('/api/admin/services').then(data)
export const adminCreateService = (payload) => api.post('/api/admin/services', payload).then(data)
export const adminUpdateService = (id, payload) => api.patch(`/api/admin/services/${id}`, payload).then(data)
export const adminListCounters = () => api.get('/api/counters').then(data)
export const adminCreateCounter = (payload) => api.post('/api/counters', payload).then(data)
export const adminUpdateCounter = (id, payload) => api.patch(`/api/counters/${id}`, payload).then(data)
export const adminAssignStaff = (counterId, staffId) => api.post(`/api/counters/${counterId}/staff`, { staff_id: staffId }).then(data)
export const adminUnassignStaff = (counterId, staffId) => api.delete(`/api/counters/${counterId}/staff/${staffId}`).then(data)
export const getSettings = () => api.get('/api/settings').then(data)
export const updateSettings = (settings) => api.patch('/api/settings', { settings }).then(data)

// ---- machine learning (admin) ----
export const mlListModels = () => api.get('/api/ml/models').then(data)
export const mlTrain = (payload) => api.post('/api/ml/train', payload, { timeout: 180000 }).then(data)
export const mlActivate = (id) => api.post(`/api/ml/models/${id}/activate`).then(data)
export const mlPerformance = () => api.get('/api/ml/performance').then(data)
export const mlPredictionLogs = (params) => api.get('/api/ml/prediction-logs', { params }).then(data)

export default api
