// Atomistic geometry builder — pure helpers extracted from atomistic_renderer.js
// (Refactor 13-F). Bundles the THREE scratch objects with the geometry helpers
// to preserve the allocation-avoidance contract: callers reuse one state bag
// per renderer rather than allocating per-call.
//
// Leaf module: imports `three` (external) ONLY — NO imports from
// `atomistic_renderer.js` or sibling modules under `atomistic_renderer/`
// (substantive precondition #19). This is the purest leaf possible alongside
// `atom_palette.js` (which has zero imports).
//
// Public API:
//   createGeometryState() → state bag of THREE temps + shared geometry constants
//   atomOffset(state, atom, offsets, t)            → THREE.Vector3 (clone — safe to keep)
//   sphereMatrix(state, x, y, z, r)                → THREE.Matrix4 (clone — safe to keep)
//   bondMatrix(state, ax, ay, az, bx, by, bz, r)   → THREE.Matrix4 | null
//   makeSphereMaterial()                            → THREE.MeshStandardMaterial
//   makeBondMaterial()                              → THREE.MeshStandardMaterial
//
// All helpers take `state` as the first argument so the THREE scratch buffers
// (tmpMat / tmpQ / tmpS / yAxis / zeroVec) live with the renderer instance and
// are not module-globals leaking across multiple `initAtomisticRenderer` calls
// (assembly_renderer.js builds one renderer per assembly entry).

import * as THREE from 'three'

// ── Shared geometry constants (module-level — pure data, safe to share) ──────

export const SPHERE_GEO   = new THREE.SphereGeometry(1, 10, 8)
export const CYLINDER_GEO = new THREE.CylinderGeometry(1, 1, 1, 6, 1)

/**
 * Allocate a per-renderer state bag of THREE scratch buffers + axis constants.
 * Each renderer instance gets its own bag so concurrent renderers (e.g. one
 * per assembly entry) cannot stomp on each other's temporaries.
 *
 * @returns {{
 *   tmpMat:  THREE.Matrix4,
 *   tmpQ:    THREE.Quaternion,
 *   tmpS:    THREE.Vector3,
 *   tColor:  THREE.Color,
 *   yAxis:   THREE.Vector3,
 *   zeroVec: THREE.Vector3,
 * }}
 */
export function createGeometryState() {
  return {
    tmpMat:  new THREE.Matrix4(),
    tmpQ:    new THREE.Quaternion(),
    tmpS:    new THREE.Vector3(),
    tColor:  new THREE.Color(),
    yAxis:   new THREE.Vector3(0, 1, 0),
    zeroVec: new THREE.Vector3(),
  }
}

// ── Materials (factory functions — fresh material per call) ──────────────────

// Material base colour stays white so that the per-instance colour in
// InstancedBufferAttribute is the final rendered colour (Three.js multiplies
// material.color × instanceColor channel-wise — a non-white base would tint
// every strand/base/cluster colour).
export function makeSphereMaterial() {
  return new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.4, metalness: 0.05 })
}

export function makeBondMaterial() {
  return new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.6 })
}

// ── Pure geometry helpers ────────────────────────────────────────────────────

/** Interpolated world offset for an atom using aux_helix_id / aux_t. */
export function atomOffset(state, atom, offsets, t) {
  const base = offsets.get(atom.helix_id) ?? state.zeroVec
  if (!atom.aux_helix_id || atom.aux_t === 0) return base.clone().multiplyScalar(t)
  const aux = offsets.get(atom.aux_helix_id) ?? state.zeroVec
  return base.clone().lerp(aux, atom.aux_t).multiplyScalar(t)
}

/** Build a translation+uniform-scale Matrix4 for a sphere instance. */
export function sphereMatrix(state, x, y, z, r) {
  state.tmpMat.identity()
  state.tmpMat.makeScale(r, r, r)
  state.tmpMat.setPosition(x, y, z)
  return state.tmpMat.clone()
}

/**
 * Build a transform Matrix4 for a cylinder instance spanning a → b with the
 * given radius, oriented along the segment direction.
 *
 * Returns null for degenerate (zero-length) bonds so callers can skip them.
 */
export function bondMatrix(state, ax, ay, az, bx, by, bz, radius) {
  const start = new THREE.Vector3(ax, ay, az)
  const end   = new THREE.Vector3(bx, by, bz)
  const dir   = new THREE.Vector3().subVectors(end, start)
  const len   = dir.length()
  if (len < 1e-9) return null
  const mid = new THREE.Vector3().addVectors(start, end).multiplyScalar(0.5)
  state.tmpQ.setFromUnitVectors(state.yAxis, dir.normalize())
  state.tmpS.set(radius, len, radius)
  state.tmpMat.compose(mid, state.tmpQ, state.tmpS)
  return state.tmpMat.clone()
}
