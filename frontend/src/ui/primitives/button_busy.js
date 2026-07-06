/**
 * Busy-guard for async action buttons (Start / Stop / Resume / …).
 *
 * The problem: a Stop request (and friends) take a beat to register on the
 * backend, so an impatient user mashes the button and fires the same call
 * several times. This wraps a click handler so that pressing the button:
 *   1. immediately grays it out + shows a spinner (instant acknowledgement),
 *   2. blocks any further presses until the async action settles
 *      (no double-submit while the request is in flight).
 *
 * The button's original label + disabled state are restored when the action
 * settles; callers typically re-render / re-gate the button right after.
 *
 * Pure DOM — no app deps — so it unit-tests under jsdom.
 */

// Buttons with an action currently in flight. WeakSet so a removed button is
// GC'd without leaking, and the guard is keyed on the element identity.
const _inFlight = new WeakSet()

/** Is an action currently running for this button? */
export function isButtonBusy(btn) {
  return !!btn && _inFlight.has(btn)
}

/**
 * Run `action` while the button shows a busy state. A press that arrives while
 * one is already in flight is swallowed (the spam guard). Returns the action's
 * result, or `undefined` if the press was ignored as a duplicate.
 *
 * @param {HTMLButtonElement|null} btn
 * @param {() => (Promise<any>|any)} action
 * @param {{ label?: string|null, spinner?: boolean }} [opts]
 *   label   — text shown beside the spinner while busy (default: keep original)
 *   spinner — show the spinner glyph (default: true)
 */
export async function runExclusive(btn, action, opts = {}) {
  const { label = null, spinner = true } = opts
  if (!btn) return action()
  if (_inFlight.has(btn)) return undefined
  _inFlight.add(btn)

  const prevHtml = btn.innerHTML
  const prevDisabled = btn.disabled
  const prevAriaBusy = btn.getAttribute('aria-busy')
  btn.disabled = true
  btn.classList.add('is-busy')
  btn.setAttribute('aria-busy', 'true')
  if (spinner || label != null) {
    btn.textContent = ''
    if (spinner) {
      const sp = document.createElement('span')
      sp.className = 'nadoc-spinner'
      sp.setAttribute('aria-hidden', 'true')
      btn.appendChild(sp)
    }
    if (label != null) {
      btn.appendChild(document.createTextNode(spinner ? ` ${label}` : label))
    }
  }
  try {
    return await action()
  } finally {
    _inFlight.delete(btn)
    btn.innerHTML = prevHtml
    btn.disabled = prevDisabled
    if (prevAriaBusy == null) btn.removeAttribute('aria-busy')
    else btn.setAttribute('aria-busy', prevAriaBusy)
    btn.classList.remove('is-busy')
  }
}

/**
 * Convenience: attach a busy-guarded click handler to a button. The handler
 * runs through {@link runExclusive}, so concurrent clicks are ignored and the
 * button shows a spinner for the duration.
 *
 * @param {HTMLButtonElement|null} btn
 * @param {() => (Promise<any>|any)} handler
 * @param {{ label?: string|null, spinner?: boolean }} [opts]
 */
export function onClickExclusive(btn, handler, opts) {
  btn?.addEventListener('click', () => runExclusive(btn, handler, opts))
}
