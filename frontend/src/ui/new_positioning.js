/**
 * Placement comparison: OFF = baseline, ON = candidate.
 *
 * Both slots start from the accepted 2026-09-20 native measured placement.
 * The retired legacy viewer geometry is no longer selectable. The selector is
 * retained so future small placement changes can be compared against this baseline.
 * The backend owns the dispatch (core/display_placement.py); the historical
 * measured_positioning query/header names remain compatible with existing clients.
 * This is a browser preference, not authored design geometry or simulation state.
 */

const STORAGE_KEY = 'nadoc.newPositioning.v3'

let _on = _read()
const _listeners = new Set()

function _read() {
  try {
    // Discard preferences for the retired native/legacy comparison.
    localStorage.removeItem('nadoc.newPositioning.v1')
    localStorage.removeItem('nadoc.newPositioning.v2')
    // Start on candidate; both slots currently reproduce the accepted baseline.
    return localStorage.getItem(STORAGE_KEY) !== 'false'
  } catch {
    return true    // private mode / storage disabled — native, never throw
  }
}

function _write(on) {
  try {
    localStorage.setItem(STORAGE_KEY, String(on))
  } catch {
    /* non-fatal: the toggle still works for this session */
  }
}

/** Is the candidate comparison slot selected? */
export function isNewPositioningOn() {
  return _on
}

/**
 * Set the flag.  Returns true when the value actually changed, so callers can
 * skip an expensive geometry refetch on a no-op.
 */
export function setNewPositioning(on) {
  const next = !!on
  if (next === _on) return false
  _on = next
  _write(next)
  for (const fn of _listeners) fn(next)
  return true
}

/** Subscribe to changes.  Returns an unsubscribe function. */
export function onNewPositioningChange(fn) {
  _listeners.add(fn)
  return () => _listeners.delete(fn)
}

/** Send the baseline/candidate selector explicitly using the compatible wire name. */
export function geometryQuerySuffix(hasQuery) {
  return `${hasQuery ? '&' : '?'}measured_positioning=${_on ? 'true' : 'false'}`
}

/**
 * Test seam — reset module state without touching localStorage semantics.
 * Called with no argument it re-reads storage, which is the only way to exercise
 * the "never chosen ⇒ native" default without reloading the module.
 */
export function __resetForTests(on) {
  _on = on === undefined ? _read() : on
  _listeners.clear()
}
