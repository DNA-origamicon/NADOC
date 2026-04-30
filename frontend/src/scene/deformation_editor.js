/**
 * Deformation Editor — Bend and Twist tool state machine.
 *
 * State machine:
 *   IDLE
 *   AWAITING_A   — ghost plane A follows cursor
 *   A_PLACED     — plane A solid; ghost B follows cursor
 *   BOTH         — both planes placed; popup open; live preview active
 *
 * Interaction:
 *   • Click near helix axis to place plane A, then plane B
 *   • Drag the sphere handle on a placed plane to reposition it
 *   • Orbit / pan always works when not dragging a handle
 *
 * Visual:
 *   • All geometry fades to 0.15 opacity while tool is active
 *   • Ghost planes: translucent quads that track cursor bp
 *   • Solid planes: semi-opaque quads with edge outline + drag handle
 *   • Plane A: yellow-white; Plane B: orange
 */

import * as THREE from 'three'
import { store }          from '../state/store.js'
import * as api           from '../api/client.js'
import { BDNA_RISE_PER_BP } from '../constants.js'
import { showPersistentToast, dismissToast } from '../ui/toast.js'

// ── Constants ─────────────────────────────────────────────────────────────────

const PLANE_SIZE = 8.0   // nm — half-extent of each plane quad (full size = 2×)

// ── State ─────────────────────────────────────────────────────────────────────

const STATE = { IDLE: 'IDLE', AWAITING_A: 'AWAITING_A', A_PLACED: 'A_PLACED', BOTH: 'BOTH' }

let _state   = STATE.IDLE
let _toolType = null      // 'twist' | 'bend'
let _planeA   = null      // { bp }
let _planeB   = null      // { bp }
let _previewOpId       = null
let _previewPending    = false  // true while an addDeformation network call is in-flight
let _lastPreviewParams = null   // params from the most recent previewDeformation call
let _previewOriginalAxes = null // currentHelixAxes snapshot before preview was applied
let _editMode          = false  // true when opened via startToolForEdit; Esc exits directly

// Three.js plumbing
let _scene          = null
let _camera         = null
let _canvas         = null
let _controls       = null
let _renderer       = null
let _onExit         = null
let _onPlaneDragEnd = null  // (which: 'A'|'B', bp: number) => void

// Scene objects — ghost planes
let _ghostA = null
let _ghostB = null

// Scene objects — solid planes (each is a THREE.Group)
let _solidA = null   // { group, beadMeshes: [sphere, coneFwd, coneBack] }
let _solidB = null

// Drag state
let _dragging       = null    // null | 'A' | 'B'
let _dragBillboard  = new THREE.Plane()
let _dragStartPoint = new THREE.Vector3()
let _dragStartBp    = 0

// Hover bead — small sphere shown on the nearest helix axis while in AWAITING_A state
let _hoverBead = null

const _raycaster = new THREE.Raycaster()
const _ndc       = new THREE.Vector2()
const _tmpVec    = new THREE.Vector3()

// ── Public API ────────────────────────────────────────────────────────────────

export function initDeformationEditor(scene, camera, canvas, controls, designRenderer, onExit, onPlaneDragEnd = null) {
  _scene          = scene
  _camera         = camera
  _canvas         = canvas
  _controls       = controls
  _renderer       = designRenderer
  _onExit         = onExit
  _onPlaneDragEnd = onPlaneDragEnd
}

export function startTool(toolType) {
  if (!_scene) return
  _toolType = toolType
  _setState(STATE.AWAITING_A)
}

/**
 * Start the tool with planes pre-set for a domain end at (helixId, bp, openSide).
 *
 * openSide == -1 (start end): place only plane A at arm global start.
 * openSide == +1 (end end):   place A at arm global start, B at bp.
 *
 * Skips the "click to place" steps and opens the parameter popup immediately.
 */
export function startToolAtBp(toolType, helixId, bp, openSide) {
  if (!_scene) return
  _toolType = toolType
  _setState(STATE.AWAITING_A)

  const helices    = _getHelixAxisData()
  const armBpStart = helices.length ? Math.min(...helices.map(h => h.bpStart)) : 0

  if (openSide < 0) {
    // Start domain end — place only A; B is placed by user or auto-span
    _placeA(armBpStart)
  } else {
    // End domain end — A at global arm start, B at the domain end bp
    _planeA = { bp: armBpStart }
    _hideGhost(true)
    _solidA = _makeSolidPlane(armBpStart, 0xffffaa, 'A')
    _scene.add(_solidA.group)
    _setState(STATE.A_PLACED)
    _placeB(bp)
  }
}

