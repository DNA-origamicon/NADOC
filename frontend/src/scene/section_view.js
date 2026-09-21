import * as THREE from 'three'
import { createSectionViewControls } from '../ui/section_view_controls.js'
import { sectionStencilGeometry } from './section_geometry.js'
import { TransformControls } from 'three/addons/controls/TransformControls.js'
import { sectionCapShader } from './section_cap_material.js'

const materials = object => Array.isArray(object.material) ? object.material : [object.material]

const isVisibleMaterial = material => material && material.visible && material.colorWrite &&
  !(material.transparent && material.opacity <= 0)

const isGpuPositionedImpostor = material => {
  if (!material?.userData?.isImpostor) return false
  const key = material.customProgramCacheKey?.() || ''
  return key.startsWith('sharedInstanced_') || key.startsWith('atomImpostor_')
}

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
  // An impostor's display shader turns every vertex into a camera-facing quad.
  // Its section proxy uses real sphere geometry, so it also needs an unpatched
  // material or the closed sphere would be flattened back into the billboard.
  const impostor = source.userData?.isImpostor
  const material = impostor ? new THREE.MeshBasicMaterial() : source.clone()
  if (!impostor) {
    material.onBeforeCompile = source.onBeforeCompile
    material.customProgramCacheKey = source.customProgramCacheKey
  }
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

