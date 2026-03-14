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
  scene.add(_root)
  _root.add(_gridGroup)
  _root.add(_latGroup)

  // State
  let _activePlane = null   // null | 'XY' | 'XZ' | 'YZ'
  let _hoverPlane  = null
  let _hoverCell   = null   // { row, col } | null
  let _selected    = new Set()   // 'row,col' keys
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

  function _buildLattice(plane) {
    _clearLattice()
    const cfg = PLANE_CFG[plane]

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
    _circleMeshes = []
    _selected.clear()
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
        _selected.add(`${cell.row},${cell.col}`)
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
      const cellHit  = _rayCells()
      const planeHit = _rayPlanes()
      if (cellHit || planeHit) {
        _pendingCellClick = true
        e.stopImmediatePropagation()
      }
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
        const key = `${cell.row},${cell.col}`
        if (_selected.has(key)) _selected.delete(key)
        else _selected.add(key)
        _updateCircleColors()
      }
    } else {
      const pname = _rayPlanes()
      if (pname) {
        _activePlane = pname
        _gridMaterials[pname].uniforms.uBrightness.value = 0.35
        _buildLattice(pname)
        controls.enableRotate = false
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
    if (cell && !_selected.has(`${cell.row},${cell.col}`)) {
      _selected.add(`${cell.row},${cell.col}`)
      _updateCircleColors()
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
      const lengthInput = _ctxEl.querySelector('#ctx-length')
      const unitSelect  = _ctxEl.querySelector('#ctx-unit')
      const rawVal = parseFloat(lengthInput.value)
      const unit   = unitSelect.value
      const RISE   = 0.334
      const lengthBp = unit === 'bp' ? Math.round(rawVal) : Math.max(1, Math.round(rawVal / RISE))
      const cells = [..._selected].map(k => k.split(',').map(Number))
      _hideContextMenu()
      const plane = _activePlane
      try {
        await onExtrude?.({ cells, lengthBp, plane })
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