/**
 * Reopen the editor pre-loaded with an existing op's plane positions.
 * Skips the "click to place" steps and opens the popup immediately.
 * In edit mode, Escape from BOTH exits directly (skipping the A_PLACED step).
 *
 * @param {'twist'|'bend'} toolType
 * @param {number} globalBpA  - plane A global bp index
 * @param {number} globalBpB  - plane B global bp index
 */
export function startToolForEdit(toolType, globalBpA, globalBpB) {
  if (!_scene) return
  _editMode = true
  _toolType = toolType
  _setState(STATE.AWAITING_A)
  // Place A manually (mirrors startToolAtBp's second branch)
  _planeA = { bp: globalBpA }
  _hideGhost(true)
  _solidA = _makeSolidPlane(globalBpA, 0xffffaa, 'A')
  _scene.add(_solidA.group)
  _setState(STATE.A_PLACED)
  // Place B — transitions to STATE.BOTH → popup opens via _watchDeformState in main.js
  _placeB(globalBpB)
}

export function isActive() {
  return _state !== STATE.IDLE
}

/** Force-exit the tool from any state (e.g. File > New). */
export function exitTool() {
  if (_state !== STATE.IDLE) _exitTool()
}

/**
 * Call from the canvas pointerup capture handler (main.js) BEFORE
 * stopImmediatePropagation so bead drag state is always cleaned up even
 * though the document bubble listener is blocked by the canvas capture.
 */
export function handlePointerUp() {
  if (_dragging) _onDocDragUp()
}

/** Returns true if the event was consumed (caller should stopImmediatePropagation). */
export function handlePointerDown(event) {
  if (_state === STATE.IDLE || event.button !== 0) return false

  _setNDC(event)

  // ── Plane face drag — clicking anywhere on a solid plane starts a drag ───
  const planeTargets = []
  if (_solidA?.planeMesh) planeTargets.push({ mesh: _solidA.planeMesh, which: 'A' })
  if (_solidB?.planeMesh) planeTargets.push({ mesh: _solidB.planeMesh, which: 'B' })
  if (planeTargets.length) {
    const hits = _raycaster.intersectObjects(planeTargets.map(t => t.mesh))
    if (hits.length) {
      const which = planeTargets.find(t => t.mesh === hits[0].object)?.which
      if (which) {
        _dragging = which
        const planePos = which === 'A' ? _worldPosForBp(_planeA.bp) : _worldPosForBp(_planeB.bp)
        _camera.getWorldDirection(_tmpVec)
        _dragBillboard.setFromNormalAndCoplanarPoint(_tmpVec, planePos)
        _raycaster.ray.intersectPlane(_dragBillboard, _dragStartPoint)
        _dragStartBp = which === 'A' ? _planeA.bp : _planeB.bp
        if (_controls) _controls.enabled = false
        document.addEventListener('pointermove',   _onDocDragMove)
        document.addEventListener('pointerup',     _onDocDragUp)
        document.addEventListener('pointercancel', _onDocDragUp)
        return true
      }
    }
  }

  // ── Plane placement ──────────────────────────────────────────────────────
  const hit = _pickBpFull(event)
  if (!hit) return false
  const { bp } = hit

  _showHoverBead(null)

  if (_state === STATE.AWAITING_A) {
    _placeA(bp)
    return true
  } else if (_state === STATE.A_PLACED) {
    if (bp !== _planeA.bp) { _placeB(bp); return true }
  }
  return false
}

function _onDocDragMove(event) {
  _setNDC(event)
  if (_raycaster.ray.intersectPlane(_dragBillboard, _tmpVec)) {
    const bp = _pickBpFromPoint(_tmpVec)
    if (bp !== null) {
      if (_dragging === 'A' && _planeA) {
        _planeA.bp = bp
        _updateSolidPlane(_solidA, bp)
      } else if (_dragging === 'B' && _planeB) {
        _planeB.bp = bp
        _updateSolidPlane(_solidB, bp)
      }
      // Preview stays visible during drag — refreshed on pointerup
    }
  }
}

function _onDocDragUp() {
  const which = _dragging  // save before clearing
  _dragging = null
  if (_controls) _controls.enabled = true
  document.removeEventListener('pointermove',   _onDocDragMove)
  document.removeEventListener('pointerup',     _onDocDragUp)
  document.removeEventListener('pointercancel', _onDocDragUp)

  // Notify caller of the final plane position so popup inputs can be updated
  if (which === 'A' && _planeA) _onPlaneDragEnd?.('A', _planeA.bp)
  else if (which === 'B' && _planeB) _onPlaneDragEnd?.('B', _planeB.bp)

  _refreshPreview()
}

