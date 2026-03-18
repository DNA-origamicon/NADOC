/**
 * Workspace — blank 3D workspace with plane-picker and honeycomb lattice editor.
 *
 * Blank workspace shows:
 *   - 3 semi-infinite faded grid planes (XY, XZ, YZ) with honeycomb grid spacing
 *     (planes fade out within ~10 nm of origin)
 *
 * On plane hover: brightens
 * On plane click: honeycomb lattice circles appear (camera NOT moved)
 * On cell left-click: toggle selection (gold #fcba03)
 * On right-click (with cells selected): context menu → Extrude
 * On Escape: go back to blank workspace
 *
 * Returns { show, hide, reset, attach }
 */

import * as THREE from 'three'
import {
  HONEYCOMB_LATTICE_RADIUS,
  HONEYCOMB_COL_PITCH,
  HONEYCOMB_ROW_PITCH,
  HELIX_RADIUS,
} from '../constants.js'

const ROWS = 8
const COLS = 12

// ── GLSL shaders for fading grid planes ───────────────────────────────────────

const GRID_VERT = `
  varying vec3 vWorldPos;
  void main() {
    vec4 wp = modelMatrix * vec4(position, 1.0);
    vWorldPos = wp.xyz;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`

const GRID_FRAG = `
  uniform vec3  uColor;
  uniform float uBrightness;
  uniform vec3  uAxisU;
  uniform vec3  uAxisV;
  varying vec3  vWorldPos;

  void main() {
    float u = dot(vWorldPos, uAxisU);
    float v = dot(vWorldPos, uAxisV);

    float d = length(vec2(u, v));
    float fade = 1.0 - smoothstep(4.0, 10.0, d);
    if (fade <= 0.0) discard;

    float sp = 2.25;
    float lineW = 0.07;
    float modU = mod(u + sp * 0.5, sp) - sp * 0.5;
    float modV = mod(v + sp * 0.5, sp) - sp * 0.5;
    float lx = 1.0 - smoothstep(0.0, lineW, abs(modU));
    float ly = 1.0 - smoothstep(0.0, lineW, abs(modV));
    float line = max(lx, ly);

    float alpha = line * fade * uBrightness;
    if (alpha < 0.005) discard;
    gl_FragColor = vec4(uColor, alpha);
  }
`

// ── Plane configs ──────────────────────────────────────────────────────────────

// Each plane: grid rotation, axis vectors for shader, camera position, helix direction
const PLANE_CFG = {
  XY: {
    gridRotation:  [0, 0, 0],
    axisU: new THREE.Vector3(1, 0, 0),
    axisV: new THREE.Vector3(0, 1, 0),
    hitRotation:   [0, 0, 0],
    label: 'XY — helices along Z',
  },
  XZ: {
    gridRotation:  [-Math.PI / 2, 0, 0],
    axisU: new THREE.Vector3(1, 0, 0),
    axisV: new THREE.Vector3(0, 0, 1),
    hitRotation:   [-Math.PI / 2, 0, 0],
    label: 'XZ — helices along Y',
  },
  YZ: {
    gridRotation:  [0, Math.PI / 2, 0],
    axisU: new THREE.Vector3(0, 1, 0),
    axisV: new THREE.Vector3(0, 0, 1),
    hitRotation:   [0, Math.PI / 2, 0],
    label: 'YZ — helices along X',
  },
}

// ── Cell helpers ───────────────────────────────────────────────────────────────

/** Returns 0 (FORWARD), 1 (REVERSE), or 2 (hole — not a valid helix position). */
function honeycombCellValue(row, col) {
  return (row + col % 2) % 3
}

function isValidCell(row, col) {
  return honeycombCellValue(row, col) !== 2
}

function cellWorldPos(row, col, plane) {
  const lx = col * HONEYCOMB_COL_PITCH
  const ly = row * HONEYCOMB_ROW_PITCH + ((col % 2 === 0) ? HONEYCOMB_LATTICE_RADIUS : 0)
  if (plane === 'XY') return new THREE.Vector3(lx, ly, 0)
  if (plane === 'XZ') return new THREE.Vector3(lx, 0, ly)
  if (plane === 'YZ') return new THREE.Vector3(0, lx, ly)
  return new THREE.Vector3(lx, ly, 0)
}

const C_BASE     = new THREE.Color(0xfcba03)
const C_SELECTED = new THREE.Color(0x58a6ff)
const C_HOVER    = new THREE.Color(0xffffff)

