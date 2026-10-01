/** Capture only the rendered scene, composited onto its displayed background. */
export function mountViewerScreenshot({ parent, viewer, canvas, document: doc = document, download = blob => {
  const url = URL.createObjectURL(blob), a = doc.createElement('a')
  a.href = url; a.download = 'NADOC-view.png'; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000)
} }) {
  const button = doc.createElement('button'); button.type = 'button'; button.dataset.screenshot = ''; button.textContent = 'Screenshot'
  button.title = 'Save the current 3D view as a PNG without interface elements'
  const status = doc.createElement('span'); status.setAttribute('role', 'status')
  parent.append(button, status)
  let disposed = false
  button.onclick = async () => {
    if (!viewer.current || button.disabled) return
    button.disabled = true; status.textContent = ''
    try {
      const output = doc.createElement('canvas'); output.width = canvas.width; output.height = canvas.height
      const ctx = output.getContext('2d')
      ctx.fillStyle = viewer.current.data.background || '#161b22'; ctx.fillRect(0, 0, output.width, output.height)
      // Render and copy in one synchronous turn: WebGL may clear its buffer later.
      viewer.runtime.renderNow(); ctx.drawImage(canvas, 0, 0)
      const blob = await new Promise((resolve, reject) => output.toBlob(value => value ? resolve(value) : reject(new Error('Could not create screenshot')), 'image/png'))
      if (!disposed) download(blob)
    } catch (error) { if (!disposed) status.textContent = error.message }
    finally { if (!disposed) button.disabled = false }
  }
  return { dispose() { disposed = true; button.remove(); status.remove() } }
}
