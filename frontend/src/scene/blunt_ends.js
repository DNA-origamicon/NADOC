/**
 * Blunt end indicators — rings at free helix endpoints, visible only on hover.
 *
 * A helix endpoint is "free" when no other helix in the design starts or ends
 * at the same 3-D position (within 1 pm tolerance).
 *
 * Each blunt end has:
 *  - an invisible hit disk (CircleGeometry) that absorbs raycasts for hover detection
 *  - a visible ring (RingGeometry) that fades in when the cursor is over the hit disk
 *
 * Clicking a ring (pointerdown+up without drag) opens the slice plane at that
 * exact offset in continuation mode.  The pointerdown is intercepted in the
 * CAPTURE phase so OrbitControls never sees it, preventing unwanted rotation.
 */

import * as THREE from 'three'
import { store }  from '../state/store.js'
import { BDNA_RISE_PER_BP } from '../constants.js'

const RING_INNER      = 0.35
const RING_OUTER      = 1.15
const HIT_RADIUS      = RING_OUTER * 1.25   // slightly larger than ring for comfortable clicking
const RING_SEGS       = 32
const RING_COLOR      = 0x58a6ff
const _Z_HAT          = new THREE.Vector3(0, 0, 1)
const _bluntAxisDir   = new THREE.Vector3()
const _bluntStraightQ = new THREE.Quaternion()
const _bluntLerpedQ   = new THREE.Quaternion()
const _bluntLabelOff  = new THREE.Vector3()   // scratch for lerped label offset
const _bluntClusterV  = new THREE.Vector3()   // scratch for cluster transform
const _bluntClusterQ  = new THREE.Quaternion()
const RING_OPACITY    = 0.45
const TOL             = 0.001               // nm — two endpoints at the same position
const LABEL_OPACITY   = 0.72               // always-visible label opacity
const LABEL_OPACITY_H = 1.00               // label opacity when ring is hovered

