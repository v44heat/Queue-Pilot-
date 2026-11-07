// Normalise an Axios error into { message, details }.
export function apiError(err) {
  const data = err?.response?.data
  if (data?.message) return { message: data.message, details: data.details || {}, status: err.response.status }
  if (err?.code === 'ECONNABORTED' || !err?.response) {
    return { message: 'Cannot reach the server. Please try again.', details: {}, status: 0 }
  }
  return { message: 'Something went wrong. Please try again.', details: {}, status: err.response.status }
}

// Blob.text() is missing in older browsers (and in jsdom), so fall back to FileReader.
const blobText = (blob) => (typeof blob.text === 'function' ? blob.text() : new Promise((resolve, reject) => {
  const reader = new FileReader()
  reader.onload = () => resolve(reader.result)
  reader.onerror = () => reject(reader.error)
  reader.readAsText(blob)
}))

// A failed blob download carries its JSON error body as a Blob; turn it back into a normal error shape.
export async function readBlobError(err) {
  const body = err?.response?.data
  if (body instanceof Blob) {
    try {
      err.response.data = JSON.parse(await blobText(body))
    } catch { /* not JSON: keep the generic message */ }
  }
  return err
}
