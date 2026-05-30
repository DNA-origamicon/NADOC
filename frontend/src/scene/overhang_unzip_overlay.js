/**
 * Overhang unzip animation — DISPLAY-ONLY splay of the REAL overhang nucleotide
 * beads + slabs, driven by a reaction coordinate φ ∈ [0,1] (φ=1 bound, φ=0
 * unzipped). No synthetic geometry: it moves the actual rendered beads via the
 * helix renderer's surgical `setBeadOverrides` and restores them on clear().
 *
 * Choreography (confirmed with the user):
 *  - φ=1 → every bead sits at its AUTHORED position (zero displacement; no jump
 *    at play start).
 *  - φ→0 → a melt fork travels from each overhang's free TIP toward its ROOT;
 *    freed nucleotides (tip side of the fork) splay out as a straight ssDNA arm
 *    whose direction points TOWARD that strand's own root (the perpendicular-to-
 *    duplex-axis component of root−center). Two overhangs therefore open apart
 *    in the plane of their two roots — ~90° for overhang-to-overhang.
 *  - Linkers: only the two overhangs' own beads are animated (the bridge is left
 *    as-is), so it reads like a direct overhang-overhang pairing.
 *
 * Moving-arm coupling: beads on the hinge's driven cluster are additionally
 * rotated by the live hinge rotation (passed in per driver) so the splayed
 * overhang stays attached to its rotating arm.
 *
 * Three-Layer Law: pure display. Reads geometry + the driver's overhang ids;
 * writes only transient bead/slab matrices via setBeadOverrides. Restored on
 * stop (here, and redundantly by the player's _restoreBaseClusters).
 *
 * Wiring:
 *   const overlay = initOverhangUnzipOverlay({ getHelixCtrl, getDesign })
 *   overlay.update(items, geometry)   // items: [{binding, phi, hinge}]
 *   overlay.clear()                   // restore moved beads to authored
 */

import * as THREE from 'three'
import { meltFraction } from '../strand-anim/melt.js'
import { DEFAULTS as STRAND_DEFAULTS } from '../strand-anim/params.js'

