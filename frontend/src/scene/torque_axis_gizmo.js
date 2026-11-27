import * as THREE from 'three'
import { TransformControls } from 'three/addons/controls/TransformControls.js'

const ARROW_LENGTH = 14.3
const DEFAULT_ARROW_PIXELS = 136

export function initTorqueAxisGizmo(scene, getCamera, canvas, getOrbit, addFrameCallback) {
  const target = new THREE.Group()
  target.name = 'torque-axis'
  target.userData.setupOnly = true
  target.visible = false
  const visual = new THREE.Group()
  const material = new THREE.MeshBasicMaterial({
    color: 0xffb14c, transparent: true, depthTest: false, depthWrite: false, toneMapped: false,
  })
  const shaft = new THREE.Mesh(new THREE.CylinderGeometry(0.32, 0.32, 12, 16), material)
  const head = new THREE.Mesh(new THREE.ConeGeometry(0.95, 2.6, 20), material)
  const origin = new THREE.Mesh(new THREE.RingGeometry(0.51, 0.75, 24), material)
  shaft.rotateX(Math.PI / 2)
  head.rotateX(Math.PI / 2)
  shaft.position.z = 6
  head.position.z = 13
  for (const mesh of [shaft, head, origin]) mesh.renderOrder = 1200
  origin.renderOrder++
  visual.add(shaft, head, origin)
  target.add(visual)
  scene.add(target)
  const transform = new TransformControls(getCamera(), canvas)
  transform.setMode('translate')
  transform.setSize(0.7)
  const helper = transform.getHelper()
  helper.name = 'torque-axis-controls'
  helper.userData.setupOnly = true
  const updateHelper = helper.updateMatrixWorld.bind(helper)
  helper.updateMatrixWorld = force => {
    transform.camera = getCamera()
    updateHelper(force)
  }
  scene.add(helper)
  const ray = new THREE.Raycaster()
  let changed = null
  let orbit = null
  let orbitWasEnabled = false
  let consumed = false
  let sizePercent = 100
  const viewPoint = new THREE.Vector3()
  const cameraRotation = new THREE.Quaternion()
  const axisRotation = new THREE.Quaternion()

  function updateVisual() {
    if (!target.visible) return
    const camera = getCamera()
    const height = canvas.clientHeight
    if (!camera || !height) return
    target.getWorldPosition(viewPoint).applyMatrix4(camera.matrixWorldInverse)
    const depth = camera.isPerspectiveCamera ? Math.max(camera.near, -viewPoint.z) : 1
    const worldPerPixel = 2 * depth / (height * camera.projectionMatrix.elements[5])
    visual.scale.setScalar(DEFAULT_ARROW_PIXELS * sizePercent / 100 * worldPerPixel / ARROW_LENGTH)
    // Keep the axis origin visible when the arrow points along the line of sight.
    target.getWorldQuaternion(axisRotation)
    camera.getWorldQuaternion(cameraRotation)
    origin.quaternion.copy(axisRotation.invert()).multiply(cameraRotation)
    target.updateMatrixWorld(true)
  }
  addFrameCallback(updateVisual)

  function pose() {
    return {
      kind: 'pose',
      position_nm: target.position.toArray(),
      rotation_deg: [target.rotation.x, target.rotation.y, target.rotation.z].map(THREE.MathUtils.radToDeg),
    }
  }
  function setPose(value) {
    target.position.fromArray(value.position_nm)
    target.rotation.set(...value.rotation_deg.map(THREE.MathUtils.degToRad), 'XYZ')
    target.updateMatrixWorld()
    updateVisual()
  }
  function select() {
    if (target.visible) {
      transform.enabled = true
      transform.attach(target)
    }
  }
  function deselect() {
    if (transform.dragging) transform.pointerUp(null)
    transform.detach()
    transform.enabled = false
  }
  function show(visible) {
    target.visible = visible
    if (!visible) deselect()
    else updateVisual()
  }
  transform.addEventListener('objectChange', () => changed?.(pose()))
  transform.addEventListener('dragging-changed', ({ value }) => {
    if (value) {
      orbit = getOrbit()
      if (orbit) { orbitWasEnabled = orbit.enabled; orbit.enabled = false }
    } else if (orbit) {
      orbit.enabled = orbitWasEnabled
      orbit = null
    }
  })
  canvas.addEventListener('pointerdown', event => {
    consumed = false
    if (!target.visible || event.button !== 0 || (transform.object && transform.axis)) return
    const rect = canvas.getBoundingClientRect()
    ray.setFromCamera({ x: 2 * (event.clientX - rect.left) / rect.width - 1,
      y: 1 - 2 * (event.clientY - rect.top) / rect.height }, getCamera())
    if (ray.intersectObject(visual, true).length) {
      select()
      consumed = true
      event.stopImmediatePropagation()
    } else {
      deselect()
    }
  }, true)
  canvas.addEventListener('pointerup', event => {
    if (!consumed) return
    consumed = false
    event.stopImmediatePropagation()
  }, true)
  window.addEventListener('keydown', event => {
    if (!transform.object || transform.dragging || event.target?.closest?.('input, textarea, select, [contenteditable]')) return
    if (event.key === 'Tab' && !event.ctrlKey && !event.altKey && !event.metaKey) {
      event.preventDefault()
      transform.setMode(transform.mode === 'translate' ? 'rotate' : 'translate')
    } else if (event.key === 'Escape') {
      deselect()
    }
  })
  deselect()
  return { show, select, setPose, setOnChange(handler) { changed = handler },
    setSize(percent) { sizePercent = percent; updateVisual() },
    ownsPointer: () => !!transform.object && (transform.dragging || !!transform.axis) }
}
