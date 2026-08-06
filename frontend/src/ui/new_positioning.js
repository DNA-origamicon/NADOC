/**
 * "New positioning" — the MD-measured placement of backbone beads and base slabs.
 *
 * OFF (default) keeps every current position exactly as it was.  ON re-places the
 * full representation onto the geometry measured from free NAMD trajectories:
 * backbone bead at the phosphorus radius rather than HELIX_RADIUS, base bead on the
 * real base-ring centroid rather than 0.71 nm out, and one P-P azimuthal separation
 * for every helix instead of the +-150 deg mirror that FORWARD- and REVERSE-cell
 * helices are built with today.
 *
 * The positions themselves are computed in the backend
 * (`backend/core/measured_positioning.py`, which carries the provenance and the
 * measured numbers); this module owns only the flag and the slab geometry that
 * rides with it.
 *
 * Display-only.  Nothing here touches topology, and the flag is not part of the
 * design — it is a per-browser view preference, like the wireframe debug toggle.
 */

const STORAGE_KEY = 'nadoc.newPositioning.v1'

// Slab geometry that goes with the measured placement.  The legacy slab is centred
// 0.45 nm inward from the bead along the cross-strand direction and is 0.70 nm long;
// with measured positioning the slab is centred on the nucleotide's own measured
// base-ring centroid and sized to span its base — from that strand's C1' (0.566 nm
// from the axis) inward to just past the Watson-Crick atom (0.165 nm).
export const MEASURED_SLAB_EXTENT = 0.45

let _on = _read()
const _listeners = new Set()

function _read() {
  try {
    return localStorage.getItem(STORAGE_KEY) === 'true'
  } catch {
    return false   // private mode / storage disabled — default OFF, never throw
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
  if (!_on) return ''
  return `${hasQuery ? '&' : '?'}measured_positioning=true`
}

/**
 * Centre point for a nucleotide's base slab.
 *
 * With measured positioning the slab sits on the measured base-ring centroid the
 * backend ships as `base_position`.  Legacy keeps the historical construction —
 * a fixed offset inward from the backbone bead along the cross-strand direction —
 * which is why this takes both and picks.
 *
 * @param {{x:number,y:number,z:number}} bbPos      backbone bead
 * @param {{x:number,y:number,z:number}} bnDir      cross-strand unit vector
 * @param {number} legacyOffset                     HELIX_RADIUS - slabParams.distance
 * @param {number[]|null} basePosition              nuc.base_position, if available
 * @param {{x:number,y:number,z:number}} out        vector to write into
 */
export function slabCenterInto(bbPos, bnDir, legacyOffset, basePosition, out) {
  if (_on && basePosition) {
    out.set(basePosition[0], basePosition[1], basePosition[2])
    return out
  }
  out.copy(bbPos).addScaledVector(bnDir, legacyOffset)
  return out
}

/** Long in-plane extent of the base slab, in nm. */
export function slabExtent(legacyExtent) {
  return _on ? MEASURED_SLAB_EXTENT : legacyExtent
}

/** Test seam — reset module state without touching localStorage semantics. */
export function __resetForTests(on = false) {
  _on = on
  _listeners.clear()
}
