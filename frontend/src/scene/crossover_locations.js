/**
 * Crossover Locations overlay.
 *
 * When visible, fetches all valid staple crossover positions from the backend
 * and draws an ArrowHelper at the midpoint of each unligated pair, pointing
 * from backbone-A toward backbone-B.  Mirrors the overhang_locations pattern.
 *
 * Usage:
 *   const cl = initCrossoverLocations(scene)
 *   cl.rebuild(geometry)         // async — fetches API and rebuilds arrows
 *   cl.setVisible(bool)
 *   cl.applyDeformLerp(straightPosMap, t)
 *   cl.applyUnfoldOffsets(helixOffsets, t)
 *   cl.hitTest(raycaster)        // → entry | null
 *   cl.dispose()
 */

import * as THREE from 'three'
import * as api   from '../api/client.js'

// ── Arrow appearance ───────────────────────────────────────────────────────────

const ARROW_COLOR    = 0x00ccff   // cyan — matches the original crossover marker colour
const ARROW_LENGTH   = 1.5        // nm — fixed display length
const ARROW_HEAD_LEN = 0.5        // nm
const ARROW_HEAD_W   = 0.22       // nm

// ── Helpers ───────────────────────────────────────────────────────────────────

function _makeArrow(origin, dir) {
  const arrow = new THREE.ArrowHelper(dir, origin, ARROW_LENGTH, ARROW_COLOR, ARROW_HEAD_LEN, ARROW_HEAD_W)
  arrow.line.material.depthTest    = false
  arrow.line.material.transparent  = true
  arrow.line.material.opacity      = 0.82
  arrow.cone.material.depthTest    = false
  arrow.cone.material.transparent  = true
  arrow.cone.material.opacity      = 0.82
  arrow.renderOrder = 11
  return arrow
}

// ── Main export ───────────────────────────────────────────────────────────────

