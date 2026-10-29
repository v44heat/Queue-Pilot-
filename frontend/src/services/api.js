import axios from 'axios'

// Empty base URL => same-origin requests, handled by the Vite dev proxy.
const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '',
  timeout: 10000,
})

export const getHealth = () => api.get('/api/health').then((r) => r.data)
export const getDbHealth = () => api.get('/api/health/db').then((r) => r.data)

export default api
