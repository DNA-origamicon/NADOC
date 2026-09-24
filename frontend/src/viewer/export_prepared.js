import { capturePresentationSelection } from '../scene/presentation_selection.js'
import { captureSceneAnnotations } from '../scene/annotation_overlay.js'
import { captureViewTools } from './shared_view_tools.js'
import { preparedImpostorSpec } from '../scene/impostor_material.js'
import { createSharedViewMotion } from './shared_view_motion.js'
import { prepareScene } from './prepared_scene.js'
import { axisSegments } from '../scene/multiscale_nav.js'
import { navigationDesign } from '../scene/reference_navigation.js'
import { showToast } from '../ui/toast.js'

/** Thin editor host. Export is explicit and runs outside the render loop. */
export function initPreparedExport({ scene, camera, renderer, controls, canvas, store, captureCurrentCamera, getPresentationView = () => null, getDetailLevel = () => null, getVisualization = () => null, isStandardRender = () => true, document: doc = document }) {
  const button = doc.getElementById('menu-file-export-viewer')
  let busy = false, motionOptions = {}
  const motion = createSharedViewMotion({ getView: () => {
    if (motionOptions.canMove?.() === false) throw new Error('Select the currently shared job before viewing a guest perspective')
    const source = captureView(motionOptions.presentation)
    if (!source.controls) throw new Error('Return to the 3D viewer to open this perspective')
    const state = store.getState()
    return { ...source, canvas, context: `${state.currentDesign?.id}:${state.currentAssembly?.id}:${state.assemblyActive}:${source.pane}` }
  } })
  function captureView(presentation = true) {
    const alternate = presentation ? getPresentationView() : null
    if ((!alternate && !isStandardRender()) || (camera.layers && camera.layers.mask !== 1)) throw new Error('Return to the normal 3D view before exporting a prepared snapshot')
    const state = store.getState()
    if (state.cadnanoActive || state.unfoldActive) throw new Error('Return to the 3D view before exporting')
    return { controls: alternate?.controls ?? controls, scene: alternate?.scene ?? scene, camera: alternate?.camera ?? camera, pose: alternate?.pose ?? captureCurrentCamera(), view: { ...alternate?.view, viewTools: captureViewTools(doc), visualization: alternate ? null : getVisualization(), annotations: captureSceneAnnotations(alternate?.scene ?? scene), selection: capturePresentationSelection(alternate?.scene ?? scene) }, pane: alternate?.pane }
  }
  async function exportView({ presentation = false } = {}) {
    if (busy) return
    const state = store.getState()
    if (!state.currentDesign && !state.currentAssembly) throw new Error('Open a design before exporting a viewer package')
    const source = captureView(presentation)
    busy = true
    try {
      const title = state.currentAssembly?.name ?? state.currentDesign?.metadata?.name ?? 'Prepared view'
      const background = '#0d1117'
      const bytes = new TextEncoder().encode(JSON.stringify(state.assemblyActive ? state.currentAssembly : state.currentDesign))
      const digest = await crypto.subtle.digest('SHA-256', bytes)
      const sourceHash = [...new Uint8Array(digest)].map(v => v.toString(16).padStart(2, '0')).join('')
      if (store.getState().currentDesign !== state.currentDesign || store.getState().currentAssembly !== state.currentAssembly) throw new Error('The design changed during export; retry when idle')
      if (captureView(presentation).scene !== source.scene || store.getState().assemblyActive !== state.assemblyActive) throw new Error('The view changed during export; retry when idle')
      const pose = { ...source.pose, near: source.camera.near, far: source.camera.far }
      const view = { assembly: !!state.assemblyActive, detail_level: getDetailLevel(), atomistic: state.atomisticMode ?? 'off', surface: state.surfaceMode ?? 'off', coloring: state.coloringMode ?? 'strand', ...source.view }
      let requiresWideLineViewer = false, requiresImpostorViewer = false
      source.scene.traverseVisible(object => {
        if (object.isLineSegments2) requiresWideLineViewer = true
        if ((Array.isArray(object.material) ? object.material : [object.material]).some(preparedImpostorSpec)) requiresImpostorViewer = true
      })
      return { requiresVisualizationLabelViewer: !!view.visualization, requiresSelectionViewer: !!view.selection, requiresAnnotationsViewer: !!view.annotations?.length, requiresWideLineViewer, requiresImpostorViewer, requiresViewToolsViewer: Object.values(view.viewTools ?? {}).some(value => value === true), buffer: prepareScene({ scene: source.scene, camera: pose, renderer, navigation: axisSegments(navigationDesign(state)), title, background, sourceHash, view }), title, requiresSectionViewer: !!renderer.localClippingEnabled }
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
  async function sourceHash() {
    const state = store.getState(), value = state.assemblyActive ? state.currentAssembly : state.currentDesign
    const hash = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(JSON.stringify(value)))
    return [...new Uint8Array(hash)].map(v => v.toString(16).padStart(2, '0')).join('')
  }
  return { exportView, captureView, sourceHash,
    viewSharedCamera(pose, options = {}) { motionOptions = options; motion.move(pose) },
    cancelSharedCamera: motion.cancel,
    dispose() { motion.dispose(); button?.removeEventListener('click', download) } }
}