// ── Main export ────────────────────────────────────────────────────────────────

export function initWorkspace(scene, camera, controls, { onExtrude } = {}) {
  const _root       = new THREE.Group()
  const _gridGroup  = new THREE.Group()
  const _latGroup   = new THREE.Group()
  _latGroup.frustumCulled = false
  scene.add(_root)
  _root.add(_gridGroup)
  _root.add(_latGroup)

  // State
  let _activePlane = null   // null | 'XY' | 'XZ' | 'YZ'
  let _hoverPlane  = null
  let _hoverCell   = null   // { row, col } | null
  let _selected    = new Set()   // 'row,col' keys (fast lookup)
  let _selectionOrder = []       // 'row,col' keys in click order — determines helix numbers
  let _circleMeshes = []         // { fill, ring, row, col }
  let _visible = false
  let _pointerDownPos   = null   // for drag-vs-click detection
  let _pendingCellClick = false  // pointerdown on cell/plane, not yet dragged
  let _isDragSelecting  = false  // lasso active (>4px movement with _pendingCellClick)

  const _raycaster = new THREE.Raycaster()
  const _ndc       = new THREE.Vector2()

  // ── Build grid planes ──────────────────────────────────────────────────────

  const _gridMaterials = {}
  const _hitPlanes     = {}

  for (const [name, cfg] of Object.entries(PLANE_CFG)) {
    const mat = new THREE.ShaderMaterial({
      vertexShader:   GRID_VERT,
      fragmentShader: GRID_FRAG,
      uniforms: {
        uColor:      { value: new THREE.Color(0x58a6ff) },
        uBrightness: { value: 0.22 },
        uAxisU:      { value: cfg.axisU },
        uAxisV:      { value: cfg.axisV },
      },
      transparent: true,
      depthWrite:  false,
      side: THREE.DoubleSide,
    })
    _gridMaterials[name] = mat

    const gridMesh = new THREE.Mesh(new THREE.PlaneGeometry(44, 44, 1, 1), mat)
    gridMesh.rotation.set(...cfg.gridRotation)
    gridMesh.userData.planeName = name
    _gridGroup.add(gridMesh)

    // Invisible hit plane (larger, always double-sided for raycasting)
    const hitMat  = new THREE.MeshBasicMaterial({ visible: false, side: THREE.DoubleSide })
    const hitMesh = new THREE.Mesh(new THREE.PlaneGeometry(44, 44, 1, 1), hitMat)
    hitMesh.rotation.set(...cfg.hitRotation)
    hitMesh.userData.planeName = name
    _gridGroup.add(hitMesh)
    _hitPlanes[name] = hitMesh
  }

  // ── Build lattice circles ──────────────────────────────────────────────────

  const _circleGeo = new THREE.CircleGeometry(HELIX_RADIUS, 32)
  const _ringGeo   = new THREE.RingGeometry(HELIX_RADIUS * 0.82, HELIX_RADIUS, 32)

  // _labelSprites[i] = { spr, cv, ctx, tex, row, col } — parallel to _circleMeshes
  let _labelSprites = []

  // Normal vectors for each plane — used to nudge labels in front of the grid face
  const _planeNormal = {
    XY: new THREE.Vector3(0, 0, 1),
    XZ: new THREE.Vector3(0, 1, 0),
    YZ: new THREE.Vector3(1, 0, 0),
  }

  const LABEL_SIZE = 128

  /** Draw a coordinate label "(row,col)" onto an existing canvas, trigger texture update. */
  function _drawCoordLabel(cv, ctx, tex, row, col) {
    const r = LABEL_SIZE / 2
    ctx.clearRect(0, 0, LABEL_SIZE, LABEL_SIZE)
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

  /** Draw a helix-number badge (1-based) onto an existing canvas, trigger texture update. */
  function _drawNumberLabel(cv, ctx, tex, num) {
    const r = LABEL_SIZE / 2
    ctx.clearRect(0, 0, LABEL_SIZE, LABEL_SIZE)
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

  /** Create a label sprite with its own canvas/texture (redrawn in-place on selection changes). */
  function _makeLabelEntry(row, col) {
    const cv  = document.createElement('canvas')
    cv.width  = LABEL_SIZE; cv.height = LABEL_SIZE
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
   * Selected cells show their 1-based helix number (in selection order).
   * Unselected cells show their (row,col) coordinate.
   */
  function _updateLabels() {
    // Build a lookup: key → 1-based position in _selectionOrder
    const orderMap = new Map()
    for (let i = 0; i < _selectionOrder.length; i++) {
      orderMap.set(_selectionOrder[i], i + 1)
    }
    for (const entry of _labelSprites) {
      const key = `${entry.row},${entry.col}`
      const num = orderMap.get(key)
      if (num !== undefined) {
        _drawNumberLabel(entry.cv, entry.ctx, entry.tex, num)
        entry.spr.scale.set(0.80, 0.80, 1)  // slightly larger for number badge
      } else {
        _drawCoordLabel(entry.cv, entry.ctx, entry.tex, entry.row, entry.col)
        entry.spr.scale.set(0.80, 0.80, 1)
      }
    }
  }

  /** Add a cell to the ordered selection. No-op if already selected. */
  function _selectCell(key) {
    if (_selected.has(key)) return
    _selected.add(key)
    _selectionOrder.push(key)
  }

  /** Remove a cell from the ordered selection. Renumbers remaining cells. */
  function _deselectCell(key) {
    if (!_selected.has(key)) return
    _selected.delete(key)
    const idx = _selectionOrder.indexOf(key)
    if (idx >= 0) _selectionOrder.splice(idx, 1)
  }

  /** Toggle selection for a cell key, returns new selected state. */
  function _toggleCell(key) {
    if (_selected.has(key)) { _deselectCell(key); return false }
    else { _selectCell(key); return true }
  }

  function _buildLattice(plane) {
    _clearLattice()
    const cfg   = PLANE_CFG[plane]
    const nudge = _planeNormal[plane].clone().multiplyScalar(0.05)

    // Orientation quaternion so circles face the plane normal
    const quat = new THREE.Quaternion()
    const euler = new THREE.Euler(...cfg.gridRotation)
    quat.setFromEuler(euler)

    for (let row = 0; row < ROWS; row++) {
      for (let col = 0; col < COLS; col++) {
        if (!isValidCell(row, col)) continue
        const pos   = cellWorldPos(row, col, plane)
        const fillMat = new THREE.MeshBasicMaterial({
          color: C_BASE.clone(), transparent: true, opacity: 0.55, side: THREE.DoubleSide,
        })
        const fillMesh = new THREE.Mesh(_circleGeo, fillMat)
        fillMesh.position.copy(pos)
        fillMesh.applyQuaternion(quat)
        fillMesh.userData = { row, col, type: 'cell' }

        const ringMat = new THREE.MeshBasicMaterial({
          color: C_BASE.clone(), transparent: true, opacity: 0.85, side: THREE.DoubleSide,
        })
        const ringMesh = new THREE.Mesh(_ringGeo, ringMat)
        ringMesh.position.copy(pos)
        ringMesh.applyQuaternion(quat)
        ringMesh.userData = { row, col, type: 'ring' }

        _latGroup.add(fillMesh)
        _latGroup.add(ringMesh)
        _circleMeshes.push({ fill: fillMesh, ring: ringMesh, row, col })

        // Label sprite nudged slightly in front of the plane
        const entry = _makeLabelEntry(row, col)
        entry.spr.position.copy(pos).add(nudge)
        _latGroup.add(entry.spr)
        _labelSprites.push(entry)
      }
    }
  }

  function _clearLattice() {
    for (const { fill, ring } of _circleMeshes) {
      fill.material.dispose()
      ring.material.dispose()
      _latGroup.remove(fill)
      _latGroup.remove(ring)
    }
    for (const { spr, tex } of _labelSprites) {
      tex.dispose()
      spr.material.dispose()
      _latGroup.remove(spr)
    }
    _circleMeshes    = []
    _labelSprites    = []
    _selected.clear()
    _selectionOrder  = []
    _hoverCell        = null
    _pendingCellClick = false
    _isDragSelecting  = false
    controls.enableRotate = true
  }

  function _updateCircleColors() {
    for (const { fill, ring, row, col } of _circleMeshes) {
      const key = `${row},${col}`
      const isSelected = _selected.has(key)
      const isHover = _hoverCell?.row === row && _hoverCell?.col === col
      const color = isSelected ? C_SELECTED : (isHover ? C_HOVER : C_BASE)
      const opacity = isSelected ? 0.9 : (isHover ? 0.75 : 0.55)
      fill.material.color.copy(color)
      fill.material.opacity = opacity
      ring.material.color.copy(isSelected ? C_SELECTED : C_BASE)
      ring.material.opacity = isSelected ? 1.0 : 0.85
    }
  }

  // ── Camera snap ────────────────────────────────────────────────────────────

  function _snapCamera(plane) {
    // Center of visible lattice (ROWS×COLS grid)
    const cx = ((COLS - 1) / 2) * HONEYCOMB_COL_PITCH
    const cy = ((ROWS - 1) / 2) * HONEYCOMB_ROW_PITCH + HONEYCOMB_LATTICE_RADIUS / 2
    const dist = 28

    if (plane === 'XY') {
      camera.position.set(cx, cy, dist)
      controls.target.set(cx, cy, 0)
    } else if (plane === 'XZ') {
      camera.position.set(cx, dist, cy)
      controls.target.set(cx, 0, cy)
    } else {
      camera.position.set(dist, cx, cy)
      controls.target.set(0, cx, cy)
    }
    controls.update()
  }

  // ── Raycasting helpers ─────────────────────────────────────────────────────

  function _setNDC(e) {
    const rect = e.target.getBoundingClientRect()
    _ndc.set(
      ((e.clientX - rect.left) / rect.width)  * 2 - 1,
      -((e.clientY - rect.top)  / rect.height) * 2 + 1,
    )
    _raycaster.setFromCamera(_ndc, camera)
  }

  function _rayCells() {
    const meshes = _circleMeshes.map(c => c.fill)
    const hits   = _raycaster.intersectObjects(meshes)
    if (!hits.length) return null
    const { row, col } = hits[0].object.userData
    return { row, col }
  }

  function _rayPlanes() {
    const meshes = Object.values(_hitPlanes)
    const hits   = _raycaster.intersectObjects(meshes)
    if (!hits.length) return null
    return hits[0].object.userData.planeName
  }

  // ── Event handlers ────────────────────────────────────────────────────────

  function _onMouseMove(e) {
    if (!_visible) return
    _setNDC(e)

    if (_activePlane) {
      const cell = _rayCells()

      // Upgrade pending click → lasso once movement exceeds 4px
      if (_pendingCellClick && _pointerDownPos &&
          Math.hypot(e.clientX - _pointerDownPos.x, e.clientY - _pointerDownPos.y) > 4) {
        _pendingCellClick = false
        _isDragSelecting  = true
      }

      // Lasso: add any hovered selectable cell to selection
      if (_isDragSelecting && cell) {
        const added = !_selected.has(`${cell.row},${cell.col}`)
        _selectCell(`${cell.row},${cell.col}`)
        if (added) _updateLabels()
      }

      if (cell?.row !== _hoverCell?.row || cell?.col !== _hoverCell?.col) {
        _hoverCell = cell
        _updateCircleColors()
      } else if (_isDragSelecting) {
        _updateCircleColors()
      }
    } else {
      const pname = _rayPlanes()
      if (pname !== _hoverPlane) {
        if (_hoverPlane) _gridMaterials[_hoverPlane].uniforms.uBrightness.value = 0.22
        _hoverPlane = pname
        if (_hoverPlane) _gridMaterials[_hoverPlane].uniforms.uBrightness.value = 0.55
      }
    }
  }

  function _onPointerDown(e) {
    if (!_visible || e.button !== 0) return
    _pointerDownPos = { x: e.clientX, y: e.clientY }

    if (_activePlane) {
      _setNDC(e)
      if (_rayCells()) {
        // Cell hit: block OrbitControls so drag becomes lasso, not orbit.
        _pendingCellClick = true
        e.stopImmediatePropagation()
      }
      // Plane hit with no cell: let OrbitControls orbit normally.
    } else {
      // Still record position so click detection works when activating a plane
      _setNDC(e)
      if (_rayPlanes()) {
        _pendingCellClick = true
        e.stopImmediatePropagation()
      }
    }
  }

  function _onPointerUp(e) {
    if (!_visible || e.button !== 0) return

    if (_isDragSelecting) {
      _isDragSelecting  = false
      _pendingCellClick = false
      _updateCircleColors()
      _updateLabels()
      return
    }

    _pendingCellClick = false

    // Ignore orbits — only treat as click if pointer barely moved
    if (_pointerDownPos && Math.hypot(e.clientX - _pointerDownPos.x, e.clientY - _pointerDownPos.y) > 4) return

    _setNDC(e)
    _hideContextMenu()

    if (_activePlane) {
      const cell = _rayCells()
      if (cell) {
        _toggleCell(`${cell.row},${cell.col}`)
        _updateCircleColors()
        _updateLabels()
      }
    } else {
      const pname = _rayPlanes()
      if (pname) {
        _activePlane = pname
        _gridMaterials[pname].uniforms.uBrightness.value = 0.35
        _buildLattice(pname)
      }
    }
  }

  // Context menu element (created once in DOM)
  const _ctxEl = document.getElementById('workspace-ctx-menu')

  function _showContextMenu(e) {
    if (!_ctxEl) return
    const count = _selected.size
    if (count === 0) return
    _ctxEl.querySelector('.ctx-count').textContent = `${count} helix${count > 1 ? 'es' : ''}`
    _ctxEl.style.left = `${e.clientX}px`
    _ctxEl.style.top  = `${e.clientY}px`
    _ctxEl.style.display = 'block'
  }

  function _hideContextMenu() {
    if (_ctxEl) _ctxEl.style.display = 'none'
  }

  function _onContextMenu(e) {
    if (!_visible || !_activePlane) return
    e.preventDefault()
    _setNDC(e)
    const cell = _rayCells()
    if (cell) {
      const added = !_selected.has(`${cell.row},${cell.col}`)
      _selectCell(`${cell.row},${cell.col}`)
      if (added) { _updateCircleColors(); _updateLabels() }
    }
    _showContextMenu(e)
  }

  function _onKeyDown(e) {
    if (!_visible) return
    if (e.key === 'Escape') {
      _hideContextMenu()
      if (_activePlane) {
        _gridMaterials[_activePlane].uniforms.uBrightness.value = 0.22
        _activePlane = null
        _clearLattice()   // also restores controls.enableRotate
      }
    }
  }

  function _onDocClick(e) {
    if (_ctxEl && !_ctxEl.contains(e.target)) _hideContextMenu()
  }

  // Wire ctx menu Extrude button
  if (_ctxEl) {
    _ctxEl.querySelector('#ctx-extrude-btn').addEventListener('click', async () => {
      const lengthInput  = _ctxEl.querySelector('#ctx-length')
      const unitSelect   = _ctxEl.querySelector('#ctx-unit')
      const filterRadio  = _ctxEl.querySelector('input[name="ctx-filter"]:checked')
      const rawVal = parseFloat(lengthInput.value)
      const unit   = unitSelect.value
      const RISE   = 0.334
      const lengthBp    = unit === 'bp' ? Math.round(rawVal) : Math.max(1, Math.round(rawVal / RISE))
      const strandFilter = filterRadio?.value ?? 'both'
      // Use _selectionOrder so helix numbering matches what was shown as labels
      const cells = _selectionOrder.map(k => k.split(',').map(Number))
      _hideContextMenu()
      const plane = _activePlane
      try {
        await onExtrude?.({ cells, lengthBp, plane, strandFilter })
      } catch (err) {
        console.error('Extrude failed:', err)
      }
      // After extrude: reset to blank
      _gridMaterials[plane].uniforms.uBrightness.value = 0.22
      _activePlane = null
      _clearLattice()   // also restores controls.enableRotate
    })
    _ctxEl.querySelector('#ctx-cancel-btn').addEventListener('click', _hideContextMenu)
  }

  // ── Attach events ──────────────────────────────────────────────────────────

  function attach(canvas) {
    canvas.addEventListener('mousemove',    _onMouseMove)
    canvas.addEventListener('pointerdown',  _onPointerDown, { capture: true })
    canvas.addEventListener('pointerup',    _onPointerUp)
    canvas.addEventListener('contextmenu',  _onContextMenu)
    document.addEventListener('keydown',    _onKeyDown)
    document.addEventListener('click',      _onDocClick)
  }

  function show() {
    _visible = true
    _root.visible = true
    // Reset to blank state
    if (_activePlane) {
      _gridMaterials[_activePlane].uniforms.uBrightness.value = 0.22
      _activePlane = null
    }
    _clearLattice()
    for (const mat of Object.values(_gridMaterials)) {
      mat.uniforms.uBrightness.value = 0.22
    }
    _hoverPlane = null
  }

  function hide() {
    _visible = false
    _root.visible = false
    _hideContextMenu()
  }

  function reset() {
    show()
    camera.position.set(6, 3, 18)
    controls.target.set(6, 3, 0)
    controls.update()
  }

  return { show, hide, reset, attach }
}
