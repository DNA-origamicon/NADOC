import { prepareScene } from './prepared_scene.js'
import { axisSegments } from '../scene/multiscale_nav.js'
import { navigationDesign } from '../scene/reference_navigation.js'
import { showToast } from '../ui/toast.js'

/** Thin editor host. Export is explicit and runs outside the render loop. */
export function initPreparedExport({ scene, camera, renderer, store, captureCurrentCamera, getDetailLevel = () => null, isStandardRender = () => true, document: doc = document }) {
  const button = doc.getElementById('menu-file-export-viewer')
  let busy = false
  async function exportView() {
    if (busy) return
    const state = store.getState()
    if (!state.currentDesign && !state.currentAssembly) throw new Error('Open a design before exporting a viewer package')
    if (!isStandardRender() || (camera.layers && camera.layers.mask !== 1)) throw new Error('Return to the normal 3D view before exporting a prepared snapshot')
    if (state.cadnanoActive || state.unfoldActive) throw new Error('Return to the 3D view before exporting')
    busy = true
    try {
      const title = state.currentAssembly?.name ?? state.currentDesign?.metadata?.name ?? 'Prepared view'
      const background = '#0d1117'
      const bytes = new TextEncoder().encode(JSON.stringify(state.assemblyActive ? state.currentAssembly : state.currentDesign))
      const digest = await crypto.subtle.digest('SHA-256', bytes)
      const sourceHash = [...new Uint8Array(digest)].map(v => v.toString(16).padStart(2, '0')).join('')
      if (store.getState().currentDesign !== state.currentDesign || store.getState().currentAssembly !== state.currentAssembly) throw new Error('The design changed during export; retry when idle')
      if (!isStandardRender() || store.getState().assemblyActive !== state.assemblyActive) throw new Error('The view changed during export; retry when idle')
      const pose = { ...captureCurrentCamera(), near: camera.near, far: camera.far }
      const view = { assembly: !!state.assemblyActive, detail_level: getDetailLevel(), atomistic: state.atomisticMode ?? 'off', surface: state.surfaceMode ?? 'off', coloring: state.coloringMode ?? 'strand' }
      return { buffer: prepareScene({ scene, camera: pose, renderer, navigation: axisSegments(navigationDesign(state)), title, background, sourceHash, view }), title }
    } finally { busy = false }
  }
  async function download() {
    button.disabled = true
    try {
      const result = await exportView()
      if (!result) return
      const url = URL.createObjectURL(new Blob([result.buffer], { type: 'application/octet-stream' }))
      const a = doc.createElement('a'); a.href = url
      a.download = `${result.title.replace(/[^a-z0-9_-]/gi, '_')}.nadocview`
      a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000)
      showToast('Prepared view exported. Open it in the standalone viewer; this version supports static orbiting.')
    } catch (error) { showToast(error.message, { severity: 'error', duration: 10000 }) }
    finally { button.disabled = false }
  }
  button?.addEventListener('click', download)
  return { exportView, dispose: () => button?.removeEventListener('click', download) }
}
