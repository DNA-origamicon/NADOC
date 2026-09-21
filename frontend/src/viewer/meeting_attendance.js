/** Presenter presence is independent of the lifetime of the shared snapshot. */
export function mountPresenterAttendance({ viewer, base, resume, mount, document: doc = document, fetch: request = fetch }) {
  const bar = doc.createElement('div')
  bar.style.cssText = 'display:flex;align-items:center;gap:12px;padding:8px 18px;flex-wrap:wrap'
  bar.innerHTML = '<button data-attendance>Leave presentation</button><span data-attendance-status role="status"></span>'
  doc.body.insertBefore(bar, doc.querySelector('main'))
  const button = bar.querySelector('button'), status = bar.querySelector('span'), open = doc.querySelector('.open'), abort = new AbortController()
  // Identity tracking must not retain a disposed large scene while inspecting another file.
  const shared = new WeakSet([viewer.current])
  let away = false, busy = false, disposed = false, stop = () => {}, pendingLeave = Promise.resolve()
  function leave() {
    if (away || disposed) return
    away = true; stop(); stop = () => {}; open.hidden = false
    button.textContent = 'Return to presentation'
    status.textContent = 'You have stepped away. Guests keep the shared view; other files you open here stay private.'
    const leaving = new AbortController(), stopLeaving = () => leaving.abort(), timeout = setTimeout(stopLeaving, 10000)
    abort.signal.addEventListener('abort', stopLeaving, { once: true })
    pendingLeave = request(`${base}/leave`, { method: 'POST', signal: leaving.signal }).then(response => {
      if (!response.ok) throw new Error('Could not notify the host')
    }).catch(() => { if (!disposed && away) status.textContent = 'You have stepped away locally. Reconnect to return; guests keep their loaded view.' })
      .finally(() => { clearTimeout(timeout); abort.signal.removeEventListener('abort', stopLeaving) })
  }
  async function reenter() {
    busy = true; button.disabled = true; status.textContent = 'Returning to the shared view…'
    try {
      await pendingLeave
      if (disposed) return
      await resume()
      if (disposed) return
      shared.add(viewer.current); away = false; open.hidden = true; stop = mount({ onSharedView: scene => shared.add(scene) })
      button.textContent = 'Leave presentation'; status.textContent = 'Leaving this view keeps the guest link active.'
    } catch (error) { if (!disposed) status.textContent = `Could not return: ${error.message}` }
    finally { busy = false; if (!disposed) button.disabled = false }
  }
  button.onclick = () => { if (!busy) { if (away) void reenter(); else leave() } }
  const frame = () => { if (!away && !busy && !shared.has(viewer.current)) leave() }
  // Register before the perspective channel so a private load detaches it first.
  viewer.runtime.addFrameCallback(frame)
  stop = mount({ onSharedView: scene => shared.add(scene) }); status.textContent = 'Leaving this view keeps the guest link active.'
  return () => { if (disposed) return; disposed = true; abort.abort(); stop(); viewer.runtime.removeFrameCallback(frame); bar.remove(); open.hidden = true }
}