/**
 * Delete the current preview op and re-fire previewDeformation with the latest
 * params and (potentially updated) plane positions.  Safe to call from both
 * plane drag-end and programmatic plane repositioning.
 */
function _refreshPreview() {
  if (_previewOpId && _lastPreviewParams) {
    const staleOpId = _previewOpId
    const params    = _lastPreviewParams
    _previewOpId = null
    // Do NOT call clearGhost() here — keep the pre-deform ghost intact so the
    // scene stays stable while the delete resolves.
    showPersistentToast('Generating preview…')
    api.deleteDeformation(staleOpId, /*preview=*/true)
      .then(() => previewDeformation(params))
      .catch(() => { dismissToast() })
  }
}

export function handlePointerMove(event) {
  if (_state === STATE.IDLE || _dragging) return  // drag handled by document listener

  // ── Ghost plane tracking + hover bead ────────────────────────────────────
  const hit = _pickBpFull(event)
  if (!hit) {
    _hideGhost(true); _hideGhost(false)
    _showHoverBead(null)
    return
  }
  const { bp } = hit
  if (_state === STATE.AWAITING_A) {
    _showGhost(true, bp)
    _showHoverBead(hit)
  } else if (_state === STATE.A_PLACED) {
    _showHoverBead(null)
    if (bp !== _planeA.bp) _showGhost(false, bp)
    else _hideGhost(false)
  }
}


export function handleEscape() {
  if (_state === STATE.IDLE) return
  if (_state === STATE.BOTH) {
    if (_editMode) {
      // In edit mode, Escape from BOTH exits directly (no A_PLACED intermediate).
      _exitTool()
    } else {
      _clearPreviewSession()
      if (_solidB) { _scene.remove(_solidB.group); _solidB = null }
      _planeB = null
      _setState(STATE.A_PLACED)
    }
  } else {
    _exitTool()
  }
}

// Called by popup when confirmed
export async function confirmDeformation(params) {
  if (_state !== STATE.BOTH || !_planeA || !_planeB) return
  _clearPreviewSession()
  if (_previewOpId) {
    await api.deleteDeformation(_previewOpId, /*preview=*/true)
    _previewOpId = null
  }
  const a = Math.min(_planeA.bp, _planeB.bp)
  const b = Math.max(_planeA.bp, _planeB.bp)
  await api.addDeformation(_toolType, a, b, params, [], /*preview=*/false, _effectiveClusterId())
  _exitTool()
}

// Called by popup on cancel — keep plane A, remove B so user can re-select
export function cancelDeformation() {
  _clearPreviewSession()
  if (_solidB) { _scene.remove(_solidB.group); _solidB = null }
  _planeB = null
  _setState(STATE.A_PLACED)
}

// Called by popup when preview params change
export async function previewDeformation(params) {
  if (_state !== STATE.BOTH || !_planeA || !_planeB) return
  _lastPreviewParams = params
  const a = Math.min(_planeA.bp, _planeB.bp)
  const b = Math.max(_planeA.bp, _planeB.bp)
  if (_previewOpId) {
    showPersistentToast('Generating preview…')
    await api.updateDeformation(_previewOpId, params)
    dismissToast()
  } else if (_previewPending) {
    // An addDeformation is already in-flight. Latest params are stored in
    // _lastPreviewParams and will be flushed as an update once it resolves.
    return
  } else {
    // Snapshot axes and capture ghost only once per preview session.
    // The drag auto-refresh calls this again with _previewOriginalAxes already
    // set — don't re-capture or the delete→rebuild cycle will replace the
    // pre-deform ghost with the intermediate straight geometry.
    if (!_previewOriginalAxes) {
      _previewOriginalAxes = store.getState().currentHelixAxes
      _renderer?.captureGhost?.(0.5, 0.3)
    }
    _previewPending = true
    showPersistentToast('Generating preview…')
    await api.addDeformation(_toolType, a, b, params, [], /*preview=*/true, _effectiveClusterId())
    _previewPending = false
    // Only set ID and flush if we're still in an active preview session
    // (session may have been cancelled or confirmed while the add was in-flight).
    if (_state === STATE.BOTH) {
      const deformations = store.getState().currentDesign?.deformations ?? []
      if (deformations.length > 0) {
        _previewOpId = deformations[deformations.length - 1].id
      }
      // Flush any param updates that arrived while the add was in-flight.
      if (_previewOpId && _lastPreviewParams !== params) {
        await api.updateDeformation(_previewOpId, _lastPreviewParams)
      }
    }
    dismissToast()
  }
}