export function initCrossoverLocations(scene) {
  const _group = new THREE.Group()
  _group.renderOrder = 11
  scene.add(_group)

  let _visible    = false
  let _entries    = []
  let _generation = 0          // cancels in-flight rebuilds after clear

  // Map from ArrowHelper cone mesh → entry, for raycasting.
  const _coneMap = new Map()

  // ── Rebuild ──────────────────────────────────────────────────────────────

  /**
   * Async rebuild — fetches all valid crossover pairs then builds arrows.
   * @param {Array|null} geometry  nucleotide position list from store
   */
  async function rebuild(geometry) {
    const gen = ++_generation
    _clearArrows()
    if (!geometry || !geometry.length) return

    const pairs = await api.getAllValidCrossovers()
    if (gen !== _generation) return   // superseded
    if (!pairs) return

    // Fast lookup: "helix_id|bp_index|direction" → backbone_position [x,y,z]
    const nucMap = new Map()
    for (const n of geometry) {
      nucMap.set(`${n.helix_id}|${n.bp_index}|${n.direction}`, n.backbone_position)
    }

    for (const pair of pairs) {
      const { helix_a_id, helix_b_id, positions } = pair
      for (const pos of positions) {
        // Skip scaffold positions and already-placed jumps.
        if (pos.strand_type_a === 'scaffold' || pos.strand_type_b === 'scaffold') continue
        if (pos.half_ab_placed) continue

        const rawA = nucMap.get(`${helix_a_id}|${pos.bp_a}|${pos.direction_a}`)
        const rawB = nucMap.get(`${helix_b_id}|${pos.bp_b}|${pos.direction_b}`)
        if (!rawA || !rawB) continue

        const posA = new THREE.Vector3(...rawA)
        const posB = new THREE.Vector3(...rawB)

        const mid = new THREE.Vector3().addVectors(posA, posB).multiplyScalar(0.5)

        const dir = new THREE.Vector3().subVectors(posB, posA)
        const len = dir.length()
        if (len < 1e-6) continue
        dir.divideScalar(len)

        const arrow = _makeArrow(mid.clone(), dir)
        _group.add(arrow)

        const entry = {
          helixAId:   helix_a_id,
          bpA:        pos.bp_a,
          directionA: pos.direction_a,
          helixBId:   helix_b_id,
          bpB:        pos.bp_b,
          directionB: pos.direction_b,
          posA:       posA.clone(),
          posB:       posB.clone(),
          mid:        mid.clone(),   // deformed midpoint — lerped from straight
          arrow,
        }
        _entries.push(entry)
        _coneMap.set(arrow.cone, entry)
      }
    }

    _group.visible = _visible
    console.log(`[CrossoverLocations] rebuilt: ${_entries.length} arrows`)
  }

  // ── Internal clear ───────────────────────────────────────────────────────

  function _clearArrows() {
    for (const child of [..._group.children]) {
      _group.remove(child)
      if (child.line) { child.line.material.dispose(); child.line.geometry.dispose() }
      if (child.cone) { child.cone.material.dispose(); child.cone.geometry.dispose() }
    }
    _entries = []
    _coneMap.clear()
  }

  // ── Deform lerp ──────────────────────────────────────────────────────────

  /**
   * Lerp arrow origins between straight (t=0) and deformed (t=1) positions.
   *
   * @param {Map<string,THREE.Vector3>} straightPosMap  key "hid:bp:dir"
   * @param {number}                    t
   */
  function applyDeformLerp(straightPosMap, t) {
    for (const e of _entries) {
      const sa = straightPosMap?.get(`${e.helixAId}:${e.bpA}:${e.directionA}`)
      const sb = straightPosMap?.get(`${e.helixBId}:${e.bpB}:${e.directionB}`)
      if (!sa || !sb) continue
      const mx = (sa.x + sb.x) * 0.5 + ((e.posA.x + e.posB.x) * 0.5 - (sa.x + sb.x) * 0.5) * t
      const my = (sa.y + sb.y) * 0.5 + ((e.posA.y + e.posB.y) * 0.5 - (sa.y + sb.y) * 0.5) * t
      const mz = (sa.z + sb.z) * 0.5 + ((e.posA.z + e.posB.z) * 0.5 - (sa.z + sb.z) * 0.5) * t
      e.arrow.position.set(mx, my, mz)
    }
  }

  // ── Unfold offsets ───────────────────────────────────────────────────────

  /**
   * Translate arrows by the average of both helices' unfold offsets.
   *
   * @param {Map<string,THREE.Vector3>} helixOffsets
   * @param {number}                    t  lerp 0→1
   */
  function applyUnfoldOffsets(helixOffsets, t) {
    for (const e of _entries) {
      const offA = helixOffsets.get(e.helixAId)
      const offB = helixOffsets.get(e.helixBId)
      const ox = ((offA ? offA.x : 0) + (offB ? offB.x : 0)) * 0.5 * t
      const oy = ((offA ? offA.y : 0) + (offB ? offB.y : 0)) * 0.5 * t
      const oz = ((offA ? offA.z : 0) + (offB ? offB.z : 0)) * 0.5 * t
      e.arrow.position.set(e.mid.x + ox, e.mid.y + oy, e.mid.z + oz)
    }
  }

  // ── Public API ───────────────────────────────────────────────────────────

  function setVisible(v) {
    _visible = v
    _group.visible = v
  }

  function isVisible() { return _visible }

  /**
   * Raycast against arrow cones.
   * @param {THREE.Raycaster} raycaster
   * @returns {object|null} The matching entry, or null if none hit.
   */
  function hitTest(raycaster) {
    if (!_visible || _entries.length === 0) return null
    const cones = [..._coneMap.keys()]
    const hits  = raycaster.intersectObjects(cones)
    if (!hits.length) return null
    return _coneMap.get(hits[0].object) ?? null
  }

  function dispose() {
    _clearArrows()
    scene.remove(_group)
  }

  return { rebuild, setVisible, isVisible, hitTest, applyDeformLerp, applyUnfoldOffsets, dispose }
}
