/**
 * Annotation list state. The source of truth is `currentDesign.annotations`
 * (saved in the .nadoc); this controller holds the working copy the sidebar
 * and overlay edit, hydrates it from the design, and hands debounced commits to
 * an injected `commit({designId, annotations, enabled})` (store write + PUT).
 *
 * Race rules: while local edits are unsent or in flight an incoming design
 * (e.g. a response to an unrelated edit) never overwrites them; switching
 * designs drops unsent edits rather than writing them into the wrong design.
 */
import {
  ANNOTATION_COLORS, annotationFromWire, annotationToWire, deserializeAnnotations,
  legacyStorageKeyFor, normalizeAnnotation,
} from './annotation_model.js'

const COMMIT_DELAY_MS = 300
/** Patch keys that change list structure or card layout (vs. a value tweak). */
const STRUCTURAL_KEYS = new Set(['refs'])

export function createAnnotationController({
  commit = async () => {}, legacyStorage = globalThis.localStorage,
  setTimer = setTimeout, clearTimer = clearTimeout, delay = COMMIT_DELAY_MS,
} = {}) {
  let designId = null
  let entries = []
  let enabled = true
  let timer = null
  let dirty = false
  let inflight = 0
  let lastWire = null       // the annotations array last hydrated from / committed to the design
  const listeners = new Set()

  const emit = event => { for (const fn of [...listeners]) fn(event) }
  const cancel = () => { if (timer) { clearTimer(timer); timer = null } }
  const toWire = () => entries.map(annotationToWire)

  function flush() {
    cancel()
    if (!dirty || designId == null) return Promise.resolve()
    dirty = false
    const wire = toWire()
    lastWire = wire
    inflight += 1
    return Promise.resolve()
      .then(() => commit({ designId, annotations: wire, enabled }))
      .catch(() => { dirty = true })   // stays local; the next edit retries
      .finally(() => { inflight -= 1 })
  }
  function touch() {
    dirty = true
    cancel()
    timer = setTimer(flush, delay)
  }

  function hydrate(design) {
    const wire = design.annotations ?? []
    const next = wire.map((w, i) => annotationFromWire(w, { index: i }))
    const nextEnabled = design.annotations_enabled !== false
    const same = nextEnabled === enabled && JSON.stringify(next) === JSON.stringify(entries)
    lastWire = wire
    entries = next
    enabled = nextEnabled
    if (!same) emit({ type: 'reset', structural: true })
  }

  /** One-time adoption of annotations saved in browser storage before they lived in the file. */
  function migrateLegacy(id) {
    let raw = null
    try { raw = legacyStorage?.getItem(legacyStorageKeyFor(id)) } catch { return }
    const legacy = raw ? deserializeAnnotations(raw) : []
    if (!legacy.length) return
    entries = legacy
    try { legacyStorage.removeItem(legacyStorageKeyFor(id)) } catch { /* ignore */ }
    emit({ type: 'reset', structural: true })
    touch()
  }

  return {
    list: () => entries,
    get: id => entries.find(e => e.id === id) ?? null,
    getDesignId: () => designId,
    isEnabled: () => enabled,
    /** The annotations array currently in (or on its way to) the design. */
    getCommitted: () => ({ annotations: lastWire, enabled }),
    hasPendingEdits: () => dirty || inflight > 0,

    /** Follow the active design; pass null when no part is being edited. */
    syncFromDesign(design) {
      if (!design) {
        cancel(); dirty = false
        if (designId !== null || entries.length) {
          designId = null; entries = []; enabled = true; lastWire = null
          emit({ type: 'reset', structural: true })
        }
        return
      }
      if (design.id !== designId) {
        cancel(); dirty = false
        designId = design.id
        const before = entries.length
        entries = []; enabled = true
        hydrate(design)
        if (before && !entries.length) emit({ type: 'reset', structural: true })
        if (!entries.length && !(design.annotations ?? []).length) migrateLegacy(design.id)
        return
      }
      const wire = design.annotations ?? []
      if (wire === lastWire && (design.annotations_enabled !== false) === enabled) return
      if (dirty || inflight) return
      hydrate(design)
    },

    add(partial = {}) {
      const entry = normalizeAnnotation({
        color: ANNOTATION_COLORS[entries.length % ANNOTATION_COLORS.length], ...partial,
      }, { index: entries.length })
      entries = [...entries, entry]
      touch()
      emit({ type: 'add', id: entry.id, structural: true })
      return entry
    },

    update(id, patch) {
      const i = entries.findIndex(e => e.id === id)
      if (i < 0) return null
      const next = normalizeAnnotation({ ...entries[i], ...patch }, { index: i })
      entries = entries.map((e, j) => (j === i ? next : e))
      touch()
      emit({ type: 'update', id, patch, structural: Object.keys(patch).some(k => STRUCTURAL_KEYS.has(k)) })
      return next
    },

    remove(id) {
      if (!entries.some(e => e.id === id)) return false
      entries = entries.filter(e => e.id !== id)
      touch()
      emit({ type: 'remove', id, structural: true })
      return true
    },

    /** Global show/hide of every annotation in the viewport. */
    setEnabled(next) {
      const value = !!next
      if (value === enabled) return
      enabled = value
      touch()
      emit({ type: 'enabled', structural: false })
    },

    subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn) },
    flush,
    dispose() { cancel(); listeners.clear() },
  }
}