// ── State transitions ────────────────────────────────────────────────────────

function _setState(newState) {
  _state = newState
  if (newState === STATE.AWAITING_A) {
    _dimScene(true)
    store.setState({ deformToolActive: true })
  } else if (newState === STATE.IDLE) {
    _dimScene(false)
    store.setState({ deformToolActive: false })
    _removePlanes()
  }
  // STATE.A_PLACED and STATE.BOTH — no additional scene changes here
}

function _placeA(bp) {
  _planeA = { bp }
  _hideGhost(true)
  _solidA = _makeSolidPlane(bp, 0xffffaa, 'A')
  _scene.add(_solidA.group)
  _setState(STATE.A_PLACED)
  // Auto-place B at the farthest consistent position and go straight to BOTH
  _placeB(_defaultBpForPlaneB(bp))
}

function _placeB(bp) {
  _planeB = { bp }
  _hideGhost(false)
  // Replace any existing solid B (e.g. re-placing after Cancel)
  if (_solidB) { _scene.remove(_solidB.group); _solidB = null }
  _solidB = _makeSolidPlane(bp, 0xff9900, 'B')
  _scene.add(_solidB.group)
  _setState(STATE.BOTH)
}

/** Farthest bp from bpA where all helices that cover bpA are still present. */
function _defaultBpForPlaneB(bpA) {  // bpA is GLOBAL
  const helices = _getHelixAxisData()
  if (!helices.length) return bpA + 1
  const active = helices.filter(h => h.bpStart + h.lengthBp > bpA)
  if (!active.length) return bpA + 1
  const maxGlobalBp = Math.min(...active.map(h => h.bpStart + h.lengthBp)) - 1
  return maxGlobalBp > bpA ? maxGlobalBp : bpA + 1
}

// Cancel the active preview op and ghost, but intentionally keep
// _previewOriginalAxes — the drag auto-refresh path calls this then
// immediately re-previews, and the snapshot is still valid across that cycle.
function _cancelPreview() {
  _previewPending = false
  dismissToast()
  _renderer?.clearGhost?.()
  if (_previewOpId) {
    api.deleteDeformation(_previewOpId, /*preview=*/true).catch(() => {})
    _previewOpId = null
  }
}

// Full teardown of the preview session — call when truly leaving BOTH state
// (Escape, Cancel popup, Confirm, exit tool).
function _clearPreviewSession() {
  _cancelPreview()
  _previewOriginalAxes = null
}

function _exitTool() {
  _editMode = false
  _clearPreviewSession()
  _lastPreviewParams = null
  _planeA = null
  _planeB = null
  if (_dragging) _onDocDragUp()   // clean up document listeners + restore controls
  _showHoverBead(null)
  _setState(STATE.IDLE)
  if (_onExit) _onExit()
}

// ── NDC helper ────────────────────────────────────────────────────────────────

function _setNDC(event) {
  const rect = _canvas.getBoundingClientRect()
  _ndc.set(
    ((event.clientX - rect.left) / rect.width)  *  2 - 1,
    -((event.clientY - rect.top)  / rect.height) *  2 + 1,
  )
  _raycaster.setFromCamera(_ndc, _camera)
}

// ── Helix axis helpers ────────────────────────────────────────────────────────

/**
 * Returns the cluster ID to use for scoping this deformation session:
 *   - activeClusterId when the user has explicitly selected a cluster
 *   - the single cluster's id when exactly one cluster exists (no selection needed)
 *   - null otherwise (unscoped — all helices)
 */
function _effectiveClusterId() {
  const { activeClusterId, currentDesign } = store.getState()
  if (activeClusterId) return activeClusterId
  const clusters = currentDesign?.cluster_transforms ?? []
  return clusters.length === 1 ? clusters[0].id : null
}

function _getHelixAxisData() {
  const { currentDesign } = store.getState()
  if (!currentDesign) return []
  // While a preview is live, the store has the bent axes — use the original snapshot
  // so planes and hover beads track the undeformed contour.
  const helixAxes = _previewOriginalAxes ?? store.getState().currentHelixAxes

  // Restrict plane interaction to the effective cluster's helices so ghost planes,
  // picking, and centering are all scoped to the cluster being deformed.
  const cid = _effectiveClusterId()
  const clusterHelixIds = cid
    ? new Set(currentDesign.cluster_transforms?.find(c => c.id === cid)?.helix_ids ?? [])
    : null

  return currentDesign.helices
    .filter(h => !clusterHelixIds || clusterHelixIds.has(h.id))
    .map(h => {
      const axDef = helixAxes?.[h.id]
      return {
        id:       h.id,
        bpStart:  h.bp_start ?? 0,
        start:    axDef ? new THREE.Vector3(...axDef.start)
                        : new THREE.Vector3(h.axis_start.x, h.axis_start.y, h.axis_start.z),
        end:      axDef ? new THREE.Vector3(...axDef.end)
                        : new THREE.Vector3(h.axis_end.x,   h.axis_end.y,   h.axis_end.z),
        lengthBp: h.length_bp,
        samples:  axDef?.samples ?? null,
      }
    })
}

