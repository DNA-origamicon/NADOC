/** Discrete presentation channel, independent of topology and editable state. */
export const PRESENTATION_EVENT = 'nadoc:presentation-frame'
export const isPresentationCheckpoint = entry => ['annotations-state', 'view-volumes-state'].includes(entry?.op_kind)

export function presentationAt(document, position) {
  const log = document?.feature_log ?? []
  const count = position === -2 ? 0 : position === -1 ? log.length : position + 1
  const result = {}
  log.forEach((entry, index) => {
    if (!isPresentationCheckpoint(entry) || entry.suppressed) return
    if (entry.op_kind === 'annotations-state') {
      result.annotations ??= []
      result.annotations_enabled ??= true
      if (index < count) {
        result.annotations = entry.params.annotations
        result.annotations_enabled = entry.params.annotations_enabled
      }
    } else {
      result.view_volumes ??= []
      if (index < count) result.view_volumes = entry.params.view_volumes
    }
  })
  return result
}

export function createPresentationAnimation({ getDocument, emit = detail => globalThis.window?.dispatchEvent(new CustomEvent(PRESENTATION_EVENT, { detail })) }) {
  let featureIndex = null, source = null, previous = null, ready = Promise.resolve(true)
  return {
    getFeatureIndex: () => featureIndex,
    start() { source = getDocument?.(); previous = null },
    show(from, to, t, annotationIds = null, viewVolumeIds = null, zoomVolumeIds = null) {
      if (!source) return
      featureIndex = t >= 1 ? to : from
      const state = presentationAt(source, featureIndex)
      const liveAnnotations = Array.isArray(annotationIds) || !Object.hasOwn(state, 'annotations')
      const current = getDocument?.()
      const live = current?.id === source.id ? current : source
      if (Array.isArray(annotationIds)) {
        const selected = new Set(annotationIds)
        state.annotations = (live.annotations ?? []).filter(entry => selected.has(entry.id)).map(entry => ({ ...entry, visible: true }))
        state.annotations_enabled = true
      } else {
        state.annotations ??= live.annotations ?? []
        state.annotations_enabled ??= live.annotations_enabled !== false
      }
      if (Array.isArray(viewVolumeIds)) {
        const selected = new Set(viewVolumeIds)
        state.view_volumes = (live.view_volumes ?? []).filter(entry => selected.has(entry.id)).map(entry => ({ ...entry, enabled: true }))
      }
      const signature = JSON.stringify({ state, zoomVolumeIds })
      if (signature === previous) return
      previous = signature
      const pending = []
      emit({ documentId: source.id, state, annotationIds, liveAnnotations, zoomVolumeIds, waitUntil: promise => pending.push(promise) })
      ready = Promise.all(pending).then(results => results.every(value => value !== false))
      ready.catch(() => {}) // Playback/export owns the surfaced failure.

    },
    settle: () => ready,
    clear() {
      if (previous !== null) emit(null)
      previous = null; source = null; featureIndex = null; ready = Promise.resolve(true)
    },
  }
}
