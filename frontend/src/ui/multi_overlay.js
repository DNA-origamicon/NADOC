import * as THREE from 'three'
import { COLORING_LABELS, supportedColoringSet } from '../scene/coloring_modes.js'
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

export function designGeometryBounds(state) {
  const box = new THREE.Box3()
  if (state?.assemblyActive) return box
  for (const nucleotide of state?.currentGeometry ?? []) {
    const position = nucleotide.axis_position ?? nucleotide.backbone_position ?? nucleotide.base_position
    if (!Array.isArray(position) || position.length < 3 || position.some(value => !Number.isFinite(Number(value)))) continue
    box.expandByPoint(new THREE.Vector3(Number(position[0]), Number(position[1]), Number(position[2])))
  }
  return box
}

/** Painter's order for separately rendered transparent scenes: farthest first. */
export function overlayRenderOrder(layers, count, camera) {
  camera.updateMatrixWorld?.(true)
  const world = new THREE.Vector3()
  return layers.slice(0, count).map((layer, index) => {
    const scene = layer.renderScene
    scene?.updateMatrixWorld?.(true)
    if (scene) scene.getWorldPosition(world)
    else world.set(0, 0, 0)
    const cameraZ = world.clone().applyMatrix4(camera.matrixWorldInverse).z
    return { index, cameraZ }
  }).sort((a, b) => a.cameraZ - b.cameraZ || a.index - b.index)
    .map(entry => entry.index)
}

function setSceneOpacity(scene, opacity) {
  scene?.traverse?.(obj => {
    const materials = Array.isArray(obj.material) ? obj.material : [obj.material]
    for (const material of materials) {
      if (!material) continue
      material.userData.multiOverlayBaseOpacity ??= material.opacity
      material.transparent = true
      material.opacity = material.userData.multiOverlayBaseOpacity * opacity
      // Preserve depth within a representation so separate InstancedMeshes
      // (notably mrDNA beads + rods) do not painter-sort through one another as
      // the camera orbits. renderOverlay clears depth between isolated layers.
      material.depthWrite = true
      material.needsUpdate = true
    }
  })
}