/**
 * Pick the nearest bp and helix from the current pointer event.
 * Returns { bp, helixId, axisPoint } or null.
 * For curved (deformed) helices, checks each sample segment individually.
 */
function _pickBpFull(event) {
  _setNDC(event)
  const rayOrigin = _raycaster.ray.origin
  const rayDir    = _raycaster.ray.direction
  const helices   = _getHelixAxisData()
  let bestBp = null, bestDist = Infinity, bestHelixId = null, bestAxisPoint = null

  // Reusable inner: ray-to-segment closest-approach (corrected two-line formula).
  // Returns { axisPoint, dist, t } where t is distance along segment from segStart.
  function _segClosest(segStart, segDir, segLen) {
    const w     = rayOrigin.clone().sub(segStart)
    const b     = rayDir.dot(segDir)     // d1·d2
    const d     = rayDir.dot(rayDir)     // d1·d1  (= 1 for normalised ray)
    const f     = w.dot(segDir)          // w·d2
    const denom = d - b * b              // d·e - b² where e = segDir·segDir = 1
    if (Math.abs(denom) < 1e-9) return null
    const tc       = (d * f - b * w.dot(rayDir)) / denom  // axis parameter (CORRECTED sign)
    const tClamped = Math.max(0, Math.min(segLen, tc))
    const axisPoint = segStart.clone().addScaledVector(segDir, tClamped)
    const sc        = (b * f - w.dot(rayDir)) / denom     // ray parameter
    const rayPoint  = rayOrigin.clone().addScaledVector(rayDir, sc)
    return { axisPoint, dist: axisPoint.distanceTo(rayPoint), t: tClamped }
  }

  const SAMPLE_STEP = 7  // bp per sample interval — must match backend _AXIS_SAMPLE_STEP

  for (const h of helices) {
    if (h.samples && h.samples.length > 2) {
      // Curved (deformed) axis: iterate over each consecutive sample segment
      for (let si = 0; si < h.samples.length - 1; si++) {
        const segStart = new THREE.Vector3(...h.samples[si])
        const segEnd   = new THREE.Vector3(...h.samples[si + 1])
        const segVec   = segEnd.clone().sub(segStart)
        const segLen   = segVec.length()
        if (segLen < 1e-9) continue
        const segDir = segVec.divideScalar(segLen)

        const r = _segClosest(segStart, segDir, segLen)
        if (!r || r.dist >= 2.5 || r.dist >= bestDist) continue

        // Compute actual bp span of this segment — last segment may be < SAMPLE_STEP
        const loBp   = si * SAMPLE_STEP
        const hiBp   = si + 1 < h.samples.length - 1 ? (si + 1) * SAMPLE_STEP : h.lengthBp - 1
        const localBp = Math.round(loBp + (r.t / segLen) * (hiBp - loBp))
        if (localBp >= 0 && localBp < h.lengthBp) {
          bestDist = r.dist; bestBp = localBp + h.bpStart  // convert to global
          bestHelixId = h.id; bestAxisPoint = r.axisPoint
        }
      }
    } else {
      // Straight axis: single segment from start to end
      const axisVec = h.end.clone().sub(h.start)
      const axisLen = axisVec.length()
      if (axisLen < 1e-9) continue
      const axisDir = axisVec.divideScalar(axisLen)

      const r = _segClosest(h.start, axisDir, axisLen)
      if (!r || r.dist >= 2.5 || r.dist >= bestDist) continue

      const localBp = Math.round(r.t / BDNA_RISE_PER_BP)
      if (localBp >= 0 && localBp < h.lengthBp) {
        bestDist = r.dist; bestBp = localBp + h.bpStart  // convert to global
        bestHelixId = h.id; bestAxisPoint = r.axisPoint
      }
    }
  }
  if (bestBp === null) return null
  return { bp: bestBp, helixId: bestHelixId, axisPoint: bestAxisPoint }
}

/**
 * Pick the nearest bp to a world-space point by finding the closest point along
 * each helix axis (sample-aware for deformed helices) and returning the average bp.
 */
