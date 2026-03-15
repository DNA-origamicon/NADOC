/**
 * Loop/Skip highlight overlay.
 *
 * Renders coloured markers at every loop (+1) and skip (-1) position:
 *   Loop  (delta=+1) → orange ring around the two duplicate backbone beads
 *   Skip  (delta=-1) → red X cross at the axis point where the bead would be
 *
 * Usage:
 *   const lsh = initLoopSkipHighlight(scene)
 *   lsh.rebuild(design, geometry)   // call after geometry changes
 *   lsh.setVisible(bool)
 *   lsh.dispose()
 */

import * as THREE from 'three'

// Match helix_renderer.js BEAD_RADIUS = 0.10 nm
const LOOP_RING_R   = 0.20   // torus tube radius (nm)
const LOOP_TORUS_R  = 0.16   // torus major radius — wraps around the two beads
const SKIP_ARM      = 0.18   // half-length of each X arm (nm)
const SKIP_TUBE     = 0.04   // cylinder radius for X arms

const COL_LOOP = 0xff8800   // bright orange
const COL_SKIP = 0xff2222   // bright red

// Reusable geometries
const _GEO_TORUS  = new THREE.TorusGeometry(LOOP_TORUS_R, LOOP_RING_R, 8, 24)

// Skip X = two thin cylinders rotated ±45°
const _GEO_ARM = new THREE.CylinderGeometry(SKIP_TUBE, SKIP_TUBE, SKIP_ARM * 2, 6)
const _Q45A    = new THREE.Quaternion().setFromEuler(new THREE.Euler(0, 0,  Math.PI / 4))
const _Q45B    = new THREE.Quaternion().setFromEuler(new THREE.Euler(0, 0, -Math.PI / 4))

function _makeMat(color) {
  return new THREE.MeshBasicMaterial({ color, depthTest: false, transparent: true, opacity: 0.85 })
}

export function initLoopSkipHighlight(scene) {
  const _group = new THREE.Group()
  _group.renderOrder = 10   // render on top
  scene.add(_group)

  let _visible = false

  // ── Build ─────────────────────────────────────────────────────────────────

  function rebuild(design, geometry) {
    // Clear old markers
    for (const child of [..._group.children]) {
      _group.remove(child)
      // materials are shared; don't dispose them
    }
    if (!design || !geometry) return

    // Index geometry: (helix_id, bp_index) → list of backbone positions
    const geoMap = new Map()
    for (const nuc of geometry) {
      const key = `${nuc.helix_id}:${nuc.bp_index}`
      let arr = geoMap.get(key)
      if (!arr) { arr = []; geoMap.set(key, arr) }
      arr.push(nuc.backbone_position)
    }

    // Index helices by id
    const helixMap = new Map(design.helices.map(h => [h.id, h]))

    const loopMat = _makeMat(COL_LOOP)
    const skipMat = _makeMat(COL_SKIP)

    for (const helix of design.helices) {
      if (!helix.loop_skips?.length) continue

      // Compute axis direction for skip positions
      const as = helix.axis_start
      const ae = helix.axis_end
      const axLen = Math.sqrt(
        (ae.x - as.x) ** 2 + (ae.y - as.y) ** 2 + (ae.z - as.z) ** 2,
      )

      for (const ls of helix.loop_skips) {
        const key = `${helix.id}:${ls.bp_index}`

        if (ls.delta >= 1) {
          // Loop — show a torus at the midpoint between the two backbone beads.
          // If geometry isn't present yet (e.g. straight view has different counts),
          // fall back to the axis point.
          const positions = geoMap.get(key)
          let cx, cy, cz
          if (positions && positions.length >= 2) {
            // Average all backbone positions at this bp_index
            cx = 0; cy = 0; cz = 0
            for (const p of positions) { cx += p[0]; cy += p[1]; cz += p[2] }
            cx /= positions.length; cy /= positions.length; cz /= positions.length
          } else if (axLen > 0) {
            const t = ls.bp_index / helix.length_bp
            cx = as.x + (ae.x - as.x) * t
            cy = as.y + (ae.y - as.y) * t
            cz = as.z + (ae.z - as.z) * t
          } else {
            continue
          }
          const mesh = new THREE.Mesh(_GEO_TORUS, loopMat)
          mesh.position.set(cx, cy, cz)
          _group.add(mesh)
        } else if (ls.delta <= -1) {
          // Skip — show red X at the axis point (no backbone bead here).
          if (axLen <= 0) continue
          const t = ls.bp_index / helix.length_bp
          const px = as.x + (ae.x - as.x) * t
          const py = as.y + (ae.y - as.y) * t
          const pz = as.z + (ae.z - as.z) * t

          const arm1 = new THREE.Mesh(_GEO_ARM, skipMat)
          arm1.position.set(px, py, pz)
          arm1.quaternion.copy(_Q45A)

          const arm2 = new THREE.Mesh(_GEO_ARM, skipMat)
          arm2.position.set(px, py, pz)
          arm2.quaternion.copy(_Q45B)

          _group.add(arm1, arm2)
        }
      }
    }

    _group.visible = _visible
  }

  // ── Public API ────────────────────────────────────────────────────────────

  function setVisible(v) {
    _visible = v
    _group.visible = v
  }

  function dispose() {
    for (const child of [..._group.children]) _group.remove(child)
    scene.remove(_group)
  }

  return { rebuild, setVisible, isVisible: () => _visible, dispose }
}
