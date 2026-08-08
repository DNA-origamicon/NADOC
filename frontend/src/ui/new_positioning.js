/**
 * "New positioning" — the MD-measured placement, which is now NADOC's native geometry.
 *
 * ON is the default and the normal state of the app. The backend supplies measured
 * nucleotide coordinates, with forward and reverse strands measured separately in one
 * shared base-pair frame; the renderer consumes those coordinates without rebuilding them.
 *
 * Turning it OFF reverts to the legacy build geometry — HELIX_RADIUS beads, the +-150
 * deg groove mirrored by lattice cell type, and the 1ZEW-derived atom templates whose
 * frame-origin correction collapses Watson-Crick C1'-C1' to 0.967 nm.  That is a
 * COMPARISON AFFORDANCE, not a supported mode: it is there to see what changed.
 *
 * The positions themselves come from the backend
 * (`backend/core/measured_positioning.py` for the beads, `measured_atomistic.py` for
 * the atoms — both carry the provenance and the measured numbers); this module owns
 * only the view-preference flag and its query-string representation.
 *
 * Display-only in the sense that matters here: nothing touches topology, and the flag
 * is not part of the design — it is a per-browser view preference.  Note the backend
 * now uses the measured geometry for EXPORTS and SIMULATION SEEDS too, independently
 * of this flag.
 */

// v2: the MD-measured placement became NATIVE (default ON) once the atomistic
// templates were re-extracted from free NAMD.  The key is versioned so a browser
// carrying the old opt-in `false` does not silently keep showing legacy geometry —
// v1 was an opt-in flag, v2 is an opt-OUT.
const STORAGE_KEY = 'nadoc.newPositioning.v2'

let _on = _read()
const _listeners = new Set()

function _read() {
  try {
    // Absent = never chosen = native.  Only an explicit 'false' opts out.
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

/** Is measured positioning active? */
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

/**
 * Query-string fragment for the geometry endpoint, including the leading
 * separator, or '' when off.  Keeps the flag's wire name in one place.
 *
 * @param {boolean} hasQuery — whether the URL already carries a '?'
 */
export function geometryQuerySuffix(hasQuery) {
  // Always explicit, never inferred from a default.  The two endpoints this feeds do
  // NOT default the same way — the atomistic build is measured natively, while the
  // coarse-grained geometry stays opt-in until the other CG position paths (oxDNA
  // seeding, linker relax, extension tails) share the measured placement — so the app
  // states what it wants rather than relying on either default.
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