export function sectionStencilGeometryFor(object) {
  const impostor = materials(object).find(material => material?.userData?.isImpostor)
  // Shared assembly instances keep their centers in GPU textures rather than
  // instanceMatrix. A plain sphere proxy cannot reproduce those transforms.
  if (isGpuPositionedImpostor(impostor)) return null
  const radius = Number(impostor?.userData?.impostorRadius)
  if (Number.isFinite(radius) && radius > 0) {
    return new THREE.SphereGeometry(radius, 10, 8)
  }
  return sectionStencilGeometry(object.geometry)
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
  // Each child group renders its winding passes and cap before ordinary content.
  root.renderOrder = -10000
  scene.add(root)
  let selected = null, nextId = 1
  const planes = []
  let anchor = new THREE.Object3D(), plane = new THREE.Plane()
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
  function createPlaneVisuals(group) {
    const capMaterial = new THREE.MeshBasicMaterial({ color: 0x94bdd0, side: THREE.DoubleSide,
      stencilWrite: true, stencilRef: 0, stencilFunc: THREE.NotEqualStencilFunc,
      stencilFail: THREE.ReplaceStencilOp, stencilZFail: THREE.ReplaceStencilOp, stencilZPass: THREE.ReplaceStencilOp })
    capMaterial.onBeforeCompile = sectionCapShader
    const cap = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), capMaterial)
    cap.renderOrder = 2
    cap.frustumCulled = false
    cap.raycast = () => {}
    cap.onAfterRender = r => r.clearStencil()
    group.add(cap)
    const outline = new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(-0.5, -0.5, 0), new THREE.Vector3(0.5, -0.5, 0),
      new THREE.Vector3(0.5, 0.5, 0), new THREE.Vector3(-0.5, 0.5, 0),
    ]), new THREE.LineBasicMaterial({ color: 0x73cfff, transparent: true, opacity: 0.65 }))
    outline.raycast = () => {}
    group.add(outline)
    return { cap, outline }
  }

  let controlsHidden = false
  const options = createSectionViewControls({ document, parent: body,
    readPlanes: () => planes.map(p => ({ id: p.id, visible: p.visible, selected: p === selected })),
    addPlane, selectPlane, deletePlane,
    togglePlane(id) { const p = planes.find(p => p.id === id); p.visible = !p.visible; rebuild(); },
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
    flip() { flipped = !flipped; selected.flipped = flipped; updatePlane() },
    reset() {
      const bounds = contentBounds()
      const center = bounds.isEmpty() ? controls.target.clone() : bounds.getCenter(new THREE.Vector3())
      anchor.position.copy(getPartCentroid?.(center) ?? center)
      anchor.rotation.set(Math.PI, 0, 0, 'XYZ')
      flipped = false
      selected.flipped = false
      updatePlane()
    },
    setControlsHidden(hidden) { controlsHidden = hidden; updateControlsVisibility() },
  })
  function selectPlane(id) {
    selected = planes.find(p => p.id === id) || null
    anchor = selected?.anchor || new THREE.Object3D()
    plane = selected?.plane || new THREE.Plane()
    flipped = selected?.flipped || false
    updateControlsVisibility()
    options.sync(true)
  }
  function addPlane() {
    const previous = planes.at(-1)
    const group = new THREE.Group()
    group.renderOrder = -10000 + planes.length
    root.add(group)
    const pose = new THREE.Object3D()
    group.add(pose)
    if (previous) {
      pose.position.copy(previous.anchor.position)
      pose.quaternion.copy(previous.anchor.quaternion)
    } else {
      const bounds = contentBounds()
      pose.position.copy(bounds.isEmpty() ? controls.target : bounds.getCenter(new THREE.Vector3()))
      pose.quaternion.setFromUnitVectors(normal, (getRenderCamera?.() || camera).getWorldDirection(new THREE.Vector3()))
    }
    const entry = { id: nextId++, anchor: pose, plane: new THREE.Plane(), flipped: previous?.flipped || false,
      visible: true, group, ...createPlaneVisuals(group) }
    planes.push(entry)
    selectPlane(entry.id)
    rebuild()
    return entry
  }
  function deletePlane() {
    if (!selected) return
    const index = planes.indexOf(selected)
    const entry = selected
    planes.splice(index, 1)
    disposePlane(entry)
    selectPlane(planes[Math.min(index, planes.length - 1)]?.id)
    rebuild()
  }
  function disposePlane(entry) {
    entry.group.removeFromParent()
    for (const object of [entry.cap, entry.outline]) { object.geometry.dispose(); object.material.dispose() }
  }
  function rebuild() {
    for (const object of proxies.keys()) removeProxy(object)
    for (const [material, clippingPlanes] of saved) { material.clippingPlanes = clippingPlanes; material.needsUpdate = true }
    saved.clear()
    planes.forEach((p, i) => { p.group.renderOrder = -10000 + i })
    boundsDirty = true
    updateControlsVisibility()
    sync()
    options.sync(true)
  }
  function updateControlsVisibility() {
    for (const p of planes) p.outline.visible = p === selected && !controlsHidden && p.visible
    if (enabled && selected?.visible && !controlsHidden) { gizmo.enabled = true; gizmo.attach(anchor) }
    else {
      gizmo.detach(); gizmo.enabled = false
      if (previousControls !== null) { controls.enabled = previousControls; previousControls = null }
    }
  }

  function updatePlane() {
    for (const p of planes) {
      p.plane.setFromNormalAndCoplanarPoint(normal.clone().applyQuaternion(p.anchor.quaternion).multiplyScalar(p.flipped ? -1 : 1), p.anchor.position)
      p.cap.position.copy(p.anchor.position)
      p.cap.quaternion.copy(p.anchor.quaternion)
      p.outline.position.copy(p.anchor.position)
      p.outline.quaternion.copy(p.anchor.quaternion)
      p.group.visible = p.visible
    }
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
  let boundsDirty = true
  let capBounds = new THREE.Box3()
  function sync() {
    if (!enabled) return
    gizmo.camera = getRenderCamera?.() || camera
    scene.updateMatrixWorld(true)
    updatePlane()
    const activePlanes = planes.filter(p => p.visible)
    for (const p of planes) {
      const others = activePlanes.filter(other => other !== p).map(other => other.plane)
      if (p.cap.material.clippingPlanes?.length !== others.length || others.some((v, i) => p.cap.material.clippingPlanes[i] !== v)) {
        p.cap.material.clippingPlanes = others
        p.cap.material.needsUpdate = true
      }
    }
    if (boundsDirty) { capBounds = contentBounds(); boundsDirty = false }
    const bounds = capBounds
    const size = bounds.isEmpty() ? 10 : Math.max(bounds.getSize(new THREE.Vector3()).length() * 2, 1)
    for (const p of planes) {
      const extent = size + (bounds.isEmpty() ? 0 : p.anchor.position.distanceTo(bounds.getCenter(new THREE.Vector3())) * 2)
      p.cap.scale.set(extent, extent, 1); p.outline.scale.copy(p.cap.scale)
    }
    const active = new Set()
    scene.traverseVisible(object => {
      if (!isSectionContent(object)) return
      active.add(object)
      for (const material of materials(object)) {
        if (!saved.has(material)) {
          saved.set(material, material.clippingPlanes)
          material.clippingPlanes = [...(material.clippingPlanes || []), ...activePlanes.map(p => p.plane)]
          material.needsUpdate = true
        }
      }
      if (!object.isMesh) return
      const impostorRadius = materials(object).find(m => m?.userData?.isImpostor)?.userData?.impostorRadius
      const stencilKey = impostorRadius == null ? object.geometry : `impostor-sphere:${impostorRadius}`
      if (!stencilGeometries.has(stencilKey)) {
        const geometry = sectionStencilGeometryFor(object)
        stencilGeometries.set(stencilKey, { geometry, owned: geometry !== object.geometry })
      }
      const stencilGeometry = stencilGeometries.get(stencilKey).geometry
      if (!stencilGeometry) { removeProxy(object); return }
      let entry = proxies.get(object)
      if (entry && (entry.material !== object.material || entry.geometry !== object.geometry || entry.stencilKey !== stencilKey)) { removeProxy(object); entry = null }
      if (!entry) {
        boundsDirty = true
        const meshes = activePlanes.flatMap(p => [THREE.BackSide, THREE.FrontSide].map((side, index) => {
          const mesh = object.clone(false)
          // Winding must use the original closed solid, clipped only by this plane.
          // Clipping winding geometry by other section planes opens it and leaks caps.
          const ms = materials(object).map(m => {
            const stencil = sectionStencilMaterial(m, p.plane, side)
            stencil.clippingPlanes = [...(saved.get(m) || []), p.plane]
            return stencil
          })
          mesh.geometry = stencilGeometry
          mesh.material = Array.isArray(object.material) ? ms : ms[0]
          mesh.matrixAutoUpdate = false
          mesh.frustumCulled = false
          mesh.renderOrder = index
          mesh.raycast = () => {}
          mesh.onBeforeRender = object.onBeforeRender
          p.group.add(mesh)
          return mesh
        }))
        entry = { meshes, material: object.material, geometry: object.geometry, stencilKey }
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
    for (const object of proxies.keys()) if (!active.has(object)) { removeProxy(object); boundsDirty = true }
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
      boundsDirty = true
      if (!planes.length) addPlane()
      updateControlsVisibility()
      sync()
      options.sync(true)
    } else {
      gizmo.detach(); gizmo.enabled = false
      if (previousControls !== null) { controls.enabled = previousControls; previousControls = null }
      for (const [material, clippingPlanes] of saved) { material.clippingPlanes = clippingPlanes; material.needsUpdate = true }
      saved.clear()
      for (const object of proxies.keys()) removeProxy(object)
      for (const { geometry, owned } of stencilGeometries.values()) if (owned) geometry?.dispose()
      stencilGeometries.clear()
      renderer.localClippingEnabled = previousClipping
    }
  }
  button.addEventListener('click', () => setEnabled(!enabled))
  addFrameCallback(sync)
  return { setEnabled, addPlane, selectPlane, deletePlane, get planes() { return planes }, get plane() { return plane }, get anchor() { return anchor }, sync, get enabled() { return enabled }, dispose() {
    setEnabled(false); removeFrameCallback(sync); gizmo.dispose(); helper.removeFromParent(); root.removeFromParent()
    planes.forEach(disposePlane)
    button.remove(); options.dispose()
  } }
}