export function initBluntEnds(scene, camera, canvas, { onBluntEndClick, onBluntEndRightClick, isDisabled, getUnfoldView } = {}) {

  const _group   = new THREE.Group()
  scene.add(_group)

  const _ringGeo = new THREE.RingGeometry(RING_INNER, RING_OUTER, RING_SEGS)
  const _hitGeo  = new THREE.CircleGeometry(HIT_RADIUS, RING_SEGS)

  // ── Number sprite helper ──────────────────────────────────────────────────
  function _makeNumberSprite(num) {
    const size = 128
    const cv   = document.createElement('canvas')
    cv.width   = size; cv.height = size
    const ctx  = cv.getContext('2d')
    const r    = size / 2
    ctx.beginPath()
    ctx.arc(r, r, r * 0.80, 0, Math.PI * 2)
    ctx.fillStyle = 'rgba(13,17,23,0.80)'
    ctx.fill()
    ctx.beginPath()
    ctx.arc(r, r, r * 0.80, 0, Math.PI * 2)
    ctx.strokeStyle = 'rgba(88,166,255,0.65)'
    ctx.lineWidth   = r * 0.13
    ctx.stroke()
    const str = String(num)
    ctx.fillStyle = '#e6edf3'
    ctx.font      = `bold ${str.length > 2 ? r * 0.68 : r * 0.84}px monospace`
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
    ctx.fillText(str, r, r + 1)
    const tex = new THREE.CanvasTexture(cv)
    const mat = new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false })
    const spr = new THREE.Sprite(mat)
    spr.scale.set(0.90, 0.90, 1)
    return spr
  }

  // Each entry: { ringMesh, hitMesh, labelSprite, plane, offsetNm }
  let _ends = []
  let _hoveredIdx = -1   // index into _ends, -1 = none
  let _cbEnds = new Map()  // end entry → { pos, labelPos, quat } snapshots for cluster transforms

  const _raycaster = new THREE.Raycaster()
  const _ndc       = new THREE.Vector2()

  // pending click: set on pointerdown when hovering a ring
  let _pendingIdx      = -1
  let _pendingPos      = null
  let _pendingRightIdx = -1
  let _pendingRightPos = null

  // ── Helpers ────────────────────────────────────────────────────────────────

  function _planeFromHelixId(helixId) {
    const m = helixId.match(/^h_(XY|XZ|YZ)_/)
    return m ? m[1] : 'XY'
  }

  function _offsetFromEndpoint(endpoint, plane) {
    if (plane === 'XY') return endpoint.z
    if (plane === 'XZ') return endpoint.y
    return endpoint.x
  }

  function _setNDC(e) {
    const rect = canvas.getBoundingClientRect()
    _ndc.set(
      ((e.clientX - rect.left) / rect.width)  *  2 - 1,
      -((e.clientY - rect.top) / rect.height) *  2 + 1,
    )
    _raycaster.setFromCamera(_ndc, camera)
  }

  // ── Rebuild ────────────────────────────────────────────────────────────────

  /**
   * @param {object|null} design
   * @param {Record<string,{start:number[],end:number[],samples:number[][]}>|null} helixAxes
   *   Deformed axis positions from store.currentHelixAxes.  When provided, rings
   *   are placed at the deformed endpoint positions with deformed axis orientation.
   *   offsetNm still uses original axis coordinates for backend compatibility.
   */
  function _rebuild(design, helixAxes) {
    for (const { ringMesh, hitMesh, labelSprite } of _ends) {
      ringMesh.material.dispose()
      hitMesh.material.dispose()
      if (labelSprite) {
        labelSprite.material.map?.dispose()
        labelSprite.material.dispose()
        _group.remove(labelSprite)
      }
      _group.remove(ringMesh)
      _group.remove(hitMesh)
    }
    _ends       = []
    _hoveredIdx = -1
    _pendingIdx = -1
    _pendingPos = null

    if (!design?.helices?.length) return

    const helices = design.helices

    // Build deformed-position lookup so _isEndFree can compare deformed endpoints
    const deformedPos = {}  // helix_id → { start: THREE.Vector3, end: THREE.Vector3 }
    for (const h of helices) {
      const axDef = helixAxes?.[h.id]
      deformedPos[h.id] = {
        start: axDef ? new THREE.Vector3(...axDef.start)
                     : new THREE.Vector3(h.axis_start.x, h.axis_start.y, h.axis_start.z),
        end:   axDef ? new THREE.Vector3(...axDef.end)
                     : new THREE.Vector3(h.axis_end.x,   h.axis_end.y,   h.axis_end.z),
      }
    }

    function _isEndFreeDeformed(hId, testPos) {
      for (const h of helices) {
        if (h.id === hId) continue
        const dp = deformedPos[h.id]
        if (dp.start.distanceTo(testPos) < TOL) return false
        if (dp.end.distanceTo(testPos)   < TOL) return false
      }
      return true
    }

    for (const h of helices) {
      const axDef  = helixAxes?.[h.id]
      const dp     = deformedPos[h.id]
      const plane  = _planeFromHelixId(h.id)

      // Straight-axis fallback direction (used when no samples available)
      const straightDir = dp.end.clone().sub(dp.start).normalize()

      // Pair: [deformed 3-D position, original topological endpoint (for offsetNm), isStart]
      const endpointPairs = [
        { deformed: dp.start, original: h.axis_start, isStart: true  },
        { deformed: dp.end,   original: h.axis_end,   isStart: false },
      ]

      for (const { deformed, original, isStart } of endpointPairs) {
        if (!_isEndFreeDeformed(h.id, deformed)) continue

        // Per-endpoint tangent: start uses first segment, end uses last segment
        let axisDir
        if (axDef?.samples?.length >= 2) {
          const n = axDef.samples.length
          if (isStart) {
            axisDir = new THREE.Vector3(...axDef.samples[1])
              .sub(new THREE.Vector3(...axDef.samples[0])).normalize()
          } else {
            axisDir = new THREE.Vector3(...axDef.samples[n - 1])
              .sub(new THREE.Vector3(...axDef.samples[n - 2])).normalize()
          }
        } else {
          axisDir = straightDir
        }
        const quat = new THREE.Quaternion().setFromUnitVectors(
          new THREE.Vector3(0, 0, 1),
          axisDir,
        )

        // offsetNm uses original axis coordinates — backend continuation lookup relies on these
        const offsetNm = _offsetFromEndpoint(original, plane)

        const ringMat = new THREE.MeshBasicMaterial({
          color:       RING_COLOR,
          transparent: true,
          opacity:     0,
          side:        THREE.DoubleSide,
          depthWrite:  false,
        })
        const ringMesh = new THREE.Mesh(_ringGeo, ringMat)
        ringMesh.position.copy(deformed)
        ringMesh.quaternion.copy(quat)

        const hitMat = new THREE.MeshBasicMaterial({
          transparent: true,
          opacity:     0,
          side:        THREE.DoubleSide,
          depthWrite:  false,
        })
        const hitMesh = new THREE.Mesh(_hitGeo, hitMat)
        hitMesh.position.copy(deformed)
        hitMesh.quaternion.copy(quat)

        const sourceBp = isStart ? 0 : h.length_bp

        // Number label — shows helix index (1-based) as a billboard sprite.
        // Offset outward (away from helix body) to clear the axis arrow cone:
        //   isStart: axisDir points INTO helix → negate to go outward
        //   isEnd:   axisDir points OUT of helix → use as-is
        // The cone head (AXIS_HEAD_LEN=0.55 nm, centered at endpoint) extends
        // 0.275 nm beyond the endpoint; sprite radius ≈ 0.45 nm → need > 0.72 nm clear.
        const helixNum = design.helices.indexOf(h)
        const labelSprite = _makeNumberSprite(helixNum)
        const outward = isStart ? axisDir.clone().negate() : axisDir.clone()
        labelSprite.position.copy(deformed).addScaledVector(outward, 1.0)
        labelSprite.material.depthTest = false
        labelSprite.renderOrder = 5
        const showLabels = store.getState().showHelixLabels
        labelSprite.material.opacity = showLabels ? LABEL_OPACITY : 0

        _group.add(ringMesh)
        _group.add(hitMesh)
        _group.add(labelSprite)
        _ends.push({
          ringMesh, hitMesh, labelSprite, plane, offsetNm, helixId: h.id, sourceBp,
          isStart,
          // bp_index of the terminus particle (for physics position lookup).
          physicsBp: isStart ? 0 : Math.max(0, h.length_bp - 1),
          // Store original world positions for unfold/deform translation.
          basePos:      deformed.clone(),
          baseLabelPos: labelSprite.position.clone(),
          baseQuat:     ringMesh.quaternion.clone(),  // deformed orientation (t=1 anchor)
        })
      }
    }

    // ── Interior strand endpoints (gap boundaries within merged helices) ──────
    // Strand 5'/3' termini that fall strictly inside a helix (not at axis_start
    // or axis_end) get a selectable ring so users can trigger continuation from
    // within an existing gap.

    const helixById    = new Map(design.helices.map(h => [h.id, h]))
    const seenInterior = new Set()   // deduplicate: "helixId:bp"

    for (const strand of design.strands) {
      const checks = [
        { helixId: strand.domains[0]?.helix_id,    bp: strand.domains[0]?.start_bp    },
        { helixId: strand.domains.at(-1)?.helix_id, bp: strand.domains.at(-1)?.end_bp },
      ]
      for (const { helixId, bp } of checks) {
        if (helixId == null || bp == null) continue
        const h = helixById.get(helixId)
        if (!h) continue
        const key = `${helixId}:${bp}`
        if (seenInterior.has(key)) continue

        const axDef  = helixAxes?.[helixId]
        const start3 = axDef
          ? new THREE.Vector3(...axDef.start)
          : new THREE.Vector3(h.axis_start.x, h.axis_start.y, h.axis_start.z)
        const end3   = axDef
          ? new THREE.Vector3(...axDef.end)
          : new THREE.Vector3(h.axis_end.x, h.axis_end.y, h.axis_end.z)
        const axisLen = start3.distanceTo(end3)
        // Use physical RISE to compute t — correct for caDNAno imports where
        // helix.length_bp is the full vstrand array size, not the active bp span.
        // (For native helices axisLen = (length_bp-1)*RISE, so this is exact.)
        const t = axisLen > 0 ? (bp - h.bp_start) * BDNA_RISE_PER_BP / axisLen : 0
        // t≤0 or t≥1 means bp is at (or beyond) a physical axis endpoint — the
        // exterior loop above already places a ring there.
        if (t <= 0 || t >= 1) continue
        seenInterior.add(key)

        const pos = start3.clone().lerp(end3, t)
        const plane   = _planeFromHelixId(helixId)
        const axisDir = end3.clone().sub(start3).normalize()
        const quat    = new THREE.Quaternion().setFromUnitVectors(
          new THREE.Vector3(0, 0, 1), axisDir,
        )
        const offsetNm = _offsetFromEndpoint({ x: pos.x, y: pos.y, z: pos.z }, plane)

        const ringMat = new THREE.MeshBasicMaterial({
          color: RING_COLOR, transparent: true, opacity: 0,
          side: THREE.DoubleSide, depthWrite: false,
        })
        const ringMesh = new THREE.Mesh(_ringGeo, ringMat)
        ringMesh.position.copy(pos)
        ringMesh.quaternion.copy(quat)

        const hitMat = new THREE.MeshBasicMaterial({
          transparent: true, opacity: 0,
          side: THREE.DoubleSide, depthWrite: false,
        })
        const hitMesh = new THREE.Mesh(_hitGeo, hitMat)
        hitMesh.position.copy(pos)
        hitMesh.quaternion.copy(quat)

        _group.add(ringMesh)
        _group.add(hitMesh)
        _ends.push({
          ringMesh, hitMesh, labelSprite: null,
          plane, offsetNm, helixId,
          sourceBp:  bp - h.bp_start,
          isStart:   false,
          isInterior: true,
          interiorT:  t,
          physicsBp:  bp - h.bp_start,
          basePos:      pos.clone(),
          baseLabelPos: pos.clone(),
          baseQuat:     quat.clone(),
        })
      }
    }
  }

  function _getHitIndex(e) {
    if (!_ends.length) return -1
    _setNDC(e)
    const hitMeshes = _ends.map(r => r.hitMesh)
    const hits      = _raycaster.intersectObjects(hitMeshes)
    if (!hits.length) return -1
    return hitMeshes.indexOf(hits[0].object)
  }

  function _setHovered(idx) {
    if (idx === _hoveredIdx) return
    // Restore previous
    if (_hoveredIdx >= 0) {
      _ends[_hoveredIdx].ringMesh.material.opacity = 0
      if (_ends[_hoveredIdx].labelSprite)
        _ends[_hoveredIdx].labelSprite.material.opacity =
          store.getState().showHelixLabels ? LABEL_OPACITY : 0
    }
    _hoveredIdx = idx
    if (_hoveredIdx >= 0) {
      _ends[_hoveredIdx].ringMesh.material.opacity = RING_OPACITY
      if (_ends[_hoveredIdx].labelSprite)
        _ends[_hoveredIdx].labelSprite.material.opacity = LABEL_OPACITY_H
    }
  }

  function _updateLabelVisibility() {
    const show = store.getState().showHelixLabels
    for (const { labelSprite } of _ends) {
      if (!labelSprite) continue
      labelSprite.material.opacity = show ? LABEL_OPACITY : 0
    }
    // Re-apply hover emphasis if still hovering
    if (_hoveredIdx >= 0 && show && _ends[_hoveredIdx]?.labelSprite) {
      _ends[_hoveredIdx].labelSprite.material.opacity = LABEL_OPACITY_H
    }
  }

  // ── Store subscription ────────────────────────────────────────────────────

  store.subscribe((newState, prevState) => {
    if (
      newState.currentDesign    !== prevState.currentDesign ||
      newState.currentHelixAxes !== prevState.currentHelixAxes
    ) {
      // Skip rebuild when currentDesign changes due to a cluster-transform patch
      // (metadata-only: same topology, no geometry update).  The cluster gizmo
      // positions blunt ends live via applyClusterTransform; a rebuild here would
      // reset them to the stale pre-transform currentHelixAxes positions.
      if (newState.currentHelixAxes === prevState.currentHelixAxes) {
        const p = prevState.currentDesign, n = newState.currentDesign
        if (p && n &&
            p.helices.length         === n.helices.length       &&
            p.strands.length         === n.strands.length       &&
            p.crossovers.length      === n.crossovers.length    &&
            p.deformations.length    === n.deformations.length  &&
            p.extensions.length      === n.extensions.length    &&
            p.overhangs.length       === n.overhangs.length     &&
            p.crossover_bases.length === n.crossover_bases.length) return
      }
      _rebuild(newState.currentDesign, newState.currentHelixAxes)
      // After rebuild, re-apply unfold offsets if the unfold view is active so
      // that label sprites land at their unfolded positions (not 3D positions).
      // Skip when cadnano mode is active — cadnano_view.reapplyPositions() handles
      // bead/overlay positions and must not be overwritten by unfold offsets.
      if (!store.getState().cadnanoActive) getUnfoldView?.()?.reapplyIfActive()
    } else if (
      newState.toolFilters       !== prevState.toolFilters ||
      newState.showHelixLabels   !== prevState.showHelixLabels
    ) {
      _updateLabelVisibility()
    }
  })

  // ── Event handlers ────────────────────────────────────────────────────────

  function _isBlocked() {
    return isDisabled?.() || !store.getState().toolFilters.bluntEnds
  }

  function _onPointerMove(e) {
    if (_isBlocked()) { _setHovered(-1); return }
    _setHovered(_getHitIndex(e))
  }

  function _fireLeftMenu(idx) {
    const { plane, offsetNm, helixId, sourceBp } = _ends[idx]
    const design = store.getState().currentDesign
    const hasDeformations = !!(design?.deformations?.length)
    onBluntEndClick?.({ plane, offsetNm, helixId, sourceBp, hasDeformations })
  }

  function _fireRightMenu(idx, x, y) {
    const { plane, offsetNm, helixId, sourceBp } = _ends[idx]
    const design = store.getState().currentDesign
    const hasDeformations = !!(design?.deformations?.length)
    onBluntEndRightClick?.({ plane, offsetNm, helixId, sourceBp, hasDeformations, clientX: x, clientY: y })
  }

  function _onPointerDown(e) {
    if (_isBlocked()) return
    const idx = _hoveredIdx
    if (idx < 0) return

    if (e.button === 0) {
      // Intercept left-click: prevent OrbitControls from starting a drag
      e.stopImmediatePropagation()
      _pendingIdx = idx
      _pendingPos = { x: e.clientX, y: e.clientY }
    } else if (e.button === 2) {
      // Track right-click for context menu
      _pendingRightIdx = idx
      _pendingRightPos = { x: e.clientX, y: e.clientY }
    }
  }

  function _onPointerUp(e) {
    if (e.button !== 0) return
    if (_pendingIdx < 0) return
    const idx = _pendingIdx
    _pendingIdx = -1
    const moved = _pendingPos
      ? Math.hypot(e.clientX - _pendingPos.x, e.clientY - _pendingPos.y)
      : 999
    _pendingPos = null
    if (moved > 4) return
    e.stopImmediatePropagation()
    _fireLeftMenu(idx)
  }

  function _onContextMenu(e) {
    if (e.ctrlKey) return
    if (_isBlocked()) return
    if (_pendingRightIdx < 0) return
    const idx = _pendingRightIdx
    _pendingRightIdx = -1
    const moved = _pendingRightPos
      ? Math.hypot(e.clientX - _pendingRightPos.x, e.clientY - _pendingRightPos.y)
      : 999
    _pendingRightPos = null
    if (moved > 4) return
    e.preventDefault()
    e.stopImmediatePropagation()
    _fireRightMenu(idx, e.clientX, e.clientY)
  }

  // Hover uses normal bubble phase (needs to fire even when nothing intercepts)
  canvas.addEventListener('pointermove',   _onPointerMove)
  // Down/up must be capture phase so we can preventDefault orbit before it registers
  canvas.addEventListener('pointerdown',   _onPointerDown, { capture: true })
  canvas.addEventListener('pointerup',     _onPointerUp,   { capture: true })
  canvas.addEventListener('contextmenu',   _onContextMenu, { capture: true })

  return {
    clear() { _rebuild(null, null) },

    /**
     * Translate all rings, hit disks, and label sprites by their per-helix
     * unfold offset at lerp factor t.  Called every animation frame by unfold_view.js.
     *
     * @param {Map<string, THREE.Vector3>} helixOffsets  helix_id → offset vector
     * @param {number} t  lerp factor in [0, 1]
     */
    /**
     * Lerp rings and label sprites from straight to deformed axis endpoint positions.
     * @param {Map<string, {start:THREE.Vector3, end:THREE.Vector3}>} straightAxesMap
     * @param {number} t  lerp factor 0=straight, 1=deformed
     */
    applyDeformLerp(straightAxesMap, t) {
      for (const end of _ends) {
        const sa = straightAxesMap?.get(end.helixId)
        if (!sa) continue
        const sp = end.isInterior
          ? sa.start.clone().lerp(sa.end, end.interiorT)
          : (end.isStart ? sa.start : sa.end)
        const lerped = {
          x: sp.x + (end.basePos.x - sp.x) * t,
          y: sp.y + (end.basePos.y - sp.y) * t,
          z: sp.z + (end.basePos.z - sp.z) * t,
        }
        end.ringMesh.position.set(lerped.x, lerped.y, lerped.z)
        end.hitMesh.position.set(lerped.x, lerped.y, lerped.z)
        if (end.isInterior) continue   // no label or orientation slerp for interior ends
        // Label keeps same world-space offset from the ring
        const lOff = {
          x: end.baseLabelPos.x - end.basePos.x,
          y: end.baseLabelPos.y - end.basePos.y,
          z: end.baseLabelPos.z - end.basePos.z,
        }
        // Slerp ring/hit orientation: straight axis direction (t=0) → deformed (t=1).
        _bluntAxisDir.copy(sa.end).sub(sa.start).normalize()
        _bluntStraightQ.setFromUnitVectors(_Z_HAT, _bluntAxisDir)
        _bluntLerpedQ.copy(_bluntStraightQ).slerp(end.baseQuat, t)
        end.ringMesh.quaternion.copy(_bluntLerpedQ)
        end.hitMesh.quaternion.copy(_bluntLerpedQ)
        // Lerp the label offset direction between straight outward (t=0) and deformed (t=1).
        // Straight outward: isStart → negate axis (points away from helix), isEnd → axis as-is.
        const lOffLen = Math.sqrt(lOff.x * lOff.x + lOff.y * lOff.y + lOff.z * lOff.z)
        const sign    = end.isStart ? -1 : 1
        _bluntLabelOff.set(
          (sign * _bluntAxisDir.x + (lOff.x / lOffLen - sign * _bluntAxisDir.x) * t) * lOffLen,
          (sign * _bluntAxisDir.y + (lOff.y / lOffLen - sign * _bluntAxisDir.y) * t) * lOffLen,
          (sign * _bluntAxisDir.z + (lOff.z / lOffLen - sign * _bluntAxisDir.z) * t) * lOffLen,
        )
        end.labelSprite.position.set(
          lerped.x + _bluntLabelOff.x,
          lerped.y + _bluntLabelOff.y,
          lerped.z + _bluntLabelOff.z,
        )
      }
    },

    applyUnfoldOffsets(helixOffsets, t, straightAxesMap) {
      for (const end of _ends) {
        const off = helixOffsets.get(end.helixId)
        const ox  = off ? off.x * t : 0
        const oy  = off ? off.y * t : 0
        const oz  = off ? off.z * t : 0
        // Use straight axis endpoint as base when available.
        let bx, by, bz
        if (straightAxesMap) {
          const sa = straightAxesMap.get(end.helixId)
          const sp = sa
            ? (end.isInterior
                ? sa.start.clone().lerp(sa.end, end.interiorT)
                : (end.isStart ? sa.start : sa.end))
            : null
          bx = sp ? sp.x : end.basePos.x
          by = sp ? sp.y : end.basePos.y
          bz = sp ? sp.z : end.basePos.z
        } else {
          bx = end.basePos.x; by = end.basePos.y; bz = end.basePos.z
        }
        // Preserve the original world-space label-to-ring offset vector.
        const lox = end.baseLabelPos.x - end.basePos.x
        const loy = end.baseLabelPos.y - end.basePos.y
        const loz = end.baseLabelPos.z - end.basePos.z
        end.ringMesh.position.set(bx + ox, by + oy, bz + oz)
        end.hitMesh.position.set(bx + ox, by + oy, bz + oz)
        end.labelSprite?.position.set(bx + ox + lox, by + oy + loy, bz + oz + loz)
      }
    },

    /**
     * Move rings and labels to follow XPBD backbone positions.
     * Approximates the helix terminus position as the average of the FORWARD and
     * REVERSE backbone beads at the terminus bp_index.
     *
     * @param {Array<{helix_id,bp_index,direction,backbone_position}>} updates
     */
    applyPhysicsPositions(updates) {
      const posMap = new Map()
      for (const u of updates) {
        posMap.set(`${u.helix_id}:${u.bp_index}:${u.direction}`, u.backbone_position)
      }
      for (const end of _ends) {
        if (end.isInterior) continue   // no XPBD particle at interior gap boundary
        const f = posMap.get(`${end.helixId}:${end.physicsBp}:FORWARD`)
        const r = posMap.get(`${end.helixId}:${end.physicsBp}:REVERSE`)
        let px, py, pz
        if (f && r) {
          px = (f[0] + r[0]) * 0.5; py = (f[1] + r[1]) * 0.5; pz = (f[2] + r[2]) * 0.5
        } else if (f || r) {
          const p = f ?? r; px = p[0]; py = p[1]; pz = p[2]
        } else {
          continue  // no physics particle at this terminus — leave unchanged
        }
        // Preserve the label's world-space offset from the ring.
        const lox = end.baseLabelPos.x - end.basePos.x
        const loy = end.baseLabelPos.y - end.basePos.y
        const loz = end.baseLabelPos.z - end.basePos.z
        end.ringMesh.position.set(px, py, pz)
        end.hitMesh.position.set(px, py, pz)
        end.labelSprite.position.set(px + lox, py + loy, pz + loz)
      }
    },

    /**
     * Snap all rings and labels back to their geometric positions (basePos from
     * last rebuild).  Called when physics is toggled off.
     */
    revertPhysics() {
      for (const end of _ends) {
        end.ringMesh.position.copy(end.basePos)
        end.hitMesh.position.copy(end.basePos)
        end.labelSprite?.position.copy(end.baseLabelPos)
        end.ringMesh.quaternion.copy(end.baseQuat)
        end.hitMesh.quaternion.copy(end.baseQuat)
      }
    },

    /**
     * Snapshot current ring/label positions for the given cluster helices.
     * Must be called once before applyClusterTransform begins (mirrors helix_renderer API).
     */
    captureClusterBase(helixIds, append = false) {
      const helixSet = new Set(helixIds)
      if (!append) _cbEnds.clear()
      for (const end of _ends) {
        if (!helixSet.has(end.helixId)) continue
        _cbEnds.set(end, {
          pos:      end.ringMesh.position.clone(),
          labelPos: end.labelSprite ? end.labelSprite.position.clone() : null,
          quat:     end.ringMesh.quaternion.clone(),
        })
      }
    },

    /**
     * Apply an incremental cluster transform to rings and labels.
     * Mirrors the helix_renderer signature so callers can drive both in parallel.
     */
    applyClusterTransform(helixIds, centerVec, dummyPosVec, incrRotQuat) {
      const helixSet = new Set(helixIds)
      for (const end of _ends) {
        if (!helixSet.has(end.helixId)) continue
        const snap = _cbEnds.get(end)
        if (!snap) continue
        // Transform ring and hit position
        _bluntClusterV.copy(snap.pos).sub(centerVec).applyQuaternion(incrRotQuat)
        const nx = _bluntClusterV.x + dummyPosVec.x
        const ny = _bluntClusterV.y + dummyPosVec.y
        const nz = _bluntClusterV.z + dummyPosVec.z
        end.ringMesh.position.set(nx, ny, nz)
        end.hitMesh.position.set(nx, ny, nz)
        // Rotate ring/hit orientation
        _bluntClusterQ.multiplyQuaternions(incrRotQuat, snap.quat)
        end.ringMesh.quaternion.copy(_bluntClusterQ)
        end.hitMesh.quaternion.copy(_bluntClusterQ)
        // Transform label position
        if (snap.labelPos && end.labelSprite) {
          _bluntClusterV.copy(snap.labelPos).sub(centerVec).applyQuaternion(incrRotQuat)
          end.labelSprite.position.set(
            _bluntClusterV.x + dummyPosVec.x,
            _bluntClusterV.y + dummyPosVec.y,
            _bluntClusterV.z + dummyPosVec.z,
          )
        }
      }
    },

    /** Returns {mesh, helixId, isStart, label} for each end — used by debug overlay. */
    getHitMeshes() {
      return _ends.map(e => ({
        mesh:    e.hitMesh,
        helixId: e.helixId,
        isStart: e.isStart,
        label:   e.labelSprite?.userData?.text ?? null,
      }))
    },

    dispose() {
      canvas.removeEventListener('pointermove',   _onPointerMove)
      canvas.removeEventListener('pointerdown',   _onPointerDown, { capture: true })
      canvas.removeEventListener('pointerup',     _onPointerUp,   { capture: true })
      canvas.removeEventListener('contextmenu',   _onContextMenu, { capture: true })
      for (const { ringMesh, hitMesh, labelSprite } of _ends) {
        ringMesh.material.dispose()
        hitMesh.material.dispose()
        if (labelSprite) {
          labelSprite.material.map?.dispose()
          labelSprite.material.dispose()
          _group.remove(labelSprite)
        }
        _group.remove(ringMesh)
        _group.remove(hitMesh)
      }
      _ends = []
      _ringGeo.dispose()
      _hitGeo.dispose()
      scene.remove(_group)
    },
  }
}
