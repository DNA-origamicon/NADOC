/**
 * Crossover Locations overlay.
 *
 * Shows a sprite badge at each unligated staple crossover nucleotide (both 3D
 * and unfolded view).  Each badge shows the 1-based helix number of the partner.
 * Hovering either badge draws a bezier arc to its partner (same style as placed
 * crossover arcs in the unfold view).  Clicking either badge calls
 * addHalfCrossover with that nucleotide as the primary ("A") side.
 *
 * Usage:
 *   const cl = initCrossoverLocations(scene, canvas, camera)
 *   cl.rebuild(geometry)
 *   cl.setVisible(bool)
 *   cl.applyDeformLerp(straightPosMap, t)
 *   cl.applyUnfoldOffsets(helixOffsets, t)
 *   cl.dispose()
 */

import * as THREE from 'three'
import * as api   from '../api/client.js'
import { store }  from '../state/store.js'
import { showToast } from '../ui/toast.js'

const ARC_SEGS      = 20
const MAX_BOW_FRAC  = 0.15
const HOVER_COLOR   = 0x44aaff
const HOVER_PROX_PX = 22

// ── Sprite factory ────────────────────────────────────────────────────────────

function _makePartnerSprite(num) {
  const size = 128
  const cv   = document.createElement('canvas')
  cv.width   = size; cv.height = size
  const ctx  = cv.getContext('2d')
  const r    = size / 2
  ctx.beginPath()
  ctx.arc(r, r, r * 0.80, 0, Math.PI * 2)
  ctx.fillStyle = 'rgba(0,40,60,0.82)'
  ctx.fill()
  ctx.beginPath()
  ctx.arc(r, r, r * 0.80, 0, Math.PI * 2)
  ctx.strokeStyle = 'rgba(0,204,255,0.75)'
  ctx.lineWidth   = r * 0.13
  ctx.stroke()
  const str = String(num)
  ctx.fillStyle = '#c8f4ff'
  ctx.font      = `bold ${str.length > 2 ? r * 0.68 : r * 0.84}px monospace`
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
  ctx.fillText(str, r, r + 1)
  const tex = new THREE.CanvasTexture(cv)
  const mat = new THREE.SpriteMaterial({
    map: tex, transparent: true,
    depthTest: false, depthWrite: false,
  })
  const spr = new THREE.Sprite(mat)
  spr.scale.set(0.75, 0.75, 1)
  spr.renderOrder = 20
  return spr
}

function _helixNumber(helixId) {
  // Use the 0-based position in design.helices — matches blunt_ends.js and minimap.
  const helices = store.getState().currentDesign?.helices ?? []
  const idx = helices.findIndex(h => h.id === helixId)
  return idx !== -1 ? idx : '?'
}

// ── Main export ───────────────────────────────────────────────────────────────

