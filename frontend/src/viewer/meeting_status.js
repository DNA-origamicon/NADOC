/** Guest-only loading and terminal states; no editor labels or job metadata leak. */
export function mountMeetingStatus({ viewer, document: doc = document }) {
  const loading = doc.createElement('div'); loading.id = 'meeting-loading'; loading.hidden = true
  loading.style.cssText = 'position:fixed;top:112px;left:50%;transform:translateX(-50%);width:min(300px,80vw);padding:14px;background:#161b22;color:#e6edf3;border:1px solid #484f58;border-radius:8px;z-index:20;pointer-events:none'
  loading.innerHTML = '<div role="status" style="margin-bottom:8px">Loading visualization</div><progress max="1" aria-label="Loading visualization" style="width:100%;height:10px;accent-color:#58a6ff"></progress>'
  const ended = doc.createElement('div'); ended.id = 'presentation-ended'; ended.hidden = true
  ended.setAttribute('role', 'alertdialog'); ended.setAttribute('aria-label', 'Presentation ended'); ended.tabIndex = -1
  ended.style.cssText = 'position:fixed;inset:0;z-index:1000;background:#0d1117;color:#e6edf3;align-content:center;text-align:center'
  ended.innerHTML = '<h1 style="font:600 26px system-ui">Presentation ended</h1><p style="color:#8b949e;font:14px system-ui">The host has ended this presentation.</p>'
  doc.body.append(loading, ended)
  const bar = loading.querySelector('progress'), main = doc.querySelector('main')
  let finished = false
  return {
    progress(value, receiving = false) {
      if (finished) return
      loading.hidden = !value && !receiving
      if (value?.fraction != null) bar.value = Math.max(0, Math.min(1, value.fraction))
      else bar.removeAttribute('value')
    },
    end() {
      if (finished) return
      finished = true; loading.hidden = true; viewer.clear?.()
      if (main) main.inert = true
      ended.hidden = false; ended.focus()
      const status = doc.getElementById('status'); if (status) status.textContent = 'Presentation ended'
    },
    dispose() { loading.remove(); ended.remove(); if (main) main.inert = false },
  }
}
