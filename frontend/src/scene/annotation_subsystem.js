import { createAnnotationSelection } from './annotation_selection.js'
import { createAnnotationPresentationController } from './annotation_presentation_controller.js'
import { createAnnotationLoadGate } from './annotation_load_gate.js'
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
  getAssemblyRenderer = () => null, getDnaSilhouetteEntries = () => [],
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

  const selection = createAnnotationSelection({ document, container, pane, controller })

  const assemblyTargets = createAssemblyAnnotationTargets({ store, getRenderer: getAssemblyRenderer })
  const external = createExternalTargets({
    getDesign: () => store.getState().currentDesign, getProteinRenderer, getNanoparticleSubsystem,
  })
  const displayController = createAnnotationPresentationController({ controller, getDocument: () => host().doc })
  const loadGate = createAnnotationLoadGate({ store, document, getAssemblyRenderer })
  const overlay = initAnnotationOverlay({
    document, container, scene, getCamera, selection, controller: displayController, isReady: loadGate.isReady,
    getEntries: () => host().assembly ? [] : getEntries(),
    resolveTargetEntries: refs => host().assembly ? assemblyTargets.resolve(refs) : null,
    getDesign: () => host().doc, resolveBasePosition,
    resolveSilhouette: (refs, matched) => matched.concat(
      host().assembly ? [] : getDnaSilhouetteEntries(refs, matched), refs.flatMap(ref => {
        if (ref.kind === 'protein') return getProteinRenderer()?.silhouetteEntries?.(a => a.helix_id === `__protein__${ref.id}`) ?? []
        if (ref.kind === 'nanoparticle') {
          const mesh = getNanoparticleSubsystem()?.meshes?.get(ref.id)
          return mesh ? [{ mesh }] : []
        }
        return []
      })),
    resolveExternal: external.resolve, getOccluders: () => host().assembly ? assemblyTargets.occluders() : external.listAll(),
    addFrameCallback, removeFrameCallback,
  })
  const panel = initAnnotationPanel({ document, root: pane, controller, selection, store, getDesign: () => host().doc, saveCheckpoint: async () => {
    if (displayController.isPreviewing()) throw new Error("Stop playback before saving an annotation state")
    const target = host()
    await controller.flush()
    await saveQueue
    if (host().id !== target.id) throw new Error("The active document changed")
    if (controller.hasPendingEdits()) throw new Error("Annotations are still saving; try again")
    return api.savePresentationCheckpoint("annotations-state", { assembly: target.assembly, documentId: target.doc.id })
  } })

  let lastId = null
  const bind = () => {
    const current = host()
    if (lastId !== current.id) { selection.select(null); assemblyTargets.clear(); lastId = current.id }
    controller.syncFromDesign(current.doc ? { ...current.doc, id: current.id } : null)
    overlay.setEnabled(!!current.doc)
    panel.setAvailable(!!current.doc)
  }
  const unsubscribe = store.subscribe(bind)
  bind(store.getState())

  return {
    controller, overlay, panel,
    dispose() { unsubscribe(); selection.dispose(); loadGate.dispose(); panel.dispose(); overlay.dispose(); displayController.dispose(); controller.dispose() },
  }
}