function _pickBpFromPoint(worldPoint) {
  const helices = _getHelixAxisData()
  if (!helices.length) return null

  let sumBp = 0, count = 0

  for (const h of helices) {
    if (h.samples && h.samples.length > 2) {
      // Deformed axis: iterate sample segments and find the nearest point
      let bestBp = 0, bestDist = Infinity
      for (let si = 0; si < h.samples.length - 1; si++) {
        const segStart = new THREE.Vector3(...h.samples[si])
        const segEnd   = new THREE.Vector3(...h.samples[si + 1])
        const segVec   = segEnd.clone().sub(segStart)
        const segLen   = segVec.length()
        if (segLen < 1e-9) continue
        const segDir = segVec.clone().divideScalar(segLen)
        const tRaw   = worldPoint.clone().sub(segStart).dot(segDir)
        const tClamp = Math.max(0, Math.min(segLen, tRaw))
        const closest = segStart.clone().addScaledVector(segDir, tClamp)
        const dist = worldPoint.distanceTo(closest)
        if (dist < bestDist) {
          bestDist = dist
          // Actual bp span of this segment — last segment may be < _SAMPLE_STEP
          const loBp = si * _SAMPLE_STEP
          const hiBp = si + 1 < h.samples.length - 1 ? (si + 1) * _SAMPLE_STEP : h.lengthBp - 1
          bestBp = Math.round(loBp + (tClamp / segLen) * (hiBp - loBp))  // local
        }
      }
      const localClamped = Math.max(0, Math.min(h.lengthBp - 1, bestBp))
      sumBp += localClamped + h.bpStart  // convert to global
      count++
    } else {
      // Straight axis
      const axisVec = h.end.clone().sub(h.start)
      const axisLen = axisVec.length()
      if (axisLen < 1e-9) continue
      const axisDir  = axisVec.divideScalar(axisLen)
      const t        = worldPoint.clone().sub(h.start).dot(axisDir)
      const tClamped = Math.max(0, Math.min(axisLen, t))
      const localBp  = Math.round(tClamped / BDNA_RISE_PER_BP)
      sumBp += Math.max(h.bpStart, Math.min(h.bpStart + h.lengthBp - 1, localBp + h.bpStart))
      count++
    }
  }

  if (!count) return null
  return Math.round(sumBp / count)
}

// ── Hover bead ─────────────────────────────────────────────────────────────────

/**
 * Show (or update) a small sphere on the nearest helix axis at the hovered bp.
 * Pass null to hide it.
 * @param {{ bp: number, helixId: string, axisPoint: THREE.Vector3 } | null} hit
 */
function _showHoverBead(hit) {
  if (!_scene) return
  if (!_hoverBead) {
    _hoverBead = new THREE.Mesh(
      new THREE.SphereGeometry(0.45, 16, 10),
      new THREE.MeshBasicMaterial({ color: 0xffffaa, depthTest: false }),
    )
    _hoverBead.renderOrder = 6
    _scene.add(_hoverBead)
  }
  if (!hit) {
    _hoverBead.visible = false
    return
  }
  // Prefer the deformed position from currentHelixAxes; fall back to original axisPoint
  const { bp, helixId, axisPoint } = hit  // bp is GLOBAL
  const helixAxes = store.getState().currentHelixAxes
  const axDef = helixAxes?.[helixId]
  const design = store.getState().currentDesign
  const helixDef = design?.helices.find(h => h.id === helixId)
  const lengthBp  = helixDef?.length_bp  ?? 0
  const localBp   = bp - (helixDef?.bp_start ?? 0)  // convert global → local for sample lookup
  if (axDef?.samples?.length > 2) {
    const pos = _interpolateSamplePos(axDef.samples, localBp, lengthBp)
    _hoverBead.position.copy(pos)
  } else {
    _hoverBead.position.copy(axisPoint)
  }
  _hoverBead.visible = true
}

const _SAMPLE_STEP = 7  // bp per sample interval — must match backend _AXIS_SAMPLE_STEP

/**
 * Map a bp value to a (segmentIndex, t) pair within a samples array.
 * The backend places samples at bp = 0, STEP, 2*STEP, …, lengthBp-1.
 * The last segment therefore spans (lengthBp-1 - lastFullStep) bp, which may
 * be shorter than STEP.  Using a fixed STEP for the last segment gives the
 * wrong interpolation parameter — this helper computes t correctly.
 */
