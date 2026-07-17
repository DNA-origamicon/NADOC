/**
 * Electric-field direction/magnitude gizmo.
 *
 * Three fixed-radius great-circle controls surround a field arrow. Dragging any
 * ring rotates direction in that axis plane without changing field magnitude.
 * The separate arrow still points down-field and its length encodes magnitude.
 * OrbitControls are disabled mid-drag
 * (mirrors overhang_gizmo.js).  Direction + magnitude are also fully settable
 * programmatically (setVector / getVector) so automated tests drive it without a
 * mouse — that is the "make testing automatable" requirement.
 *
 * Display-layer only: the gizmo never touches topology or the design; it just
 * reports its world vector via the onChange callback.  The owning panel
 * (ui/forces_card.js) maps that vector to force-per-nucleotide (pN) + direction.
 *
 * Factory:
 *   const gizmo = initEfieldGizmo(scene, camera, canvas, controls)
 *   gizmo.attach([x,y,z])      // show at origin, start listening for drags
 *   gizmo.setVector([0,1,0])   // direction*length in world units
 *   gizmo.setOnChange(v => …)  // fired during a drag with the new world vector
 *   gizmo.detach()             // hide + stop listening
 */

import * as THREE from 'three'
import { TransformControls } from 'three/addons/controls/TransformControls.js'

const _ARROW_COLOR  = 0x4a9eff

// Thick-arrow geometry (nm).  A solid cylinder shaft + cone head reads as a real
// 3D arrow, unlike THREE.ArrowHelper's 1-px line shaft.
const _SHAFT_R = 0.45
const _HEAD_R  = 1.15
const _MAX_ARROW_LENGTH_NM = 25
const _CONTROL_SIZE = 0.7
const _MAX_CONTROL_DIAMETER_NM = 25
const _UP      = new THREE.Vector3(0, 1, 0)

