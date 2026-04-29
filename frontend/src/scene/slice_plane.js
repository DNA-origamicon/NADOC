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

// Default grid extents when no design is loaded.
// Origin (0,0) is at the world origin; row/col indices start at 0.
// MARGIN adds empty padding cells on all sides around the design extent.
//   col 0..10 + margin → −5..+15  →  X ≈ −9.7..+29.2 nm
//   row 0..8  + margin → −5..+13  →  Y ≈ −9.7..+43.9 nm (standard Y-up)
const DEFAULT_ROW_MAX = 8    // default max row index when empty
const DEFAULT_COL_MAX = 10   // default max col index when empty
const MARGIN           = 5   // extra cells around the design extent in each direction
const HARD_LIMIT       = 250 // max |row| or |col| — grid never expands beyond ±250
const EDGE_TRIGGER     = 5   // expand when cursor is within this many cells of the boundary
const EDGE_EXPAND      = 15  // cells added per expansion step
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

// Handle anchor: cell (0,0) sits at origin in world space.
const LATTICE_CX = 0
const LATTICE_CY = 0

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

// ── Honeycomb (cadnano2 system: all cells valid, (row+col)%2 parity) ──
// x = col × COL_PITCH + ox, y = row × ROW_PITCH + stagger + oy.
// ox/oy are the lattice origin offset derived from actual helix physical positions.
function isValidHoneycombCell(_row, _col) { return true }  // no hole cells in cadnano2

function honeycombCellWorldPos(row, col, plane, offset, ox = 0, oy = 0) {
  const lx  = col * HONEYCOMB_COL_PITCH + ox
  const odd = (((row + col) % 2) + 2) % 2   // 1 if odd parity, 0 if even
  const ly  = row * HONEYCOMB_ROW_PITCH + (odd ? HONEYCOMB_LATTICE_RADIUS : 0) + oy
  if (plane === 'XY') return new THREE.Vector3(lx, ly, offset)
  if (plane === 'XZ') return new THREE.Vector3(lx, offset, ly)
  /* YZ */            return new THREE.Vector3(offset, lx, ly)
}

// ── Square lattice ──
// All cells are valid (checkerboard of FORWARD/REVERSE, no holes).
function isValidSquareCell(_row, _col) { return true }  // eslint-disable-line no-unused-vars

