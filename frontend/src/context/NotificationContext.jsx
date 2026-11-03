import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import usePolling from '../hooks/usePolling.js'
import { getUnreadCount } from '../services/api.js'
import { useAuth } from './AuthContext.jsx'
import { useToast } from './ToastContext.jsx'

const NotificationContext = createContext({ unread: 0, refresh: () => {} })
const POLL_MS = 15000

// Keeps the unread badge current for customers and announces genuinely new notifications.
export function NotificationProvider({ children }) {
  const { user } = useAuth()
  const toast = useToast()
  const [unread, setUnread] = useState(0)
  const seen = useRef(null) // null until the first successful load (no toast for pre-existing unread)
  const isCustomer = user?.role === 'CUSTOMER'

  const refresh = useCallback(async () => {
    try {
      const { unread: n } = await getUnreadCount()
      if (seen.current !== null && n > seen.current) toast.info(`You have ${n - seen.current} new notification${n - seen.current > 1 ? 's' : ''}.`)
      seen.current = n
      setUnread(n)
    } catch { /* keep the previous count; the next poll will retry */ }
  }, [toast])

  useEffect(() => {
    if (isCustomer) refresh()
    else { seen.current = null; setUnread(0) }
  }, [isCustomer, user?.id, refresh])

  usePolling(refresh, POLL_MS, isCustomer)

  const value = useMemo(() => ({ unread, refresh }), [unread, refresh])
  return <NotificationContext.Provider value={value}>{children}</NotificationContext.Provider>
}

export const useNotifications = () => useContext(NotificationContext)
