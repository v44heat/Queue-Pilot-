import { useEffect, useRef } from 'react'

// Calls fn every `ms` while enabled (skipped while the browser tab is hidden).
export default function usePolling(fn, ms, enabled = true) {
  const ref = useRef(fn)
  useEffect(() => { ref.current = fn })
  useEffect(() => {
    if (!enabled) return undefined
    const id = setInterval(() => { if (!document.hidden) ref.current() }, ms)
    return () => clearInterval(id)
  }, [ms, enabled])
}
