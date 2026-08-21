import { baseKey } from './base_ref.js'
import { clusterNucKeysFor } from './cluster_entries.js'

/** Expand prepared visibility selectors over geometry in one linear pass. */
export function collectVisibilityBaseKeys(geometry, {
  strands = new Set(), extensionIds = new Set(), domains = new Set(),
  clusterSelectors = new Set(),
} = {}) {
  const out = new Set()
  const extensionHelixIds = new Set([...extensionIds].map(id => `__ext_${id}`))
  for (const nuc of geometry ?? []) {
    const key = baseKey(nuc, nuc.copy_k ?? 0)
    if (!key) continue
    if (strands.has(nuc.strand_id) || extensionIds.has(nuc.extension_id) ||
        extensionHelixIds.has(nuc.helix_id) ||
        domains.has(`${nuc.strand_id}:${nuc.domain_index}`) ||
        clusterSelectors.has(`h:${nuc.helix_id}`) ||
        clusterSelectors.has(`d:${nuc.strand_id}:${nuc.domain_index}`)) out.add(key)
  }
  return out
}

export function buildVisibilityGeometryIndex(geometry) {
  const baseKeysByStrand = new Map()
  for (const nuc of geometry ?? []) {
    if (!nuc.strand_id) continue
    const key = baseKey(nuc, nuc.copy_k ?? 0)
    if (!key) continue
    let keys = baseKeysByStrand.get(nuc.strand_id)
    if (!keys) baseKeysByStrand.set(nuc.strand_id, keys = [])
    keys.push(key)
  }
  return { baseKeysByStrand }
}

/**
 * One persisted, base-addressed visibility model for the editor. Higher-level
 * objects are expanded to base keys at hide time. It has its own undo stack and
 * is deliberately not part of the topology feature log.
 */
export function initVisibilityController({ store, designRenderer, unfoldView, onChange, onPersist } = {}) {
  const hidden = new Set()
  const shown = new Set()
  let hiddenClusters = new Set()
  const undoStack = []
  const redoStack = []
  let persistChain = Promise.resolve()
  let pendingPersists = 0
  let currentDesignRef = null
  let currentGeometryRef = null
  let currentGeometryIndex = buildVisibilityGeometryIndex([])

  const geometry = () => store.getState().currentGeometry ?? []
  const design = () => store.getState().currentDesign

  const _persistedState = () => ({
    hidden_base_keys: [...hidden].sort(),
    shown_base_keys: [...shown].sort(),
    hidden_cluster_ids: [...hiddenClusters].sort(),
  })

  function _apply({ persist = true, notify = true } = {}) {
    const all = new Set(hidden)
    for (const key of _keysFor({ clusterIds: [...hiddenClusters] })) all.add(key)
    for (const key of shown) all.delete(key)
    designRenderer.setHiddenNucs(all)
    designRenderer.setHiddenCrossovers(unfoldView?.setHiddenNucs?.(all) ?? new Set())
    if (notify) onChange?.(all, new Set(hiddenClusters))
    if (persist && onPersist) {
      const state = _persistedState()
      pendingPersists++
      const task = persistChain.then(() => onPersist(state))
      persistChain = task.catch((error) => console.error('Failed to persist visibility state', error))
        .finally(() => { pendingPersists-- })
      return task
    }
    return Promise.resolve()
  }

  function _hydrate(state = {}, { notify = true } = {}) {
    hidden.clear(); shown.clear()
    for (const key of state.hidden_base_keys ?? []) hidden.add(key)
    for (const key of state.shown_base_keys ?? []) shown.add(key)
    hiddenClusters = new Set(state.hidden_cluster_ids ?? [])
    undoStack.length = 0; redoStack.length = 0
    _apply({ persist: false, notify })
  }

  function _keysFor({ baseKeys = [], strandIds = [], domainRefs = [], clusterIds = [] } = {}) {
    const out = new Set(baseKeys)
    const strands = new Set(strandIds)
    const extensionIds = new Set((design()?.extensions ?? [])
      .filter(ext => strands.has(ext.strand_id)).map(ext => ext.id))
    const domains = new Set(domainRefs.map(d => `${d.strandId}:${d.domainIndex}`))
    const clusterSelectors = clusterNucKeysFor(design(), new Set(clusterIds))
    for (const key of collectVisibilityBaseKeys(geometry(), {
      strands, extensionIds, domains, clusterSelectors,
    })) out.add(key)
    return out
  }

  const _snapshot = () => ({
    hidden: new Set(hidden), shown: new Set(shown), hiddenClusters: new Set(hiddenClusters),
  })
  function _restore(s) {
    hidden.clear(); shown.clear()
    for (const key of s.hidden) hidden.add(key)
    for (const key of s.shown) shown.add(key)
    hiddenClusters = new Set(s.hiddenClusters)
    _apply()
  }
  function _pushUndo() { undoStack.push(_snapshot()); redoStack.length = 0 }

  function hide(refs) {
    _pushUndo()
    for (const key of _keysFor(refs)) { shown.delete(key); hidden.add(key) }
    _apply()
  }

  function show(refs) {
    _pushUndo()
    for (const key of _keysFor(refs)) { hidden.delete(key); shown.add(key) }
    _apply()
  }

  function setHiddenClusters(ids) { _pushUndo(); hiddenClusters = new Set(ids ?? []); _apply() }

  function unhideAll() { _pushUndo(); hidden.clear(); shown.clear(); hiddenClusters.clear(); _apply() }

  function undo() {
    const prior = undoStack.pop()
    if (!prior) return false
    redoStack.push(_snapshot()); _restore(prior); return true
  }
  function redo() {
    const next = redoStack.pop()
    if (!next) return false
    undoStack.push(_snapshot()); _restore(next); return true
  }

  function isStrandShown(strandId) {
    const keys = currentGeometryIndex.baseKeysByStrand.get(strandId) ?? []
    const all = new Set(hidden)
    if (hiddenClusters.size) {
      for (const key of _keysFor({ clusterIds: [...hiddenClusters] })) all.add(key)
    }
    for (const key of shown) all.delete(key)
    return keys.length === 0 || keys.some(k => !all.has(k))
  }

  currentDesignRef = design()
  currentGeometryRef = geometry()
  currentGeometryIndex = buildVisibilityGeometryIndex(currentGeometryRef)
  // Render immediately, but main.js's sidebar/atom-surface consumers are
  // declared later in startup and must not be notified while in their TDZ.
  _hydrate(currentDesignRef?.visibility_state, { notify: false })
  const unsubscribe = store.subscribe?.((next) => {
    const designChanged = next.currentDesign !== currentDesignRef
    const geometryChanged = next.currentGeometry !== currentGeometryRef
    currentDesignRef = next.currentDesign
    currentGeometryRef = next.currentGeometry
    if (geometryChanged) currentGeometryIndex = buildVisibilityGeometryIndex(currentGeometryRef)
    if (designChanged && pendingPersists === 0) _hydrate(currentDesignRef?.visibility_state)
    else if (geometryChanged) {
      _apply({ persist: false })
      // Store listeners run in registration order. The design renderer rebuilds
      // its instance meshes from this same geometry notification, so re-apply
      // once after that synchronous rebuild has completed.
      queueMicrotask(() => {
        if (geometry() === currentGeometryRef) _apply({ persist: false })
      })
    }
  })

  return {
    hide, show, setHiddenClusters, unhideAll, undo, redo, isStrandShown,
    getHiddenBaseKeys: () => new Set(hidden),
    flushPersistence: () => persistChain,
    destroy: () => unsubscribe?.(),
  }
}
