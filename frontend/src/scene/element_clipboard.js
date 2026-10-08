import { canonicalSelection } from './selection_model.js'

export function conjugateStrandRefs(design, refs) {
  const proteins = new Set(refs.filter(r => r.kind === 'protein').map(r => r.id))
  const particles = new Set(refs.filter(r => r.kind === 'nanoparticle').map(r => r.id))
  const ids = new Set()
  for (const a of design?.protein_attachments ?? []) if (proteins.has(a.id) && a.binder_strand_id) ids.add(a.binder_strand_id)
  for (const c of design?.nanoparticle_conjugations ?? []) if (particles.has(c.nanoparticle_id)) for (const r of c.surface_strands ?? []) ids.add(r.strand_id)
  for (const p of design?.nanoparticles ?? []) if (particles.has(p.id)) for (const r of p.biotin_dna ?? []) ids.add(r.strand_id)
  const live = new Set((design?.strands ?? []).map(s => s.id))
  return [...ids].filter(id => live.has(id)).map(id => ({ kind: 'strand', id }))
}

export function initElementClipboard({ store, api, selectionController, showToast }) {
  let snapshot = null
  let pasteIndex = 0
  let busy = false
  return {
    hasCopy: () => snapshot !== null,
    clear: () => { snapshot = null },
    copy() {
      const state = store.getState()
      const refs = canonicalSelection(state).items
      const protein_ids = refs.filter(r => r.kind === 'protein').map(r => r.id)
      const nanoparticle_ids = refs.filter(r => r.kind === 'nanoparticle').map(r => r.id)
      if (!state.currentDesign || (!protein_ids.length && !nanoparticle_ids.length)) return false
      const source = structuredClone(state.currentDesign)
      // History contains nested compressed design snapshots; it is not part of a copy.
      source.feature_log = []
      source.loadouts = []
      snapshot = { source, protein_ids, nanoparticle_ids }
      pasteIndex = 0
      showToast('Copied elements with conjugated DNA.')
      return true
    },
    async paste() {
      if (!snapshot || busy) return false
      busy = true
      try {
        const result = await api.pasteElements({ ...snapshot, paste_index: pasteIndex + 1 })
        if (!result) {
          showToast(store.getState().lastError?.message ?? 'Paste failed.', { severity: 'error' })
          return false
        }
        pasteIndex++
        selectionController.replace(result.pasted_refs)
        showToast('Pasted elements with conjugated DNA.')
        return true
      } catch (error) {
        showToast(error.message ?? 'Paste failed.', { severity: 'error' })
        return false
      } finally { busy = false }
    },
  }
}
