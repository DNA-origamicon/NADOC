import * as THREE from 'three'
import { initScene } from './runtime.js'
import { loadPreparedScene } from './prepared_scene.js'
import { initViewerPerformance } from '../perf/viewer_performance.js'
import { PACKAGE_LIMIT } from './package_container.js'

/** Standalone host: no editor store, API client, filesystem API, or backend calls. */
export function mountPreparedViewer({ canvas, status, title, fileInput, resetButton, modeInput }) {
  const runtime = initScene(canvas)
  runtime.scene.clear()
  let current = null, disposed = false, generation = 0
  let state = { currentDesign: null, currentGeometry: null, assemblyActive: false }
  const performanceApi = initViewerPerformance({ ...runtime, store: { getState: () => state },
    getDetailLevel: () => current?.data.view?.detail_level ?? null,
    getFixtureIdentity: () => ({ sha256: current?.data.sourceHash ?? current?.packageHash,
      kind: current?.data.sourceHash ? 'JSON design/assembly document; not simulation content' : 'Prepared scene package bytes',
      package_sha256: current?.packageHash }) })
  function resetCamera() {
    if (!current || performanceApi.busy) return
    const pose = current.data.camera
    runtime.switchOrbitMode(pose.orbitMode)
    modeInput.value = pose.orbitMode
    runtime.camera.position.fromArray(pose.position); runtime.controls.target.fromArray(pose.target)
    runtime.camera.up.fromArray(pose.up); runtime.camera.fov = pose.fov
    runtime.camera.near = pose.near ?? 0.1; runtime.camera.far = pose.far ?? 2000
    runtime.camera.updateProjectionMatrix(); runtime.controls.update()
  }
  const remotePosition = new THREE.Vector3(), remoteTarget = new THREE.Vector3(), remoteUp = new THREE.Vector3()
  function applyCamera(pose, blend = 1) {
    if (!current || performanceApi.busy) return
    // A one-shot jump also clears residual damping from the guest's last gesture.
    if (blend === 1 || modeInput.value !== pose.orbitMode) { runtime.switchOrbitMode(pose.orbitMode); modeInput.value = pose.orbitMode }
    runtime.camera.position.lerp(remotePosition.fromArray(pose.position), blend)
    runtime.controls.target.lerp(remoteTarget.fromArray(pose.target), blend)
    runtime.camera.up.lerp(remoteUp.fromArray(pose.up), blend)
    if (runtime.camera.up.lengthSq() < 1e-10) runtime.camera.up.copy(remoteUp)
    runtime.camera.up.normalize()
    const fov = runtime.camera.fov + (pose.fov - runtime.camera.fov) * blend
    if (runtime.camera.fov !== fov || runtime.camera.near !== pose.near || runtime.camera.far !== pose.far) {
      runtime.camera.fov = fov; runtime.camera.near = pose.near; runtime.camera.far = pose.far; runtime.camera.updateProjectionMatrix()
    }
    runtime.controls.update()
  }
  async function loadFile(file) {
    const ticket = ++generation
    if (!file || disposed) return
    status.textContent = 'Opening prepared view…'
    try {
      if (file.size > PACKAGE_LIMIT) throw new Error('Viewer packages are limited to 512 MB')
      const next = await loadPreparedScene(await file.arrayBuffer())
      if (disposed || ticket !== generation) { next.dispose(); return }
      performanceApi.stop()
      current?.dispose()
      runtime.scene.clear()
      current = next
      const view = next.data.view ?? {}
      state = { currentDesign: { id: next.packageHash, metadata: { name: next.data.title } }, currentGeometry: next.data.root,
        currentAssembly: view.assembly ? { id: next.packageHash } : null, assemblyActive: !!view.assembly,
        atomisticMode: view.atomistic ?? 'off', surfaceMode: view.surface ?? 'off', coloringMode: view.coloring ?? 'strand' }
      runtime.scene.add(next.scene)
      runtime.renderer.toneMapping = next.data.render.toneMapping
      runtime.renderer.toneMappingExposure = next.data.render.toneMappingExposure
      runtime.renderer.outputColorSpace = next.data.render.outputColorSpace
      runtime.renderer.setClearColor(next.data.render.clearColor, next.data.render.clearAlpha)
      canvas.parentElement.style.backgroundColor = next.data.background
      runtime.setNavScaleProvider(() => next.data.navigation)
      resetCamera()
      title.textContent = String(next.data.title || file.name)
      status.textContent = 'Static snapshot · Orbit, pan and zoom · Double-click to center'
      resetButton.disabled = false; modeInput.disabled = false
      return true
    } catch (error) {
      if (!disposed && ticket === generation) status.textContent = `Could not open view: ${error.message}`
      return false
    }
  }
  const choose = () => { loadFile(fileInput.files[0]); fileInput.value = '' }
  const changeMode = () => { if (!performanceApi.busy) runtime.switchOrbitMode(modeInput.value) }
  const drag = event => event.preventDefault()
  const drop = event => { event.preventDefault(); loadFile(event.dataTransfer.files[0]) }
  const ray = new THREE.Raycaster(), pointer = new THREE.Vector2()
  function center(event) {
    if (!current || performanceApi.busy) return
    const rect = canvas.getBoundingClientRect()
    pointer.set(2 * (event.clientX - rect.left) / rect.width - 1, 1 - 2 * (event.clientY - rect.top) / rect.height)
    ray.setFromCamera(pointer, runtime.camera)
    const hit = ray.intersectObject(current.scene, true)[0]
    if (hit) { runtime.controls.target.copy(hit.point); runtime.controls.update() }
  }
  fileInput.addEventListener('change', choose)
  resetButton.addEventListener('click', resetCamera)
  modeInput.addEventListener('change', changeMode)
  canvas.addEventListener('dragover', drag); canvas.addEventListener('drop', drop)
  canvas.addEventListener('dblclick', center)
  return { loadFile, runtime, performanceApi, applyCamera, captureCamera: () => ({ ...runtime.captureCurrentCamera(), near: runtime.camera.near, far: runtime.camera.far }), get current() { return current }, dispose() {
    if (disposed) return
    disposed = true; generation++
    performanceApi.dispose()
    current?.dispose(); current = null
    fileInput.removeEventListener('change', choose); resetButton.removeEventListener('click', resetCamera)
    modeInput.removeEventListener('change', changeMode)
    canvas.removeEventListener('dragover', drag); canvas.removeEventListener('drop', drop); canvas.removeEventListener('dblclick', center)
    runtime.dispose()
  } }
}
