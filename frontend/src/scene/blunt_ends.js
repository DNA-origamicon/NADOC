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

const RING_INNER      = 0.35
const RING_OUTER      = 1.15
const HIT_RADIUS      = RING_OUTER * 1.25   // slightly larger than ring for comfortable clicking
const RING_SEGS       = 32
const RING_COLOR      = 0x58a6ff
const RING_OPACITY    = 0.45
const TOL             = 0.001               // nm — two endpoints at the same position
const LABEL_OPACITY   = 0.72               // always-visible label opacity
const LABEL_OPACITY_H = 1.00               // label opacity when ring is hovered

export function initBluntEnds(scene, camera, canvas, { onBluntEndClick, onBluntEndRightClick, isDisabled } = {}) {

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
        const helixNum = design.helices.indexOf(h) + 1
        const labelSprite = _makeNumberSprite(helixNum)
        const outward = isStart ? axisDir.clone().negate() : axisDir.clone()
        labelSprite.position.copy(deformed).addScaledVector(outward, 1.0)
        labelSprite.material.depthTest = false
        labelSprite.renderOrder = 5
        const showLabels = !isDisabled?.() && store.getState().selectableTypes?.bluntEnds
        labelSprite.material.opacity = showLabels ? LABEL_OPACITY : 0

        _group.add(ringMesh)
        _group.add(hitMesh)
        _group.add(labelSprite)
        _ends.push({ ringMesh, hitMesh, labelSprite, plane, offsetNm, helixId: h.id, sourceBp })
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
        _ends[_hoveredIdx].labelSprite.material.opacity = LABEL_OPACITY
    }
    _hoveredIdx = idx
    if (_hoveredIdx >= 0) {
      _ends[_hoveredIdx].ringMesh.material.opacity = RING_OPACITY
      if (_ends[_hoveredIdx].labelSprite)
        _ends[_hoveredIdx].labelSprite.material.opacity = LABEL_OPACITY_H
    }
  }

  function _updateLabelVisibility() {
    const show = !_isBlocked()
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
      _rebuild(newState.currentDesign, newState.currentHelixAxes)
    } else if (newState.selectableTypes !== prevState.selectableTypes) {
      _updateLabelVisibility()
    }
  })

  // ── Event handlers ────────────────────────────────────────────────────────

  function _isBlocked() {
    return isDisabled?.() || !store.getState().selectableTypes.bluntEnds
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