export function initEfieldGizmo(scene, camera, canvas, controls, name = 'efield-gizmo') {
  let _group   = null               // named THREE.Group (test locator: `name`, default 'efield-gizmo')
  let _arrow   = null               // THREE.Group: thick shaft cylinder + cone head
  let _shaft   = null
  let _head    = null
  let _arrowMat = null
  let _dummy   = null               // TransformControls orientation target
  let _tc      = null
  let _helper  = null
  let _onChange = null
  let _dragging = false
  let _controlsVisible = true
  const _origin = new THREE.Vector3(0, 0, 0)
  const _vec    = new THREE.Vector3(0, 1, 0)   // world field vector (dir * length)
  let _arrowLength = 1

  function _build() {
    _group = new THREE.Group()
    _group.name = name
    // Emissive so the arrow reads as a bold solid even under flat lighting.
    _arrowMat = new THREE.MeshStandardMaterial({
      color: _ARROW_COLOR, emissive: _ARROW_COLOR, emissiveIntensity: 0.4,
      roughness: 0.45, metalness: 0.0,
    })
    // Both primitives are unit-height along +Y, centred at their own origin; _sync
    // scales/positions them so the shaft ends where the head begins.
    _shaft = new THREE.Mesh(new THREE.CylinderGeometry(_SHAFT_R, _SHAFT_R, 1, 16), _arrowMat)
    _shaft.name = 'efield-gizmo-arrow-shaft'
    _head  = new THREE.Mesh(new THREE.ConeGeometry(_HEAD_R, 1, 20), _arrowMat)
    _arrow = new THREE.Group()
    _arrow.name = 'efield-gizmo-arrow'
    _arrow.add(_shaft, _head)
    _group.add(_arrow)
    scene.add(_group)

    // Match the cluster rotation tool exactly: Three.js TransformControls in
    // rotate-only, world-space mode, attached to a dummy at the field origin.
    _dummy = new THREE.Object3D()
    _dummy.name = 'efield-gizmo-rotation-target'
    scene.add(_dummy)
    _tc = new TransformControls(camera, canvas)
    _tc.attach(_dummy)
    _tc.setMode('rotate')
    _tc.setSpace('world')
    _tc.setSize(_CONTROL_SIZE)
    _helper = _tc.getHelper()
    _helper.name = 'efield-gizmo-rotation-controls'
    // TransformControls normally keeps its rings a constant screen size.  At a
    // large camera distance that makes them enormous in world units, so reduce
    // its screen-size setting only once a ring would exceed 25 nm in diameter.
    // The gizmo geometry has unit radius and TransformControls scales it by
    // `factor * size / 4`, hence diameter = `factor * size / 2`.
    const updateHelperMatrixWorld = _helper.updateMatrixWorld.bind(_helper)
    _helper.updateMatrixWorld = force => {
      let factor
      if (camera.isOrthographicCamera) {
        factor = (camera.top - camera.bottom) / camera.zoom
      } else {
        factor = camera.position.distanceTo(_dummy.position)
          * Math.min(1.9 * Math.tan(Math.PI * camera.fov / 360) / camera.zoom, 7)
      }
      const cappedSize = factor > 0
        ? Math.min(_CONTROL_SIZE, 2 * _MAX_CONTROL_DIAMETER_NM / factor)
        : _CONTROL_SIZE
      _tc.setSize(cappedSize)
      updateHelperMatrixWorld(force)
    }
    scene.add(_helper)
    _tc.addEventListener('dragging-changed', e => {
      _dragging = !!e.value
      if (controls) controls.enabled = !e.value
    })
    _tc.addEventListener('objectChange', () => {
      _vec.copy(_UP).applyQuaternion(_dummy.quaternion).normalize()
      _syncArrow()
      _onChange?.(getVector())
    })
  }

  /** Re-position the field arrow from the current origin/direction/magnitude. */
  function _syncArrow() {
    if (!_group) return
    const len = Math.min(Math.max(_arrowLength, 1e-3), _MAX_ARROW_LENGTH_NM)
    const dir = _vec.clone().normalize()
    const headLen  = Math.min(Math.max(len * 0.28, 1.2), 4.0)
    const shaftLen = Math.max(len - headLen, 0.01)
    // Orient the whole arrow (+Y → field direction) and anchor it at the origin.
    _arrow.position.copy(_origin)
    _arrow.quaternion.setFromUnitVectors(_UP, dir)
    _shaft.scale.set(1, shaftLen, 1)
    _shaft.position.set(0, shaftLen / 2, 0)
    _head.scale.set(1, headLen, 1)
    _head.position.set(0, shaftLen + headLen / 2, 0)
  }

  // ── Public API ───────────────────────────────────────────────────────────
  /** Show the gizmo at `origin` (world nm) and start listening for drags. */
  function attach(origin = [0, 0, 0]) {
    _origin.set(origin[0] || 0, origin[1] || 0, origin[2] || 0)
    if (!_group) _build()
    _group.visible = true
    _dummy.position.copy(_origin)
    _helper.visible = _controlsVisible
    _tc.enabled = _controlsVisible
    _syncArrow()
  }

  /** Hide the gizmo and stop listening (kept around for cheap re-attach). */
  function detach() {
    _dragging = false
    if (controls) controls.enabled = true
    if (_group) _group.visible = false
    if (_helper) _helper.visible = false
    if (_tc) _tc.enabled = false
  }

  /** Set the world field vector (direction * length). */
  function setVector(v) {
    _vec.set(v[0] || 0, v[1] || 0, v[2] || 0)
    _arrowLength = Math.max(_vec.length(), 1e-3)
    _vec.normalize()
    if (_dummy) _dummy.quaternion.setFromUnitVectors(_UP, _vec)
    _syncArrow()
  }
  function setDirection(v) {
    const next = new THREE.Vector3(v[0] || 0, v[1] || 0, v[2] || 0)
    if (next.lengthSq() > 1e-8) _vec.copy(next.normalize())
    if (_dummy) _dummy.quaternion.setFromUnitVectors(_UP, _vec)
    _syncArrow()
  }
  function setArrowLength(length) {
    _arrowLength = Math.min(Math.max(Number(length) || 0, 1e-3), _MAX_ARROW_LENGTH_NM)
    _syncArrow()
  }
  function setControlsVisible(visible) {
    _controlsVisible = !!visible
    if (_helper) _helper.visible = _controlsVisible && !!_group?.visible
    if (_tc) _tc.enabled = _controlsVisible && !!_group?.visible
  }
  function setOffset(offset) {
    _origin.set(Number(offset?.[0]) || 0, Number(offset?.[1]) || 0, Number(offset?.[2]) || 0)
    if (_dummy) _dummy.position.copy(_origin)
    _syncArrow()
  }
  /** Current direction as a unit plain [x,y,z]. */
  function getVector() { return [_vec.x, _vec.y, _vec.z] }

  function setCamera(cam) { camera = cam; if (_tc) _tc.camera = cam }
  function setOnChange(cb) { _onChange = cb }

  /** Recolour the field arrow (the rotation handles keep cluster-tool axis colours). */
  function setColor(hex) {
    _arrowMat?.color?.set(hex)
    _arrowMat?.emissive?.set(hex)
  }

  /** Full teardown (remove from scene). */
  function dispose() {
    detach()
    if (_group) {
      _group.parent?.remove(_group)
      _tc?.detach?.()
      _tc?.dispose?.()
      _helper?.parent?.remove(_helper)
      _dummy?.parent?.remove(_dummy)
      _shaft?.geometry?.dispose?.()
      _head?.geometry?.dispose?.()
      _arrowMat?.dispose?.()
      _group = _arrow = _shaft = _head = _arrowMat = _dummy = _tc = _helper = null
    }
  }

  return {
    attach,
    detach,
    setVector,
    setDirection,
    setArrowLength,
    setControlsVisible,
    setOffset,
    getVector,
    setOnChange,
    setColor,
    setCamera,
    dispose,
    isActive: () => !!_group && _group.visible,
    isDragging: () => _dragging,
    get group() { return _group },
  }
}
