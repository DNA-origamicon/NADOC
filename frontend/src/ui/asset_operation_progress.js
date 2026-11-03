import { createButton } from './primitives/button.js'

/** Progress for the existing recipe job; closing a private job cancels it. */
export function showAssetOperationProgress({ title, cancel }) {
  let publishing = false, closing = false
  // Native top-layer ownership keeps Cancel above the launching coating dialog.
  const modal = document.createElement('dialog')
  modal.className = 'modal modal--sm'
  modal.setAttribute('role', 'dialog'); modal.setAttribute('aria-label', title)
  const heading = document.createElement('h3'); heading.textContent = title
  const status = document.createElement('p'); status.setAttribute('role', 'status')
  function close() {
    if (publishing && !closing) return
    if (!closing) cancel()
    window.removeEventListener('keydown', escape, { capture: true })
    if (modal.open && typeof modal.close === 'function') modal.close()
    modal.remove()
  }
  const escape = event => { if (event.key === 'Escape') { event.preventDefault(); event.stopImmediatePropagation(); close() } }
  const stop = createButton({ label: 'Cancel', onClick: close })
  const retry = createButton({ label: 'Refresh result', onClick: () => retry.action?.() })
  retry.hidden = true
  modal.append(heading, status, stop, retry)
  modal.addEventListener('cancel', event => { event.preventDefault(); close() })
  document.body.append(modal)
  if (typeof modal.showModal === 'function') modal.showModal()
  else modal.setAttribute('open', '')
  window.addEventListener('keydown', escape, { capture: true })
  return {
    update(message, { committing = false, refresh } = {}) {
      status.textContent = message; publishing = committing
      stop.disabled = committing; retry.hidden = !refresh; retry.action = refresh
    },
    close() { closing = true; close() },
  }
}
