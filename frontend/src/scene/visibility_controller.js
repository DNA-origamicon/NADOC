import { baseKey } from './base_ref.js'
import { clusterNucKeysFor } from './cluster_entries.js'
import { hasOrganization, displayGroups, partGroupIdsForNucleotide } from './part_group_display.js'

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
 * Persisted presentation visibility. Named groups and placements retain identity;
 * individual selections retain exact base addresses. Group membership is resolved
 * from the current immutable snapshot, never from the feature log or render loop.
 */
export function initVisibilityController({ store, designRenderer, unfoldView, onChange, onPersist,
  getRevision = () => null, eventTarget = globalThis.window } = {}) {
  const hidden = new Set()
  const shown = new Set()
  let effectiveHidden = new Set()
  let hiddenClusters = new Set()
  let hiddenGroupIds = new Set()
  const undoStack = []
  const redoStack = []
  let persistChain = Promise.resolve()
  let pendingPersists = 0
  let currentDesignRef = null
  let currentGeometryRef = null
  let currentGeometryIndex = buildVisibilityGeometryIndex([])
  let groupBaseKeys = new Map()
  let hiddenPartGroups = new Set()
  let groupInputs = []
  let editEpoch = 0
  let contextGeneration = 0
  let needsHydration = false
  let disposed = false
  let acknowledged = null

  const invalidateContext = () => {
    contextGeneration++; editEpoch++
    // The previous generation can still be draining its network request, but it
    // must neither block replacement hydration nor consume a new save's count.
    pendingPersists = 0
    needsHydration = true
    acknowledged = null
  }
  eventTarget?.addEventListener('nadoc:document-reset', invalidateContext)

  const geometry = () => store.getState().currentGeometry ?? []
  const design = () => store.getState().currentDesign

  function _groupIndex() {
    const current = design()
    const inputs = [current?.group_organization, current?.strands, current?.extensions, geometry()]
    if (inputs.every((value, i) => value === groupInputs[i])) return
    groupInputs = inputs
    groupBaseKeys = new Map()
    if (!hasOrganization(current)) return
    for (const group of displayGroups(current)) groupBaseKeys.set(group.id, new Set())
    for (const nucleotide of geometry()) {
      const key = baseKey(nucleotide, nucleotide.copy_k ?? 0)
      if (!key) continue
      for (const id of partGroupIdsForNucleotide(nucleotide, current)) groupBaseKeys.get(id)?.add(key)
    }
  }

  const _persistedState = () => ({
    hidden_base_keys: [...hidden].sort(),
    shown_base_keys: [...shown].sort(),
    hidden_cluster_ids: [...hiddenClusters].sort(),
    hidden_part_group_ids: [...hiddenGroupIds].sort(),
  })

  function _apply({ persist = true, notify = true, edit = null } = {}) {
    const all = new Set(hidden)
    for (const key of _keysFor({ clusterIds: [...hiddenClusters] })) all.add(key)
    for (const id of hiddenGroupIds) for (const key of groupBaseKeys.get(id) ?? []) all.add(key)
    for (const key of shown) all.delete(key)
    effectiveHidden = all
    hiddenPartGroups = new Set()
    for (const [id, keys] of groupBaseKeys) {
      if (keys.size ? [...keys].every(key => all.has(key)) : hiddenGroupIds.has(id)) hiddenPartGroups.add(id)
    }
    designRenderer.setHiddenNucs(all)
    designRenderer.setHiddenCrossovers(unfoldView?.setHiddenNucs?.(all) ?? new Set())
    if (notify) onChange?.(all, new Set(hiddenClusters), new Set(hiddenPartGroups))
    if (persist && onPersist) {
      const state = _persistedState()
      const generation = contextGeneration
      const checkpoint = _checkpoint()
      pendingPersists++
      const task = persistChain.then(async () => {
        if (disposed || generation !== contextGeneration) return
        // Earlier queued saves may have installed a new canonical revision.
        // Bind this request to its dispatch origin and retain the gesture's
        // epoch so a newer local edit is never overwritten.
        const dispatched = edit && { ...edit, design: design(), revision: getRevision() }
        try {
          const result = await onPersist(state)
          // Existing presentation callbacks may intentionally return void.
          // Null is the client adapter's explicit rejected/stale outcome.
          if (result === null) _rollback(dispatched)
          else if (!disposed && generation === contextGeneration) acknowledged = checkpoint
        } catch (error) {
          _rollback(dispatched)
          console.error('Failed to persist visibility state', error)
        }
      })
      persistChain = task
        .finally(() => { if (generation === contextGeneration) pendingPersists-- })
      return task
    }
    return Promise.resolve()
  }

  function _hydrate(state = {}, { notify = true } = {}) {
    editEpoch++
    needsHydration = false
    hidden.clear(); shown.clear()
    for (const key of state.hidden_base_keys ?? []) hidden.add(key)
    for (const key of state.shown_base_keys ?? []) shown.add(key)
    hiddenClusters = new Set(state.hidden_cluster_ids ?? [])
    hiddenGroupIds = new Set(state.hidden_part_group_ids ?? [])
    undoStack.length = 0; redoStack.length = 0
    acknowledged = _checkpoint()
    _apply({ persist: false, notify })
  }

  function _keysFor({ baseKeys = [], strandIds = [], domainRefs = [], clusterIds = [], partGroupIds = [] } = {}) {
    const out = new Set(baseKeys)
    for (const id of partGroupIds) for (const key of groupBaseKeys.get(id) ?? []) out.add(key)
    if (!strandIds.length && !domainRefs.length && !clusterIds.length) return out
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
    hiddenGroupIds: new Set(hiddenGroupIds),
  })
  const _checkpoint = () => ({ visibility: _snapshot(), undo: [...undoStack], redo: [...redoStack] })
  function _restore(s, options) {
    hidden.clear(); shown.clear()
    for (const key of s.hidden) hidden.add(key)
    for (const key of s.shown) shown.add(key)
    hiddenClusters = new Set(s.hiddenClusters)
    hiddenGroupIds = new Set(s.hiddenGroupIds)
    _apply(options)
  }
  function _pushUndo() { undoStack.push(_snapshot()); redoStack.length = 0 }

  function _beginEdit() {
    const epoch = ++editEpoch
    if (!onPersist || !hasOrganization(design())) return null
    return { epoch, generation: contextGeneration }
  }

  function _rollback(edit) {
    if (!edit || !acknowledged || disposed || edit.epoch !== editEpoch ||
        edit.generation !== contextGeneration || design() !== edit.design ||
        getRevision() !== edit.revision) return
    editEpoch++
    // A previous queued save may also have failed. The latest gesture's
    // before-state can contain that unsaved edit, so restore only acknowledged
    // presentation. Accepted complete saves retain intermediate gesture undo.
    undoStack.splice(0, undoStack.length, ...acknowledged.undo)
    redoStack.splice(0, redoStack.length, ...acknowledged.redo)
    _restore(acknowledged.visibility, { persist: false })
  }

  function hide(refs = {}) {
    const edit = _beginEdit()
    _pushUndo()
    for (const id of refs.partGroupIds ?? []) {
      if (!groupBaseKeys.has(id)) continue
      hiddenGroupIds.add(id)
      for (const key of groupBaseKeys.get(id)) shown.delete(key)
    }
    for (const key of _keysFor({ ...refs, partGroupIds: [] })) { shown.delete(key); hidden.add(key) }
    _apply({ edit })
  }

  function show(refs = {}) {
    const edit = _beginEdit()
    _pushUndo()
    for (const id of refs.partGroupIds ?? []) hiddenGroupIds.delete(id)
    // Preserve explicit Show precedence for current members of overlapping
    // hidden groups/placements; their independent identity rules remain intact.
    for (const key of _keysFor(refs)) { hidden.delete(key); shown.add(key) }
    _apply({ edit })
  }

  function setHiddenClusters(ids) {
    const edit = _beginEdit()
    _pushUndo(); hiddenClusters = new Set(ids ?? []); _apply({ edit })
  }

  function unhideAll() {
    const edit = _beginEdit()
    _pushUndo(); hidden.clear(); shown.clear(); hiddenClusters.clear(); hiddenGroupIds.clear(); _apply({ edit })
  }

  function undo() {
    if (!undoStack.length) return false
    const edit = _beginEdit()
    const prior = undoStack.pop()
    redoStack.push(_snapshot()); _restore(prior, { edit }); return true
  }
  function redo() {
    if (!redoStack.length) return false
    const edit = _beginEdit()
    const next = redoStack.pop()
    undoStack.push(_snapshot()); _restore(next, { edit }); return true
  }

  function isStrandShown(strandId) {
    const keys = currentGeometryIndex.baseKeysByStrand.get(strandId) ?? []
    return keys.length === 0 || keys.some(k => !effectiveHidden.has(k))
  }

  currentDesignRef = design()
  currentGeometryRef = geometry()
  currentGeometryIndex = buildVisibilityGeometryIndex(currentGeometryRef)
  _groupIndex()
  // Render immediately, but main.js's sidebar/atom-surface consumers are
  // declared later in startup and must not be notified while in their TDZ.
  _hydrate(currentDesignRef?.visibility_state, { notify: false })
  const unsubscribe = store.subscribe?.((next) => {
    const designChanged = next.currentDesign !== currentDesignRef
    const geometryChanged = next.currentGeometry !== currentGeometryRef
    const documentChanged = next.currentDesign?.id !== currentDesignRef?.id
    if (documentChanged) invalidateContext()
    currentDesignRef = next.currentDesign
    currentGeometryRef = next.currentGeometry
    if (geometryChanged) currentGeometryIndex = buildVisibilityGeometryIndex(currentGeometryRef)
    if (designChanged || geometryChanged) _groupIndex()
    if (designChanged && (pendingPersists === 0 || needsHydration)) _hydrate(currentDesignRef?.visibility_state)
    else if (geometryChanged || designChanged) {
      _apply({ persist: false })
      // Store listeners run in registration order. The design renderer rebuilds
      // its instance meshes from this same geometry notification, so re-apply
      // once after that synchronous rebuild has completed.
      queueMicrotask(() => {
        if (!disposed && geometry() === currentGeometryRef) _apply({ persist: false })
      })
    }
  })

  return {
    hide, show, setHiddenClusters, unhideAll, undo, redo, isStrandShown,
    isPartGroupShown: id => !hiddenPartGroups.has(id),
    getHiddenBaseKeys: () => new Set(hidden),
    isBaseShown: key => !effectiveHidden.has(key),
    flushPersistence: () => persistChain,
    destroy: () => {
      disposed = true
      invalidateContext()
      eventTarget?.removeEventListener('nadoc:document-reset', invalidateContext)
      unsubscribe?.()
    },
  }
}
