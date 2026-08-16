import * as THREE from 'three'
import { MULTI_VIEW_REPRESENTATIONS, cloneMultiScene, disposeMultiScene,
  multiViewContentBounds, multiViewDesignCentroid } from './multi_view.js'
import './multi_overlay.css'

export function overlayOffsets(count, separation, longestDimension) {
  const spacing = Math.max(0, separation) * Math.max(0, longestDimension)
  return Array.from({ length: count }, (_, i) => (i - (count - 1) / 2) * spacing)
}

export function designLongestDimension(state, fallbackSize = new THREE.Vector3(1, 1, 1)) {
  if (!state?.assemblyActive && state?.currentGeometry?.length) {
    const box = new THREE.Box3()
    for (const nucleotide of state.currentGeometry) {
      const position = nucleotide.axis_position ?? nucleotide.backbone_position ?? nucleotide.base_position
      if (!Array.isArray(position) || position.length < 3 || position.some(value => !Number.isFinite(Number(value)))) continue
      box.expandByPoint(new THREE.Vector3(Number(position[0]), Number(position[1]), Number(position[2])))
    }
    if (!box.isEmpty()) {
      const size = box.getSize(new THREE.Vector3())
      return Math.max(size.x, size.y, size.z, 1)
    }
  }
  return Math.max(fallbackSize.x, fallbackSize.y, fallbackSize.z, 1)
}

function setSceneOpacity(scene, opacity) {
  scene?.traverse?.(obj => {
    const materials = Array.isArray(obj.material) ? obj.material : [obj.material]
    for (const material of materials) {
      if (!material) continue
      material.userData.multiOverlayBaseOpacity ??= material.opacity
      material.transparent = true
      material.opacity = material.userData.multiOverlayBaseOpacity * opacity
      // Each representation is an independent compositing layer. Leaving depth
      // writes on would let an opaque first layer erase coincident later layers.
      material.depthWrite = false
      material.needsUpdate = true
    }
  })
}

