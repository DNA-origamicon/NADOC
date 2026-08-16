import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import { COLORING_LABELS, supportedColoringSet } from '../scene/coloring_modes.js'
import './multi_view.css'

export const MULTI_VIEW_REPRESENTATIONS = [
  ['hull-prism', 'Hull Prism'], ['cylinders', 'Cylinders'], ['beads', 'Beads'], ['full', 'Full'],
  ['surface', 'Surface'], ['vdw', 'VDW / Space-fill'], ['ballstick', 'Ball & Stick'], ['stick', 'Stick'],
  ['mrdna-coarse', 'mrDNA Coarse'], ['mrdna-fine', 'mrDNA Fine'],
]

/** CSS-pixel panel rectangles, measured from bottom-left for WebGL. */
export function multiViewRects(count, width, height) {
  const halfW = Math.floor(width / 2), halfH = Math.floor(height / 2)
  if (count === 2) return [{ x: 0, y: 0, w: halfW, h: height }, { x: halfW, y: 0, w: width - halfW, h: height }]
  if (count === 3) return [
    { x: 0, y: 0, w: halfW, h: height },
    { x: halfW, y: halfH, w: width - halfW, h: height - halfH },
    { x: halfW, y: 0, w: width - halfW, h: halfH },
  ]
  return [
    { x: 0, y: halfH, w: halfW, h: height - halfH }, { x: halfW, y: halfH, w: width - halfW, h: height - halfH },
    { x: 0, y: 0, w: halfW, h: halfH }, { x: halfW, y: 0, w: width - halfW, h: halfH },
  ]
}

function layoutIcon(count) {
  const cells = count === 2 ? '<i></i><i></i>' : count === 3 ? '<i class="wide"></i><i></i><i></i>' : '<i></i><i></i><i></i><i></i>'
  return `<span class="mv-layout-icon mv-layout-icon--${count}" aria-hidden="true">${cells}</span>`
}

export function cloneMultiScene(scene) {
  const clone = scene.clone(true)
  const interactiveControls = []
  clone.traverse(obj => {
    if (obj.isTransformControlsRoot) { interactiveControls.push(obj); return }
    if (obj.geometry) obj.geometry = obj.geometry.clone()
    if (Array.isArray(obj.material)) obj.material = obj.material.map(material => material.clone())
    else if (obj.material) obj.material = obj.material.clone()
  })
  for (const control of interactiveControls) control.removeFromParent()
  return clone
}

export function disposeMultiScene(scene) {
  scene?.traverse?.(obj => {
    obj.geometry?.dispose?.()
    const materials = Array.isArray(obj.material) ? obj.material : [obj.material]
    for (const material of materials) material?.dispose?.()
  })
}

/** Hull-Audit-style bounds: rendered molecular geometry only, not viewport tools. */
export function multiViewContentBounds(root) {
  const box = new THREE.Box3()
  const childBox = new THREE.Box3()
  root?.updateMatrixWorld?.(true)
  const traverse = root?.traverseVisible?.bind(root) ?? root?.traverse?.bind(root)
  traverse?.(obj => {
    let ancestor = obj
    while (ancestor && ancestor !== root) {
      if (ancestor.isAxesHelper || ancestor.type === 'AxesHelper' ||
          ancestor.isArrowHelper || ancestor.type === 'ArrowHelper' ||
          ancestor.isGridHelper || ancestor.type === 'GridHelper' ||
          ancestor.isTransformControlsRoot || ancestor.userData?.isGizmo ||
          ancestor.userData?.overlay || ancestor.userData?.helper) return
      ancestor = ancestor.parent
    }
    if (!obj.geometry || !(obj.isMesh || obj.isLine || obj.isPoints || obj.isSprite)) return
    // Diagnostic/tool overlays are intentionally outside the molecular framing,
    // matching Hull Audit, whose fit root contains only the audited hull mesh.
    if (!obj.geometry.boundingBox) obj.geometry.computeBoundingBox?.()
    if (!obj.geometry.boundingBox) return
    childBox.copy(obj.geometry.boundingBox).applyMatrix4(obj.matrixWorld)
    box.union(childBox)
  })
  return box
}

