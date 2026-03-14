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
} from '../constants.js'

// Default grid size when no design is loaded (matches workspace)
const DEFAULT_ROWS = 8
const DEFAULT_COLS = 12
const MARGIN       = 5    // extra cells around the design extent in each direction
const RISE         = BDNA_RISE_PER_BP

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

// Approximate centre of the default honeycomb lattice (used to place the handle)
const LATTICE_CX = ((DEFAULT_COLS - 1) / 2) * HONEYCOMB_COL_PITCH
const LATTICE_CY = ((DEFAULT_ROWS - 1) / 2) * HONEYCOMB_ROW_PITCH + HONEYCOMB_LATTICE_RADIUS / 2

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

function honeycombCellValue(row, col) { return _mod(row + _mod(col, 2), 3) }
function isValidCell(row, col)        { return honeycombCellValue(row, col) !== 2 }

function cellWorldPos(row, col, plane, offset) {
  const lx = col * HONEYCOMB_COL_PITCH
  const ly = row * HONEYCOMB_ROW_PITCH + ((col % 2 === 0) ? HONEYCOMB_LATTICE_RADIUS : 0)
  if (plane === 'XY') return new THREE.Vector3(lx, ly, offset)
  if (plane === 'XZ') return new THREE.Vector3(lx, offset, ly)
  /* YZ */            return new THREE.Vector3(offset, lx, ly)
}

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
export function initSlicePlane(scene, camera, canvas, controls, { onExtrude, getDesign, getHelixAxes } = {}) {

  // ── Scene graph ─────────────────────────────────────────────────────────────

  const _root = new THREE.Group()
  scene.add(_root)
  _root.visible = false

  // Semi-transparent plane face
  const _planeMat = new THREE.MeshBasicMaterial({
    color: 0x58a6ff, transparent: true, opacity: 0.07,
    side: THREE.DoubleSide, depthWrite: false,
  })
  const _planeMesh = new THREE.Mesh(new THREE.PlaneGeometry(40, 40), _planeMat)
  _planeMesh.userData.isSlicePlane = true
  _root.add(_planeMesh)

  // Border outline
  const _borderMat = new THREE.LineBasicMaterial({ color: 0x58a6ff, transparent: true, opacity: 0.35 })
  const _borderMesh = new THREE.LineSegments(
    new THREE.EdgesGeometry(new THREE.PlaneGeometry(40, 40)),
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

  // ── State ───────────────────────────────────────────────────────────────────

  let _plane            = 'XY'
  let _offset           = 0.0
  let _latticeMode      = false
  let _continuationMode = false
  let _deformedFrame    = null   // { grid_origin, axis_dir, frame_right, frame_up } when in deformed mode
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
    _raycaster.setFromCamera(_ndc, camera)
  }

  // ── Snapping ────────────────────────────────────────────────────────────────

  function _snap(val) { return Math.round(val / RISE) * RISE }

  // ── Deformed mode helpers ───────────────────────────────────────────────────

  /** Cell world position using the deformed cross-section frame. */
  function _cellWorldPosDeformed(row, col) {
    const lx = col * HONEYCOMB_COL_PITCH
    const ly = row * HONEYCOMB_ROW_PITCH + ((col % 2 === 0) ? HONEYCOMB_LATTICE_RADIUS : 0)
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

    // Plane mesh at offset along normal
    _planeMesh.position.copy(cfg.normal).multiplyScalar(_offset)
    _planeMesh.setRotationFromEuler(cfg.rotation)
    _borderMesh.position.copy(_planeMesh.position)
    _borderMesh.setRotationFromEuler(cfg.rotation)

    // Handle at lattice centre + offset along normal
    _handleGroup.position.copy(cfg.handleCenter(_offset))

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
  // falling back to the default 8×12 grid if the design is empty.
  function _computeGridBounds() {
    const helices = getDesign?.()?.helices ?? []
    let minRow = 0, maxRow = DEFAULT_ROWS - 1
    let minCol = 0, maxCol = DEFAULT_COLS - 1
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
        camera.getWorldDirection(_tmp)
        _dragPlane.setFromNormalAndCoplanarPoint(_tmp, _handleGroup.position)
        _raycaster.ray.intersectPlane(_dragPlane, _dragStartPoint)
        controls.enabled = false
        e.stopImmediatePropagation()
      } else if (_rayPlane() || (_latticeMode && _rayAnyCells())) {
        // Intercept ALL plane/cell clicks — prevent OrbitControls from starting rotation
        _pendingCellClick = true
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
        return
      }
    }

    // Click on plane face → toggle lattice
    if (_rayPlane()) {
      _latticeMode = !_latticeMode
      if (_latticeMode) _buildLattice()
      else              _clearLattice()
    }
  }

  function _onContextMenu(e) {
    if (!_visible || !_latticeMode) return
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

  function _showContextMenu(x, y) {
    if (!_ctxEl) return
    _ctxEl.querySelector('.ctx-count').textContent =
      `${_selected.size} helix${_selected.size > 1 ? 'es' : ''}`
    _ctxEl.style.left    = `${x}px`
    _ctxEl.style.top     = `${y}px`
    _ctxEl.style.display = 'block'
  }

  function _hideContextMenu() {
    if (_ctxEl) _ctxEl.style.display = 'none'
  }

  if (_ctxEl) {
    _ctxEl.querySelector('#slice-extrude-btn').addEventListener('click', async () => {
      const rawVal  = parseFloat(_ctxEl.querySelector('#slice-length').value)
      const unit    = _ctxEl.querySelector('#slice-unit').value
      const sign    = rawVal < 0 ? -1 : 1
      const absVal  = Math.abs(rawVal)
      const lengthBp = unit === 'bp'
        ? Math.trunc(rawVal) || 1
        : sign * Math.max(1, Math.round(absVal / RISE))

      const cells = [..._selected].map(k => k.split(',').map(Number))
      _hideContextMenu()
      try {
        await onExtrude?.({
          cells, lengthBp, plane: _plane, offsetNm: _offset,
          continuationMode: _continuationMode,
          deformedFrame: _deformedFrame,
        })
      } catch (err) {
        console.error('Slice extrude failed:', err)
      }
      // Rebuild lattice so newly-occupied cells are greyed
      if (_latticeMode) _buildLattice()
      _selected.clear()
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
    show(plane, offsetNm, continuation = false) {
      _plane            = plane ?? 'XY'
      _offset           = _snap(offsetNm ?? 0)
      _continuationMode = !!continuation
      _latticeMode      = true    // lattice always pre-opened
      _visible          = true
      _root.visible     = true
      controls.enableRotate = false   // disable orbit rotation while slice plane is active
      _updatePosition()
      _buildLattice()             // build immediately so cells are ready
    },

    hide() {
      _visible       = false
      _root.visible  = false
      _latticeMode   = false
      _deformedFrame = null
      _clearLattice()
      _hideContextMenu()
      _isDragging       = false
      _isDragSelecting  = false
      _pendingCellClick = false
      controls.enabled      = true
      controls.enableRotate = true    // restore orbit rotation
    },

    isVisible() { return _visible },

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
    showDeformed(frame, { plane = 'XY', continuation = false } = {}) {
      _deformedFrame    = frame
      _plane            = plane
      _continuationMode = !!continuation
      _latticeMode      = true
      _visible          = true
      _root.visible     = true
      controls.enableRotate = false
      _updatePosition()
      _buildLattice()
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
