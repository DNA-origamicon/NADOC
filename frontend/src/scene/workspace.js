/**
 * Workspace — blank 3D workspace with plane-picker.
 *
 * Shows three semi-infinite faded GLSL grid planes (XY, XZ, YZ).
 * Hovering a plane brightens it; clicking activates it and fires onPlanePicked(plane, latticeType).
 * The actual lattice + cell selection + extrude dialog are all handled by slice_plane.js.
 *
 * Public API:  show(latticeType), hide(), reset(), attach(canvas), deactivate()
 */

import * as THREE from 'three'
import {
  HONEYCOMB_ROW_PITCH,
  SQUARE_HELIX_SPACING,
} from '../constants.js'

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
  uniform float uSpacing;
  varying vec3  vWorldPos;

  void main() {
    float u = dot(vWorldPos, uAxisU);
    float v = dot(vWorldPos, uAxisV);

    float d = length(vec2(u, v));
    float fade = 1.0 - smoothstep(4.0, 10.0, d);
    if (fade <= 0.0) discard;

    float sp = uSpacing;
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

const PLANE_CFG = {
  XY: {
    gridRotation: [0, 0, 0],
    axisU: new THREE.Vector3(1, 0, 0),
    axisV: new THREE.Vector3(0, 1, 0),
    hitRotation: [0, 0, 0],
    label: 'XY — helices along Z',
  },
  XZ: {
    gridRotation: [-Math.PI / 2, 0, 0],
    axisU: new THREE.Vector3(1, 0, 0),
    axisV: new THREE.Vector3(0, 0, 1),
    hitRotation: [-Math.PI / 2, 0, 0],
    label: 'XZ — helices along Y',
  },
  YZ: {
    gridRotation: [0, Math.PI / 2, 0],
    axisU: new THREE.Vector3(0, 1, 0),
    axisV: new THREE.Vector3(0, 0, 1),
    hitRotation: [0, Math.PI / 2, 0],
    label: 'YZ — helices along X',
  },
}

// ── Main export ────────────────────────────────────────────────────────────────

export function initWorkspace(scene, camera, controls, { onPlanePicked } = {}) {
  const _root      = new THREE.Group()
  const _gridGroup = new THREE.Group()
  scene.add(_root)
  _root.add(_gridGroup)

  // State
  let _latticeType  = 'HONEYCOMB'
  let _activePlane  = null   // plane currently selected (awaiting slice_plane activation)
  let _hoverPlane   = null
  let _visible      = false
  let _pointerDownPos = null

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
        uSpacing:    { value: HONEYCOMB_ROW_PITCH },
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

    const hitMat  = new THREE.MeshBasicMaterial({ visible: false, side: THREE.DoubleSide })
    const hitMesh = new THREE.Mesh(new THREE.PlaneGeometry(44, 44, 1, 1), hitMat)
    hitMesh.rotation.set(...cfg.hitRotation)
    hitMesh.userData.planeName = name
    _gridGroup.add(hitMesh)
    _hitPlanes[name] = hitMesh
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

  function _rayPlanes() {
    const meshes = Object.values(_hitPlanes)
    const hits   = _raycaster.intersectObjects(meshes)
    if (!hits.length) return null
    return hits[0].object.userData.planeName
  }

  // ── Event handlers ─────────────────────────────────────────────────────────

  function _onMouseMove(e) {
    if (!_visible || _activePlane) return
    _setNDC(e)
    const pname = _rayPlanes()
    if (pname !== _hoverPlane) {
      if (_hoverPlane) _gridMaterials[_hoverPlane].uniforms.uBrightness.value = 0.22
      _hoverPlane = pname
      if (_hoverPlane) _gridMaterials[_hoverPlane].uniforms.uBrightness.value = 0.55
    }
  }

  function _onPointerDown(e) {
    if (!_visible || e.button !== 0) return
    _pointerDownPos = { x: e.clientX, y: e.clientY }
    _setNDC(e)
    if (!_activePlane && _rayPlanes()) e.stopImmediatePropagation()
  }

  function _onPointerUp(e) {
    if (!_visible || e.button !== 0) return
    if (_pointerDownPos && Math.hypot(e.clientX - _pointerDownPos.x, e.clientY - _pointerDownPos.y) > 4) return
    if (_activePlane) return   // slice_plane owns interaction while a plane is active

    _setNDC(e)
    const pname = _rayPlanes()
    if (pname) {
      _activePlane = pname
      _gridMaterials[pname].uniforms.uBrightness.value = 0.35
      onPlanePicked?.(pname, _latticeType)
    }
  }

  function _onKeyDown(e) {
    if (!_visible || !_activePlane) return
    if (e.key === 'Escape') {
      // slice_plane handles its own Escape; we just reset the grid highlight here.
      _gridMaterials[_activePlane].uniforms.uBrightness.value = 0.22
      _activePlane = null
      if (_hoverPlane) { _gridMaterials[_hoverPlane].uniforms.uBrightness.value = 0.22; _hoverPlane = null }
    }
  }

  // ── Public API ─────────────────────────────────────────────────────────────

  function attach(canvas) {
    canvas.addEventListener('mousemove',   _onMouseMove)
    canvas.addEventListener('pointerdown', _onPointerDown, { capture: true })
    canvas.addEventListener('pointerup',   _onPointerUp)
    document.addEventListener('keydown',   _onKeyDown)
  }

  function show(latticeType = 'HONEYCOMB') {
    _latticeType = latticeType
    _visible = true
    _root.visible = true
    if (_activePlane) {
      _gridMaterials[_activePlane].uniforms.uBrightness.value = 0.22
      _activePlane = null
    }
    const spacing = latticeType === 'SQUARE' ? SQUARE_HELIX_SPACING : HONEYCOMB_ROW_PITCH
    for (const mat of Object.values(_gridMaterials)) {
      mat.uniforms.uBrightness.value = 0.22
      mat.uniforms.uSpacing.value    = spacing
    }
    _hoverPlane = null
    // Default to XY plane (helices along +Z) — activate immediately without requiring a click.
    _activePlane = 'XY'
    _gridMaterials['XY'].uniforms.uBrightness.value = 0.35
    onPlanePicked?.('XY', _latticeType)
  }

  function hide() {
    _visible = false
    _root.visible = false
  }

  function reset() { show() }

  /**
   * Reset active-plane highlight from outside (called by main.js after a new-bundle
   * extrude completes or is cancelled via slice_plane's Escape handler).
   */
  function deactivate() {
    if (_activePlane) {
      _gridMaterials[_activePlane].uniforms.uBrightness.value = 0.22
      _activePlane = null
    }
  }

  return { show, hide, reset, attach, deactivate }
}
