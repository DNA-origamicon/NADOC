import * as THREE from 'three'
import { createSectionViewControls } from '../ui/section_view_controls.js'
import { sectionStencilGeometry } from './section_geometry.js'
import { TransformControls } from 'three/addons/controls/TransformControls.js'

const materials = object => Array.isArray(object.material) ? object.material : [object.material]

const isVisibleMaterial = material => material && material.visible && material.colorWrite &&
  !(material.transparent && material.opacity <= 0)

export function isSectionContent(object) {
  if (!(object.isMesh || object.isLine || object.isPoints) || !object.geometry) return false
  for (let node = object; node; node = node.parent) {
    if (node.isTransformControlsRoot || /Helper$/.test(node.type) ||
        node.userData?.isGizmo || node.userData?.overlay || node.userData?.helper) return false
  }
  return materials(object).some(isVisibleMaterial)
}

// Preserve application shader patches (instance transforms, visibility and animation).
export function sectionStencilMaterial(source, plane, side) {
  const material = source.clone()
  material.onBeforeCompile = source.onBeforeCompile
  material.customProgramCacheKey = source.customProgramCacheKey
  material.visible = isVisibleMaterial(source) && !source.wireframe
  material.side = side
  material.clippingPlanes = [...(source.clippingPlanes || []).filter(p => p !== plane), plane]
  material.colorWrite = material.depthWrite = material.depthTest = false
  material.transparent = false
  material.stencilWrite = true
  material.stencilFunc = THREE.AlwaysStencilFunc
  const op = side === THREE.BackSide ? THREE.IncrementWrapStencilOp : THREE.DecrementWrapStencilOp
  material.stencilFail = material.stencilZFail = material.stencilZPass = op
  return material
}