export function initMultiOverlay({ document, scene, camera, renderer, canvas, controls,
  store, setRenderFn, resetRenderFn, setRepresentation, setColoringMode }) {
  const host = document?.getElementById('right-multi-overlay-body')
  if (!host) return null
  let count = 0
  let generation = 0
  let separation = 0
  let longestDimension = 1
  let savedCamera = null
  const layers = Array.from({ length: 4 }, (_, i) => ({
    representation: ['hull-prism', 'cylinders', 'mrdna-fine', 'full'][i],
    coloring: 'strand',
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
      const coloring = document.createElement('select'); coloring.className = 'mo-coloring'; coloring.title = `Layer ${i + 1} coloring`
      const fillColors = () => {
        coloring.replaceChildren()
        const modes = [...supportedColoringSet(select.value, !!store.getState().assemblyActive)]
        if (!modes.length) {
          const option = document.createElement('option'); option.value = ''; option.textContent = 'Not available'; coloring.append(option)
        }
        for (const mode of modes) {
          const option = document.createElement('option'); option.value = mode; option.textContent = COLORING_LABELS[mode] ?? mode; coloring.append(option)
        }
        coloring.disabled = !modes.length
        coloring.value = modes.includes(layers[i].coloring) ? layers[i].coloring : (modes[0] ?? '')
        layers[i].coloring = coloring.value
      }
      fillColors()
      select.addEventListener('change', () => {
        layers[i].representation = select.value; fillColors(); rebuild()
      })
      coloring.addEventListener('change', () => { layers[i].coloring = coloring.value; rebuild() })
      const opacity = document.createElement('input')
      opacity.type = 'range'; opacity.className = 'mo-opacity'; opacity.min = '0'; opacity.max = '1'; opacity.step = '0.01'; opacity.value = String(layers[i].opacity)
      opacity.title = `Layer ${i + 1} opacity`
      const output = document.createElement('output'); output.textContent = `${Math.round(layers[i].opacity * 100)}%`
      opacity.addEventListener('input', () => {
        layers[i].opacity = Number(opacity.value); output.textContent = `${Math.round(layers[i].opacity * 100)}%`
        setSceneOpacity(layers[i].renderScene, layers[i].opacity)
      })
      const loading = document.createElement('span'); loading.className = 'mo-loading'; loading.textContent = 'Loading…'
      row.append(number, select, coloring, opacity, output, loading); viewportControls.append(row)
    }
  }

  function positionLayers() {
    const offsets = overlayOffsets(count, separation, longestDimension)
    for (let i = 0; i < count; i++) if (layers[i].renderScene) layers[i].renderScene.position.x = offsets[i]
  }

  function fitInitial() {
    const first = layers[0].renderScene
    if (!first) return
    // Frame the design itself, not layer 1. Otherwise changing the first layer
    // (e.g. Hull → mrDNA Fine) changes camera distance and makes identical beads
    // appear to have different radii across overlay combinations.
    const designBox = designGeometryBounds(store.getState())
    const box = designBox.isEmpty() ? multiViewContentBounds(first) : designBox
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
      const available = await setRepresentation(layers[i].representation)
      if (available === false) {
        layers[i].renderScene = new THREE.Scene()
        const row = viewportControls.children[i]
        const loading = row?.querySelector('.mo-loading')
        if (loading) loading.textContent = 'Unavailable'
        if (row) row.dataset.ready = 'unavailable'
        continue
      }
      if (layers[i].coloring) setColoringMode(layers[i].coloring)
      if (mine !== generation || count === 0) return
      layers[i].renderScene = cloneMultiScene(scene)
      setSceneOpacity(layers[i].renderScene, layers[i].opacity)
      const loading = viewportControls.children[i]?.querySelector('.mo-loading')
      if (loading) loading.textContent = 'Loading…'
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
    const order = overlayRenderOrder(layers, count, camera)
    for (let drawIndex = 0; drawIndex < order.length; drawIndex++) {
      renderer.autoClear = drawIndex === 0
      if (drawIndex > 0) renderer.clearDepth?.()
      const layerIndex = order[drawIndex]
      renderer.render(layers[layerIndex].renderScene ?? scene, camera)
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
      if (layers[0].coloring) setColoringMode(layers[0].coloring)
      return
    }
    const waits = []
    globalThis.window?.dispatchEvent(new CustomEvent('nadoc:comparison-mode', { detail: { mode: 'multi-overlay', waits } }))
    await Promise.all(waits)
    if (!savedCamera) savedCamera = {
      position: camera.position.toArray(), target: controls.target.toArray(), up: camera.up.toArray(),
      fov: camera.fov, near: camera.near, far: camera.far,
    }
    setRenderFn(renderOverlay); await rebuild()
  }

  const exclusiveMode = event => {
    if (event.detail?.mode !== 'multi-view' || !count) return
    const closing = activate(0)
    event.detail?.waits?.push(closing)
  }
  globalThis.window?.addEventListener('nadoc:comparison-mode', exclusiveMode)
  renderControls()
  async function configure({ count: nextCount = count || 1, representations = [], colorings = [], opacities = [], separation: nextSeparation = separation } = {}) {
    for (let i = 0; i < layers.length; i++) {
      if (representations[i]) layers[i].representation = representations[i]
      if (colorings[i] !== undefined) layers[i].coloring = colorings[i]
      if (Number.isFinite(Number(opacities[i]))) layers[i].opacity = Math.min(1, Math.max(0, Number(opacities[i])))
    }
    separation = Math.min(1, Math.max(0, Number(nextSeparation) || 0))
    separationInput.value = String(separation)
    separationRow.querySelector('output').textContent = `${Math.round(separation * 100)}%`
    await activate(Math.min(4, Math.max(0, Number(nextCount) || 0)))
    positionLayers()
    return layers.slice(0, count).map(layer => ({
      representation: layer.representation, coloring: layer.coloring, opacity: layer.opacity,
    }))
  }

  return { activate, configure, getCount: () => count, layers,
    renderOrder: () => overlayRenderOrder(layers, count, camera),
    diagnostics: () => layers.slice(0, count).map(layer => {
      const beads = []
      const rods = []
      const oxdna = { backbone: [], base: [], 'base-connector': [], 'backbone-connector': [] }
      const oxdnaColors = { backbone: new Set(), base: new Set(), 'base-connector': new Set(), 'backbone-connector': new Set() }
      let geometryHash = 2166136261
      const hashMatrix = matrix => {
        for (const value of matrix.elements) {
          geometryHash ^= Math.round(value * 1e5)
          geometryHash = Math.imul(geometryHash, 16777619) >>> 0
        }
      }
      layer.renderScene?.traverse?.(object => {
        const oxPrimitive = object.userData?.oxdnaPrimitive
        if (object.isInstancedMesh && oxPrimitive && oxdna[oxPrimitive]) {
          const matrix = new THREE.Matrix4(), position = new THREE.Vector3(), quaternion = new THREE.Quaternion(), scale = new THREE.Vector3()
          for (let i = 0; i < object.count; i++) {
            object.getMatrixAt(i, matrix); matrix.decompose(position, quaternion, scale)
            oxdna[oxPrimitive].push(scale.toArray())
            if (object.instanceColor) {
              const color = new THREE.Color(); object.getColorAt(i, color)
              oxdnaColors[oxPrimitive].add(color.getHex())
            }
          }
        }
        const material = Array.isArray(object.material) ? object.material[0] : object.material
        const isMrdnaBlue = material?.color?.getHex?.() === 0x58a6ff
        const isMrdnaRod = material?.color?.getHex?.() === 0xcdd8ee
        if (!object.isInstancedMesh || (!object.userData?.mrdnaInputResolution && !isMrdnaBlue && !isMrdnaRod)) return
        const matrix = new THREE.Matrix4(), position = new THREE.Vector3(), quaternion = new THREE.Quaternion(), scale = new THREE.Vector3()
        for (let i = 0; i < object.count; i++) {
          object.getMatrixAt(i, matrix); matrix.decompose(position, quaternion, scale)
          hashMatrix(matrix)
          if (isMrdnaRod) rods.push(Math.min(scale.x, scale.z))
          else beads.push(scale.x)
        }
      })
      return {
        representation: layer.representation,
        beadCount: beads.length,
        minBeadRadius: beads.length ? Math.min(...beads) : null,
        maxBeadRadius: beads.length ? Math.max(...beads) : null,
        rodCount: rods.length,
        minRodRadius: rods.length ? Math.min(...rods) : null,
        maxRodRadius: rods.length ? Math.max(...rods) : null,
        oxdna,
        oxdnaColors: Object.fromEntries(Object.entries(oxdnaColors).map(([key, values]) => [key, [...values]])),
        geometryHash,
      }
    }),
    dispose: () => {
    globalThis.window?.removeEventListener('nadoc:comparison-mode', exclusiveMode)
    activate(0); viewportControls.remove()
  } }
}
