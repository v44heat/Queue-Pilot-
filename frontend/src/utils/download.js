// Save a Blob as a file in the browser.
export function saveBlob(blob, filename) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

// Local calendar date as YYYY-MM-DD (not the UTC date).
export const todayLocal = () => new Date().toLocaleDateString('en-CA')