function squareCellWorldPos(row, col, plane, offset, ox = 0, oy = 0) {
  const lx = col * SQUARE_HELIX_SPACING + ox
  const ly = row * SQUARE_HELIX_SPACING + oy
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

  // ── Reusable canvas label helpers ────────────────────────────────────────────

  const _LABEL_SIZE = 128

  /** Redraw a coord label "(row,col)" onto an existing canvas in-place. */
  function _drawCoordLabel(cv, ctx, tex, row, col) {
    const r = _LABEL_SIZE / 2
    ctx.clearRect(0, 0, _LABEL_SIZE, _LABEL_SIZE)
    ctx.beginPath()
    ctx.arc(r, r, r * 0.72, 0, Math.PI * 2)
    ctx.fillStyle = 'rgba(13,17,23,0.65)'
    ctx.fill()
    ctx.fillStyle = 'rgba(220,220,220,0.92)'
    ctx.font = `${Math.floor(r * 0.44)}px sans-serif`
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
    ctx.fillText(`${row},${col}`, r, r)
    tex.needsUpdate = true
  }

  /** Redraw a helix-number badge onto an existing canvas in-place. */
  function _drawNumberLabel(cv, ctx, tex, num) {
    const r = _LABEL_SIZE / 2
    ctx.clearRect(0, 0, _LABEL_SIZE, _LABEL_SIZE)
    ctx.beginPath()
    ctx.arc(r, r, r * 0.80, 0, Math.PI * 2)
    ctx.fillStyle = 'rgba(13,17,23,0.92)'
    ctx.fill()
    ctx.beginPath()
    ctx.arc(r, r, r * 0.80, 0, Math.PI * 2)
    ctx.strokeStyle = 'rgba(88,166,255,0.90)'
    ctx.lineWidth = r * 0.14
    ctx.stroke()
    const str = String(num)
    ctx.fillStyle = '#ffffff'
    ctx.font = `bold ${Math.floor(str.length > 2 ? r * 0.66 : r * 0.84)}px sans-serif`
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
    ctx.fillText(str, r, r + 1)
    tex.needsUpdate = true
  }

  /** Create a label entry with a reusable canvas/texture.  Initial content = coord label. */
  function _makeLabelEntry(row, col) {
    const cv  = document.createElement('canvas')
    cv.width  = _LABEL_SIZE; cv.height = _LABEL_SIZE
    const ctx = cv.getContext('2d')
    const tex = new THREE.CanvasTexture(cv)
    const mat = new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false, depthTest: false })
    const spr = new THREE.Sprite(mat)
    spr.scale.set(0.80, 0.80, 1)
    spr.frustumCulled = false
    spr.renderOrder = 10
    _drawCoordLabel(cv, ctx, tex, row, col)
    return { spr, cv, ctx, tex, row, col }
  }

  /**
   * Redraw all label sprites to reflect current selection state.
   * Selected cells show their provisional helix number (existing count + selection order).
   * Occupied/continuable cells show their actual helix number.
   * All other cells show their (row,col) coordinate.
   */
  function _updateLabels() {
    const base = getDesign?.()?.helices?.length ?? 0
    const orderMap = new Map()
    for (let i = 0; i < _selectionOrder.length; i++) {
      orderMap.set(_selectionOrder[i], base + i)
    }
    for (const entry of _labelEntries) {
      const key = `${entry.row},${entry.col}`
      const selNum = orderMap.get(key)
      if (selNum !== undefined) {
        _drawNumberLabel(entry.cv, entry.ctx, entry.tex, selNum)
      } else {
        // Find cell state from _circleMeshes (parallel array)
        const cm = _circleMeshes.find(c => c.row === entry.row && c.col === entry.col)
        if (cm && (cm.state === 'occupied' || cm.state === 'continuable')) {
          const num = _helixNumberForCell(entry.row, entry.col)
          if (num !== null) _drawNumberLabel(entry.cv, entry.ctx, entry.tex, num)
          else _drawCoordLabel(entry.cv, entry.ctx, entry.tex, entry.row, entry.col)
        } else {
          _drawCoordLabel(entry.cv, entry.ctx, entry.tex, entry.row, entry.col)
        }
      }
    }
  }

  // ── Selection helpers (maintain _selected Set + _selectionOrder array) ────────

  function _selectCell(key) {
    if (_selected.has(key)) return
    _selected.add(key)
    _selectionOrder.push(key)
  }

  function _deselectCell(key) {
    if (!_selected.has(key)) return
    _selected.delete(key)
    const idx = _selectionOrder.indexOf(key)
    if (idx >= 0) _selectionOrder.splice(idx, 1)
  }

  function _toggleCell(key) {
    if (_selected.has(key)) { _deselectCell(key); return false }
    else { _selectCell(key); return true }
  }

  // ── Lattice type detection ──────────────────────────────────────────────────

  function _isSquareLattice() {
    const helices = getDesign?.()?.helices
    if (!helices?.length) return _latticeType === 'SQUARE'
    return Math.abs(helices[0].twist_per_bp_rad - SQUARE_TWIST_PER_BP_RAD) < 1e-4
  }

  // ── State ───────────────────────────────────────────────────────────────────

  let _plane            = 'XY'
  let _offset           = 0.0
  let _latticeMode      = false
  let _continuationMode = false
  let _newBundle        = false   // true when opened from workspace (new design, no existing helices)
  let _latticeType      = 'HONEYCOMB'  // 'HONEYCOMB' | 'SQUARE' — used before any helices exist
  let _deformedFrame    = null   // { grid_origin, axis_dir, frame_right, frame_up } when in deformed mode
  let _refHelixId       = null   // helix that opened the deformed frame (for cluster membership)
  let _readOnly         = false  // when true: no lattice, no extrude — display + snap only
  let _cadnanoDims      = null   // when set, overrides _computeLerpedDimensions in _resizePlane
  let _planeW           = 40    // current plane width  (nm) — updated by _resizePlane
  let _planeH           = 40    // current plane height (nm)
  let _unfoldT          = 0     // lerp factor from 3D cross-section (0) to unfold cross-section (1)
  const _lateralCenter  = new THREE.Vector3()  // centroid of helices in tangent axes (read-only mode)
  let _latticeOffsetX   = 0        // world-space X shift: cell(0,0) → this X in nm
  let _latticeOffsetY   = 0        // world-space Y shift: cell(0,0) → this Y in nm
  let _circleMeshes     = []       // { fill, ring, row, col, state }  state ∈ 'free'|'continuable'|'occupied'
  let _labelEntries     = []       // { spr, cv, ctx, tex, row, col } — canvas reused on selection change; parallel to _circleMeshes
  // helix_id → display index (design.helices position — user-determined creation order)
  let _sortedHelixIndexMap = new Map()
  let _selected         = new Set()
  let _selectionOrder   = []       // 'row,col' keys in click/lasso order — determines provisional helix numbers
  let _hoverCell        = null
  let _visible          = false
  let _cursorPx         = null     // { x, y } canvas-local pixels for proximity opacity
  let _canvasRect       = null     // cached getBoundingClientRect() — updated once per pointermove
  let _dynBounds        = null     // dynamic grid bounds — grows as cursor nears edges
  let _baseBounds       = null     // stable bounds from _computeGridBounds() (occupied + MARGIN)

  // ── Drag state ─────────────────────────────────────────────────────────────

  let _isDragging       = false    // handle drag
  let _isDragSelecting  = false    // lasso-select drag over cells (activated after >4px movement)
  let _pendingCellClick = false    // pointerdown landed on plane/cell but hasn't moved yet
  let _dragStartOffset  = 0
  let _dragPlane        = new THREE.Plane()
  let _dragStartPoint   = new THREE.Vector3()
  let _pointerDownPos   = null
  let _rightDownPos     = null

  const _raycaster    = new THREE.Raycaster()
  const _ndc          = new THREE.Vector2()
  const _tmp          = new THREE.Vector3()
  const _projVec      = new THREE.Vector3()   // reused for screen-space projection
  const _approxPlane  = new THREE.Plane()     // reused in _cursorGridApprox
  const _approxHitPt  = new THREE.Vector3()   // reused in _cursorGridApprox
  const _approxPlaneP = new THREE.Vector3()   // reused in _cursorGridApprox
  const _latQuat      = new THREE.Quaternion()// current lattice orientation — set by _refreshLatTransform
  const _latNudge     = new THREE.Vector3()   // current label offset     — set by _refreshLatTransform

  function _setNDC(e) {
    _canvasRect = canvas.getBoundingClientRect()
    _ndc.set(
      ((e.clientX - _canvasRect.left) / _canvasRect.width)  *  2 - 1,
      -((e.clientY - _canvasRect.top)  / _canvasRect.height) *  2 + 1,
    )
    _raycaster.setFromCamera(_ndc, _camera)
    _cursorPx = { x: e.clientX - _canvasRect.left, y: e.clientY - _canvasRect.top }
  }

  // ── Snapping ────────────────────────────────────────────────────────────────

  function _snap(val) { return Math.round(val / RISE) * RISE }

  // ── Plane sizing ────────────────────────────────────────────────────────────

  const PLANE_SIZE_MARGIN = 4.5  // nm — padding beyond outermost helix axis

  function _computePlaneDimensions() {
    const helices = getDesign?.()?.helices ?? []
    if (!helices.length) {
      // Default grid: cols 0..DEFAULT_COL_MAX, rows 0..DEFAULT_ROW_MAX (+ MARGIN on each side).
      // Centre of that range: col = DEFAULT_COL_MAX/2 = 5, row = DEFAULT_ROW_MAX/2 = 4.
      // Always HC when no design is loaded (_isSquareLattice returns false with no helices).
      const cx = (DEFAULT_COL_MAX / 2) * HONEYCOMB_COL_PITCH
      const cy = (DEFAULT_ROW_MAX / 2) * HONEYCOMB_ROW_PITCH
      return { width: 20, height: 20, cx, cy }
    }
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
      const _odd = (((row + col) % 2) + 2) % 2
      ly = row * HONEYCOMB_ROW_PITCH + (_odd ? HONEYCOMB_LATTICE_RADIUS : 0)
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
        const pos = cellWorldPos(row, col, _plane, _offset, _latticeOffsetX, _latticeOffsetY)
        fill.position.copy(pos)
        ring.position.copy(pos)
        if (i < _labelEntries.length) _labelEntries[i].spr.position.copy(pos).add(nudge)
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
    const cfg     = PLANE_CFG[_plane]
    const tol     = RISE * 0.05

    for (const h of helices) {
      // Match by grid_pos when available (works for any ID format, including h_sc_*).
      // Fall back to ID parsing for legacy helices without grid_pos.
      let hRow, hCol
      if (h.grid_pos) {
        ;[hRow, hCol] = h.grid_pos
      } else {
        const m = /^h_(?:XY|XZ|YZ)_(-?\d+)_(-?\d+)/.exec(h.id)
        if (!m) continue
        hRow = parseInt(m[1], 10); hCol = parseInt(m[2], 10)
      }
      if (hRow !== row || hCol !== col) continue
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

  // Compute row/col extent of existing helices + margin.
  // Uses grid_pos when available; falls back to ID parsing for legacy helices.
  function _computeGridBounds() {
    const helices = getDesign?.()?.helices ?? []
    let minRow = 0, maxRow = DEFAULT_ROW_MAX
    let minCol = 0, maxCol = DEFAULT_COL_MAX
    let found = false
    for (const h of helices) {
      let row, col
      if (h.grid_pos) {
        ;[row, col] = h.grid_pos
      } else {
        const m = /^h_(?:XY|XZ|YZ)_(-?\d+)_(-?\d+)/.exec(h.id)
        if (!m) continue
        row = parseInt(m[1], 10); col = parseInt(m[2], 10)
      }
      if (!isFinite(row) || !isFinite(col)) continue
      if (!found) {
        minRow = maxRow = row
        minCol = maxCol = col
        found = true
      } else {
        minRow = Math.min(minRow, row); maxRow = Math.max(maxRow, row)
        minCol = Math.min(minCol, col); maxCol = Math.max(maxCol, col)
      }
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
    if (!_cursorPx || !_canvasRect) return 0
    _projVec.copy(worldPos).project(camera)
    const sx   = (_projVec.x *  0.5 + 0.5) * _canvasRect.width
    const sy   = (_projVec.y * -0.5 + 0.5) * _canvasRect.height
    const dist = Math.hypot(sx - _cursorPx.x, sy - _cursorPx.y)
    if (dist <= PROX_FULL_PX) return 1
    if (dist >= PROX_FADE_PX) return 0
    return (PROX_FADE_PX - dist) / (PROX_FADE_PX - PROX_FULL_PX)
  }

  /** Return 0-based helix index for the occupied cell (row, col), or null if not found. */
  function _helixNumberForCell(row, col) {
    const design = getDesign?.()
    if (!design?.helices) return null
    if (_deformedFrame) {
      // Deformed mode: find helix whose deformed endpoint is nearest to this cell position.
      // Use design-order index so deformed labels match cadnano editor + pathview.
      const helixAxes = getHelixAxes?.()
      if (!helixAxes) return null
      const cellPos = _cellWorldPosDeformed(row, col)
      const TOL = 0.6
      for (const h of design.helices) {
        const ax = helixAxes[h.id]
        if (!ax) continue
        if (cellPos.distanceTo(new THREE.Vector3(...ax.end))   < TOL ||
            cellPos.distanceTo(new THREE.Vector3(...ax.start)) < TOL) {
          return _sortedHelixIndexMap.get(h.id) ?? null
        }
      }
      return null
    }
    // Normal mode: find helix at this (row, col) and return its design-order index.
    const isHC = !design.lattice_type || design.lattice_type === 'HONEYCOMB'
    for (const h of design.helices) {
      let hRow, hCol
      if (h.grid_pos) {
        ;[hRow, hCol] = h.grid_pos
      } else {
        const RE = /^h_(?:XY|XZ|YZ)_(-?\d+)_(-?\d+)/
        const m  = RE.exec(h.id)
        if (m) { hRow = parseInt(m[1]); hCol = parseInt(m[2]) }
        else {
          const pitch = isHC ? 2.6 : 2.25
          hRow = Math.round(h.axis_start.y / pitch)
          hCol = Math.round(h.axis_start.x / pitch)
        }
      }
      if (hRow === row && hCol === col) return _sortedHelixIndexMap.get(h.id) ?? null
    }
    return null
  }

  // Small nudge vector to put labels in front of the plane face (avoids z-fighting)
  function _labelNudge() {
    if (_deformedFrame) {
      return new THREE.Vector3(..._deformedFrame.axis_dir).normalize().multiplyScalar(0.05)
    }
    return PLANE_CFG[_plane].normal.clone().multiplyScalar(0.05)
  }

  // Convert current raycaster ray to an approximate grid (row, col) on the slice plane.
  // Returns null in deformed mode or if the ray misses the plane. Zero allocations.
  function _cursorGridApprox() {
    if (_deformedFrame) return null
    const planeNorm = PLANE_CFG[_plane].normal
    _approxPlaneP.copy(planeNorm).multiplyScalar(_offset).add(_lateralCenter)
    _approxPlane.setFromNormalAndCoplanarPoint(planeNorm, _approxPlaneP)
    if (!_raycaster.ray.intersectPlane(_approxPlane, _approxHitPt)) return null
    let lx = _plane === 'YZ' ? _approxHitPt.y : _approxHitPt.x
    let ly = _plane === 'XY' ? _approxHitPt.y : _approxHitPt.z
    lx -= _latticeOffsetX
    ly -= _latticeOffsetY
    if (_isSquareLattice()) {
      return { row: Math.round(ly / SQUARE_HELIX_SPACING), col: Math.round(lx / SQUARE_HELIX_SPACING) }
    } else {
      return { row: Math.round(ly / HONEYCOMB_ROW_PITCH), col: Math.round(lx / HONEYCOMB_COL_PITCH) }
    }
  }

  // Update _latQuat and _latNudge from current plane/deformed state.
  function _refreshLatTransform() {
    if (_deformedFrame) {
      const axisDir = new THREE.Vector3(..._deformedFrame.axis_dir).normalize()
      _latQuat.setFromUnitVectors(new THREE.Vector3(0, 0, 1), axisDir)
      _latNudge.set(..._deformedFrame.axis_dir).normalize().multiplyScalar(0.05)
    } else {
      _latQuat.copy(PLANE_CFG[_plane].latticeQuat)
      _latNudge.copy(PLANE_CFG[_plane].normal).multiplyScalar(0.05)
    }
  }

  // Add a single cell mesh + label to the scene without clearing anything.
  function _addCell(row, col) {
    if (!isValidCell(row, col)) return
    const state = _cellState(row, col)
    const pos   = _deformedFrame
      ? _cellWorldPosDeformed(row, col)
      : cellWorldPos(row, col, _plane, _offset, _latticeOffsetX, _latticeOffsetY)

    const baseColor = state === 'occupied'    ? C_OCCUPIED
                    : state === 'continuable' ? C_CONTINUABLE
                    :                           C_CELL

    const fillMat = new THREE.MeshBasicMaterial({
      color: baseColor.clone(), transparent: true,
      opacity: state === 'occupied' ? FILL_MIN_OCC : FILL_MIN_FREE,
      side: THREE.DoubleSide,
    })
    const fill = new THREE.Mesh(_circleGeo, fillMat)
    fill.position.copy(pos)
    fill.quaternion.copy(_latQuat)
    fill.userData = { row, col, state }

    const ringMat = new THREE.MeshBasicMaterial({
      color: baseColor.clone(), transparent: true,
      opacity: state === 'occupied' ? RING_MIN_OCC : RING_MIN_FREE,
      side: THREE.DoubleSide,
    })
    const ring = new THREE.Mesh(_ringGeo, ringMat)
    ring.position.copy(pos)
    ring.quaternion.copy(_latQuat)
    ring.userData = { row, col, state }

    _latGroup.add(fill)
    _latGroup.add(ring)
    _circleMeshes.push({ fill, ring, row, col, state })

    const entry = _makeLabelEntry(row, col)
    if (state === 'occupied' || state === 'continuable') {
      const num = _helixNumberForCell(row, col)
      if (num !== null) _drawNumberLabel(entry.cv, entry.ctx, entry.tex, num)
    }
    entry.spr.position.copy(pos).add(_latNudge)
    _latGroup.add(entry.spr)
    _labelEntries.push(entry)
  }

  // Add only the cells in newBounds that are not already in prevBounds — no full rebuild.
  function _appendCells(prevBounds, newBounds) {
    _refreshLatTransform()
    const { rowStart, rowEnd, colStart, colEnd } = newBounds
    const { rowStart: pr, rowEnd: pr2, colStart: pc, colEnd: pc2 } = prevBounds
    // New rows above old range (full new width)
    for (let r = rowStart; r < pr; r++)
      for (let c = colStart; c <= colEnd; c++) _addCell(r, c)
    // New rows below old range (full new width)
    for (let r = pr2 + 1; r <= rowEnd; r++)
      for (let c = colStart; c <= colEnd; c++) _addCell(r, c)
    // New cols left, existing rows only
    for (let r = pr; r <= pr2; r++)
      for (let c = colStart; c < pc; c++) _addCell(r, c)
    // New cols right, existing rows only
    for (let r = pr; r <= pr2; r++)
      for (let c = pc2 + 1; c <= colEnd; c++) _addCell(r, c)
  }

  // Expand the visible grid when the cursor approaches a boundary, up to ±HARD_LIMIT.
  function _maybeExpandGrid(cursorCell) {
    if (!cursorCell || !_dynBounds || !_baseBounds) return
    const { row, col } = cursorCell
    let { rowStart, rowEnd, colStart, colEnd } = _dynBounds
    let changed = false
    if (row - rowStart < EDGE_TRIGGER && rowStart > -HARD_LIMIT) {
      rowStart = Math.max(rowStart - EDGE_EXPAND, -HARD_LIMIT); changed = true
    }
    if (rowEnd - row < EDGE_TRIGGER && rowEnd < HARD_LIMIT) {
      rowEnd = Math.min(rowEnd + EDGE_EXPAND, HARD_LIMIT); changed = true
    }
    if (col - colStart < EDGE_TRIGGER && colStart > -HARD_LIMIT) {
      colStart = Math.max(colStart - EDGE_EXPAND, -HARD_LIMIT); changed = true
    }
    if (colEnd - col < EDGE_TRIGGER && colEnd < HARD_LIMIT) {
      colEnd = Math.min(colEnd + EDGE_EXPAND, HARD_LIMIT); changed = true
    }
    if (!changed) return
    const prevBounds = { ..._dynBounds }
    _dynBounds = { rowStart, rowEnd, colStart, colEnd }
    _appendCells(prevBounds, _dynBounds)
    _updateCircleColors()
    _updateLabels()
  }

  function _buildLattice() {
    _clearLattice()

    // Rebuild index map: helix display index = its position in design.helices (user-determined).
    {
      const design = getDesign?.()
      _sortedHelixIndexMap = new Map()
      if (design?.helices) {
        design.helices.forEach((h, i) => _sortedHelixIndexMap.set(h.id, h.label ?? i))
      }
    }

    // Pick cell helpers based on the current design's lattice type.
    const sq = _isSquareLattice()
    isValidCell  = sq ? isValidSquareCell  : isValidHoneycombCell
    cellWorldPos = sq ? squareCellWorldPos : honeycombCellWorldPos

    // Compute lattice origin: the world-space XY position of cell (0,0).
    // Derived from a helix with a known grid_pos by inverting the cell formula.
    // Without this offset the lattice is anchored at (0,0) and won't align with
    // designs that have been translated (e.g. after re-centering on import).
    _latticeOffsetX = 0
    _latticeOffsetY = 0
    const _helices = getDesign?.()?.helices ?? []
    for (const h of _helices) {
      if (!h.grid_pos) continue
      const [r, c] = h.grid_pos
      if (sq) {
        _latticeOffsetX = h.axis_start.x - c * SQUARE_HELIX_SPACING
        _latticeOffsetY = h.axis_start.y - r * SQUARE_HELIX_SPACING
      } else {
        const odd = (((r + c) % 2) + 2) % 2
        _latticeOffsetX = h.axis_start.x - c * HONEYCOMB_COL_PITCH
        _latticeOffsetY = h.axis_start.y - r * HONEYCOMB_ROW_PITCH - (odd ? HONEYCOMB_LATTICE_RADIUS : 0)
      }
      break
    }

    _baseBounds = _computeGridBounds()
    if (!_dynBounds) {
      _dynBounds = { ..._baseBounds }
    } else {
      // Merge: never let _dynBounds shrink below what the design now requires
      _dynBounds = {
        rowStart: Math.min(_dynBounds.rowStart, _baseBounds.rowStart),
        rowEnd:   Math.max(_dynBounds.rowEnd,   _baseBounds.rowEnd),
        colStart: Math.min(_dynBounds.colStart, _baseBounds.colStart),
        colEnd:   Math.max(_dynBounds.colEnd,   _baseBounds.colEnd),
      }
    }
    const { rowStart, rowEnd, colStart, colEnd } = _dynBounds

    _refreshLatTransform()
    for (let row = rowStart; row <= rowEnd; row++)
      for (let col = colStart; col <= colEnd; col++)
        _addCell(row, col)
    // In interactive (non-read-only) mode, center the plane mesh on the design's XY
    // centroid so it visually tracks the design even when helices are not near origin.
    // (Read-only mode does this via _resizePlane; deformed mode uses grid_origin.)
    if (!_readOnly && !_deformedFrame && _helices.length) {
      const xs = _helices.map(h => h.axis_start.x)
      const ys = _helices.map(h => h.axis_start.y)
      const cx = (Math.min(...xs) + Math.max(...xs)) / 2
      const cy = (Math.min(...ys) + Math.max(...ys)) / 2
      if      (_plane === 'XY') _lateralCenter.set(cx, cy, 0)
      else if (_plane === 'XZ') _lateralCenter.set(cx, 0, cy)
      else                      _lateralCenter.set(0, cx, cy)
      _updatePosition()  // reposition plane mesh at design center
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
    for (const { spr } of _labelEntries) {
      spr.material.map?.dispose()
      spr.material.dispose()
      _latGroup.remove(spr)
    }
    _circleMeshes = []
    _labelEntries = []
    _selected.clear()
    _selectionOrder = []
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
    _setNDC(e)  // also updates _canvasRect and _cursorPx

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
        const key = `${_hoverCell.row},${_hoverCell.col}`
        if (!_selected.has(key)) {
          _selectCell(key)
          _updateLabels()
        }
      }

      _updateCircleColors()   // always refresh — cursor moved so proximity changed

      _maybeExpandGrid(_cursorGridApprox())
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
      _updateLabels()
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
        _toggleCell(key)
        _updateCircleColors()
        _updateLabels()
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
      const key = `${cell.row},${cell.col}`
      _selectCell(key)
      _updateCircleColors()
      _updateLabels()
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
  let _sliceDirSign = 1   // default +axis

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

      const cells = _selectionOrder.map(k => k.split(',').map(Number))
      const filterEl = _ctxEl.querySelector('input[name="slice-strand-filter"]:checked')
      const strandFilter = filterEl?.value ?? 'both'
      const ligateAdjacent = _ctxEl.querySelector('#slice-ligate-adjacent')?.checked ?? true
      _hideContextMenu()
      try {
        await onExtrude?.({
          cells, lengthBp, plane: _plane, offsetNm: _offset,
          continuationMode: _continuationMode,
          newBundle: _newBundle,
          latticeType: _latticeType,
          deformedFrame: _deformedFrame,
          refHelixId: _refHelixId,
          strandFilter,
          ligateAdjacent,
        })
      } catch (err) {
        console.error('Slice extrude failed:', err)
      }
      // Rebuild lattice so newly-occupied cells are greyed
      if (_latticeMode) _buildLattice()
      _selected.clear()
      _selectionOrder = []
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
    show(plane, offsetNm, continuation = false, readOnly = false, { latticeType = 'HONEYCOMB', newBundle = false } = {}) {
      _dynBounds        = null
      _baseBounds       = null
      _plane            = plane ?? 'XY'
      _offset           = _snap(offsetNm ?? 0)
      _continuationMode = !!continuation
      _readOnly         = !!readOnly
      _latticeMode      = !readOnly   // no lattice in read-only mode
      _latticeType      = latticeType
      _newBundle        = newBundle && !readOnly
      _visible          = true
      _root.visible     = true
      // Orbit rotation stays enabled in all modes so the user can freely rotate
      // during extrude/lattice operations.
      _handleGroup.visible = !readOnly && !_newBundle
      // Hide the volume slab and border for new-bundle mode (only show lattice)
      _planeMesh.visible  = !_newBundle
      _borderMesh.visible = !_newBundle
      if (readOnly) {
        _resizePlane()
        _clearLattice()             // ensure no stale lattice cells are visible
        _latGroup.visible = false
      }
      _updatePosition()
      if (!readOnly) {
        _buildLattice()
      }
    },

    /**
     * Show the slice plane positioned at a domain-end disk.
     * Derives plane orientation from helixId prefix and offset from axis position at diskBp.
     */
    showAtEnd(helixId, diskBp, continuation = false) {
      const plane = helixId.match(/^h_(XY|XZ|YZ)_/)?.[1] ?? 'XY'
      const h     = getDesign?.()?.helices?.find(x => x.id === helixId)
      const axDef = getHelixAxes?.()?.[helixId]
      let offsetNm = 0
      if (h) {
        const sx = axDef ? axDef.start[0] : h.axis_start.x, sy = axDef ? axDef.start[1] : h.axis_start.y, sz = axDef ? axDef.start[2] : h.axis_start.z
        const ex = axDef ? axDef.end[0]   : h.axis_end.x,   ey = axDef ? axDef.end[1]   : h.axis_end.y,   ez = axDef ? axDef.end[2]   : h.axis_end.z
        const dLen = Math.sqrt((ex-sx)**2 + (ey-sy)**2 + (ez-sz)**2)
        const physLen = Math.max(1, Math.round(dLen / BDNA_RISE_PER_BP) + 1)
        const t  = physLen > 1 ? (diskBp - (h.bp_start ?? 0)) / (physLen - 1) : 0
        const px = sx + (ex - sx) * t, py = sy + (ey - sy) * t, pz = sz + (ez - sz) * t
        if (plane === 'XY') offsetNm = pz
        else if (plane === 'XZ') offsetNm = py
        else offsetNm = px
      }
      this.show(plane, offsetNm, continuation)
    },

    hide() {
      _dynBounds     = null
      _baseBounds    = null
      _visible       = false
      _root.visible  = false
      _latticeMode   = false
      _readOnly      = false
      _newBundle     = false
      _latticeType   = 'HONEYCOMB'
      _handleGroup.visible = true
      _planeMesh.visible   = true
      _borderMesh.visible  = true
      _deformedFrame  = null
      _refHelixId     = null
      _latticeOffsetX = 0
      _latticeOffsetY = 0
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
    isContinuation() { return _visible && _continuationMode },

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
      _dynBounds        = null
      _baseBounds       = null
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
      console.log('_labelEntries:', _labelEntries.length)
      if (_labelEntries.length > 0) {
        const s = _labelEntries[0].spr
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
