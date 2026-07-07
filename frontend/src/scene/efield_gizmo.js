/**
 * Electric-field direction/magnitude gizmo.
 *
 * A single draggable arrow in the scene: it points along the field direction and
 * its length encodes magnitude.  Dragging the tip handle reorients + resizes the
 * arrow (raycast the handle, then intersect a camera-facing plane through the
 * origin — see efield_math.rayPlaneVector); OrbitControls are disabled mid-drag
 * (mirrors overhang_gizmo.js).  Direction + magnitude are also fully settable
 * programmatically (setVector / getVector) so automated tests drive it without a
 * mouse — that is the "make testing automatable" requirement.
 *
 * Display-layer only: the gizmo never touches topology or the design; it just
 * reports its world vector via the onChange callback.  The owning panel
 * (ui/efield_setup.js) maps that vector to force-per-nucleotide (pN) + direction.
 *
 * Factory:
 *   const gizmo = initEfieldGizmo(scene, camera, canvas, controls)
 *   gizmo.attach([x,y,z])      // show at origin, start listening for drags
 *   gizmo.setVector([0,1,0])   // direction*length in world units
 *   gizmo.setOnChange(v => …)  // fired during a drag with the new world vector
 *   gizmo.detach()             // hide + stop listening
 */

import * as THREE from 'three'
import { rayPlaneVector } from './efield_math.js'

const _ARROW_COLOR  = 0x4a9eff
const _HANDLE_COLOR = 0x9ad1ff

// Thick-arrow geometry (nm).  A solid cylinder shaft + cone head reads as a real
// 3D arrow, unlike THREE.ArrowHelper's 1-px line shaft.
const _SHAFT_R = 0.45
const _HEAD_R  = 1.15
const _UP      = new THREE.Vector3(0, 1, 0)

export function initEfieldGizmo(scene, camera, canvas, controls, name = 'efield-gizmo') {
  let _group   = null               // named THREE.Group (test locator: `name`, default 'efield-gizmo')
  let _arrow   = null               // THREE.Group: thick shaft cylinder + cone head
  let _shaft   = null
  let _head    = null
  let _arrowMat = null
  let _handle  = null               // tip sphere (drag target)
  let _onChange = null
  let _dragging = false
  const _origin = new THREE.Vector3(0, 0, 0)
  const _vec    = new THREE.Vector3(0, 1, 0)   // world field vector (dir * length)
  const _ray    = new THREE.Raycaster()

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
    _head  = new THREE.Mesh(new THREE.ConeGeometry(_HEAD_R, 1, 20), _arrowMat)
    _arrow = new THREE.Group()
    _arrow.name = 'efield-gizmo-arrow'
    _arrow.add(_shaft, _head)
    _handle = new THREE.Mesh(
      new THREE.SphereGeometry(0.7, 16, 12),
      new THREE.MeshBasicMaterial({ color: _HANDLE_COLOR, depthTest: false }),
    )
    _handle.name = 'efield-gizmo-handle'
    _handle.renderOrder = 999
    _group.add(_arrow, _handle)
    scene.add(_group)
  }

  /** Re-position the arrow + handle from the current origin/vector. */
  function _sync() {
    if (!_group) return
    const len = Math.max(_vec.length(), 1e-3)
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
    _handle.position.copy(_origin).addScaledVector(dir, len)
  }

  // ── Pointer drag ───────────────────────────────────────────────────────────
  function _ndc(e) {
    const r = canvas.getBoundingClientRect()
    return new THREE.Vector2(
      ((e.clientX - r.left) / r.width) * 2 - 1,
      -((e.clientY - r.top) / r.height) * 2 + 1,
    )
  }

  function _onDown(e) {
    if (!_group || !_group.visible) return
    _ray.setFromCamera(_ndc(e), camera)
    if (_ray.intersectObject(_handle, false).length) {
      _dragging = true
      if (controls) controls.enabled = false
      e.stopPropagation()
    }
  }

  function _onMove(e) {
    if (!_dragging) return
    _ray.setFromCamera(_ndc(e), camera)
    const ro = _ray.ray.origin, rd = _ray.ray.direction
    const n = camera.getWorldDirection(new THREE.Vector3())   // camera-facing drag plane
    const v = rayPlaneVector([ro.x, ro.y, ro.z], [rd.x, rd.y, rd.z],
                             [n.x, n.y, n.z], [_origin.x, _origin.y, _origin.z])
    if (v) { setVector(v); _onChange?.(getVector()) }
  }

  function _onUp() {
    if (!_dragging) return
    _dragging = false
    if (controls) controls.enabled = true
  }

  let _bound = false
  function _bind() {
    if (_bound || !canvas?.addEventListener) return
    canvas.addEventListener('pointerdown', _onDown, true)
    window.addEventListener('pointermove', _onMove)
    window.addEventListener('pointerup', _onUp)
    _bound = true
  }
  function _unbind() {
    if (!_bound) return
    canvas?.removeEventListener?.('pointerdown', _onDown, true)
    window.removeEventListener('pointermove', _onMove)
    window.removeEventListener('pointerup', _onUp)
    _bound = false
  }

  // ── Public API ───────────────────────────────────────────────────────────
  /** Show the gizmo at `origin` (world nm) and start listening for drags. */
  function attach(origin = [0, 0, 0]) {
    _origin.set(origin[0] || 0, origin[1] || 0, origin[2] || 0)
    if (!_group) _build()
    _group.visible = true
    _sync()
    _bind()
  }

  /** Hide the gizmo and stop listening (kept around for cheap re-attach). */
  function detach() {
    _dragging = false
    if (controls) controls.enabled = true
    _unbind()
    if (_group) _group.visible = false
  }

  /** Set the world field vector (direction * length). */
  function setVector(v) {
    _vec.set(v[0] || 0, v[1] || 0, v[2] || 0)
    _sync()
  }
  /** Current world field vector as a plain [x,y,z]. */
  function getVector() { return [_vec.x, _vec.y, _vec.z] }

  function setCamera(cam) { camera = cam }
  function setOnChange(cb) { _onChange = cb }

  /** Recolour the arrow + tip handle (e.g. magnitude-graded blue→green→red). */
  function setColor(hex) {
    _arrowMat?.color?.set(hex)
    _arrowMat?.emissive?.set(hex)
    _handle?.material?.color?.set(hex)
  }

  /** Full teardown (remove from scene). */
  function dispose() {
    detach()
    if (_group) {
      _group.parent?.remove(_group)
      _shaft?.geometry?.dispose?.()
      _head?.geometry?.dispose?.()
      _arrowMat?.dispose?.()
      _handle?.geometry?.dispose?.()
      _handle?.material?.dispose?.()
      _group = _arrow = _shaft = _head = _arrowMat = _handle = null
    }
  }

  return {
    attach,
    detach,
    setVector,
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
