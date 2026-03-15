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

// ── Constants ─────────────────────────────────────────────────────────────────

const PLANE_SIZE    = 8.0   // nm — half-extent of each plane quad (full size = 2×)
const HANDLE_RADIUS = 0.38  // nm — drag bead radius
const CONE_R        = 0.22  // nm — cone base radius
const CONE_H        = 0.75  // nm — cone height

// ── State ─────────────────────────────────────────────────────────────────────

const STATE = { IDLE: 'IDLE', AWAITING_A: 'AWAITING_A', A_PLACED: 'A_PLACED', BOTH: 'BOTH' }

let _state   = STATE.IDLE
let _toolType = null      // 'twist' | 'bend'
let _planeA   = null      // { bp }
let _planeB   = null      // { bp }
let _previewOpId       = null
let _lastPreviewParams = null   // params from the most recent previewDeformation call
let _previewOriginalAxes = null // currentHelixAxes snapshot before preview was applied

// Three.js plumbing
let _scene    = null
let _camera   = null
let _canvas   = null
let _controls = null
let _renderer = null
let _onExit   = null

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

export function initDeformationEditor(scene, camera, canvas, controls, designRenderer, onExit) {
  _scene    = scene
  _camera   = camera
  _canvas   = canvas
  _controls = controls
  _renderer = designRenderer
  _onExit   = onExit
}

export function startTool(toolType) {
  if (!_scene) return
  _toolType = toolType
  _setState(STATE.AWAITING_A)
}

/**
 * Start the tool with planes pre-set to span the arm ending at *sourceBp*.
 *
 * End blunt end (sourceBp = helix.length_bp):
 *   plane A = 0, plane B = sourceBp − 1  (covers the whole arm)
 * Start blunt end (sourceBp = 0):
 *   plane A = 0, plane B = farthest consistent position
 *
 * Skips the "click to place" steps and opens the parameter popup immediately.
 */