export function initSectionView({ scene, camera, renderer, controls, addFrameCallback, removeFrameCallback, getRenderCamera, getPartCentroid, document }) {
  const body = document.querySelector('#right-view-actions .ox-card__body')
  if (!body) return null
  const button = document.createElement('button')
  button.id = 'section-view-btn'
  button.className = 'def-btn'
  button.textContent = 'Section view'
  button.type = 'button'
  button.setAttribute('aria-pressed', 'false')
  body.append(button)
  button.setAttribute('aria-controls', 'section-view-controls')
  button.setAttribute('aria-expanded', 'false')
  const root = new THREE.Group()
  root.userData.helper = true
  root.visible = false
  // Group order makes all stencil passes precede the cap and ordinary content.
  root.renderOrder = -10000
  scene.add(root)
  const anchor = new THREE.Object3D()
  root.add(anchor)
  const plane = new THREE.Plane()
  const normal = new THREE.Vector3(0, 0, 1)
  const gizmo = new TransformControls(camera, renderer.domElement)
  gizmo.setSpace('local')
  gizmo.showX = gizmo.showY = false
  gizmo.enabled = false
  const helper = gizmo.getHelper()
  helper.userData.helper = true
  scene.add(helper)
  let enabled = false, flipped = false, previousControls = null, previousClipping = false
  const saved = new Map(), proxies = new Map(), stencilGeometries = new Map()
  const capMaterial = new THREE.MeshBasicMaterial({ color: 0x94bdd0, side: THREE.DoubleSide,
    stencilWrite: true, stencilRef: 0, stencilFunc: THREE.NotEqualStencilFunc,
    stencilFail: THREE.ReplaceStencilOp, stencilZFail: THREE.ReplaceStencilOp, stencilZPass: THREE.ReplaceStencilOp })
  capMaterial.onBeforeCompile = shader => {
    shader.fragmentShader = shader.fragmentShader.replace('#include <color_fragment>', `#include <color_fragment>
      float stripe = mod(gl_FragCoord.x + gl_FragCoord.y, 12.0);
      float ink = 1.0 - smoothstep(0.7, 1.8, min(stripe, 12.0 - stripe));
      diffuseColor.rgb = mix(diffuseColor.rgb, vec3(0.18, 0.27, 0.32), ink * 0.8);`)
  }
  const cap = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), capMaterial)
  cap.renderOrder = 2
  cap.frustumCulled = false
  cap.raycast = () => {}
  cap.onAfterRender = r => r.clearStencil()
  root.add(cap)
  const outline = new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints([
    new THREE.Vector3(-0.5, -0.5, 0), new THREE.Vector3(0.5, -0.5, 0),
    new THREE.Vector3(0.5, 0.5, 0), new THREE.Vector3(-0.5, 0.5, 0),
  ]), new THREE.LineBasicMaterial({ color: 0x73cfff, transparent: true, opacity: 0.65 }))
  outline.raycast = () => {}
  root.add(outline)

  let controlsHidden = false
  const options = createSectionViewControls({ document, parent: body,
    readPose: () => ({ position: anchor.position, rotation: {
      x: THREE.MathUtils.radToDeg(anchor.rotation.x),
      y: THREE.MathUtils.radToDeg(anchor.rotation.y),
      z: THREE.MathUtils.radToDeg(anchor.rotation.z),
    } }),
    writeValue(kind, axis, value) {
      if (kind === 'position') anchor.position[axis] = value
      else anchor.rotation[axis] = THREE.MathUtils.degToRad(value)
      updatePlane()
    },
    setMode(mode) { gizmo.setMode(mode); gizmo.showX = gizmo.showY = mode === 'rotate' },
    flip() { flipped = !flipped; updatePlane() },
    reset() {
      const bounds = contentBounds()
      const center = bounds.isEmpty() ? controls.target.clone() : bounds.getCenter(new THREE.Vector3())
      anchor.position.copy(getPartCentroid?.(center) ?? center)
      anchor.rotation.set(Math.PI, 0, 0, 'XYZ')
      flipped = false
      updatePlane()
    },
    setControlsHidden(hidden) { controlsHidden = hidden; updateControlsVisibility() },
  })
  function updateControlsVisibility() {
    outline.visible = !controlsHidden
    if (enabled && !controlsHidden) { gizmo.enabled = true; gizmo.attach(anchor) }
    else {
      gizmo.detach(); gizmo.enabled = false
      if (previousControls !== null) { controls.enabled = previousControls; previousControls = null }
    }
  }

  function updatePlane() {
    plane.setFromNormalAndCoplanarPoint(normal.clone().applyQuaternion(anchor.quaternion).multiplyScalar(flipped ? -1 : 1), anchor.position)
    cap.position.copy(anchor.position)
    cap.quaternion.copy(anchor.quaternion)
    outline.position.copy(anchor.position)
    outline.quaternion.copy(anchor.quaternion)
    options.sync()
  }
  gizmo.addEventListener('objectChange', updatePlane)
  gizmo.addEventListener('dragging-changed', event => {
    if (event.value) { previousControls = controls.enabled; controls.enabled = false }
    else if (previousControls !== null) { controls.enabled = previousControls; previousControls = null }
  })
  function removeProxy(object) {
    for (const mesh of proxies.get(object)?.meshes || []) {
      mesh.removeFromParent()
      materials(mesh).forEach(m => m.dispose())
    }
    proxies.delete(object)
  }
  function sync() {
    if (!enabled) return
    gizmo.camera = getRenderCamera?.() || camera
    scene.updateMatrixWorld(true)
    const active = new Set()
    scene.traverseVisible(object => {
      if (!isSectionContent(object)) return
      active.add(object)
      for (const material of materials(object)) {
        if (!saved.has(material)) {
          saved.set(material, material.clippingPlanes)
          material.clippingPlanes = [...(material.clippingPlanes || []), plane]
          material.needsUpdate = true
        }
      }
      if (!object.isMesh) return
      if (!stencilGeometries.has(object.geometry)) {
        stencilGeometries.set(object.geometry, sectionStencilGeometry(object.geometry))
      }
      const stencilGeometry = stencilGeometries.get(object.geometry)
      if (!stencilGeometry) { removeProxy(object); return }
      let entry = proxies.get(object)
      if (entry && (entry.material !== object.material || entry.geometry !== object.geometry)) { removeProxy(object); entry = null }
      if (!entry) {
        const meshes = [THREE.BackSide, THREE.FrontSide].map((side, index) => {
          const mesh = object.clone(false)
          const ms = materials(object).map(m => sectionStencilMaterial(m, plane, side))
          mesh.geometry = stencilGeometry
          mesh.material = Array.isArray(object.material) ? ms : ms[0]
          mesh.matrixAutoUpdate = false
          mesh.frustumCulled = false
          mesh.renderOrder = index
          mesh.raycast = () => {}
          mesh.onBeforeRender = object.onBeforeRender
          root.add(mesh)
          return mesh
        })
        entry = { meshes, material: object.material, geometry: object.geometry }
        proxies.set(object, entry)
      }
      for (const mesh of entry.meshes) {
        materials(mesh).forEach((material, i) => {
          const source = materials(object)[i]
          material.visible = isVisibleMaterial(source) && !source.wireframe
        })
        mesh.matrix.copy(object.matrixWorld)
        mesh.layers.mask = object.layers.mask
        if (object.isInstancedMesh) {
          mesh.instanceMatrix = object.instanceMatrix
          mesh.instanceColor = object.instanceColor
          mesh.count = object.count
        }
      }
    })
    for (const object of proxies.keys()) if (!active.has(object)) removeProxy(object)
    updatePlane()
  }
  function contentBounds() {
    scene.updateMatrixWorld(true)
    const bounds = new THREE.Box3()
    scene.traverseVisible(object => {
      if (!isSectionContent(object)) return
      if (object.isInstancedMesh) object.computeBoundingBox()
      else if (!object.geometry.boundingBox) object.geometry.computeBoundingBox()
      const box = object.isInstancedMesh ? object.boundingBox : object.geometry.boundingBox
      if (box) bounds.union(box.clone().applyMatrix4(object.matrixWorld))
    })
    return bounds
  }
  function setEnabled(value) {
    if (enabled === value) return
    enabled = value
    root.visible = value
    options.setVisible(value)
    button.setAttribute('aria-expanded', String(value))
    button.classList.toggle('active', value)
    button.setAttribute('aria-pressed', String(value))
    if (value) {
      previousClipping = renderer.localClippingEnabled
      renderer.localClippingEnabled = true
      const bounds = contentBounds()
      anchor.position.copy(bounds.isEmpty() ? controls.target : bounds.getCenter(new THREE.Vector3()))
      const direction = (getRenderCamera?.() || camera).getWorldDirection(new THREE.Vector3())
      anchor.quaternion.setFromUnitVectors(normal, direction)
      flipped = false
      const size = bounds.isEmpty() ? 10 : Math.max(bounds.getSize(new THREE.Vector3()).length() * 2, 1)
      cap.scale.set(size, size, 1)
      outline.scale.copy(cap.scale)
      updateControlsVisibility()
      sync()
      options.sync(true)
    } else {
      gizmo.detach(); gizmo.enabled = false
      if (previousControls !== null) { controls.enabled = previousControls; previousControls = null }
      for (const [material, clippingPlanes] of saved) { material.clippingPlanes = clippingPlanes; material.needsUpdate = true }
      saved.clear()
      for (const object of proxies.keys()) removeProxy(object)
      for (const [source, geometry] of stencilGeometries) if (geometry && geometry !== source) geometry.dispose()
      stencilGeometries.clear()
      renderer.localClippingEnabled = previousClipping
    }
  }
  button.addEventListener('click', () => setEnabled(!enabled))
  addFrameCallback(sync)
  return { setEnabled, plane, anchor, sync, get enabled() { return enabled }, dispose() {
    setEnabled(false); removeFrameCallback(sync); gizmo.dispose(); helper.removeFromParent(); root.removeFromParent()
    cap.geometry.dispose(); capMaterial.dispose(); outline.geometry.dispose(); outline.material.dispose()
    button.remove(); options.dispose()
  } }
}
