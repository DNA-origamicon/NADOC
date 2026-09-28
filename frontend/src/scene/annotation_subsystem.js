/**
 * Annotation subsystem: controller + 3D/DOM overlay + sidebar tab, plus the
 * document bindings (saved in the active .nadoc or .nass). One factory so main.js carries a single init line.
 */
import { createAssemblyAnnotationTargets } from './assembly_annotation_targets.js'
import { createAnnotationController } from './annotation_controller.js'
import { createExternalTargets } from './annotation_external.js'
import { initAnnotationOverlay } from './annotation_overlay.js'
import { initAnnotationPanel } from '../ui/annotation_panel.js'

export function initAnnotations({
  document = globalThis.document, store, api, scene, getCamera, addFrameCallback, removeFrameCallback,
  getEntries = () => [], resolveBasePosition, getProteinRenderer = () => null, getNanoparticleSubsystem = () => null,
  getAssemblyRenderer = () => null,
  container = document.getElementById('canvas-area'),
  pane = document.getElementById('right-tab-content-annotations'), legacyStorage,
}) {
  if (!container || !pane) return null

  // Sequential PUTs: an older response must never land after a newer edit.
  let saveQueue = Promise.resolve()
  let controller = null
  const host = () => {
    const state = store.getState()
    const assembly = !!state.assemblyActive
    const key = assembly ? 'currentAssembly' : 'currentDesign'
    const doc = state[key]
    return { assembly, key, doc, id: doc ? (assembly ? `assembly:${doc.id}` : doc.id) : null }
  }
  const commit = ({ designId, annotations, enabled }) => {
    const target = host()
    if (target.id !== designId) return Promise.resolve()
    store.setState({ [target.key]: { ...target.doc, annotations, annotations_enabled: enabled } })
    // Retain local recovery even if the server save fails.
    if (target.assembly) api.persistAssembly?.()
    else api.persistDesign?.()
    const save = async () => {
      if (host().id !== designId) return
      const result = await (target.assembly ? api.saveAssemblyAnnotations({ annotations, enabled }) : api.saveAnnotations({ annotations, enabled }))
      if (result === null) throw new Error("Annotation save failed")
      return result
    }
    saveQueue = saveQueue.catch(() => {}).then(save).then(() => {
      const now = host()
      if (now.id !== designId) return
      const latest = controller.getCommitted()
      if (latest.annotations && (now.doc.annotations !== latest.annotations || now.doc.annotations_enabled !== latest.enabled))
        store.setState({ [now.key]: { ...now.doc, annotations: latest.annotations, annotations_enabled: latest.enabled } })
      if (target.assembly) api.persistAssembly?.()
      else api.persistDesign?.()
    })
    return saveQueue
  }
  controller = createAnnotationController({ commit, ...(legacyStorage ? { legacyStorage } : {}) })

  const assemblyTargets = createAssemblyAnnotationTargets({ store, getRenderer: getAssemblyRenderer })
  const external = createExternalTargets({
    getDesign: () => store.getState().currentDesign, getProteinRenderer, getNanoparticleSubsystem,
  })
  const overlay = initAnnotationOverlay({
    document, container, scene, getCamera, controller,
    getEntries: () => host().assembly ? [] : getEntries(),
    resolveTargetEntries: refs => host().assembly ? assemblyTargets.resolve(refs) : null,
    getDesign: () => host().doc, resolveBasePosition,
    resolveExternal: external.resolve, getOccluders: () => host().assembly ? assemblyTargets.occluders() : external.listAll(),
    addFrameCallback, removeFrameCallback,
  })
  const panel = initAnnotationPanel({ document, root: pane, controller, store, getDesign: () => host().doc })

  let lastId = null
  const bind = () => {
    const current = host()
    if (lastId !== current.id) { assemblyTargets.clear(); lastId = current.id }
    controller.syncFromDesign(current.doc ? { ...current.doc, id: current.id } : null)
    overlay.setEnabled(!!current.doc)
    panel.setAvailable(!!current.doc)
  }
  const unsubscribe = store.subscribe(bind)
  bind(store.getState())

  return {
    controller, overlay, panel,
    dispose() { unsubscribe(); panel.dispose(); overlay.dispose(); controller.dispose() },
  }
}