export function initOverhangUnzipOverlay({ getHelixCtrl, getDesign }) {
  // Keys (helix:bp:dir) currently overridden — so we can restore exactly those.
  let _movedKeys = new Set()
  let _lastGeometry = null

  const _tipA = new THREE.Vector3(), _tipB = new THREE.Vector3()
  const _C = new THREE.Vector3(), _axis = new THREE.Vector3()
  const _root = new THREE.Vector3(), _D = new THREE.Vector3()
  const _fork = new THREE.Vector3(), _H = new THREE.Vector3(), _arm = new THREE.Vector3()
  const _q = new THREE.Quaternion(), _J = new THREE.Vector3(), _ax = new THREE.Vector3()
  const _UP = new THREE.Vector3(0, 1, 0), _Z = new THREE.Vector3(0, 0, 1)

  const _key = (n) => `${n.helix_id}:${n.bp_index}:${n.direction}`
  const _vec = (a, out) => out.set(a[0], a[1], a[2])

  /** Overhang nucleotides, root-first (lowest bp_index). */
  function _overhangNucs(geometry, ohId) {
    return geometry
      .filter(n => n.overhang_id === ohId)
      .sort((a, b) => a.bp_index - b.bp_index)
  }

  /** Hinge rotation (about world line J,axis by deltaRad) + its cluster's helices. */
  function _hingeRot(hinge, design) {
    if (!hinge || !design) return null
    const cluster = design.cluster_transforms?.find(c => c.id === hinge.clusterId)
    if (!cluster) return null
    _vec(hinge.axisDir, _ax).normalize()
    _q.setFromAxisAngle(_ax, hinge.deltaRad)
    _vec(hinge.J, _J)
    return { q: _q.clone(), J: _J.clone(), helixIds: new Set(cluster.helix_ids ?? []) }
  }

  /** Append splay updates for one overhang strand into `updates`. */
  function _strandUpdates(nucs, center, axis, phi, rot, updates, nowKeys) {
    const M = nucs.length
    if (!M) return
    _vec(nucs[0].backbone_position, _root)        // root = first (lowest bp)
    // Toward-root splay direction: perpendicular-to-axis component of (root − center).
    _D.copy(_root).sub(center)
    _D.addScaledVector(axis, -_D.dot(axis))
    if (_D.lengthSq() < 1e-9) {                    // root ~on the axis → fallback
      _D.copy(_UP).addScaledVector(axis, -_UP.dot(axis))
      if (_D.lengthSq() < 1e-9) _D.copy(_Z).addScaledVector(axis, -_Z.dot(axis))
    }
    _D.normalize()

    const armStep = STRAND_DEFAULTS.rise * STRAND_DEFAULTS.armPull
    const meltBp  = STRAND_DEFAULTS.meltBp
    // Fork index: freed = tip side (high index). φ=1→k=M (none freed); φ=0→k=0 (all).
    const k = Math.round(phi * M)
    const jIdx = k - 0.5                            // continuous fork center for melt blend
    _vec(nucs[Math.max(0, Math.min(M - 1, k))].backbone_position, _fork)

    for (let i = 0; i < M; i++) {
      const nuc = nucs[i]
      _vec(nuc.backbone_position, _H)               // paired/authored position
      _arm.copy(_fork).addScaledVector(_D, (i - k) * armStep)  // straight ssDNA arm from fork
      const w = meltFraction(i, jIdx, meltBp)        // 0 paired .. 1 freed
      _H.multiplyScalar(1 - w).addScaledVector(_arm, w)        // lerp → final (in _H)
      if (rot && rot.helixIds.has(nuc.helix_id)) {   // follow the rotating arm
        _H.sub(rot.J).applyQuaternion(rot.q).add(rot.J)
      }
      updates.push({
        helix_id: nuc.helix_id, bp_index: nuc.bp_index, direction: nuc.direction,
        backbone_position: [_H.x, _H.y, _H.z],
      })
      nowKeys.add(_key(nuc))
    }
  }

  /**
   * Animate the real overhang beads for the given drivers at their φ.
   * @param {Array<{binding:object, phi:number, hinge?:object}>} items
   * @param {Array} geometry  store.currentGeometry
   */
  function update(items, geometry) {
    const helixCtrl = getHelixCtrl?.()
    if (!helixCtrl?.setBeadOverrides || !geometry) { clear(); return }
    _lastGeometry = geometry
    const design = getDesign?.()
    const updates = []
    const nowKeys = new Set()

    for (const { binding, phi, hinge } of (items ?? [])) {
      const A = _overhangNucs(geometry, binding.overhang_a_id)
      const B = _overhangNucs(geometry, binding.overhang_b_id)
      if (!A.length || !B.length) continue
      _vec(A[A.length - 1].backbone_position, _tipA)
      _vec(B[B.length - 1].backbone_position, _tipB)
      _C.copy(_tipA).add(_tipB).multiplyScalar(0.5)              // duplex center
      _axis.copy(_tipB).sub(_tipA)                               // duplex axis
      if (_axis.lengthSq() < 1e-9) _axis.set(1, 0, 0)
      _axis.normalize()
      const rot = _hingeRot(hinge, design)
      _strandUpdates(A, _C, _axis, phi, rot, updates, nowKeys)
      _strandUpdates(B, _C, _axis, phi, rot, updates, nowKeys)
    }

    // Restore any bead we moved last frame but isn't animated now → authored pos.
    for (const key of _movedKeys) {
      if (nowKeys.has(key)) continue
      const u = _authoredUpdate(key, geometry)
      if (u) updates.push(u)
    }

    helixCtrl.setBeadOverrides(updates)
    _movedKeys = nowKeys
  }

  /** Build an "restore to authored position" update for a moved key. */
  function _authoredUpdate(key, geometry) {
    for (const n of geometry) {
      if (_key(n) === key) {
        const p = n.backbone_position
        return { helix_id: n.helix_id, bp_index: n.bp_index, direction: n.direction,
                 backbone_position: [p[0], p[1], p[2]] }
      }
    }
    return null
  }

  /** Restore every overridden bead to its authored position. */
  function clear() {
    const helixCtrl = getHelixCtrl?.()
    if (helixCtrl?.setBeadOverrides && _movedKeys.size && _lastGeometry) {
      const updates = []
      for (const key of _movedKeys) {
        const u = _authoredUpdate(key, _lastGeometry)
        if (u) updates.push(u)
      }
      helixCtrl.setBeadOverrides(updates)
    }
    _movedKeys = new Set()
  }

  function dispose() { clear() }

  return { update, clear, dispose }
}