export function initMultiOverlay({ document, scene, camera, renderer, canvas, controls,
  store, setRenderFn, resetRenderFn, setRepresentation }) {
  const host = document?.getElementById('right-multi-overlay-body')
  if (!host) return null
  let count = 0
  let generation = 0
  let separation = 0
  let longestDimension = 1
  let savedCamera = null
  const layers = Array.from({ length: 4 }, (_, i) => ({
    representation: ['full', 'surface', 'vdw', 'hull-prism'][i],
    opacity: i === 0 ? 1 : 0.65,
    renderScene: null,
  }))

  const buttons = document.createElement('div'); buttons.className = 'mo-count-buttons'
  for (const n of [1, 2, 3, 4]) {
    const button = document.createElement('button')
    button.type = 'button'; button.dataset.count = String(n); button.className = 'mo-count-btn'
    button.textContent = String(n); button.title = `Overlay ${n} representation${n === 1 ? '' : 's'}`
    button.addEventListener('click', () => activate(count === n ? 0 : n))
    buttons.append(button)
  }
  const separationRow = document.createElement('label'); separationRow.className = 'mo-separation-row'
  separationRow.innerHTML = '<span>Separation</span><output>0%</output>'
  const separationInput = document.createElement('input')
  separationInput.type = 'range'; separationInput.min = '0'; separationInput.max = '1'; separationInput.step = '0.01'; separationInput.value = '0'
  separationRow.insertBefore(separationInput, separationRow.lastElementChild)
  separationInput.addEventListener('input', () => {
    separation = Number(separationInput.value)
    separationRow.querySelector('output').textContent = `${Math.round(separation * 100)}%`
    positionLayers()
  })
  host.append(buttons, separationRow)

  const viewportControls = document.createElement('div')
  viewportControls.className = 'mo-viewport-controls'
  canvas.parentElement?.append(viewportControls)

  function renderControls() {
    viewportControls.replaceChildren()
    viewportControls.hidden = count === 0
    for (let i = 0; i < count; i++) {
      const row = document.createElement('div'); row.className = 'mo-layer-row'; row.dataset.layer = String(i + 1)
      const number = document.createElement('span'); number.className = 'mv-panel-label'; number.textContent = String(i + 1)
      const select = document.createElement('select'); select.className = 'mo-representation'; select.title = `Layer ${i + 1} representation`
      for (const [value, text] of MULTI_VIEW_REPRESENTATIONS) {
        const option = document.createElement('option'); option.value = value; option.textContent = text; select.append(option)
      }
      select.value = layers[i].representation
      select.addEventListener('change', () => { layers[i].representation = select.value; rebuild() })
      const opacity = document.createElement('input')
      opacity.type = 'range'; opacity.className = 'mo-opacity'; opacity.min = '0'; opacity.max = '1'; opacity.step = '0.01'; opacity.value = String(layers[i].opacity)
      opacity.title = `Layer ${i + 1} opacity`
      const output = document.createElement('output'); output.textContent = `${Math.round(layers[i].opacity * 100)}%`
      opacity.addEventListener('input', () => {
        layers[i].opacity = Number(opacity.value); output.textContent = `${Math.round(layers[i].opacity * 100)}%`
        setSceneOpacity(layers[i].renderScene, layers[i].opacity)
      })
      const loading = document.createElement('span'); loading.className = 'mo-loading'; loading.textContent = 'Loading…'
      row.append(number, select, opacity, output, loading); viewportControls.append(row)
    }
  }

  function positionLayers() {
    const offsets = overlayOffsets(count, separation, longestDimension)
    for (let i = 0; i < count; i++) if (layers[i].renderScene) layers[i].renderScene.position.x = offsets[i]
  }

  function fitInitial() {
    const first = layers[0].renderScene
    if (!first) return
    const box = multiViewContentBounds(first)
    if (box.isEmpty()) return
    const size = box.getSize(new THREE.Vector3())
    longestDimension = designLongestDimension(store.getState(), size)
    const center = multiViewDesignCentroid(store.getState(), box.getCenter(new THREE.Vector3()))
    const radius = Math.max(size.length() / 2, 1)
    controls.target.copy(center)
    camera.position.copy(center).add(new THREE.Vector3(1, 0.75, 1).normalize().multiplyScalar(radius * 2.6))
    camera.near = Math.max(0.01, radius / 100); camera.far = Math.max(1000, radius * 20)
    camera.updateProjectionMatrix(); controls.update()
    positionLayers()
  }

  async function rebuild() {
    const mine = ++generation
    for (const layer of layers) { disposeMultiScene(layer.renderScene); layer.renderScene = null }
    for (const row of viewportControls.children) row.dataset.ready = 'false'
    for (let i = 0; i < count; i++) {
      await setRepresentation(layers[i].representation)
      if (mine !== generation || count === 0) return
      layers[i].renderScene = cloneMultiScene(scene)
      setSceneOpacity(layers[i].renderScene, layers[i].opacity)
      viewportControls.children[i].dataset.ready = 'true'
    }
    fitInitial()
  }

  function renderOverlay() {
    const width = canvas.clientWidth || canvas.parentElement?.clientWidth || 1
    const height = canvas.clientHeight || canvas.parentElement?.clientHeight || 1
    const ratio = renderer.getPixelRatio?.() ?? 1
    renderer.setViewport(0, 0, width * ratio, height * ratio)
    renderer.setScissorTest(false)
    const oldAutoClear = renderer.autoClear
    for (let i = 0; i < count; i++) {
      renderer.autoClear = i === 0
      renderer.render(layers[i].renderScene ?? scene, camera)
    }
    renderer.autoClear = oldAutoClear
  }

  async function activate(next) {
    count = next
    for (const button of buttons.children) {
      const active = Number(button.dataset.count) === count
      button.classList.toggle('active', active); button.setAttribute('aria-pressed', String(active))
    }
    renderControls()
    if (!count) {
      generation++; resetRenderFn()
      for (const layer of layers) { disposeMultiScene(layer.renderScene); layer.renderScene = null }
      if (savedCamera) {
        camera.position.fromArray(savedCamera.position); camera.up.fromArray(savedCamera.up)
        camera.fov = savedCamera.fov; camera.near = savedCamera.near; camera.far = savedCamera.far
        controls.target.fromArray(savedCamera.target); savedCamera = null
        camera.updateProjectionMatrix(); controls.update()
      }
      await setRepresentation(layers[0].representation)
      return
    }
    const waits = []
    globalThis.window?.dispatchEvent(new CustomEvent('nadoc:comparison-mode', { detail: { mode: 'multi-overlay', waits } }))
    await Promise.all(waits)
    if (!savedCamera) savedCamera = {
      position: camera.position.toArray(), target: controls.target.toArray(), up: camera.up.toArray(),
      fov: camera.fov, near: camera.near, far: camera.far,
    }
    setRenderFn(renderOverlay); rebuild()
  }

  const exclusiveMode = event => {
    if (event.detail?.mode !== 'multi-view' || !count) return
    const closing = activate(0)
    event.detail?.waits?.push(closing)
  }
  globalThis.window?.addEventListener('nadoc:comparison-mode', exclusiveMode)
  renderControls()
  return { activate, getCount: () => count, layers, dispose: () => {
    globalThis.window?.removeEventListener('nadoc:comparison-mode', exclusiveMode)
    activate(0); viewportControls.remove()
  } }
}