export function initCrossoverLocations(scene, canvas, camera) {
  let _camera = camera   // mutable — updated by setCamera() when ortho camera is active

  const _group = new THREE.Group()
  scene.add(_group)

  let _visible    = false
  let _entries    = []
  let _generation = 0
  let _hoverEntry = null
  let _hoverSide  = null   // 'A' or 'B' — which sprite within _hoverEntry is closest

  // ── Hover arc (quadratic bezier) ─────────────────────────────────────────

  const _arcPts = new Float32Array((ARC_SEGS + 1) * 3)
  const _arcGeo = new THREE.BufferGeometry()
  _arcGeo.setAttribute('position', new THREE.BufferAttribute(_arcPts, 3))
  const _arcMat = new THREE.LineBasicMaterial({
    color: HOVER_COLOR, depthTest: false, transparent: true, opacity: 0.90,
  })
  const _hoverArc = new THREE.Line(_arcGeo, _arcMat)
  _hoverArc.renderOrder = 25
  _hoverArc.frustumCulled = false
  _hoverArc.visible = false
  scene.add(_hoverArc)

  function _updateHoverArc() {
    if (!_hoverEntry || !_visible) { _hoverArc.visible = false; return }
    const pa   = _hoverEntry.spriteA.position
    const pb   = _hoverEntry.spriteB.position
    const dist = pa.distanceTo(pb)
    const bow  = dist * MAX_BOW_FRAC
    const cx = (pa.x + pb.x) * 0.5
    const cy = (pa.y + pb.y) * 0.5
    const cz = (pa.z + pb.z) * 0.5 + bow
    for (let j = 0; j <= ARC_SEGS; j++) {
      const u  = j / ARC_SEGS
      const u2 = 1 - u
      const w0 = u2 * u2, w1 = 2 * u2 * u, w2 = u * u
      const i  = j * 3
      _arcPts[i]     = w0 * pa.x + w1 * cx + w2 * pb.x
      _arcPts[i + 1] = w0 * pa.y + w1 * cy + w2 * pb.y
      _arcPts[i + 2] = w0 * pa.z + w1 * cz + w2 * pb.z
    }
    _arcGeo.attributes.position.needsUpdate = true
    _hoverArc.visible = true
  }

  // ── Screen-space sprite proximity ────────────────────────────────────────

  function _findClosestSprite(clientX, clientY) {
    const rect = canvas.getBoundingClientRect()
    const sx = clientX - rect.left
    const sy = clientY - rect.top
    let best = null, bestSide = null, bestDist = HOVER_PROX_PX
    for (const entry of _entries) {
      for (const [spr, side] of [[entry.spriteA, 'A'], [entry.spriteB, 'B']]) {
        const v  = spr.position.clone().project(_camera)
        const px = ( v.x * 0.5 + 0.5) * rect.width
        const py = (-v.y * 0.5 + 0.5) * rect.height
        const d  = Math.hypot(px - sx, py - sy)
        if (d < bestDist) { bestDist = d; best = entry; bestSide = side }
      }
    }
    return best ? { entry: best, side: bestSide } : null
  }

  // ── Mouse hover ──────────────────────────────────────────────────────────

  function _onMouseMove(e) {
    if (!_visible || !_entries.length) {
      if (_hoverEntry) { _hoverEntry = null; _hoverArc.visible = false }
      return
    }
    const hit  = _findClosestSprite(e.clientX, e.clientY)
    const next = hit?.entry ?? null
    if (next !== _hoverEntry) {
      _hoverEntry = next
      _hoverSide  = hit?.side ?? null
      _updateHoverArc()
    }
  }

  canvas.addEventListener('mousemove', _onMouseMove)

  // ── Click to place half-crossover ────────────────────────────────────────

  function _removeEntry(entry) {
    if (_hoverEntry === entry) {
      _hoverEntry = null
      _hoverArc.visible = false
    }
    const idx = _entries.indexOf(entry)
    if (idx !== -1) _entries.splice(idx, 1)
    for (const spr of [entry.spriteA, entry.spriteB]) {
      _group.remove(spr)
      spr.material.map?.dispose()
      spr.material.dispose()
    }
  }

  canvas.addEventListener('click', async e => {
    if (!_visible || !_entries.length || e.ctrlKey || e.button !== 0) return
    const hit = _findClosestSprite(e.clientX, e.clientY)
    if (!hit) return
    const { entry: en } = hit
    const { helixAId, bpA, directionA, helixBId, bpB, directionB } = en

    // Check for an adjacent companion entry (adjacent DX pairs like {6,7}, {13,14}).
    // For such pairs we must use addStapleCrossover at the "master" position so
    // both halves are created atomically and no loop strand is formed.
    function findAdj(delta) {
      return _entries.find(x =>
        x.helixAId === helixAId && x.helixBId === helixBId && x.bpA === bpA + delta
      )
    }

    let masterBpA = bpA, masterBpB = bpB, companion = null

    if (directionA === 'REVERSE' && directionB === 'FORWARD') {
      // Companion is 1 bp lower (lo) or higher (hi).
      const lo = findAdj(-1)
      const hi = findAdj(+1)
      if (lo) {
        companion = lo          // clicked hi — master = this entry (bpA)
      } else if (hi) {
        companion = hi          // clicked lo — master = hi
        masterBpA = bpA + 1
        masterBpB = bpB + 1
      }
    } else if (directionA === 'FORWARD' && directionB === 'REVERSE') {
      const lo = findAdj(-1)
      const hi = findAdj(+1)
      if (hi) {
        companion = hi          // clicked lo — master = this entry (bpA)
      } else if (lo) {
        companion = lo          // clicked hi — master = lo
        masterBpA = bpA - 1
        masterBpB = bpB - 1
      }
    }

    // Optimistically remove sprites before the async API call.
    _removeEntry(en)
    if (companion) _removeEntry(companion)

    let result
    if (companion) {
      result = await api.addStapleCrossover({
        helixAId, bpA: masterBpA, directionA,
        helixBId, bpB: masterBpB, directionB,
      })
    } else {
      result = await api.addHalfCrossover({ helixAId, bpA, directionA, helixBId, bpB, directionB })
    }
    if (!result) {
      const msg = store.getState().lastError?.message ?? 'Crossover failed'
      showToast(`Crossover error: ${msg}`)
    }
  })

  // ── Rebuild ───────────────────────────────────────────────────────────────

  async function rebuild(geometry) {
    const gen = ++_generation
    _clear()
    if (!geometry || !geometry.length) return

    const pairs = await api.getAllValidCrossovers()
    if (gen !== _generation) return
    if (!pairs) return

    const nucMap = new Map()
    for (const n of geometry) {
      nucMap.set(`${n.helix_id}|${n.bp_index}|${n.direction}`, n.backbone_position)
    }

    for (const pair of pairs) {
      const { helix_a_id, helix_b_id, positions } = pair
      for (const pos of positions) {
        if (!pos.strand_type_a || !pos.strand_type_b) continue   // unoccupied bp — no strand there
        if (pos.strand_type_a === 'scaffold' || pos.strand_type_b === 'scaffold') continue
        if (pos.half_ab_placed || pos.half_ba_placed) continue

        const rawA = nucMap.get(`${helix_a_id}|${pos.bp_a}|${pos.direction_a}`)
        const rawB = nucMap.get(`${helix_b_id}|${pos.bp_b}|${pos.direction_b}`)
        if (!rawA || !rawB) continue

        const posA = new THREE.Vector3(...rawA)
        const posB = new THREE.Vector3(...rawB)

        const spriteA = _makePartnerSprite(_helixNumber(helix_b_id))
        const spriteB = _makePartnerSprite(_helixNumber(helix_a_id))
        spriteA.position.copy(posA)
        spriteB.position.copy(posB)
        _group.add(spriteA)
        _group.add(spriteB)

        _entries.push({
          helixAId:   helix_a_id,
          bpA:        pos.bp_a,
          directionA: pos.direction_a,
          helixBId:   helix_b_id,
          bpB:        pos.bp_b,
          directionB: pos.direction_b,
          posA:       posA.clone(),
          posB:       posB.clone(),
          spriteA,
          spriteB,
        })
      }
    }

    _group.visible = _visible
    console.log(`[CrossoverLocations] rebuilt: ${_entries.length} crossover sites`)
  }

  // ── Internal clear ────────────────────────────────────────────────────────

  function _clear() {
    _hoverEntry = null
    _hoverArc.visible = false
    for (const child of [..._group.children]) {
      _group.remove(child)
      if (child.isSprite) { child.material.map?.dispose(); child.material.dispose() }
    }
    _entries = []
  }

  // ── Deform lerp ───────────────────────────────────────────────────────────

  function applyDeformLerp(straightPosMap, t) {
    for (const e of _entries) {
      const sa = straightPosMap?.get(`${e.helixAId}:${e.bpA}:${e.directionA}`)
      const sb = straightPosMap?.get(`${e.helixBId}:${e.bpB}:${e.directionB}`)
      if (sa) e.spriteA.position.set(
        sa.x + (e.posA.x - sa.x) * t,
        sa.y + (e.posA.y - sa.y) * t,
        sa.z + (e.posA.z - sa.z) * t,
      )
      if (sb) e.spriteB.position.set(
        sb.x + (e.posB.x - sb.x) * t,
        sb.y + (e.posB.y - sb.y) * t,
        sb.z + (e.posB.z - sb.z) * t,
      )
    }
    _updateHoverArc()
  }

  // ── Unfold offsets ────────────────────────────────────────────────────────

  function applyUnfoldOffsets(helixOffsets, t) {
    for (const e of _entries) {
      const offA = helixOffsets.get(e.helixAId)
      const offB = helixOffsets.get(e.helixBId)
      e.spriteA.position.set(
        e.posA.x + (offA ? offA.x : 0) * t,
        e.posA.y + (offA ? offA.y : 0) * t,
        e.posA.z + (offA ? offA.z : 0) * t,
      )
      e.spriteB.position.set(
        e.posB.x + (offB ? offB.x : 0) * t,
        e.posB.y + (offB ? offB.y : 0) * t,
        e.posB.z + (offB ? offB.z : 0) * t,
      )
    }
    _updateHoverArc()
  }

  // ── Public API ────────────────────────────────────────────────────────────

  function setVisible(v) {
    _visible = v
    _group.visible = v
    if (!v) { _hoverEntry = null; _hoverArc.visible = false }
  }

  function isVisible() { return _visible }

  function dispose() {
    canvas.removeEventListener('mousemove', _onMouseMove)
    _clear()
    scene.remove(_group)
    scene.remove(_hoverArc)
    _arcGeo.dispose()
    _arcMat.dispose()
  }

  /**
   * Lerp sprite positions from unfold-layout positions toward cadnano flat positions.
   * @param {Map<string,THREE.Vector3>} cadnanoPosMap  keyed "helix_id:bp_index:direction"
   * @param {number} t  [0,1]; 0 = unfold, 1 = cadnano flat
   * @param {Map<string,THREE.Vector3>} unfoldPosMap   positions at t=0
   */
  function applyCadnanoPositions(cadnanoPosMap, t, unfoldPosMap) {
    for (const e of _entries) {
      const keyA = `${e.helixAId}:${e.bpA}:${e.directionA}`
      const keyB = `${e.helixBId}:${e.bpB}:${e.directionB}`
      const cpA = cadnanoPosMap?.get(keyA)
      const upA = unfoldPosMap?.get(keyA) ?? e.posA
      const cpB = cadnanoPosMap?.get(keyB)
      const upB = unfoldPosMap?.get(keyB) ?? e.posB
      if (cpA) e.spriteA.position.set(
        upA.x + (cpA.x - upA.x) * t,
        upA.y + (cpA.y - upA.y) * t,
        upA.z + (cpA.z - upA.z) * t,
      )
      if (cpB) e.spriteB.position.set(
        upB.x + (cpB.x - upB.x) * t,
        upB.y + (cpB.y - upB.y) * t,
        upB.z + (cpB.z - upB.z) * t,
      )
    }
    _updateHoverArc()
  }

  /**
   * Returns the currently hovered crossover entry and which sprite side is
   * closest to the cursor, or null if nothing is hovered.
   * Shape: { entry: { helixAId, bpA, directionA, helixBId, bpB, directionB, ... }, side: 'A'|'B' } | null
   */
  function getHoveredState() {
    return _hoverEntry ? { entry: _hoverEntry, side: _hoverSide } : null
  }

  return { rebuild, setVisible, isVisible, getHoveredState, applyDeformLerp, applyUnfoldOffsets, applyCadnanoPositions, setCamera(cam) { _camera = cam }, dispose }
}
