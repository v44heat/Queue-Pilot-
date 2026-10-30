// Access token persistence. localStorage trade-off is documented in the README.
const KEY = 'qp_token'

export const tokenStore = {
  get() {
    try { return localStorage.getItem(KEY) } catch { return null }
  },
  set(token) {
    try { localStorage.setItem(KEY, token) } catch { /* storage unavailable */ }
  },
  clear() {
    try { localStorage.removeItem(KEY) } catch { /* storage unavailable */ }
  },
}