/** Arithmetic centroid of the design's nucleotide positions (world-pose geometry). */
export function multiViewDesignCentroid(state, fallback = new THREE.Vector3()) {
  // Assembly geometry is placed by per-instance transforms, so the active part's
  // nucleotide centroid is not the assembly centroid. Use rendered bounds there.
  if (state?.assemblyActive) return fallback.clone()
  const sum = new THREE.Vector3()
  let count = 0
  for (const nucleotide of state?.currentGeometry ?? []) {
    const position = nucleotide.axis_position ?? nucleotide.backbone_position ?? nucleotide.base_position
    if (!Array.isArray(position) || position.length < 3 || position.some(value => !Number.isFinite(Number(value)))) continue
    sum.add(new THREE.Vector3(Number(position[0]), Number(position[1]), Number(position[2])))
    count++
  }
  return count ? sum.divideScalar(count) : fallback.clone()
}

export function initMultiView({ document, scene, camera, renderer, canvas, store,
  controls, setRenderFn, resetRenderFn, setRepresentation, setColoringMode }) {
  const host = document?.getElementById('right-multi-view-body')
  if (!host) return null
  const viewportGrid = document.createElement('div')
  viewportGrid.className = 'mv-viewport-grid'
  canvas.parentElement?.append(viewportGrid)
  let count = 1, generation = 0
  let savedCamera = null
  let needsFit = false
  let syncingControls = false
  let savedControlsEnabled = true
  const panels = Array.from({ length: 4 }, (_, i) => ({
    representation: ['full', 'ballstick', 'surface', 'cylinders'][i],
    coloring: i === 1 ? 'cpk' : 'strand', renderScene: null,
    camera: new THREE.PerspectiveCamera(38, 1, 0.01, 10000), controls: null,
  }))
  const buttons = document.createElement('div'); buttons.className = 'mv-layout-buttons'
  for (const n of [2, 3, 4]) {
    const button = document.createElement('button')
    button.type = 'button'; button.className = 'mv-layout-btn'; button.dataset.count = String(n)
    button.title = `Split into ${n} synchronized panels`; button.setAttribute('aria-label', button.title)
    button.innerHTML = layoutIcon(n); button.addEventListener('click', () => activate(count === n ? 1 : n))
    buttons.append(button)
  }
  host.append(buttons)
  const hint = document.createElement('div'); hint.className = 'mv-sidebar-hint'; hint.textContent = 'Choose a layout, then configure each view in the viewport.'; host.append(hint)

  function renderControls() {
    for (const panel of panels) { panel.controls?.dispose?.(); panel.controls = null }
    viewportGrid.replaceChildren()
    for (let i = 0; i < count; i++) {
      const panel = document.createElement('div'); panel.className = 'mv-viewport-panel'; panel.dataset.panel = String(i + 1)
      panel.dataset.ready = panels[i].renderScene ? 'true' : 'false'
      const row = document.createElement('div'); row.className = 'mv-panel-head'
      const label = document.createElement('span'); label.className = 'mv-panel-label'; label.textContent = `${i + 1}`
      const repr = document.createElement('select'); repr.className = 'mv-representation'; repr.title = `Panel ${i + 1} representation`
      for (const [value, text] of MULTI_VIEW_REPRESENTATIONS) {
        const option = document.createElement('option'); option.value = value; option.textContent = text; repr.append(option)
      }
      repr.value = panels[i].representation
      const coloring = document.createElement('select'); coloring.className = 'mv-coloring'; coloring.title = `Panel ${i + 1} coloring`
      const fillColors = () => {
        coloring.replaceChildren()
        const modes = [...supportedColoringSet(repr.value, !!store.getState().assemblyActive)]
        if (!modes.length) {
          const option = document.createElement('option'); option.value = ''; option.textContent = 'Not available'; coloring.append(option)
        }
        for (const mode of modes) {
          const option = document.createElement('option'); option.value = mode; option.textContent = COLORING_LABELS[mode] ?? mode; coloring.append(option)
        }
        coloring.disabled = !modes.length
        coloring.value = modes.includes(panels[i].coloring) ? panels[i].coloring : (modes[0] ?? '')
        panels[i].coloring = coloring.value
      }
      fillColors()
      repr.addEventListener('change', () => { panels[i].representation = repr.value; fillColors(); rebuild() })
      coloring.addEventListener('change', () => { panels[i].coloring = coloring.value; rebuild() })
      const loading = document.createElement('span'); loading.className = 'mv-panel-loading'; loading.textContent = 'Loading…'
      row.append(label, repr, coloring, loading); panel.append(row); viewportGrid.append(panel)
      const panelControls = new OrbitControls(panels[i].camera, panel)
      panelControls.enableDamping = false
      panelControls.zoomToCursor = true
      panelControls.screenSpacePanning = true
      panels[i].camera.position.copy(camera.position)
      panels[i].camera.quaternion.copy(camera.quaternion)
      panels[i].camera.up.copy(camera.up)
      panels[i].camera.near = camera.near; panels[i].camera.far = camera.far
      panelControls.target.copy(controls.target)
      panelControls.addEventListener('change', () => syncPanelNavigation(i))
      panels[i].controls = panelControls
      for (const eventName of ['pointerdown', 'wheel']) {
        row.addEventListener(eventName, event => event.stopPropagation())
      }
    }
  }

  function syncPanelNavigation(sourceIndex) {
    if (syncingControls || count === 1) return
    syncingControls = true
    const source = panels[sourceIndex]
    camera.position.copy(source.camera.position)
    camera.quaternion.copy(source.camera.quaternion)
    camera.up.copy(source.camera.up)
    controls.target.copy(source.controls.target)
    for (let i = 0; i < count; i++) {
      if (i === sourceIndex) continue
      panels[i].camera.position.copy(source.camera.position)
      panels[i].camera.quaternion.copy(source.camera.quaternion)
      panels[i].camera.up.copy(source.camera.up)
      panels[i].controls.target.copy(source.controls.target)
      panels[i].controls.update()
    }
    syncingControls = false
  }

  async function rebuild() {
    const mine = ++generation
    for (const panel of panels) { disposeMultiScene(panel.renderScene); panel.renderScene = null }
    for (const element of viewportGrid.querySelectorAll('.mv-viewport-panel')) element.dataset.ready = 'false'
    for (let i = 0; i < count; i++) {
      const available = await setRepresentation(panels[i].representation)
      if (available === false) {
        panels[i].renderScene = new THREE.Scene()
        const element = viewportGrid.querySelector(`.mv-viewport-panel[data-panel="${i + 1}"]`)
        const loading = element?.querySelector('.mv-panel-loading')
        if (loading) loading.textContent = 'Unavailable'
        if (element) element.dataset.ready = 'unavailable'
        continue
      }
      if (panels[i].coloring) setColoringMode(panels[i].coloring)
      await Promise.resolve()
      if (mine !== generation || count === 1) return
      panels[i].renderScene = cloneMultiScene(scene)
      // Molecular Audit frames the inspected geometry once, then synchronizes
      // navigation. Do the same from the first completed panel.
      if (i === 0 && needsFit) {
        const box = multiViewContentBounds(panels[i].renderScene)
        if (!box.isEmpty()) {
          const boundsCenter = box.getCenter(new THREE.Vector3())
          const center = multiViewDesignCentroid(store.getState(), boundsCenter)
          const radius = Math.max(box.getSize(new THREE.Vector3()).length() / 2, 1)
          controls.target.copy(center)
          camera.position.copy(center).add(
            new THREE.Vector3(1, 0.75, 1).normalize().multiplyScalar(radius * 2.6),
          )
          camera.near = Math.max(0.01, radius / 100)
          camera.far = Math.max(1000, radius * 20)
          camera.updateProjectionMatrix(); controls.update()
          for (let panelIndex = 0; panelIndex < count; panelIndex++) {
            const panel = panels[panelIndex]
            panel.camera.position.copy(camera.position)
            panel.camera.quaternion.copy(camera.quaternion)
            panel.camera.up.copy(camera.up)
            panel.camera.near = camera.near; panel.camera.far = camera.far
            panel.controls?.target.copy(center); panel.controls?.update()
          }
          needsFit = false
        }
      }
      const element = viewportGrid.querySelector(`.mv-viewport-panel[data-panel="${i + 1}"]`)
      const loading = element?.querySelector('.mv-panel-loading')
      if (loading) loading.textContent = 'Loading…'
      if (element) element.dataset.ready = 'true'
    }
  }

  function renderMulti() {
    const width = canvas.clientWidth || canvas.parentElement?.clientWidth || 1
    const height = canvas.clientHeight || canvas.parentElement?.clientHeight || 1
    const ratio = renderer.getPixelRatio?.() ?? 1
    renderer.setScissorTest(true)
    for (const [i, r] of multiViewRects(count, width, height).entries()) {
      const panelCamera = panels[i].camera
      panelCamera.near = camera.near
      panelCamera.far = camera.far
      panelCamera.aspect = r.w / Math.max(r.h, 1)
      panelCamera.updateProjectionMatrix()
      renderer.setViewport(r.x * ratio, r.y * ratio, r.w * ratio, r.h * ratio)
      renderer.setScissor(r.x * ratio, r.y * ratio, r.w * ratio, r.h * ratio)
      renderer.render(panels[i].renderScene ?? scene, panelCamera)
    }
    renderer.setScissorTest(false)
  }

  async function activate(next) {
    const previousCount = count
    count = next
    viewportGrid.dataset.count = count > 1 ? String(count) : ''
    for (const button of buttons.children) {
      const active = Number(button.dataset.count) === count
      button.classList.toggle('active', active); button.setAttribute('aria-pressed', String(active))
    }
    renderControls()
    if (count === 1) {
      generation++; resetRenderFn(); renderer.setScissorTest(false)
      for (const panel of panels) { disposeMultiScene(panel.renderScene); panel.renderScene = null }
      const width = canvas.clientWidth || canvas.parentElement?.clientWidth || 1
      const height = canvas.clientHeight || canvas.parentElement?.clientHeight || 1
      const ratio = renderer.getPixelRatio?.() ?? 1
      renderer.setViewport(0, 0, width * ratio, height * ratio)
      if (savedCamera) {
        camera.position.fromArray(savedCamera.position)
        camera.up.fromArray(savedCamera.up)
        camera.fov = savedCamera.fov
        camera.near = savedCamera.near
        camera.far = savedCamera.far
        controls.target.fromArray(savedCamera.target)
        savedCamera = null
      }
      camera.aspect = width / height; camera.updateProjectionMatrix(); controls.update()
      controls.enabled = savedControlsEnabled
      await setRepresentation(panels[0].representation)
      if (panels[0].coloring) setColoringMode(panels[0].coloring)
    } else {
      const waits = []
      globalThis.window?.dispatchEvent(new CustomEvent('nadoc:comparison-mode', { detail: { mode: 'multi-view', waits } }))
      await Promise.all(waits)
      if (previousCount !== count) needsFit = true
      if (!savedCamera) {
        savedCamera = {
          position: camera.position.toArray(), target: controls.target.toArray(), up: camera.up.toArray(),
          fov: camera.fov, near: camera.near, far: camera.far,
        }
        savedControlsEnabled = controls.enabled
      }
      controls.enabled = false
      setRenderFn(renderMulti); rebuild()
    }
  }

  renderControls()
  const exclusiveMode = event => {
    if (event.detail?.mode !== 'multi-overlay' || count <= 1) return
    const closing = activate(1)
    event.detail?.waits?.push(closing)
  }
  globalThis.window?.addEventListener('nadoc:comparison-mode', exclusiveMode)
  return { activate, getCount: () => count, panels, dispose: () => {
    globalThis.window?.removeEventListener('nadoc:comparison-mode', exclusiveMode)
    activate(1); viewportGrid.remove()
  } }
}
