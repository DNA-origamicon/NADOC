/** One editor's cancellable wait; it owns its modal, clock and listeners. */
import { createModal } from './primitives/modal.js'
import { createButton } from './primitives/button.js'
import { el } from './primitives/dom.js'
import { formatElapsed } from './op_progress.js'

export function createTransformHistoryProgress({ onCancel, now = () => performance.now() }) {
  let disposed = false, cancelling = false, timer = null, operation = null
  let started = now(), elapsed = 0, computationKey = null, failure = null, cancellationMessage = ''
  const phase = el('p', { attrs: { role: 'status', 'aria-live': 'polite' } })
  const clock = el('p', { attrs: { 'aria-live': 'off' } })
  const detail = el('p', { attrs: { role: 'status', 'aria-live': 'polite' } })
  const cancel = createButton({ label: 'Cancel', onClick: () => { void requestCancel() } })
  const modal = createModal({ title: 'Move/Rotate history', size: 'sm', body: [phase, clock, detail],
    actions: [cancel], dismissOnBackdrop: false, dismissOnEscape: false,
    onClose: () => { if (disposed) return; void requestCancel(); return false } })
  modal.root.dataset.transformHistoryProgress = ''
  modal.root.setAttribute('aria-label', 'Move/Rotate history computation')

  function render() {
    if (disposed) return
    phase.textContent = operation === 'apply' ? 'Rebuilding later features…' : 'Preparing historical inputs…'
    clock.textContent = `Elapsed ${formatElapsed((elapsed * 1000) + Math.max(0, now() - started))}`
    detail.textContent = cancelling ? 'Requesting cancellation…' : (failure?.message ?? cancellationMessage)
    detail.hidden = !detail.textContent
    cancel.disabled = cancelling
  }
  async function requestCancel() {
    if (disposed || cancelling) return
    cancelling = true; cancellationMessage = ''; failure = null; render()
    try {
      const closed = await onCancel()
      if (disposed) return
      if (closed === true) { dispose(); return }
      cancellationMessage = 'Cancellation is not confirmed. Wait for the saved result before closing this editor.'
    } catch (error) { if (!disposed) failure = error }
    finally { if (!disposed) { cancelling = false; render() } }
  }
  function escape(event) {
    if (disposed || !modal.isOpen() || event.key !== 'Escape') return
    // The private gizmo also listens on document. This window-capture listener
    // consumes one modal cancellation before the underlying tool can issue it.
    event.preventDefault(); event.stopImmediatePropagation(); void requestCancel()
  }
  function dispose() {
    if (disposed) return
    disposed = true; clearInterval(timer); timer = null
    window.removeEventListener('keydown', escape, true)
    modal.close()
  }
  return {
    show({ operation: next, computation = null, error = null }) {
      if (disposed) return
      if (next !== operation) {
        operation = next; started = now(); elapsed = 0; computationKey = null
      }
      // These scalar reports were checked by the controller. Keep local elapsed
      // ticking between reports; remaining_seconds is a limit, never an ETA.
      if (computation?.operation === operation && Number.isFinite(computation.elapsed_seconds)
          && computation.elapsed_seconds >= 0) {
        const key = `${computation.request_sequence}:${computation.elapsed_seconds}`
        if (key !== computationKey) {
          computationKey = key; elapsed = computation.elapsed_seconds; started = now()
        }
      }
      if (error) failure = error
      render()
      if (!modal.isOpen()) {
        modal.open(); window.addEventListener('keydown', escape, true)
        cancel.focus(); timer = setInterval(render, 500)
      }
    },
    dispose,
  }
}
