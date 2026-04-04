/**
 * Slice plane — a draggable cross-section plane for extruding new helix segments.
 *
 * Usage:
 *   const sp = initSlicePlane(scene, camera, canvas, controls, { onExtrude, getDesign })
 *   sp.show('XY', offsetNm)   // display at given plane / offset
 *   sp.hide()                 // remove from scene
 *
 * Interaction:
 *   Drag the yellow handle to slide the plane along the bundle axis (snaps to 0.334 nm grid).
 *   Click the plane face → honeycomb lattice appears; occupied cells are greyed.
 *   Left-click cells to select (blue); right-click with selection → Extrude context menu.
 */

import * as THREE from 'three'
import {
  HONEYCOMB_LATTICE_RADIUS,
  HONEYCOMB_COL_PITCH,
  HONEYCOMB_ROW_PITCH,
  HELIX_RADIUS,
  BDNA_RISE_PER_BP,
  SQUARE_HELIX_SPACING,
  SQUARE_TWIST_PER_BP_RAD,
} from '../constants.js'
import { store } from '../state/store.js'

// Default grid half-extents when no design is loaded.
// Combined with MARGIN below, these produce a grid that fills the 40×40 nm slice plane:
//   col −5..+5 + margin → −10..+10  →  X ≈ ±19.5 nm  (COL_PITCH ≈ 1.9486 nm)
//   row −4..+4 + margin → −9..+9    →  Y ≈ −19..+21 nm (ROW_PITCH = 2.25 nm)
const DEFAULT_ROW_HALF = 4   // default inner half-extent in row direction
const DEFAULT_COL_HALF = 5   // default inner half-extent in col direction
const MARGIN           = 5   // extra cells around the design extent in each direction
const RISE             = BDNA_RISE_PER_BP

// Proximity-based opacity: cells brighten as the cursor approaches
const PROX_FULL_PX = 70    // pixel radius — full opacity
const PROX_FADE_PX = 220   // pixel radius — minimum opacity reached

// Min / max opacity values per cell state
const FILL_MIN_FREE  = 0.04   // free cell fill, far from cursor
const FILL_MAX_FREE  = 0.55   // free cell fill, near cursor
const RING_MIN_FREE  = 0.07   // free cell ring, far
const RING_MAX_FREE  = 0.85   // free cell ring, near
const FILL_MIN_OCC   = 0.02   // occupied cell fill, far
const FILL_MAX_OCC   = 0.18   // occupied cell fill, near
const RING_MIN_OCC   = 0.03   // occupied cell ring, far
const RING_MAX_OCC   = 0.18   // occupied cell ring, near

// Centre of the default lattice = world origin (col=0, row=0)
const LATTICE_CX = 0
const LATTICE_CY = HONEYCOMB_LATTICE_RADIUS   // ≈ 1.125 nm (y of row=0, even col)

// ── Plane configs ─────────────────────────────────────────────────────────────

const PLANE_CFG = {
  XY: {
    normal:       new THREE.Vector3(0, 0, 1),
    rotation:     new THREE.Euler(0, 0, 0),
    // centre of the handle sits at (LATTICE_CX, LATTICE_CY, offset)
    handleCenter: (offset) => new THREE.Vector3(LATTICE_CX, LATTICE_CY, offset),
    // quaternion that makes circles face +Z
    latticeQuat:  new THREE.Quaternion(),
    // extract offset component from a helix
    axisRange:    (h) => [
      Math.min(h.axis_start.z, h.axis_end.z),
      Math.max(h.axis_start.z, h.axis_end.z),
    ],
  },
  XZ: {
    normal:       new THREE.Vector3(0, 1, 0),
    rotation:     new THREE.Euler(-Math.PI / 2, 0, 0),
    handleCenter: (offset) => new THREE.Vector3(LATTICE_CX, offset, LATTICE_CY),
    latticeQuat:  (() => {
      const q = new THREE.Quaternion()
      q.setFromEuler(new THREE.Euler(-Math.PI / 2, 0, 0))
      return q
    })(),
    axisRange: (h) => [
      Math.min(h.axis_start.y, h.axis_end.y),
      Math.max(h.axis_start.y, h.axis_end.y),
    ],
  },
  YZ: {
    normal:       new THREE.Vector3(1, 0, 0),
    rotation:     new THREE.Euler(0, Math.PI / 2, 0),
    handleCenter: (offset) => new THREE.Vector3(offset, LATTICE_CX, LATTICE_CY),
    latticeQuat:  (() => {
      const q = new THREE.Quaternion()
      q.setFromEuler(new THREE.Euler(0, Math.PI / 2, 0))
      return q
    })(),
    axisRange: (h) => [
      Math.min(h.axis_start.x, h.axis_end.x),
      Math.max(h.axis_start.x, h.axis_end.x),
    ],
  },
}

// ── Cell helpers ──────────────────────────────────────────────────────────────

// Always-positive modulo (matches Python's % for negative operands)
function _mod(n, m) { return ((n % m) + m) % m }

// ── Honeycomb ──
function honeycombCellValue(row, col) { return _mod(row + _mod(col, 2), 3) }
function isValidHoneycombCell(row, col) { return honeycombCellValue(row, col) !== 2 }

function honeycombCellWorldPos(row, col, plane, offset) {
  const lx = col * HONEYCOMB_COL_PITCH
  const ly = row * HONEYCOMB_ROW_PITCH + ((col % 2 === 0) ? HONEYCOMB_LATTICE_RADIUS : 0)
  if (plane === 'XY') return new THREE.Vector3(lx, ly, offset)
  if (plane === 'XZ') return new THREE.Vector3(lx, offset, ly)
  /* YZ */            return new THREE.Vector3(offset, lx, ly)
}

// ── Square lattice ──
// All cells are valid (checkerboard of FORWARD/REVERSE, no holes).
function isValidSquareCell(_row, _col) { return true }  // eslint-disable-line no-unused-vars

function squareCellWorldPos(row, col, plane, offset) {
  const lx = col * SQUARE_HELIX_SPACING
  const ly = row * SQUARE_HELIX_SPACING
  if (plane === 'XY') return new THREE.Vector3(lx, ly, offset)
  if (plane === 'XZ') return new THREE.Vector3(lx, offset, ly)
  /* YZ */            return new THREE.Vector3(offset, lx, ly)
}

// Legacy aliases — overwritten per-call in _buildLattice based on lattice type.
let isValidCell   = isValidHoneycombCell
let cellWorldPos  = honeycombCellWorldPos

// ── Colours ───────────────────────────────────────────────────────────────────

const C_CELL        = new THREE.Color(0xfcba03)  // gold   — selectable (free)
const C_CONTINUABLE = new THREE.Color(0xff9900)  // amber  — selectable (continuation)
const C_SELECTED    = new THREE.Color(0x58a6ff)  // blue   — selected
const C_OCCUPIED    = new THREE.Color(0x444444)  // grey   — occupied (non-selectable)
const C_HOVER       = new THREE.Color(0xffffff)  // white  — hover

// ── Main export ───────────────────────────────────────────────────────────────

