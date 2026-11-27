import * as THREE from 'three'
import { TransformControls } from 'three/addons/controls/TransformControls.js'
import { nearestBevelBp, bevelAngles } from './bevel_math.js'

/** Bend face dragging plus Tab-switched native rotation rings. */
export function createBevelPlaneControls({ scene, camera, canvas, controls, onChange, onMode }) {
  if (!canvas || !camera) return { update() {}, clear() {}, dispose() {} }
  const group = new THREE.Group(); group.name = 'bevel-plane-controls'
  const face = new THREE.Mesh(new THREE.PlaneGeometry(16, 16), new THREE.MeshBasicMaterial({
    color: 0x9fc9ed, transparent: true, opacity: .30, side: THREE.DoubleSide, depthWrite: false }))
  face.name = 'bevel-plane'
  group.add(face, new THREE.LineSegments(new THREE.EdgesGeometry(face.geometry), new THREE.LineBasicMaterial({ color: 0x9fc9ed })))
  const rotation = new TransformControls(camera, canvas)
  rotation.setMode('rotate'); rotation.setSpace('local'); rotation.setSize(.8); rotation.showZ = false
  rotation.enabled = false
  const helper = rotation.getHelper(); helper.name = 'bevel-rotation-controls'; scene.add(helper)
  let frame = null, paths = [], values = null, mode = 'translate', interactive = true, dragging = false, orbitEnabled = true, syncing = false
  const raycaster = new THREE.Raycaster(), billboard = new THREE.Plane(), point = new THREE.Vector3()
  function ray(event) {
    const r = canvas.getBoundingClientRect()
    raycaster.setFromCamera(new THREE.Vector2((event.clientX - r.left) / r.width * 2 - 1, -(event.clientY - r.top) / r.height * 2 + 1), camera)
  }
  function block(event) { event.preventDefault(); event.stopImmediatePropagation() }
  function down(event) {
    if (!interactive || !frame || mode !== 'translate' || event.button !== 0) return
    ray(event); group.updateMatrixWorld(true)
    if (!raycaster.intersectObject(face).length) return
    billboard.setFromNormalAndCoplanarPoint(camera.getWorldDirection(new THREE.Vector3()), frame.center)
    dragging = true; orbitEnabled = controls?.enabled ?? true
    if (controls) controls.enabled = false
    canvas.setPointerCapture?.(event.pointerId); block(event)
  }
  function move(event) {
    if (!dragging) return
    ray(event)
    if (raycaster.ray.intersectPlane(billboard, point)) {
      const bp = nearestBevelBp(paths, point)
      if (bp != null && bp !== values.positionBp) onChange({ ...values, positionBp: bp })
    }
    block(event)
  }
  function up(event) {
    if (!dragging) return
    dragging = false; if (controls) controls.enabled = orbitEnabled
    if (canvas.hasPointerCapture?.(event.pointerId)) canvas.releasePointerCapture(event.pointerId)
    block(event)
  }
  function tab(event) {
    if (!interactive || !frame || event.key !== 'Tab' || dragging || rotation.dragging || event.ctrlKey || event.metaKey || event.altKey) return
    if (event.target?.closest?.('input, select, textarea, button, [contenteditable="true"]')) return
    block(event); mode = mode === 'translate' ? 'rotate' : 'translate'
    rotation.enabled = mode === 'rotate'
    if (rotation.enabled) rotation.attach(group); else rotation.detach()
    group.userData.mode = mode; onMode?.(mode)
  }
  rotation.addEventListener('dragging-changed', event => {
    if (event.value) { orbitEnabled = controls?.enabled ?? true; if (controls) controls.enabled = false }
    else if (controls) controls.enabled = orbitEnabled
  })
  rotation.addEventListener('objectChange', () => {
    if (!frame || syncing) return
    onChange({ ...values, ...bevelAngles(new THREE.Vector3(0, 0, 1).applyQuaternion(group.quaternion), frame) })
  })
  canvas.addEventListener('pointerdown', down, true)
  canvas.addEventListener('pointermove', move, true)
  canvas.addEventListener('pointerup', up, true)
  canvas.addEventListener('pointercancel', up, true)
  document.addEventListener('keydown', tab, true)
  function clear() {
    if (dragging || rotation.dragging) { if (controls) controls.enabled = orbitEnabled }
    dragging = false; frame = null; rotation.detach(); rotation.enabled = false; group.removeFromParent(); mode = 'translate'; interactive = true
  }
  return {
    setEnabled(value) { interactive = value; rotation.enabled = value && mode === 'rotate' },
    update(nextFrame, nextPaths, nextValues) {
      frame = nextFrame; paths = nextPaths; values = nextValues; syncing = true
      group.position.copy(frame.center)
      if (!rotation.dragging) group.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), frame.normal)
      group.userData = { mode, positionBp: values.positionBp, normal: frame.normal.toArray() }
      if (!group.parent) scene.add(group)
      syncing = false
    },
    clear,
    dispose() {
      clear(); rotation.dispose(); helper.removeFromParent()
      group.traverse(node => { node.geometry?.dispose(); node.material?.dispose() })
      canvas.removeEventListener('pointerdown', down, true); canvas.removeEventListener('pointermove', move, true)
      canvas.removeEventListener('pointerup', up, true); canvas.removeEventListener('pointercancel', up, true)
      document.removeEventListener('keydown', tab, true)
    },
  }
}
