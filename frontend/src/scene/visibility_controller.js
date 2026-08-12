import { baseKey } from './base_ref.js'
import { clusterNucKeysFor } from './cluster_entries.js'

/**
 * One transient, base-addressed visibility model for the editor. Higher-level
 * objects are expanded to base keys at hide time; visibility is deliberately
 * not part of the design/undo log.
 */
export function initVisibilityController({ store, designRenderer, unfoldView, onChange } = {}) {
  const hidden = new Set()
  const shown = new Set()
  let hiddenClusters = new Set()
  const undoStack = []
  const redoStack = []

  const geometry = () => store.getState().currentGeometry ?? []
  const design = () => store.getState().currentDesign

  function _apply() {
    const all = new Set(hidden)
    for (const key of _keysFor({ clusterIds: [...hiddenClusters] })) all.add(key)
    for (const key of shown) all.delete(key)
    designRenderer.setHiddenNucs(all)
    designRenderer.setHiddenCrossovers(unfoldView?.setHiddenNucs?.(all) ?? new Set())
    onChange?.(all, new Set(hiddenClusters))
  }

  function _keysFor({ baseKeys = [], strandIds = [], domainRefs = [], clusterIds = [] } = {}) {
    const out = new Set(baseKeys)
    const strands = new Set(strandIds)
    const extensionIds = new Set((design()?.extensions ?? [])
      .filter(ext => strands.has(ext.strand_id)).map(ext => ext.id))
    const domains = new Set(domainRefs.map(d => `${d.strandId}:${d.domainIndex}`))
    const clusterSelectors = clusterNucKeysFor(design(), new Set(clusterIds))
    for (const nuc of geometry()) {
      const key = baseKey(nuc, nuc.copy_k ?? 0)
      if (!key) continue
      if (strands.has(nuc.strand_id) || extensionIds.has(nuc.extension_id) ||
          [...extensionIds].some(id => nuc.helix_id === `__ext_${id}`) ||
          domains.has(`${nuc.strand_id}:${nuc.domain_index}`) ||
          clusterSelectors.has(`h:${nuc.helix_id}`) ||
          clusterSelectors.has(`d:${nuc.strand_id}:${nuc.domain_index}`)) out.add(key)
    }
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
    const keys = geometry().filter(n => n.strand_id === strandId)
      .map(n => baseKey(n, n.copy_k ?? 0)).filter(Boolean)
    const all = new Set(hidden)
    for (const key of _keysFor({ clusterIds: [...hiddenClusters] })) all.add(key)
    for (const key of shown) all.delete(key)
    return keys.length === 0 || keys.some(k => !all.has(k))
  }

  return { hide, show, setHiddenClusters, unhideAll, undo, redo, isStrandShown, getHiddenBaseKeys: () => new Set(hidden) }
}
