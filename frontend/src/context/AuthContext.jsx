import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { getMe, loginRequest, logoutRequest, registerRequest } from '../services/api.js'
import { tokenStore } from '../utils/tokenStore.js'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(() => Boolean(tokenStore.get()))

  // Restore the session from a stored token.
  useEffect(() => {
    if (!tokenStore.get()) return
    getMe()
      .then((d) => setUser(d.user))
      .catch(() => tokenStore.clear())
      .finally(() => setLoading(false))
  }, [])

  // Any 401 from a protected call (expired/revoked token) ends the session.
  useEffect(() => {
    const onUnauthorized = () => {
      tokenStore.clear()
      setUser(null)
    }
    window.addEventListener('qp:unauthorized', onUnauthorized)
    return () => window.removeEventListener('qp:unauthorized', onUnauthorized)
  }, [])

  const login = useCallback(async (email, password) => {
    const d = await loginRequest(email, password)
    tokenStore.set(d.access_token)
    setUser(d.user)
    return d.user
  }, [])

  const register = useCallback(async (payload) => {
    const d = await registerRequest(payload)
    tokenStore.set(d.access_token)
    setUser(d.user)
    return d.user
  }, [])

  const logout = useCallback(async () => {
    try { await logoutRequest() } catch { /* token may already be invalid */ }
    tokenStore.clear()
    setUser(null)
  }, [])

  const value = useMemo(() => ({ user, loading, login, register, logout }), [user, loading, login, register, logout])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>')
  return ctx
}
