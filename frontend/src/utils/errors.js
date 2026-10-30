// Normalise an Axios error into { message, details }.
export function apiError(err) {
  const data = err?.response?.data
  if (data?.message) return { message: data.message, details: data.details || {}, status: err.response.status }
  if (err?.code === 'ECONNABORTED' || !err?.response) {
    return { message: 'Cannot reach the server. Please try again.', details: {}, status: 0 }
  }
  return { message: 'Something went wrong. Please try again.', details: {}, status: err.response.status }
}