export function startToolAtBp(toolType, sourceBp) {
  if (!_scene) return
  _toolType = toolType
  _setState(STATE.AWAITING_A)

  if (sourceBp <= 0) {
    // Start blunt end — span from beginning to farthest consistent end
    _placeA(0)
  } else {
    // End blunt end — A at bp 0, B at last valid bp (sourceBp − 1)
    _planeA = { bp: 0 }
    _hideGhost(true)
    _solidA = _makeSolidPlane(0, 0xffffaa, 'A')
    _scene.add(_solidA.group)
    _setState(STATE.A_PLACED)
    _placeB(sourceBp - 1)
  }
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

  // ── Bead drag check (highest priority) ──────────────────────────────────
  const hitBead = _raycastBeads()
  if (hitBead) {
    _dragging = hitBead   // 'A' | 'B'
    // Billboard drag plane: perpendicular to camera at bead position
    const beadPos = hitBead === 'A' ? _worldPosForBp(_planeA.bp) : _worldPosForBp(_planeB.bp)
    _camera.getWorldDirection(_tmpVec)
    _dragBillboard.setFromNormalAndCoplanarPoint(_tmpVec, beadPos)
    _raycaster.ray.intersectPlane(_dragBillboard, _dragStartPoint)
    _dragStartBp = hitBead === 'A' ? _planeA.bp : _planeB.bp
    if (_controls) _controls.enabled = false
    // Document-level listeners handle the rest of the drag (works outside canvas too)
    document.addEventListener('pointermove',   _onDocDragMove)
    document.addEventListener('pointerup',     _onDocDragUp)
    document.addEventListener('pointercancel', _onDocDragUp)
    return true
  }

  // ── Plane face check — consume click to prevent OrbitControls drag ───────
  const planeMeshes = []
  if (_solidA?.planeMesh) planeMeshes.push(_solidA.planeMesh)
  if (_solidB?.planeMesh) planeMeshes.push(_solidB.planeMesh)
  if (planeMeshes.length && _raycaster.intersectObjects(planeMeshes).length) return true

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
  _dragging = null
  if (_controls) _controls.enabled = true
  document.removeEventListener('pointermove',   _onDocDragMove)
  document.removeEventListener('pointerup',     _onDocDragUp)
  document.removeEventListener('pointercancel', _onDocDragUp)

  if (_previewOpId && _lastPreviewParams) {
    const staleOpId = _previewOpId
    const params    = _lastPreviewParams
    _previewOpId = null
    // Do NOT call clearGhost() here — that would set _previewOpacity = null and
    // cause the delete's rebuild to dim the pre-deform model to 0.15 (tool dim).
    // Instead, keep the pre-deform ghost and _previewOpacity intact so the scene
    // stays stable (pre-deform at 0.5, previewed at 0.3) while we wait for the
    // delete to resolve.  captureGhost inside previewDeformation replaces the
    // ghost cleanly once the original geometry is back in the store.
    api.deleteDeformation(staleOpId, /*preview=*/true)
      .then(() => previewDeformation(params))
      .catch(() => {})
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
    _clearPreviewSession()
    if (_solidB) { _scene.remove(_solidB.group); _solidB = null }
    _planeB = null
    _setState(STATE.A_PLACED)
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
  await api.addDeformation(_toolType, a, b, params)  // preview=false → pushes to undo
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
    await api.updateDeformation(_previewOpId, params)
  } else {
    // Snapshot axes and capture ghost only once per preview session.
    // The drag auto-refresh calls this again with _previewOriginalAxes already
    // set — don't re-capture or the delete→rebuild cycle will replace the
    // pre-deform ghost with the intermediate straight geometry.
    if (!_previewOriginalAxes) {
      _previewOriginalAxes = store.getState().currentHelixAxes
      _renderer?.captureGhost?.(0.5, 0.3)
    }
    await api.addDeformation(_toolType, a, b, params, [], /*preview=*/true)
    const deformations = store.getState().currentDesign?.deformations ?? []
    if (deformations.length > 0) {
      _previewOpId = deformations[deformations.length - 1].id
    }
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
function _defaultBpForPlaneB(bpA) {
  const helices = _getHelixAxisData()
  if (!helices.length) return bpA + 1
  const active = helices.filter(h => h.lengthBp > bpA)
  if (!active.length) return bpA + 1
  const maxBp = Math.min(...active.map(h => h.lengthBp)) - 1
  return maxBp > bpA ? maxBp : bpA + 1
}

// Cancel the active preview op and ghost, but intentionally keep
// _previewOriginalAxes — the drag auto-refresh path calls this then
// immediately re-previews, and the snapshot is still valid across that cycle.
function _cancelPreview() {
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

function _getHelixAxisData() {
  const design = store.getState().currentDesign
  if (!design) return []
  // While a preview is live, the store has the bent axes — use the original snapshot
  // so planes and hover beads track the undeformed contour.
  const helixAxes = _previewOriginalAxes ?? store.getState().currentHelixAxes
  return design.helices.map(h => {
    const axDef = helixAxes?.[h.id]
    return {
      id:       h.id,
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
        const loBp  = si * SAMPLE_STEP
        const hiBp  = si + 1 < h.samples.length - 1 ? (si + 1) * SAMPLE_STEP : h.lengthBp - 1
        const bp    = Math.round(loBp + (r.t / segLen) * (hiBp - loBp))
        if (bp >= 0 && bp < h.lengthBp) {
          bestDist = r.dist; bestBp = bp
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

      const bp = Math.round(r.t / BDNA_RISE_PER_BP)
      if (bp >= 0 && bp < h.lengthBp) {
        bestDist = r.dist; bestBp = bp
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
          bestBp = Math.round(loBp + (tClamp / segLen) * (hiBp - loBp))
        }
      }
      sumBp += Math.max(0, Math.min(h.lengthBp - 1, bestBp))
      count++
    } else {
      // Straight axis
      const axisVec = h.end.clone().sub(h.start)
      const axisLen = axisVec.length()
      if (axisLen < 1e-9) continue
      const axisDir  = axisVec.divideScalar(axisLen)
      const t        = worldPoint.clone().sub(h.start).dot(axisDir)
      const tClamped = Math.max(0, Math.min(axisLen, t))
      const bp       = Math.round(tClamped / BDNA_RISE_PER_BP)
      sumBp += Math.max(0, Math.min(h.lengthBp - 1, bp))
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
  const { bp, helixId, axisPoint } = hit
  const helixAxes = store.getState().currentHelixAxes
  const axDef = helixAxes?.[helixId]
  const design = store.getState().currentDesign
  const lengthBp = design?.helices.find(h => h.id === helixId)?.length_bp ?? 0
  if (axDef?.samples?.length > 2) {
    const pos = _interpolateSamplePos(axDef.samples, bp, lengthBp)
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

function _worldPosForBp(bp) {
  const helices = _getHelixAxisData()
  if (!helices.length) return new THREE.Vector3()
  const sum = new THREE.Vector3()
  for (const h of helices) {
    if (h.samples && h.samples.length > 2) {
      sum.add(_interpolateSamplePos(h.samples, bp, h.lengthBp))
    } else {
      const dir = h.end.clone().sub(h.start).normalize()
      sum.add(h.start.clone().addScaledVector(dir, bp * BDNA_RISE_PER_BP))
    }
  }
  return sum.divideScalar(helices.length)
}

/** Average tangent direction across all helices at *bp*, following the deformed contour. */
function _tangentAtBp(bp) {
  const helices = _getHelixAxisData()
  if (!helices.length) return new THREE.Vector3(0, 0, 1)
  const sum = new THREE.Vector3()
  for (const h of helices) {
    if (h.samples && h.samples.length > 2) {
      sum.add(_interpolateSampleTangent(h.samples, bp))
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

  // Handle: sphere + two cones along the plane normal (+Z in local space)
  const handleMat  = new THREE.MeshBasicMaterial({
    color: hexColor, depthTest: false,
  })
  const sphere = new THREE.Mesh(new THREE.SphereGeometry(HANDLE_RADIUS, 16, 8), handleMat)
  sphere.renderOrder = 5
  group.add(sphere)

  const coneMat  = new THREE.MeshBasicMaterial({ color: hexColor, depthTest: false })
  const coneFwd  = new THREE.Mesh(new THREE.ConeGeometry(CONE_R, CONE_H, 12), coneMat.clone())
  const coneBack = new THREE.Mesh(new THREE.ConeGeometry(CONE_R, CONE_H, 12), coneMat.clone())
  coneFwd.renderOrder  = 5
  coneBack.renderOrder = 5

  // Orient cones: +Z and -Z in local plane space (along normal)
  const up = new THREE.Vector3(0, 1, 0)
  coneFwd.quaternion.setFromUnitVectors(up, new THREE.Vector3(0, 0,  1))
  coneFwd.position.set(0, 0,  HANDLE_RADIUS + CONE_H / 2 + 0.05)
  coneBack.quaternion.setFromUnitVectors(up, new THREE.Vector3(0, 0, -1))
  coneBack.position.set(0, 0, -(HANDLE_RADIUS + CONE_H / 2 + 0.05))

  group.add(coneFwd)
  group.add(coneBack)

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

  return { group, beadMeshes: [sphere, coneFwd, coneBack], planeMesh, bpSprite }
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

// ── Bead raycasting ────────────────────────────────────────────────────────────

/** Returns 'A', 'B', or null depending on which bead the current ray hits. */
function _raycastBeads() {
  const targets = []
  if (_solidA) _solidA.beadMeshes.forEach(m => targets.push({ mesh: m, which: 'A' }))
  if (_solidB) _solidB.beadMeshes.forEach(m => targets.push({ mesh: m, which: 'B' }))
  if (!targets.length) return null

  const hits = _raycaster.intersectObjects(targets.map(t => t.mesh))
  if (!hits.length) return null
  return targets.find(t => t.mesh === hits[0].object)?.which ?? null
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
