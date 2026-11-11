import { createAnnotationController } from './annotation_controller.js'
import { PRESENTATION_EVENT } from './presentation_checkpoint_animation.js'
import { annotationToWire } from './annotation_model.js'

/** Playback reads a separate controller and can never autosave historical notes. */
export function createAnnotationPresentationController({ controller, getDocument, target = globalThis.window }) {
  const preview = createAnnotationController({ legacyStorage: null })
  let active = false
  let annotationIds = null
  let liveAnnotations = false
  const listeners = new Set()
  const notify = event => { for (const listener of listeners) listener(event) }
  const liveState = () => {
    const selected = Array.isArray(annotationIds) ? new Set(annotationIds) : null
    return {
      annotations: controller.list().filter(entry => !selected || selected.has(entry.id))
        .map(entry => annotationToWire(selected ? { ...entry, visible: true } : entry)),
      annotations_enabled: selected ? true : controller.isEnabled(),
    }
  }
  const off = controller.subscribe(event => {
    if (active && preview.getDesignId() !== getDocument()?.id) active = false
    if (active && liveAnnotations) {
      preview.syncFromDesign({ id: preview.getDesignId(), ...liveState() })
      notify({ type: 'reset', structural: true })
    } else if (active && ['update', 'remove'].includes(event.type)) {
      // Edit the working annotation once; mirror it into the display-only copy.
      // Keep the keyframe's visibility selection, including hidden working notes.
      const entries = preview.list().flatMap(entry => {
        if (entry.id !== event.id) return [entry]
        const live = controller.get(entry.id)
        return live ? [{ ...live, visible: Array.isArray(annotationIds) ? true : entry.visible }] : []
      })
      preview.syncFromDesign({ id: preview.getDesignId(), annotations: entries.map(annotationToWire), annotations_enabled: preview.isEnabled() })
      notify({ type: 'reset', structural: true })
    } else if (!active) notify(event)
  })
  const event = ({ detail }) => {
    active = !!detail && detail.documentId === getDocument()?.id && !!detail.state.annotations
    annotationIds = detail?.annotationIds ?? null
    liveAnnotations = Array.isArray(annotationIds) || !!detail?.liveAnnotations
    if (active) {
      const state = { ...detail.state }
      // Working edits can precede the debounced document save. Explicit keyframe
      // selections refer to these live notes, not the older wire snapshot.
      if (liveAnnotations) Object.assign(state, liveState())
      preview.syncFromDesign({ id: detail.documentId, ...state })
    }
    notify({ type: 'reset', structural: true })
  }
  target?.addEventListener(PRESENTATION_EVENT, event)
  const current = () => active ? preview : controller
  return {
    isPreviewing: () => active,
    list: () => current().list(), get: id => current().get(id), isEnabled: () => current().isEnabled(),
    update: (id, patch) => { if (!active) return controller.update(id, patch) },
    subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn) },
    dispose() { off(); preview.dispose(); listeners.clear(); target?.removeEventListener(PRESENTATION_EVENT, event) },
  }
}