function _sampleSegment(samples, bp, lengthBp) {
  const si    = Math.max(0, Math.min(Math.floor(bp / _SAMPLE_STEP), samples.length - 2))
  const loBp  = si * _SAMPLE_STEP
  const hiBp  = si + 1 < samples.length - 1 ? (si + 1) * _SAMPLE_STEP : lengthBp - 1
  const span  = hiBp - loBp
  const t     = span > 0 ? Math.max(0, Math.min(1, (bp - loBp) / span)) : 0
  return { si, t, loBp, hiBp }
}

/** Interpolate world position along a samples array at the given bp. */
function _interpolateSamplePos(samples, bp, lengthBp) {
  const { si, t } = _sampleSegment(samples, bp, lengthBp)
  const ps = samples[si], pe = samples[si + 1]
  return new THREE.Vector3(
    ps[0] + (pe[0] - ps[0]) * t,
    ps[1] + (pe[1] - ps[1]) * t,
    ps[2] + (pe[2] - ps[2]) * t,
  )
}

/** Tangent direction along a samples array at the given bp. */
function _interpolateSampleTangent(samples, bp) {
  const si = Math.max(0, Math.min(Math.floor(bp / _SAMPLE_STEP), samples.length - 2))
  return new THREE.Vector3(...samples[si + 1]).sub(new THREE.Vector3(...samples[si])).normalize()
}

function _worldPosForBp(globalBp) {
  const helices = _getHelixAxisData()
  if (!helices.length) return new THREE.Vector3()
  const sum = new THREE.Vector3()
  for (const h of helices) {
    const localBp = globalBp - h.bpStart
    if (h.samples && h.samples.length > 2) {
      sum.add(_interpolateSamplePos(h.samples, localBp, h.lengthBp))
    } else {
      const dir = h.end.clone().sub(h.start).normalize()
      sum.add(h.start.clone().addScaledVector(dir, localBp * BDNA_RISE_PER_BP))
    }
  }
  return sum.divideScalar(helices.length)
}

/** Average tangent direction across all helices at *globalBp*, following the deformed contour. */
function _tangentAtBp(globalBp) {
  const helices = _getHelixAxisData()
  if (!helices.length) return new THREE.Vector3(0, 0, 1)
  const sum = new THREE.Vector3()
  for (const h of helices) {
    const localBp = globalBp - h.bpStart
    if (h.samples && h.samples.length > 2) {
      sum.add(_interpolateSampleTangent(h.samples, localBp))
    } else {
      sum.add(h.end.clone().sub(h.start).normalize())
    }
  }
  return sum.normalize()
}

// ── Ghost planes ──────────────────────────────────────────────────────────────

function _showGhost(isA, bp) {
  const color = isA ? 0xffffaa : 0xff9900
  let ghost = isA ? _ghostA : _ghostB
  if (!ghost) {
    const mat = new THREE.MeshBasicMaterial({
      color, transparent: true, opacity: 0.18,
      side: THREE.DoubleSide, depthWrite: false,
    })
    ghost = new THREE.Mesh(new THREE.PlaneGeometry(PLANE_SIZE * 2, PLANE_SIZE * 2), mat)
    _scene.add(ghost)
    if (isA) _ghostA = ghost; else _ghostB = ghost
  }
  ghost.position.copy(_worldPosForBp(bp))
  ghost.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), _tangentAtBp(bp))
  ghost.visible = true
}

function _hideGhost(isA) {
  const ghost = isA ? _ghostA : _ghostB
  if (ghost) ghost.visible = false
}

// ── Solid planes + drag handles ───────────────────────────────────────────────

/**
 * Create a camera-facing text sprite using a canvas 2D texture.
 * @param {string} text   - single character or short string to render
 * @param {number} hexCol - hex color integer (e.g. 0xffffaa)
 */
function _makeTextSprite(text, hexCol) {
  const size = 128
  const cvs  = document.createElement('canvas')
  cvs.width  = size
  cvs.height = size
  const ctx  = cvs.getContext('2d')
  ctx.clearRect(0, 0, size, size)
  ctx.font         = `bold ${Math.round(size * 0.72)}px sans-serif`
  ctx.fillStyle    = '#' + hexCol.toString(16).padStart(6, '0')
  ctx.textAlign    = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillText(text, size / 2, size / 2)
  const tex    = new THREE.CanvasTexture(cvs)
  const mat    = new THREE.SpriteMaterial({ map: tex, depthTest: false })
  const sprite = new THREE.Sprite(mat)
  sprite.renderOrder = 7
  return sprite
}

