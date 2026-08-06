/**
/**
 * "New positioning" — the MD-measured placement, which is now NADOC's native geometry.
 *
 * ON is the default and the normal state of the app.  The coarse-grained layer draws
 * its backbone bead at the phosphorus radius rather than HELIX_RADIUS and its base bead
 * on the real base-ring centroid rather than 0.71 nm out; the atomistic layer stamps
 * nucleotide templates re-extracted from free NAMD trajectories, both strands measured
 * separately in one shared base-pair frame.
 *
 * Turning it OFF reverts to the legacy build geometry — HELIX_RADIUS beads, the +-150
 * deg groove mirrored by lattice cell type, and the 1ZEW-derived atom templates whose
 * frame-origin correction collapses Watson-Crick C1'-C1' to 0.967 nm.  That is a
 * COMPARISON AFFORDANCE, not a supported mode: it is there to see what changed.
 *
 * The positions themselves come from the backend
 * (`backend/core/measured_positioning.py` for the beads, `measured_atomistic.py` for
 * the atoms — both carry the provenance and the measured numbers); this module owns
 * only the flag and the slab geometry that rides with it.
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

// Slab geometry that goes with the measured placement.  The legacy slab is centred
// 0.45 nm inward from the bead along the cross-strand direction and is 0.70 nm long.
//
// With measured positioning the slab runs along its own BEAD→BASE axis instead, from
// the backbone bead (the ribose C3') inward to just past the Watson-Crick atom, so the
// plate visibly joins the base to its own sugar.  It cannot simply be lengthened along
// the cross-strand direction: measured, the C3' sits 0.29 nm off the base's cross-strand
// line, so a slab extended that way reaches the right radius and still misses the bead.
export const MEASURED_SLAB_EXTENT = 0.6568

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
    // Half a slab inward from the bead along the bead→base axis, so the plate's OUTER
    // face lands exactly on the backbone bead — that is what makes the two connect,
    // and it holds regardless of how the bead and base happen to be oriented.
    slabAxisInto(bbPos, bnDir, basePosition, out)
    out.multiplyScalar(MEASURED_SLAB_EXTENT / 2).add(bbPos)
    return out
  }
  out.copy(bbPos).addScaledVector(bnDir, legacyOffset)
  return out
}

/**
 * Unit vector along the slab's LONG axis, written into `out`.
 *
 * Measured: from the backbone bead toward this nucleotide's own base-ring centroid.
 * Legacy: the cross-strand direction, unchanged.
 *
 * This is the slab's orientation as well as its direction of travel — the caller builds
 * the plate's basis from it — so the plate turns to face along the sugar→base line
 * rather than across the base pair.  It stays perpendicular to the helix axis either
 * way, because only the in-plane direction changes.
 *
 * @param {{x:number,y:number,z:number}} bbPos      backbone bead
 * @param {{x:number,y:number,z:number}} bnDir      cross-strand unit vector (legacy)
 * @param {number[]|null} basePosition              nuc.base_position, if available
 * @param {{x:number,y:number,z:number}} out        vector to write into
 */
export function slabAxisInto(bbPos, bnDir, basePosition, out) {
  if (_on && basePosition) {
    out.set(basePosition[0] - bbPos.x, basePosition[1] - bbPos.y, basePosition[2] - bbPos.z)
    const n = out.length()
    if (n > 1e-9) return out.multiplyScalar(1 / n)
  }
  return out.copy(bnDir)
}

/** Long in-plane extent of the base slab, in nm. */
export function slabExtent(legacyExtent) {
  return _on ? MEASURED_SLAB_EXTENT : legacyExtent
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
