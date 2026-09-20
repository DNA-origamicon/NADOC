import * as THREE from 'three'
import { recordProcess } from './process_log.js'
import { createViewerCapture } from './viewer_capture.js'
import { formatViewerMetrics } from './viewer_metrics.js'
import { connectViewerTestBridge } from './viewer_test_bridge.js'
import { snapshotViewer } from './viewer_snapshot.js'
import { openViewerFile } from './viewer_file_open.js'

let installed = null
export function getViewerPerformance() { return installed }

async function digest(value) {
  if (!globalThis.crypto?.subtle) return null
  const bytes = new TextEncoder().encode(JSON.stringify(value))
  const hash = await crypto.subtle.digest('SHA-256', bytes)
  return [...new Uint8Array(hash)].map(byte => byte.toString(16).padStart(2, '0')).join('')
}

/** Editor adapter. This observes live geometry; it never mutates design or job data. */
export function initViewerPerformance({ renderer, camera, controls, store, addFrameCallback, removeFrameCallback, captureCurrentCamera, getDetailLevel = () => null, getFileOpen = () => null }) {
  installed?.dispose()
  let preparing = false
  let disposed = false
  let watchdog = null
  let saved = null
  let started = 0
  let mode = null
  let key = null
  let initialState = null
  let viewport = null
  let latest = null
  let orbitPose = null
  let orbitFixture = null
  let pathPose = null
  let initialView = null
  const offset = new THREE.Vector3()
  const axis = new THREE.Vector3()
  const listeners = new Set()
  let disconnectBridge = () => {}
  const canvas = renderer.domElement
  const viewSize = () => [canvas.width, canvas.height, canvas.clientWidth, canvas.clientHeight, renderer.getPixelRatio()]
  const viewSettings = state => ({ assembly: !!state.assemblyActive, detail_level: getDetailLevel(),
    atomistic: state.atomisticMode, surface: state.surfaceMode, coloring: state.coloringMode })
  const announce = () => { for (const listener of listeners) listener() }
  function restore() {
    removeFrameCallback(frame)
    clearTimeout(watchdog)
    if (!saved) return
    if (mode === 'orbit') {
      camera.position.copy(saved.position)
      camera.up.copy(saved.up)
      camera.quaternion.copy(saved.quaternion)
      controls.target.copy(saved.target)
      controls.enabled = saved.enabled
      controls.update()
    }
    saved = null
  }
  const capture = createViewerCapture({ finish(record) {
    restore()
    latest = record
    const text = formatViewerMetrics(record)
    recordProcess(key, {
      label: `${record.variant} · ${record.scenario}`,
      kind: 'Viewer performance', status: record.valid ? 'Completed' : 'Invalid',
      durationMs: record.elapsed_ms, detail: text, viewerMetrics: record,
    })
    console.info(text)
    announce()
  } })
  function frame() {
    if (!capture.active) return
    if (document.hidden) { capture.stop('Tab became hidden'); return }
    const state = store.getState()
    if (state.currentDesign !== initialState.currentDesign || state.currentAssembly !== initialState.currentAssembly ||
        state.assemblyActive !== initialState.assemblyActive) {
      capture.stop('Design or assembly changed'); return
    }
    if (JSON.stringify(viewSize()) !== JSON.stringify(viewport)) { capture.stop('Viewport changed'); return }
    if (JSON.stringify(viewSettings(state)) !== JSON.stringify(initialView)) { capture.stop('Representation changed'); return }
    const time = performance.now() - started
    if (mode === 'orbit') {
      camera.position.copy(pathPose.position).sub(pathPose.target).applyAxisAngle(axis, time / 20000 * Math.PI * 2).add(pathPose.target)
      camera.up.copy(pathPose.up)
      camera.lookAt(pathPose.target)
    }
    // Scene callbacks run before rendering, so these are the PREVIOUS render's
    // Three.js counters, not an aggregate across postprocessing/multi-view passes.
    const { render, memory } = renderer.info
    capture.frame({ calls: render.calls, triangles: render.triangles, points: render.points,
      lines: render.lines, geometries: memory.geometries, textures: memory.textures },
    performance.memory?.usedJSHeapSize ?? null)
  }
  function invalidate(event) { capture.stop(event.type === 'webglcontextlost' ? 'WebGL context lost' : 'Tab became hidden') }
  function visibility() { if (document.hidden) invalidate({ type: 'visibilitychange' }) }
  document.addEventListener('visibilitychange', visibility)
  canvas.addEventListener('webglcontextlost', invalidate)
  const api = {
    defaultVariant: typeof __NADOC_BUILD_INFO__ !== 'undefined' && __NADOC_BUILD_INFO__.branch === 'feature/standalone-viewer-presentations' ? 'B' : 'A',
    async start({ scenario = 'orbit', durationMs = 20000, variant = 'A', cache = 'warm' } = {}) {
      if (disposed || preparing || capture.active) throw new Error('Viewer capture is unavailable or already running')
      if (!['orbit', 'freeform'].includes(scenario) || !['A', 'B'].includes(variant)) throw new Error('Invalid capture settings')
      if (!Number.isFinite(durationMs) || durationMs < 1000 || durationMs > 60000) throw new Error('Duration must be 1–60 seconds')
      if (document.hidden || renderer.xr?.isPresenting) throw new Error('Use a visible desktop viewer tab')
      initialState = store.getState()
      const design = initialState.assemblyActive ? initialState.currentAssembly : initialState.currentDesign
      if (!design) throw new Error('Load a part or assembly first')
      preparing = true
      announce()
      try {
        // Hash outside the measured interval; never copy scientific contents into logs.
        const fixtureHash = await digest(design)
        if (disposed) throw new Error('Viewer capture disposed')
        const current = store.getState()
        if (document.hidden || current.currentDesign !== initialState.currentDesign || current.currentAssembly !== initialState.currentAssembly ||
            current.assemblyActive !== initialState.assemblyActive) throw new Error('Viewer changed during preparation; retry when idle')
        mode = scenario
        saved = { position: camera.position.clone(), target: controls.target.clone(), up: camera.up.clone(),
          quaternion: camera.quaternion.clone(), enabled: controls.enabled }
        if (scenario === 'orbit') {
          // Reuse the same starting pose within this tab for repeatable A/B repeats.
          // Reset pose explicitly after framing a new benchmark viewpoint.
          if (orbitFixture !== design) { orbitPose = null; orbitFixture = design }
          orbitPose ??= captureCurrentCamera()
          camera.position.fromArray(orbitPose.position)
          camera.up.fromArray(orbitPose.up)
          controls.target.fromArray(orbitPose.target)
          pathPose = { position: camera.position.clone(), up: camera.up.clone(), target: controls.target.clone() }
          controls.enabled = false
          axis.copy(camera.up).normalize()
          offset.copy(camera.position).sub(controls.target)
          if (offset.lengthSq() === 0) throw new Error('Camera must be away from its orbit target')
        }
        viewport = viewSize()
        initialView = viewSettings(current)
        const gl = renderer.getContext()
        let gpu = null
        try {
          const ext = gl.getExtension('WEBGL_debug_renderer_info')
          if (ext) gpu = gl.getParameter(ext.UNMASKED_RENDERER_WEBGL)
        } catch { /* Browser privacy settings can suppress GPU metadata. */ }
        const record = {
          schema: 1, instrumentation: 'viewer-frame-capture-v1',
          run_id: globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`,
          captured_at: new Date().toISOString(), variant, scenario,
          duration_requested_ms: durationMs, fixture_sha256: fixtureHash,
          fixture_hash_kind: 'JSON design/assembly document; not simulation content',
          build: typeof __NADOC_BUILD_INFO__ === 'undefined' ? null : __NADOC_BUILD_INFO__,
          build_mode: import.meta.env.DEV ? 'development' : 'production',
          environment: { browser: navigator.userAgent, gpu, viewport, refresh_hz: null },
          view: { camera: captureCurrentCamera(), ...initialView },
          cache, measurement: 'render-loop frame intervals; previous render-pass counts; not GPU duration',
          simulation_content_verified: false,
          load_ms: null, selection_latency_ms: null,
        }
        started = performance.now()
        key = `viewer-perf:${record.run_id}`
        recordProcess(key, { label: `${variant} · ${scenario}`, kind: 'Viewer performance' })
        capture.start(record)
        addFrameCallback(frame)
        watchdog = setTimeout(() => capture.stop('Capture timed out; render loop may have stalled'), durationMs + 5000)
      } catch (error) { restore(); throw error }
      finally { preparing = false; announce() }
    },
    stop() { capture.stop('Stopped by user') },
    resetPose() { if (!capture.active && !preparing) orbitPose = null },
    get busy() { return preparing || capture.active },
    get latest() { return latest },
    subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn) },
    dispose() {
      disposed = true
      disconnectBridge()
      capture.stop('Viewer disposed')
      restore()
      document.removeEventListener('visibilitychange', visibility)
      canvas.removeEventListener('webglcontextlost', invalidate)
      listeners.clear()
      if (installed === api) installed = null
    },
  }
  installed = api
  const inspect = () => {
    const state = store.getState()
    const design = state.assemblyActive ? state.currentAssembly : state.currentDesign
    return { build: typeof __NADOC_BUILD_INFO__ === 'undefined' ? null : __NADOC_BUILD_INFO__,
      default_variant: api.defaultVariant, visible: !document.hidden, busy: api.busy,
      url: location.href,
      design: { id: design?.id ?? null, name: design?.metadata?.name ?? null },
      camera: captureCurrentCamera(), viewport: viewSize(), settings: viewSettings(state),
      controls_enabled: controls.enabled, process_log_open: !!document.querySelector('#process-log'),
      render_counts: { ...renderer.info.render }, resources: { ...renderer.info.memory },
      browser: navigator.userAgent }
  }
  disconnectBridge = connectViewerTestBridge({ hot: import.meta.hot, api, inspect,
    openFile: path => openViewerFile({ path, getFileOpen }),
    snapshot: () => snapshotViewer({ canvas, addFrameCallback, removeFrameCallback, inspect }) })
  return api
}