/** Create an updatable bp-position sprite showing "bp NNN". */
function _makeBpSprite(bp, hexCol) {
  const W = 192, H = 64
  const cvs = document.createElement('canvas')
  cvs.width = W; cvs.height = H
  const tex = new THREE.CanvasTexture(cvs)
  const mat = new THREE.SpriteMaterial({ map: tex, depthTest: false })
  const sprite = new THREE.Sprite(mat)
  sprite.renderOrder = 7
  sprite._cvs = cvs
  sprite._hexCol = hexCol
  _updateBpSprite(sprite, bp)
  return sprite
}

function _updateBpSprite(sprite, bp) {
  const cvs = sprite._cvs
  const ctx = cvs.getContext('2d')
  ctx.clearRect(0, 0, cvs.width, cvs.height)
  ctx.fillStyle    = '#' + sprite._hexCol.toString(16).padStart(6, '0')
  ctx.font         = `bold ${Math.round(cvs.height * 0.7)}px monospace`
  ctx.textAlign    = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillText(`bp ${bp}`, cvs.width / 2, cvs.height / 2)
  sprite.material.map.needsUpdate = true
}

/**
 * Build a solid plane group: quad + edge outline + sphere handle + two cones + label.
 * Returns { group, beadMeshes: [sphere, coneFwd, coneBack] }.
 * @param {number} bp       - bp position
 * @param {number} hexColor - hex color integer
 * @param {string} label    - 'A' or 'B'
 */
function _makeSolidPlane(bp, hexColor, label) {
  const group = new THREE.Group()

  // Quad face
  const planeMat = new THREE.MeshBasicMaterial({
    color: hexColor, transparent: true, opacity: 0.30,
    side: THREE.DoubleSide, depthWrite: false,
  })
  const planeGeo  = new THREE.PlaneGeometry(PLANE_SIZE * 2, PLANE_SIZE * 2)
  const planeMesh = new THREE.Mesh(planeGeo, planeMat)
  group.add(planeMesh)

  // Edge outline
  const edgeMat = new THREE.LineBasicMaterial({ color: hexColor })
  group.add(new THREE.LineSegments(new THREE.EdgesGeometry(planeGeo), edgeMat))

  // Labels — camera-facing sprites at the top-right of the plane face
  let bpSprite = null
  if (label) {
    const letterSprite = _makeTextSprite(label, hexColor)
    letterSprite.position.set(PLANE_SIZE * 0.65, PLANE_SIZE * 0.72, 0.1)
    letterSprite.scale.set(1.8, 1.8, 1)
    group.add(letterSprite)

    bpSprite = _makeBpSprite(bp, hexColor)
    // Position below the letter; scale preserves 192:64 canvas aspect ratio
    bpSprite.position.set(PLANE_SIZE * 0.65, PLANE_SIZE * 0.50, 0.1)
    bpSprite.scale.set(2.8, 0.95, 1)
    group.add(bpSprite)
  }

  // Position the whole group
  group.position.copy(_worldPosForBp(bp))
  group.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), _tangentAtBp(bp))

  return { group, planeMesh, bpSprite }
}

/** Reposition an existing solid plane group to a new bp and refresh its label. */
function _updateSolidPlane(solid, bp) {
  if (!solid) return
  solid.group.position.copy(_worldPosForBp(bp))
  solid.group.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), _tangentAtBp(bp))
  if (solid.bpSprite) _updateBpSprite(solid.bpSprite, bp)
}

function _removePlanes() {
  if (_solidA) { _scene.remove(_solidA.group); _solidA = null }
  if (_solidB) { _scene.remove(_solidB.group); _solidB = null }
  if (_ghostA) { _scene.remove(_ghostA); _ghostA = null }
  if (_ghostB) { _scene.remove(_ghostB); _ghostB = null }
}

// ── Scene opacity dim ─────────────────────────────────────────────────────────

function _dimScene(dim) {
  _renderer?.setToolOpacity?.(dim ? 0.15 : 1.0)
}

// ── State accessors ───────────────────────────────────────────────────────────

export function getState()    { return _state }
export function getPlanes()   { return { a: _planeA, b: _planeB } }
export function getToolType() { return _toolType }
export const STATES = STATE

/**
 * Programmatically reposition one plane (e.g. from the popup's bp input).
 * Updates the 3D visual and refreshes the live preview.
 * @param {'A'|'B'} which
 * @param {number}  bp
 */
export function repositionPlane(which, bp) {
  if (which === 'A' && _planeA && _solidA) {
    _planeA.bp = bp
    _updateSolidPlane(_solidA, bp)
    _refreshPreview()
  } else if (which === 'B' && _planeB && _solidB) {
    _planeB.bp = bp
    _updateSolidPlane(_solidB, bp)
    _refreshPreview()
  }
}
