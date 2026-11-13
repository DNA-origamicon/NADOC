/** Await the real frame applied by Display MD, including wire-format reloads. */
export function scheduleMdRepresentationFrame(run, jobId, { timeout = 60000 } = {}) {
  return new Promise((resolve, reject) => {
    requestAnimationFrame(() => {
      const cleanup = () => { clearTimeout(timer); window.removeEventListener('nadoc:md-display-state', changed) }
      const changed = event => {
        const detail = event.detail ?? {}
        if (detail.jobId !== jobId) return
        if (detail.state === 'frame') { cleanup(); resolve() }
        else if (['error', 'off'].includes(detail.state)) { cleanup(); reject(new Error(detail.message || 'MD display stopped before the representation was ready')) }
      }
      const timer = setTimeout(() => { cleanup(); reject(new Error('Timed out waiting for the MD representation frame')) }, timeout)
      window.addEventListener('nadoc:md-display-state', changed)
      try { run() } catch (error) { cleanup(); reject(error) }
    })
  })
}
