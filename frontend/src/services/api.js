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

export default api
