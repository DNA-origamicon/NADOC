/**
 * Annotation subsystem: controller + 3D/DOM overlay + sidebar tab, plus the
 * store bindings (annotations live in `currentDesign` and are saved in the
 * .nadoc; part-only availability). One factory so main.js carries a single init line.
 */
import { createAnnotationController } from './annotation_controller.js'
import { createExternalTargets } from './annotation_external.js'
import { initAnnotationOverlay } from './annotation_overlay.js'
import { initAnnotationPanel } from '../ui/annotation_panel.js'

export function initAnnotations({
  document = globalThis.document, store, api, scene, getCamera, addFrameCallback, removeFrameCallback,
  getEntries, resolveBasePosition, getProteinRenderer = () => null, getNanoparticleSubsystem = () => null,
  container = document.getElementById('canvas-area'),
  pane = document.getElementById('right-tab-content-annotations'), legacyStorage,
}) {
  if (!container || !pane) return null

  // Sequential PUTs: an older response must never land after a newer edit.
  let saveQueue = Promise.resolve()
  let controller = null
  const commit = ({ designId, annotations, enabled }) => {
    const current = store.getState().currentDesign
    if (current?.id !== designId) return Promise.resolve()   // design switched underneath the edit
    // The store write is what the autosave watches; the PUT gives the backend the same list
    // so the file writer (which serialises backend state) includes it.
    store.setState({ currentDesign: { ...current, annotations, annotations_enabled: enabled } })
    api.persistDesign?.()
    saveQueue = saveQueue.then(() => api.saveAnnotations({ annotations, enabled })).then(() => {
      // A design response that raced the PUT may have replaced currentDesign with the old list.
      const now = store.getState().currentDesign
      const latest = controller.getCommitted()
      if (now?.id === designId && latest.annotations && (now.annotations !== latest.annotations || now.annotations_enabled !== latest.enabled)) {
        store.setState({ currentDesign: { ...now, annotations: latest.annotations, annotations_enabled: latest.enabled } })
      }
    })
    return saveQueue
  }
  controller = createAnnotationController({ commit, ...(legacyStorage ? { legacyStorage } : {}) })

  const external = createExternalTargets({
    getDesign: () => store.getState().currentDesign, getProteinRenderer, getNanoparticleSubsystem,
  })
  const overlay = initAnnotationOverlay({
    document, container, scene, getCamera, controller, getEntries,
    getDesign: () => store.getState().currentDesign, resolveBasePosition,
    resolveExternal: external.resolve, getOccluders: external.listAll,
    addFrameCallback, removeFrameCallback,
  })
  const panel = initAnnotationPanel({ document, root: pane, controller, store, getDesign: () => store.getState().currentDesign })

  let lastPartMode = null
  const bind = state => {
    const partMode = !state.assemblyActive
    controller.syncFromDesign(partMode ? state.currentDesign : null)
    if (partMode !== lastPartMode) {
      lastPartMode = partMode
      overlay.setEnabled(partMode)
      panel.setAvailable(partMode)
    }
  }
  const unsubscribe = store.subscribe(bind)
  bind(store.getState())

  return {
    controller, overlay, panel,
    dispose() { unsubscribe(); panel.dispose(); overlay.dispose(); controller.dispose() },
  }
}