/**
 * @param {THREE.Scene}          scene
 * @param {THREE.Camera}         camera
 * @param {HTMLCanvasElement}    canvas
 * @param {import('three').OrbitControls} controls
 * @param {{ onExtrude: Function, getDesign: Function }} opts
 */
export function initSlicePlane(scene, camera, canvas, controls, { onExtrude, getDesign, getHelixAxes, onOffsetChange } = {}) {
  // Mutable camera ref — replaced by setCamera() when an ortho camera takes over (cadnano mode).
  let _camera = camera

  // ── Scene graph ─────────────────────────────────────────────────────────────

  const _root = new THREE.Group()
  scene.add(_root)
  _root.visible = false

  // Semi-transparent volume slab (one bp thick along the helix axis)
  const _planeMat = new THREE.MeshBasicMaterial({
    color: 0x58a6ff, transparent: true, opacity: 0.07,
    side: THREE.DoubleSide, depthWrite: false,
  })
  const _planeMesh = new THREE.Mesh(new THREE.BoxGeometry(40, 40, RISE), _planeMat)
  _planeMesh.userData.isSlicePlane = true
  _root.add(_planeMesh)

  // Border outline (12 edges of the slab)
  const _borderMat = new THREE.LineBasicMaterial({ color: 0x58a6ff, transparent: true, opacity: 0.35 })
  const _borderMesh = new THREE.LineSegments(
    new THREE.EdgesGeometry(new THREE.BoxGeometry(40, 40, RISE)),
    _borderMat,
  )
  _root.add(_borderMesh)

  // Handle group: sphere + two directional cones
  const _handleGroup = new THREE.Group()
  _root.add(_handleGroup)

  const _handleMat = new THREE.MeshBasicMaterial({ color: 0xfcba03 })
  const _sphere    = new THREE.Mesh(new THREE.SphereGeometry(0.4, 16, 8), _handleMat)
  _handleGroup.add(_sphere)

  const _coneGeoFwd  = new THREE.ConeGeometry(0.22, 0.8, 12)
  const _coneGeoBack = new THREE.ConeGeometry(0.22, 0.8, 12)
  const _coneFwd  = new THREE.Mesh(_coneGeoFwd,  _handleMat.clone())
  const _coneBack = new THREE.Mesh(_coneGeoBack, _handleMat.clone())
  _handleGroup.add(_coneFwd)
  _handleGroup.add(_coneBack)

  // Lattice group (circles + number labels, built on demand)
  const _latGroup  = new THREE.Group()
  _latGroup.frustumCulled = false
  _root.add(_latGroup)
  const _circleGeo = new THREE.CircleGeometry(HELIX_RADIUS, 32)
  const _ringGeo   = new THREE.RingGeometry(HELIX_RADIUS * 0.82, HELIX_RADIUS, 32)

  // ── Cell label sprite helpers ─────────────────────────────────────────────

  /**
   * Helix-number label: dark circle + blue ring + bold white number.
   * Used for occupied / continuable cells (shows which helix is here).
   */
  function _makeHelixLabel(num) {
    const size = 128
    const cv   = document.createElement('canvas')
    cv.width   = size; cv.height = size
    const ctx  = cv.getContext('2d')
    const r    = size / 2
    // Opaque background so texture is not all-transparent
    ctx.clearRect(0, 0, size, size)
    ctx.beginPath()
    ctx.arc(r, r, r * 0.80, 0, Math.PI * 2)
    ctx.fillStyle = 'rgba(13,17,23,0.90)'
    ctx.fill()
    ctx.beginPath()
    ctx.arc(r, r, r * 0.80, 0, Math.PI * 2)
    ctx.strokeStyle = 'rgba(88,166,255,0.90)'
    ctx.lineWidth   = r * 0.14
    ctx.stroke()
    const str = String(num)
    ctx.fillStyle = '#ffffff'
    ctx.font      = `bold ${str.length > 2 ? Math.floor(r * 0.66) : Math.floor(r * 0.84)}px sans-serif`
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
    ctx.fillText(str, r, r + 1)
    const tex = new THREE.CanvasTexture(cv)
    tex.needsUpdate = true
    const mat = new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false, depthTest: false })
    const spr = new THREE.Sprite(mat)
    spr.scale.set(0.80, 0.80, 1)
    spr.frustumCulled = false
    return spr
  }

  /**
   * Free-cell coordinate label: dark pill background + dim text "r,c".
   * Helps users identify which cell they're hovering / selecting.
   */
  function _makeCellCoordLabel(row, col) {
    const size = 128
    const cv   = document.createElement('canvas')
    cv.width   = size; cv.height = size
    const ctx  = cv.getContext('2d')
    const r    = size / 2
    ctx.clearRect(0, 0, size, size)
    // Subtle dark background so text is readable regardless of scene lighting
    ctx.beginPath()
    ctx.arc(r, r, r * 0.72, 0, Math.PI * 2)
    ctx.fillStyle = 'rgba(13,17,23,0.65)'
    ctx.fill()
    const str  = `${row},${col}`
    ctx.fillStyle = 'rgba(220,220,220,0.90)'
    ctx.font      = `${Math.floor(r * 0.44)}px sans-serif`
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
    ctx.fillText(str, r, r)
    const tex = new THREE.CanvasTexture(cv)
    tex.needsUpdate = true
    const mat = new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false, depthTest: false })
    const spr = new THREE.Sprite(mat)
    spr.scale.set(0.75, 0.75, 1)
    spr.frustumCulled = false
    return spr
  }

  // ── Lattice type detection ──────────────────────────────────────────────────

  function _isSquareLattice() {
    const helices = getDesign?.()?.helices
    if (!helices?.length) return false
    return Math.abs(helices[0].twist_per_bp_rad - SQUARE_TWIST_PER_BP_RAD) < 1e-4
  }

  // ── State ───────────────────────────────────────────────────────────────────

  let _plane            = 'XY'
  let _offset           = 0.0
  let _latticeMode      = false
  let _continuationMode = false
  let _deformedFrame    = null   // { grid_origin, axis_dir, frame_right, frame_up } when in deformed mode
  let _refHelixId       = null   // helix that opened the deformed frame (for cluster membership)
  let _readOnly         = false  // when true: no lattice, no extrude — display + snap only
  let _cadnanoDims      = null   // when set, overrides _computeLerpedDimensions in _resizePlane
  let _planeW           = 40    // current plane width  (nm) — updated by _resizePlane
  let _planeH           = 40    // current plane height (nm)
  let _unfoldT          = 0     // lerp factor from 3D cross-section (0) to unfold cross-section (1)
  const _lateralCenter  = new THREE.Vector3()  // centroid of helices in tangent axes (read-only mode)
  let _circleMeshes     = []       // { fill, ring, row, col, state }  state ∈ 'free'|'continuable'|'occupied'
  let _labelSprites     = []       // Sprite[]  — one per occupied cell, parallel to _circleMeshes entries
  let _selected         = new Set()
  let _hoverCell        = null
  let _visible          = false
  let _cursorPx         = null     // { x, y } canvas-local pixels for proximity opacity

  // ── Drag state ─────────────────────────────────────────────────────────────

  let _isDragging       = false    // handle drag
  let _isDragSelecting  = false    // lasso-select drag over cells (activated after >4px movement)
  let _pendingCellClick = false    // pointerdown landed on plane/cell but hasn't moved yet
  let _dragStartOffset  = 0
  let _dragPlane        = new THREE.Plane()
  let _dragStartPoint   = new THREE.Vector3()
  let _pointerDownPos   = null
  let _rightDownPos     = null

  const _raycaster = new THREE.Raycaster()
  const _ndc       = new THREE.Vector2()
  const _tmp       = new THREE.Vector3()
  const _projVec   = new THREE.Vector3()   // reused for screen-space projection

  function _setNDC(e) {
    const rect = canvas.getBoundingClientRect()
    _ndc.set(
      ((e.clientX - rect.left) / rect.width)  *  2 - 1,
      -((e.clientY - rect.top)  / rect.height) *  2 + 1,
    )
    _raycaster.setFromCamera(_ndc, _camera)
  }

  // ── Snapping ────────────────────────────────────────────────────────────────

  function _snap(val) { return Math.round(val / RISE) * RISE }

  // ── Camera orientation ───────────────────────────────────────────────────────

  /**
   * Snap the camera to look straight at the slice plane (along its normal).
   * Preserves the current camera-to-target distance so the scene stays at the
   * same apparent zoom level.  Called when entering extrude mode.
   */
  function _snapCameraToPlane() {
    const helices = getDesign?.()?.helices ?? []
    const t = { XY: ['x', 'y'], XZ: ['x', 'z'], YZ: ['y', 'z'] }[_plane] ?? ['x', 'y']
    let s0 = 0, s1 = 0
    for (const h of helices) { s0 += h.axis_start[t[0]]; s1 += h.axis_start[t[1]] }
    const n  = helices.length || 1
    const c0 = s0 / n, c1 = s1 / n

    // World-space centroid of helices on the slice plane.
    const target = _plane === 'XY' ? new THREE.Vector3(c0, c1, _offset)
                 : _plane === 'XZ' ? new THREE.Vector3(c0, _offset, c1)
                 :                   new THREE.Vector3(_offset, c0, c1)

    // Camera approaches from the positive-normal side; up vector stays sensible.
    const normal = PLANE_CFG[_plane].normal.clone()
    const up = _plane === 'XZ' ? new THREE.Vector3(0, 0, 1)
             :                   new THREE.Vector3(0, 1, 0)

    const dist = _camera.position.distanceTo(controls.target)
    controls.target.copy(target)
    _camera.position.copy(target).addScaledVector(normal, dist)
    _camera.up.copy(up)
    controls.update()
  }

  // ── Plane sizing ────────────────────────────────────────────────────────────

  const PLANE_SIZE_MARGIN = 4.5  // nm — padding beyond outermost helix axis

  function _computePlaneDimensions() {
    const helices = getDesign?.()?.helices ?? []
    if (!helices.length) return { width: 20, height: 20, cx: 0, cy: 0 }
    const t = { XY: ['x', 'y'], XZ: ['x', 'z'], YZ: ['y', 'z'] }[_plane] ?? ['x', 'y']
    let mn0 = Infinity, mx0 = -Infinity, mn1 = Infinity, mx1 = -Infinity
    for (const h of helices) {
      for (const pt of [h.axis_start, h.axis_end]) {
        const v0 = pt[t[0]], v1 = pt[t[1]]
        if (v0 < mn0) mn0 = v0; if (v0 > mx0) mx0 = v0
        if (v1 < mn1) mn1 = v1; if (v1 > mx1) mx1 = v1
      }
    }
    return {
      width:  Math.max((mx0 - mn0) + PLANE_SIZE_MARGIN * 2, 10),
      height: Math.max((mx1 - mn1) + PLANE_SIZE_MARGIN * 2, 10),
      cx: (mn0 + mx0) / 2,
      cy: (mn1 + mx1) / 2,
    }
  }

  /**
   * Compute slice plane dimensions for the unfolded cross-section layout.
   * In unfold mode all helix midpoints converge to (x=0, y=−row×spacing),
   * so the lateral footprint collapses to nearly a point in X and stretches
   * vertically by N×spacing.  Only meaningful for XY-plane (Z-axis bundles).
   */
  function _computeUnfoldDimensions() {
    const { currentDesign, unfoldSpacing = 3.0 } = store.getState()
    const nHelices = currentDesign?.helices?.length ?? 0
    if (!nHelices || _plane !== 'XY') return _computePlaneDimensions()
    const spacing = unfoldSpacing
    return {
      width:  3,
      height: Math.max((nHelices - 1) * spacing + PLANE_SIZE_MARGIN * 2, 10),
      cx:     0,
      cy:     -(nHelices - 1) * spacing / 2,
    }
  }

  /** Linearly interpolate between 3D and unfold dimensions at lerp factor t. */
  function _computeLerpedDimensions(t) {
    const d3 = _computePlaneDimensions()
    if (t === 0) return d3
    const du = _computeUnfoldDimensions()
    return {
      width:  d3.width  + (du.width  - d3.width)  * t,
      height: d3.height + (du.height - d3.height) * t,
      cx:     d3.cx     + (du.cx     - d3.cx)     * t,
      cy:     d3.cy     + (du.cy     - d3.cy)     * t,
    }
  }

  function _resizePlane() {
    const { width, height, cx, cy } = _cadnanoDims ?? _computeLerpedDimensions(_unfoldT)
    _planeW = width
    _planeH = height
    // Set lateral center: centroid of all helix positions in the plane's two tangent axes.
    if      (_plane === 'XY') _lateralCenter.set(cx, cy, 0)
    else if (_plane === 'XZ') _lateralCenter.set(cx, 0,  cy)
    else                      _lateralCenter.set(0,  cx, cy)
    _planeMesh.geometry.dispose()
    _planeMesh.geometry = new THREE.BoxGeometry(width, height, RISE)
    _borderMesh.geometry.dispose()
    _borderMesh.geometry = new THREE.EdgesGeometry(new THREE.BoxGeometry(width, height, RISE))
  }

  // ── BP corner label sprites ──────────────────────────────────────────────────

  const _BP_LABEL_W  = 128   // canvas pixels
  const _BP_LABEL_H  = 40
  const _BP_LABEL_NM = 1.1   // sprite height in world units (nm)

  /** Create a reusable sprite whose canvas texture can be redrawn. */
  function _makeBpLabelSprite() {
    const cv  = document.createElement('canvas')
    cv.width  = _BP_LABEL_W
    cv.height = _BP_LABEL_H
    const tex = new THREE.CanvasTexture(cv)
    tex.needsUpdate = true
    const mat = new THREE.SpriteMaterial({
      map: tex, transparent: true, depthWrite: false, depthTest: false,
    })
    const spr = new THREE.Sprite(mat)
    const aspect = _BP_LABEL_W / _BP_LABEL_H
    spr.scale.set(_BP_LABEL_NM * aspect, _BP_LABEL_NM, 1)
    spr.frustumCulled = false
    spr.renderOrder   = 999
    spr.visible       = false
    spr.userData._canvas = cv
    return spr
  }

  /** Redraw both bp-corner sprites with just the bp number. */
  function _updateBpLabelText(bp) {
    const text = String(bp)
    for (const spr of [_bpLabelLeft, _bpLabelRight]) {
      const cv  = spr.userData._canvas
      const ctx = cv.getContext('2d')
      ctx.clearRect(0, 0, cv.width, cv.height)
      ctx.font = 'bold 22px sans-serif'
      const tw = ctx.measureText(text).width
      // Subtle semi-transparent pill
      const pad = 6, r = 6
      const x0 = (cv.width - tw - pad * 2) / 2, y0 = 3, w = tw + pad * 2, h = cv.height - 6
      ctx.beginPath()
      ctx.moveTo(x0 + r, y0)
      ctx.lineTo(x0 + w - r, y0)
      ctx.arcTo(x0 + w, y0, x0 + w, y0 + r, r)
      ctx.lineTo(x0 + w, y0 + h - r)
      ctx.arcTo(x0 + w, y0 + h, x0 + w - r, y0 + h, r)
      ctx.lineTo(x0 + r, y0 + h)
      ctx.arcTo(x0, y0 + h, x0, y0 + h - r, r)
      ctx.lineTo(x0, y0 + r)
      ctx.arcTo(x0, y0, x0 + r, y0, r)
      ctx.closePath()
      ctx.fillStyle = 'rgba(8,16,32,0.65)'
      ctx.fill()
      ctx.fillStyle    = 'rgba(200,220,255,0.90)'
      ctx.textAlign    = 'center'
      ctx.textBaseline = 'middle'
      ctx.fillText(text, cv.width / 2, cv.height / 2)
      spr.material.map.needsUpdate = true
    }
  }

  const _bpLabelLeft  = _makeBpLabelSprite()
  const _bpLabelRight = _makeBpLabelSprite()
  _root.add(_bpLabelLeft)
  _root.add(_bpLabelRight)

  // ── Deformed mode helpers ───────────────────────────────────────────────────

  /** Cell world position using the deformed cross-section frame. */
  function _cellWorldPosDeformed(row, col) {
    let lx, ly
    if (_isSquareLattice()) {
      lx = col * SQUARE_HELIX_SPACING
      ly = row * SQUARE_HELIX_SPACING
    } else {
      lx = col * HONEYCOMB_COL_PITCH
      ly = row * HONEYCOMB_ROW_PITCH + ((col % 2 === 0) ? HONEYCOMB_LATTICE_RADIUS : 0)
    }
    const go = new THREE.Vector3(..._deformedFrame.grid_origin)
    const fr = new THREE.Vector3(..._deformedFrame.frame_right)
    const fu = new THREE.Vector3(..._deformedFrame.frame_up)
    return go.clone().addScaledVector(fr, lx).addScaledVector(fu, ly)
  }

  /**
   * Cell state in deformed mode: uses 3-D proximity of deformed helix endpoints.
   * Falls back to 'free' if no axes available.
   */
  function _cellStateDeformed(row, col) {
    const design    = getDesign?.()
    const helixAxes = getHelixAxes?.()
    if (!design || !helixAxes) return 'free'

    const cellPos = _cellWorldPosDeformed(row, col)
    const TOL = 0.5  // nm

    for (const h of design.helices) {
      const ax = helixAxes[h.id]
      if (!ax) continue
      const endPt   = new THREE.Vector3(...ax.end)
      const startPt = new THREE.Vector3(...ax.start)
      if (cellPos.distanceTo(endPt) < TOL || cellPos.distanceTo(startPt) < TOL) {
        return _continuationMode ? 'continuable' : 'occupied'
      }
    }
    return 'free'
  }

  // ── Position update ─────────────────────────────────────────────────────────

  function _updatePosition() {
    if (_deformedFrame) {
      const origin  = new THREE.Vector3(..._deformedFrame.grid_origin)
      const axisDir = new THREE.Vector3(..._deformedFrame.axis_dir).normalize()
      const quat    = new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 0, 1), axisDir)

      _planeMesh.position.copy(origin)
      _planeMesh.quaternion.copy(quat)
      _borderMesh.position.copy(origin)
      _borderMesh.quaternion.copy(quat)

      const fr = new THREE.Vector3(..._deformedFrame.frame_right)
      const fu = new THREE.Vector3(..._deformedFrame.frame_up)
      _handleGroup.position.copy(
        origin.clone().addScaledVector(fr, LATTICE_CX).addScaledVector(fu, LATTICE_CY),
      )

      const up    = new THREE.Vector3(0, 1, 0)
      const qFwd  = new THREE.Quaternion().setFromUnitVectors(up, axisDir)
      const qBack = new THREE.Quaternion().setFromUnitVectors(up, axisDir.clone().negate())
      _coneFwd.position.copy(axisDir.clone().multiplyScalar(1.3))
      _coneFwd.quaternion.copy(qFwd)
      _coneBack.position.copy(axisDir.clone().negate().multiplyScalar(1.3))
      _coneBack.quaternion.copy(qBack)
      return
    }

    const cfg = PLANE_CFG[_plane]

    // Plane mesh at offset along normal + lateral centroid of helix cross-section
    _planeMesh.position.copy(cfg.normal).multiplyScalar(_offset).add(_lateralCenter)
    _planeMesh.setRotationFromEuler(cfg.rotation)
    _borderMesh.position.copy(_planeMesh.position)
    _borderMesh.setRotationFromEuler(cfg.rotation)

    // Handle at lattice centre + offset along normal (lateral center is zero in non-read-only mode)
    _handleGroup.position.copy(cfg.handleCenter(_offset)).add(_lateralCenter)

    // Orient cones along +normal / -normal
    const up = new THREE.Vector3(0, 1, 0)
    const qFwd  = new THREE.Quaternion().setFromUnitVectors(up, cfg.normal)
    const qBack = new THREE.Quaternion().setFromUnitVectors(up, cfg.normal.clone().negate())
    _coneFwd.position.copy(cfg.normal.clone().multiplyScalar(1.3))
    _coneFwd.quaternion.copy(qFwd)
    _coneBack.position.copy(cfg.normal.clone().negate().multiplyScalar(1.3))
    _coneBack.quaternion.copy(qBack)

    // Reposition lattice circles and labels if visible
    if (_latticeMode) {
      const nudge = _labelNudge()
      for (let i = 0; i < _circleMeshes.length; i++) {
        const { fill, ring, row, col } = _circleMeshes[i]
        const pos = cellWorldPos(row, col, _plane, _offset)
        fill.position.copy(pos)
        ring.position.copy(pos)
        if (i < _labelSprites.length) _labelSprites[i].position.copy(pos).add(nudge)
      }
    }

    if (_readOnly && _visible) {
      onOffsetChange?.(_offset, _plane)

      // Position bp-corner labels at upper-left and upper-right of the plane.
      // The plane's local axes in world space: use the rotation of _planeMesh.
      const halfW   = _planeW / 2
      const halfH   = _planeH / 2
      const insetX  = _BP_LABEL_NM * (_BP_LABEL_W / _BP_LABEL_H) * 0.55
      const insetY  = _BP_LABEL_NM * 0.55

      // Build local-space corner offsets, then rotate to world space.
      const localL = new THREE.Vector3(-halfW + insetX,  halfH - insetY, 0)
      const localR = new THREE.Vector3( halfW - insetX,  halfH - insetY, 0)
      localL.applyEuler(cfg.rotation)
      localR.applyEuler(cfg.rotation)

      // Translate to plane's world position (offset along normal + lateral centroid).
      const planePos = cfg.normal.clone().multiplyScalar(_offset).add(_lateralCenter)
      _bpLabelLeft.position.copy(planePos).add(localL)
      _bpLabelRight.position.copy(planePos).add(localR)

      const bp = Math.round(_offset / RISE)
      _updateBpLabelText(bp)
      _bpLabelLeft.visible  = true
      _bpLabelRight.visible = true
    }
  }

  // ── Lattice ────────────────────────────────────────────────────────────────

  // Returns 'free' | 'continuable' | 'occupied'
  function _cellState(row, col) {
    if (_deformedFrame) return _cellStateDeformed(row, col)

    const helices = getDesign?.()?.helices ?? []
    const prefix  = `h_${_plane}_${row}_${col}`
    const cfg     = PLANE_CFG[_plane]
    const tol     = RISE * 0.05

    for (const h of helices) {
      if (!h.id.startsWith(prefix)) continue
      const [lo, hi] = cfg.axisRange(h)
      // Helix ends exactly at this offset → continuable in continuation mode
      if (Math.abs(hi - _offset) < tol || Math.abs(lo - _offset) < tol) {
        return _continuationMode ? 'continuable' : 'occupied'
      }
      // Helix strictly spans this offset → always occupied
      if (_offset > lo + tol && _offset < hi - tol) return 'occupied'
    }
    return 'free'
  }

  // Compute row/col extent of existing helices on this plane + margin,
  // falling back to a centred grid that fills the 40×40 nm slice plane.
  function _computeGridBounds() {
    const helices = getDesign?.()?.helices ?? []
    let minRow = -DEFAULT_ROW_HALF, maxRow = DEFAULT_ROW_HALF
    let minCol = -DEFAULT_COL_HALF, maxCol = DEFAULT_COL_HALF
    const prefix = `h_${_plane}_`
    for (const h of helices) {
      if (!h.id.startsWith(prefix)) continue
      const tail = h.id.slice(prefix.length).split('_')
      if (tail.length < 2) continue
      const row = parseInt(tail[0], 10)
      const col = parseInt(tail[1], 10)
      if (!isFinite(row) || !isFinite(col)) continue
      minRow = Math.min(minRow, row)
      maxRow = Math.max(maxRow, row)
      minCol = Math.min(minCol, col)
      maxCol = Math.max(maxCol, col)
    }
    return {
      rowStart: minRow - MARGIN,
      rowEnd:   maxRow + MARGIN,
      colStart: minCol - MARGIN,
      colEnd:   maxCol + MARGIN,
    }
  }

  // Returns 0–1: 1 = cursor is close (full opacity), 0 = cursor is far / absent
  function _proximityFactor(worldPos) {
    if (!_cursorPx) return 0
    _projVec.copy(worldPos).project(camera)
    const rect = canvas.getBoundingClientRect()
    const sx   = (_projVec.x *  0.5 + 0.5) * rect.width
    const sy   = (_projVec.y * -0.5 + 0.5) * rect.height
    const dist = Math.hypot(sx - _cursorPx.x, sy - _cursorPx.y)
    if (dist <= PROX_FULL_PX) return 1
    if (dist >= PROX_FADE_PX) return 0
    return (PROX_FADE_PX - dist) / (PROX_FADE_PX - PROX_FULL_PX)
  }

  /** Return 1-based helix index for the occupied cell (row, col), or null if not found. */
  function _helixNumberForCell(row, col) {
    const design = getDesign?.()
    if (!design?.helices) return null
    if (_deformedFrame) {
      // Deformed mode: find helix whose deformed endpoint is nearest to this cell position
      const helixAxes = getHelixAxes?.()
      if (!helixAxes) return null
      const cellPos = _cellWorldPosDeformed(row, col)
      const TOL = 0.6
      for (let i = 0; i < design.helices.length; i++) {
        const ax = helixAxes[design.helices[i].id]
        if (!ax) continue
        if (cellPos.distanceTo(new THREE.Vector3(...ax.end))   < TOL) return i + 1
        if (cellPos.distanceTo(new THREE.Vector3(...ax.start)) < TOL) return i + 1
      }
      return null
    }
    // Normal mode: helix ID matches exactly
    const idx = design.helices.findIndex(h => h.id === `h_${_plane}_${row}_${col}`)
    return idx >= 0 ? idx + 1 : null
  }

  // Small nudge vector to put labels in front of the plane face (avoids z-fighting)
  function _labelNudge() {
    if (_deformedFrame) {
      return new THREE.Vector3(..._deformedFrame.axis_dir).normalize().multiplyScalar(0.05)
    }
    return PLANE_CFG[_plane].normal.clone().multiplyScalar(0.05)
  }

  function _buildLattice() {
    _clearLattice()

    // Pick cell helpers based on the current design's lattice type.
    const sq = _isSquareLattice()
    isValidCell  = sq ? isValidSquareCell  : isValidHoneycombCell
    cellWorldPos = sq ? squareCellWorldPos : honeycombCellWorldPos

    const { rowStart, rowEnd, colStart, colEnd } = _computeGridBounds()

    // Quaternion that orients circles to face the current slice plane normal
    let latticeQuat
    if (_deformedFrame) {
      const axisDir = new THREE.Vector3(..._deformedFrame.axis_dir).normalize()
      latticeQuat   = new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 0, 1), axisDir)
    } else {
      latticeQuat = PLANE_CFG[_plane].latticeQuat
    }

    const nudge = _labelNudge()
    let labelCount = 0

    for (let row = rowStart; row <= rowEnd; row++) {
      for (let col = colStart; col <= colEnd; col++) {
        if (!isValidCell(row, col)) continue
        const state = _cellState(row, col)
        const pos   = _deformedFrame
          ? _cellWorldPosDeformed(row, col)
          : cellWorldPos(row, col, _plane, _offset)

        const baseColor = state === 'occupied'    ? C_OCCUPIED
                        : state === 'continuable' ? C_CONTINUABLE
                        :                           C_CELL

        // Start at minimum opacity — proximity update brightens them as cursor moves
        const fillMat = new THREE.MeshBasicMaterial({
          color: baseColor.clone(),
          transparent: true,
          opacity: state === 'occupied' ? FILL_MIN_OCC : FILL_MIN_FREE,
          side: THREE.DoubleSide,
        })
        const fill = new THREE.Mesh(_circleGeo, fillMat)
        fill.position.copy(pos)
        fill.quaternion.copy(latticeQuat)
        fill.userData = { row, col, state }

        const ringMat = new THREE.MeshBasicMaterial({
          color: baseColor.clone(),
          transparent: true,
          opacity: state === 'occupied' ? RING_MIN_OCC : RING_MIN_FREE,
          side: THREE.DoubleSide,
        })
        const ring = new THREE.Mesh(_ringGeo, ringMat)
        ring.position.copy(pos)
        ring.quaternion.copy(latticeQuat)
        ring.userData = { row, col, state }

        _latGroup.add(fill)
        _latGroup.add(ring)
        _circleMeshes.push({ fill, ring, row, col, state })

        // ── Cell label for every valid cell ───────────────────────────────
        {
          let spr
          if (state === 'occupied' || state === 'continuable') {
            const num = _helixNumberForCell(row, col)
            spr = num !== null ? _makeHelixLabel(num) : _makeCellCoordLabel(row, col)
          } else {
            spr = _makeCellCoordLabel(row, col)
          }
          // Nudge slightly in front of the plane so it clears the plane geometry
          spr.position.copy(pos).add(nudge)
          spr.renderOrder = 10
          _latGroup.add(spr)
          _labelSprites.push(spr)
          labelCount++
        }
      }
    }
    console.log(`[SlicePlane] _buildLattice: plane=${_plane} offset=${_offset.toFixed(3)} circles=${_circleMeshes.length} labels=${labelCount}`)
    if (_labelSprites.length > 0) {
      const s = _labelSprites[0]
      console.log(`[SlicePlane] first label: pos=${JSON.stringify(s.position.toArray().map(v=>+v.toFixed(3)))} renderOrder=${s.renderOrder} depthTest=${s.material.depthTest} scale=${JSON.stringify(s.scale.toArray())}`)
    }
    _latGroup.visible = true
  }

  function _clearLattice() {
    for (const { fill, ring } of _circleMeshes) {
      fill.material.dispose()
      ring.material.dispose()
      _latGroup.remove(fill)
      _latGroup.remove(ring)
    }
    for (const spr of _labelSprites) {
      spr.material.map?.dispose()
      spr.material.dispose()
      _latGroup.remove(spr)
    }
    _circleMeshes = []
    _labelSprites = []
    _selected.clear()
    _hoverCell = null
    _latGroup.visible = false
  }

  function _updateCircleColors() {
    for (const { fill, ring, row, col, state } of _circleMeshes) {
      const key     = `${row},${col}`
      const isSel   = _selected.has(key)
      const isHover = _hoverCell?.row === row && _hoverCell?.col === col
      const prox    = _proximityFactor(fill.position)

      if (state === 'occupied') {
        // Occupied: dim at all times, slightly brighter near cursor
        fill.material.opacity = FILL_MIN_OCC + prox * (FILL_MAX_OCC - FILL_MIN_OCC)
        ring.material.opacity = RING_MIN_OCC + prox * (RING_MAX_OCC - RING_MIN_OCC)
        continue
      }

      // Selected: always fully visible regardless of cursor proximity
      if (isSel) {
        fill.material.color.copy(C_SELECTED)
        fill.material.opacity = 0.9
        ring.material.color.copy(C_SELECTED)
        ring.material.opacity = 1.0
        continue
      }

      const baseColor = state === 'continuable' ? C_CONTINUABLE : C_CELL

      if (isHover) {
        fill.material.color.copy(C_HOVER)
        fill.material.opacity = 0.75
        ring.material.color.copy(baseColor)
        ring.material.opacity = RING_MAX_FREE
      } else {
        fill.material.color.copy(baseColor)
        fill.material.opacity = FILL_MIN_FREE + prox * (FILL_MAX_FREE - FILL_MIN_FREE)
        ring.material.color.copy(baseColor)
        ring.material.opacity = RING_MIN_FREE + prox * (RING_MAX_FREE - RING_MIN_FREE)
      }
    }
  }

  // ── Raycasting helpers ──────────────────────────────────────────────────────

  function _rayHandle() {
    return _raycaster.intersectObjects([_sphere, _coneFwd, _coneBack]).length > 0
  }

  function _rayPlane() {
    return _raycaster.intersectObject(_planeMesh).length > 0
  }

  function _rayCells() {
    const selectable = _circleMeshes.filter(c => c.state !== 'occupied').map(c => c.fill)
    const hits = _raycaster.intersectObjects(selectable)
    return hits.length ? hits[0].object.userData : null
  }

  /** Raycast ALL cells (including occupied) — used to detect hits for propagation blocking. */
  function _rayAnyCells() {
    const allFills = _circleMeshes.map(c => c.fill)
    const hits = _raycaster.intersectObjects(allFills)
    return hits.length ? hits[0].object.userData : null
  }

  // ── Event handlers ──────────────────────────────────────────────────────────

  function _onPointerDown(e) {
    if (!_visible) return
    _pointerDownPos = { x: e.clientX, y: e.clientY }

    if (e.button === 0) {
      _setNDC(e)
      if (_rayHandle()) {
        _isDragging = true
        _isDragSelecting = false
        _dragStartOffset = _offset
        // Billboard drag plane: perpendicular to camera at handle position
        _camera.getWorldDirection(_tmp)
        _dragPlane.setFromNormalAndCoplanarPoint(_tmp, _handleGroup.position)
        _raycaster.ray.intersectPlane(_dragPlane, _dragStartPoint)
        controls.enabled = false
        e.stopImmediatePropagation()
      } else if (_rayPlane() || (_latticeMode && _rayAnyCells())) {
        if (_readOnly) {
          // In read-only mode: clicking the plane face initiates a drag to slide the slice position
          const hits = _raycaster.intersectObject(_planeMesh)
          if (hits.length) {
            _isDragging      = true
            _isDragSelecting = false
            _dragStartOffset = _offset
            _camera.getWorldDirection(_tmp)
            _dragPlane.setFromNormalAndCoplanarPoint(_tmp, hits[0].point)
            _raycaster.ray.intersectPlane(_dragPlane, _dragStartPoint)
            controls.enabled = false
          }
        } else {
          // Intercept ALL plane/cell clicks — prevent OrbitControls from starting rotation
          _pendingCellClick = true
        }
        e.stopImmediatePropagation()
      }
    } else if (e.button === 2) {
      _rightDownPos = { x: e.clientX, y: e.clientY }
    }
  }

  function _onPointerMove(e) {
    if (!_visible) return
    _setNDC(e)

    // Track cursor for proximity-based opacity
    const rect = canvas.getBoundingClientRect()
    _cursorPx = { x: e.clientX - rect.left, y: e.clientY - rect.top }

    if (_isDragging) {
      if (_raycaster.ray.intersectPlane(_dragPlane, _tmp)) {
        const n     = PLANE_CFG[_plane].normal
        const delta = _tmp.clone().sub(_dragStartPoint).dot(n)
        _offset = _snap(_dragStartOffset + delta)
        _updatePosition()
      }
      return
    }

    if (_latticeMode) {
      _hoverCell = _rayCells()

      // Upgrade pending click → lasso once movement exceeds 4px
      if (_pendingCellClick && _pointerDownPos &&
          Math.hypot(e.clientX - _pointerDownPos.x, e.clientY - _pointerDownPos.y) > 4) {
        _pendingCellClick = false
        _isDragSelecting  = true
      }

      // Lasso drag-select: add cells to selection as cursor sweeps over them
      if (_isDragSelecting && _hoverCell) {
        _selected.add(`${_hoverCell.row},${_hoverCell.col}`)
      }

      _updateCircleColors()   // always refresh — cursor moved so proximity changed
    }
  }

  function _onPointerUp(e) {
    if (!_visible) return

    if (_isDragging) {
      _isDragging = false
      controls.enabled = true
      // Rebuild lattice so occupied state matches new offset
      if (_latticeMode) _buildLattice()
      return
    }

    if (_isDragSelecting) {
      _isDragSelecting = false
      // Lasso drag ended — selection already accumulated during pointermove, nothing more to do
      _updateCircleColors()
      return
    }

    // pendingCellClick that never became a drag → fall through to single-click toggle below
    _pendingCellClick = false

    if (e.button !== 0) return
    if (_pointerDownPos && Math.hypot(e.clientX - _pointerDownPos.x, e.clientY - _pointerDownPos.y) > 4) return

    _setNDC(e)
    _hideContextMenu()

    if (_latticeMode) {
      const cell = _rayCells()
      if (cell) {
        const key = `${cell.row},${cell.col}`
        if (_selected.has(key)) _selected.delete(key)
        else _selected.add(key)
        _updateCircleColors()
      }
      // Clicks on empty plane surface are no-ops — lattice stays open,
      // selection is preserved.  Lattice only closes via hide() or Escape.
    }
  }

  function _onContextMenu(e) {
    if (!_visible || !_latticeMode || _readOnly) return
    if (_rightDownPos) {
      const moved = Math.hypot(e.clientX - _rightDownPos.x, e.clientY - _rightDownPos.y)
      _rightDownPos = null
      if (moved > 4) return
    }
    e.preventDefault()
    _setNDC(e)
    // Auto-select cell under cursor
    const cell = _rayCells()
    if (cell) {
      _selected.add(`${cell.row},${cell.col}`)
      _updateCircleColors()
    }
    if (_selected.size === 0) return
    _showContextMenu(e.clientX, e.clientY)
  }

  // ── Context menu ────────────────────────────────────────────────────────────

  const _ctxEl = document.getElementById('slice-ctx-menu')

  const _sliceTotalBpEl   = _ctxEl?.querySelector('#slice-total-bp')
  const _sliceScaffoldRec = _ctxEl?.querySelector('#slice-scaffold-rec')
  const _sliceLengthInput = _ctxEl?.querySelector('#slice-length')
  const _sliceUnitSelect  = _ctxEl?.querySelector('#slice-unit')
  const _sliceDirFwd      = _ctxEl?.querySelector('#slice-dir-fwd')
  const _sliceDirBwd      = _ctxEl?.querySelector('#slice-dir-bwd')
  let _sliceDirSign = 1

  if (_sliceDirFwd) _sliceDirFwd.addEventListener('click', () => {
    _sliceDirSign = 1
    _sliceDirFwd.classList.add('ctx-dir-active')
    _sliceDirBwd?.classList.remove('ctx-dir-active')
    _updateSliceTotalBp()
  })
  if (_sliceDirBwd) _sliceDirBwd.addEventListener('click', () => {
    _sliceDirSign = -1
    _sliceDirBwd.classList.add('ctx-dir-active')
    _sliceDirFwd?.classList.remove('ctx-dir-active')
    _updateSliceTotalBp()
  })

  // Scaffold targets: M13mp18 and p8064
  const _SCAFFOLD_TARGETS = [{ name: 'M13', nt: 7249 }, { name: 'p8064', nt: 8064 }]
  // 7 bp extension assumed at each end of every helix for scaffold end loops/crossovers
  const _END_MARGIN_BP = 7

  function _updateSliceTotalBp() {
    if (!_sliceTotalBpEl || !_sliceLengthInput) return
    const count  = _selected.size
    const rawVal = parseFloat(_sliceLengthInput.value)
    const unit   = _sliceUnitSelect?.value ?? 'bp'
    const absBp  = unit === 'bp'
      ? Math.abs(Math.trunc(rawVal)) || 1
      : Math.max(1, Math.round(Math.abs(rawVal) / RISE))
    const bp     = _sliceDirSign * absBp
    if (!count || isNaN(rawVal)) {
      _sliceTotalBpEl.textContent = ''
      if (_sliceScaffoldRec) _sliceScaffoldRec.textContent = ''
      return
    }
    _sliceTotalBpEl.textContent =
      `${count} × ${bp < 0 ? '-' : ''}${absBp} bp = ${bp < 0 ? '-' : ''}${count * absBp} bp total`

    // Scaffold length recommendation: existing helices + selected new helices,
    // each contributing length_bp + 2×_END_MARGIN_BP to the scaffold path.
    if (_sliceScaffoldRec) {
      const existingHelices = getDesign?.()?.helices ?? []
      const existingBp = existingHelices.reduce((s, h) => s + h.length_bp + 2 * _END_MARGIN_BP, 0)
      const chips = _SCAFFOLD_TARGETS.map(({ name, nt }) => {
        const remaining = nt - existingBp
        const recBp = Math.max(1, Math.floor(remaining / count) - 2 * _END_MARGIN_BP)
        return `<button class="rec-chip" data-bp="${recBp}" title="Set length to ${recBp} bp">
          <span style="font-size:18px;font-weight:600;color:#c9d1d9;line-height:1.1">${nt}</span>
          <span style="font-size:10px;color:#8b949e"> nt</span><br>
          <span style="font-size:11px;color:#79c0ff">${recBp} bp</span>
        </button>`
      }).join('')
      _sliceScaffoldRec.innerHTML = `
        <div style="font-size:10px;color:#6e7681;margin-bottom:4px">Recommended length (14 nt scaffold loops/helix)</div>
        <div style="display:flex;gap:6px">${chips}</div>`
    }
  }

  if (_sliceLengthInput) _sliceLengthInput.addEventListener('input', _updateSliceTotalBp)
  if (_sliceUnitSelect)  _sliceUnitSelect.addEventListener('change', _updateSliceTotalBp)
  if (_sliceScaffoldRec) _sliceScaffoldRec.addEventListener('click', e => {
    const btn = e.target.closest('.rec-chip')
    if (!btn || !_sliceLengthInput) return
    e.stopPropagation()
    _sliceUnitSelect && (_sliceUnitSelect.value = 'bp')
    _sliceLengthInput.value = btn.dataset.bp
    _updateSliceTotalBp()
  })

  function _showContextMenu(x, y) {
    if (!_ctxEl) return
    _ctxEl.querySelector('.ctx-count').textContent =
      `${_selected.size} helix${_selected.size > 1 ? 'es' : ''}`
    _updateSliceTotalBp()
    _ctxEl.style.left    = `${x}px`
    _ctxEl.style.top     = `${y}px`
    _ctxEl.style.display = 'block'
  }

  function _hideContextMenu() {
    if (_ctxEl) _ctxEl.style.display = 'none'
  }

  if (_ctxEl) {
    async function _doExtrude() {
      const rawVal  = parseFloat(_ctxEl.querySelector('#slice-length').value)
      const unit    = _ctxEl.querySelector('#slice-unit').value
      const absVal  = Math.abs(rawVal)
      const absLengthBp = unit === 'bp'
        ? Math.abs(Math.trunc(rawVal)) || 1
        : Math.max(1, Math.round(absVal / RISE))
      const lengthBp = _sliceDirSign * absLengthBp

      const cells = [..._selected].map(k => k.split(',').map(Number))
      const filterEl = _ctxEl.querySelector('input[name="slice-strand-filter"]:checked')
      const strandFilter = filterEl?.value ?? 'both'
      _hideContextMenu()
      try {
        await onExtrude?.({
          cells, lengthBp, plane: _plane, offsetNm: _offset,
          continuationMode: _continuationMode,
          deformedFrame: _deformedFrame,
          refHelixId: _refHelixId,
          strandFilter,
        })
      } catch (err) {
        console.error('Slice extrude failed:', err)
      }
      // Rebuild lattice so newly-occupied cells are greyed
      if (_latticeMode) _buildLattice()
      _selected.clear()
    }

    _ctxEl.querySelector('#slice-extrude-btn').addEventListener('click', _doExtrude)

    _ctxEl.querySelector('#slice-length').addEventListener('keydown', e => {
      if (e.key === 'Enter') _doExtrude()
    })

    _ctxEl.querySelector('#slice-cancel-btn').addEventListener('click', _hideContextMenu)
  }

  document.addEventListener('pointerdown', e => {
    if (_ctxEl && !_ctxEl.contains(e.target)) _hideContextMenu()
  })

  // ── Attach events ───────────────────────────────────────────────────────────

  canvas.addEventListener('pointerdown',  _onPointerDown, { capture: true })
  canvas.addEventListener('pointermove',  _onPointerMove)
  canvas.addEventListener('pointerup',    _onPointerUp)
  canvas.addEventListener('contextmenu',  _onContextMenu)
  canvas.addEventListener('pointerleave', () => {
    if (!_visible || !_latticeMode) return
    _cursorPx  = null
    _hoverCell = null
    _updateCircleColors()
  })

  // ── Public API ──────────────────────────────────────────────────────────────

  return {
    /**
     * Show the slice plane at the given lattice plane + offset.
     * @param {string}  plane          - 'XY' | 'XZ' | 'YZ'
     * @param {number}  offsetNm       - starting offset along the axis in nm
     * @param {boolean} [continuation] - if true, cells ending at offset are amber/selectable
     */
    show(plane, offsetNm, continuation = false, readOnly = false) {
      _plane            = plane ?? 'XY'
      _offset           = _snap(offsetNm ?? 0)
      _continuationMode = !!continuation
      _readOnly         = !!readOnly
      _latticeMode      = !readOnly   // no lattice in read-only mode
      _visible          = true
      _root.visible     = true
      // Orbit rotation stays enabled in all modes so the user can freely rotate
      // during extrude/lattice operations.
      _handleGroup.visible = !readOnly
      if (readOnly) {
        _resizePlane()
        _clearLattice()             // ensure no stale lattice cells are visible
        _latGroup.visible = false
      }
      _updatePosition()
      if (!readOnly) _buildLattice()
    },

    hide() {
      _visible       = false
      _root.visible  = false
      _latticeMode   = false
      _readOnly         = false
      _handleGroup.visible = true
      _deformedFrame = null
      _refHelixId    = null
      _lateralCenter.set(0, 0, 0)
      _bpLabelLeft.visible  = false
      _bpLabelRight.visible = false
      _clearLattice()
      _hideContextMenu()
      _isDragging       = false
      _isDragSelecting  = false
      _pendingCellClick = false
      controls.enabled = true
    },

    isVisible() { return _visible },

    /**
     * Called by unfold_view each animation frame (and at t=0/1 on activate/deactivate).
     * Lerps the slice-plane dimensions from the 3D cross-section footprint (t=0)
     * to the unfolded stacked-helix cross-section (t=1).
     * Always updates _unfoldT so that the next show() uses the right dimensions,
     * even if the plane is currently hidden.
     */
    applyUnfoldT(t) {
      _unfoldT = t
      if (!_visible || !_readOnly) return
      _resizePlane()
      _updatePosition()
    },

    /** Re-render the lattice if it is currently shown (e.g. after a design update). */
    refreshLattice() {
      if (_latticeMode) _buildLattice()
    },

    /**
     * Show the slice plane in deformed mode at the given cross-section frame.
     * Cells are positioned using grid_origin + frame_right*lx + frame_up*ly.
     * @param {object} frame  - { grid_origin, axis_dir, frame_right, frame_up }
     * @param {object} [opts] - { plane, continuation }
     */
    showDeformed(frame, { plane = 'XY', continuation = false, refHelixId = null } = {}) {
      _deformedFrame    = frame
      _refHelixId       = refHelixId
      _plane            = plane
      _continuationMode = !!continuation
      _latticeMode      = true
      _visible          = true
      _root.visible     = true
      controls.enableRotate = false
      _updatePosition()
      _buildLattice()
    },

    /** Replace the camera used for raycasting (called by cadnano_view when switching to ortho). */
    setCamera(cam) { _camera = cam },

    /** Current plane and offset getters (used by cadnano_view to save/restore state). */
    getPlane()  { return _plane },
    getPlaneOffset() { return _offset },

    /**
     * Override plane dimensions for cadnano mode.
     * dims = { width, height, cx, cy } in the same coordinate system as _computeLerpedDimensions.
     * Call clearCadnanoDimensions() on exit to restore normal behaviour.
     */
    setCadnanoDimensions(dims) {
      _cadnanoDims = dims
      if (_visible && _readOnly) { _resizePlane(); _updatePosition() }
    },

    clearCadnanoDimensions() {
      _cadnanoDims = null
      if (_visible && _readOnly) { _resizePlane(); _updatePosition() }
    },

    /** Debug: call window.SLICE.debug() in browser console to inspect internal state. */
    debug() {
      console.group('[SlicePlane] debug state')
      console.log('visible:', _visible, '_root.visible:', _root.visible)
      console.log('latticeMode:', _latticeMode)
      console.log('plane:', _plane, 'offset:', _offset)
      console.log('_latGroup.visible:', _latGroup.visible)
      console.log('_latGroup children:', _latGroup.children.length)
      console.log('_circleMeshes:', _circleMeshes.length)
      console.log('_labelSprites:', _labelSprites.length)
      if (_labelSprites.length > 0) {
        const s = _labelSprites[0]
        console.log('label[0] pos:', s.position.toArray().map(v => +v.toFixed(3)))
        console.log('label[0] scale:', s.scale.toArray())
        console.log('label[0] renderOrder:', s.renderOrder)
        console.log('label[0] depthTest:', s.material.depthTest)
        console.log('label[0] opacity:', s.material.opacity)
        console.log('label[0] visible:', s.visible)
        console.log('label[0] map:', s.material.map)
        console.log('label[0] frustumCulled:', s.frustumCulled)
        // Check world position
        const wp = new THREE.Vector3()
        s.getWorldPosition(wp)
        console.log('label[0] worldPos:', wp.toArray().map(v => +v.toFixed(3)))
      }
      if (_circleMeshes.length > 0) {
        const c = _circleMeshes[0]
        console.log('circle[0] pos:', c.fill.position.toArray().map(v => +v.toFixed(3)))
        console.log('circle[0] state:', c.state)
        const wp = new THREE.Vector3()
        c.fill.getWorldPosition(wp)
        console.log('circle[0] worldPos:', wp.toArray().map(v => +v.toFixed(3)))
      }
      console.groupEnd()
    },
  }
}
