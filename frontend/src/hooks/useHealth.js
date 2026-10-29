import { useCallback, useEffect, useState } from 'react'
import { getDbHealth, getHealth } from '../services/api.js'

// status: 'loading' | 'ok' | 'error'
export default function useHealth() {
  const [api, setApi] = useState({ status: 'loading' })
  const [db, setDb] = useState({ status: 'loading' })

  const check = useCallback(async () => {
    setApi({ status: 'loading' })
    setDb({ status: 'loading' })
    try {
      const data = await getHealth()
      setApi({ status: 'ok', data })
    } catch {
      setApi({ status: 'error' })
    }
    try {
      const data = await getDbHealth()
      setDb({ status: 'ok', data })
    } catch {
      setDb({ status: 'error' })
    }
  }, [])

  useEffect(() => {
    check()
  }, [check])

  return { api, db, refresh: check }
}
