/**
 * md_box_overlay.js — the NAMD periodic cell as a wireframe.
 *
 * The cell breathes: under an NPT barostat the box rescales every frame, so the
 * corners arrive per frame with the rest of the solvent payload rather than being
 * built once.
 *
 * The cuboid is ROTATED in view space. Served MD frames are Kabsch-aligned onto the
 * design pose (backend/core/md_solvent.DisplayXform), so a cell that is axis-aligned
 * in the simulation is an arbitrarily-oriented parallelepiped by the time it reaches
 * the viewer. `THREE.Box3Helper` draws axis-aligned boxes only and is therefore
 * wrong here; writing the 12 edges straight into a position buffer handles any
 * orientation exactly and costs one buffer update per frame.
 *
 * The ORIGIN is the structure, not the lab cell: a NAMD DCD stores cell lengths but
 * no cell origin, so the backend centres the box on the PBC-robust DNA centroid.
 * Lengths and orientation are the simulation's own.
 */

import * as THREE from 'three'

/** Corner index pairs for the 12 cuboid edges — two corners share an edge exactly
 *  when their indices differ in one bit. Must match `md_solvent.BOX_EDGES`. */
export const BOX_EDGES = [
  [0, 1], [0, 2], [0, 4], [1, 3], [1, 5], [2, 3],
  [2, 6], [3, 7], [4, 5], [4, 6], [5, 7], [6, 7],
]

const _COLOR = 0x58a6ff
const _OPACITY = 0.45

/**
 * Expand 8 corners (24 floats, corner-major xyz) into the 24 line-segment vertices
 * (72 floats) THREE.LineSegments wants. Pure.
 *
 * @param {Float32Array|number[]} corners
 * @param {Float32Array} [out] reusable destination
 * @returns {Float32Array|null} 72 floats, or null when `corners` is not 8 points
 */
export function boxEdgePositions(corners, out = null) {
  if (!corners || corners.length < 24) return null
  const dst = out && out.length === 72 ? out : new Float32Array(72)
  for (let e = 0; e < 12; e++) {
    const [a, b] = BOX_EDGES[e]
    const o = e * 6
    dst[o]     = corners[a * 3]
    dst[o + 1] = corners[a * 3 + 1]
    dst[o + 2] = corners[a * 3 + 2]
    dst[o + 3] = corners[b * 3]
    dst[o + 4] = corners[b * 3 + 1]
    dst[o + 5] = corners[b * 3 + 2]
  }
  return dst
}

/**
 * @param {THREE.Scene|THREE.Group} scene
 * @returns {{setCorners:(c:Float32Array)=>boolean, hide:()=>void,
 *            isVisible:()=>boolean, dispose:()=>void}}
 */
export function initMdBoxOverlay(scene) {
  // One persistent mesh over a preallocated buffer: per frame we rewrite 72 floats
  // and flag them dirty, never reallocate.
  const _positions = new Float32Array(72)
  const _geo = new THREE.BufferGeometry()
  _geo.setAttribute('position', new THREE.BufferAttribute(_positions, 3))
  const _mat = new THREE.LineBasicMaterial({
    color: _COLOR, transparent: true, opacity: _OPACITY, depthWrite: false,
  })
  const _lines = new THREE.LineSegments(_geo, _mat)
  _lines.name = 'mdPeriodicBox'
  _lines.frustumCulled = false      // the cell encloses the camera target
  _lines.renderOrder = 1001
  _lines.visible = false
  scene.add(_lines)

  return {
    /** Draw this frame's cell. Returns false (and hides) for a missing/short payload. */
    setCorners(corners) {
      if (!boxEdgePositions(corners, _positions)) {
        _lines.visible = false
        return false
      }
      _geo.attributes.position.needsUpdate = true
      _geo.computeBoundingSphere()
      _lines.visible = true
      return true
    },

    hide() { _lines.visible = false },

    isVisible() { return _lines.visible },

    dispose() {
      scene.remove(_lines)
      _geo.dispose()
      _mat.dispose()
    },
  }
}
