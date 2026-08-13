// Protein subsystem — imported proteins rendered all-atom, independent of the DNA
// atomistic mode so proteins coexist with cylinders/beads/atomistic DNA. Owns a
// dedicated atomistic renderer instance, a transform gizmo for the selected
// protein, the coalesced server re-fetch, and the two store subscriptions that
// keep proteins + selection visual in sync.
//
// Lifted verbatim from main.js (extraction #85). Two atomistic renderer instances
// exist in main(): the global DNA `atomisticRenderer` and this `proteinRenderer` —
// distinct so proteins draw regardless of the DNA representation mode.
import { initAtomisticRenderer } from './atomistic_renderer.js'
import { initProteinGizmo } from './protein_gizmo.js'
import { docHeaders } from '../shared/doc_id.js'
import { primaryRefOfKind } from './selection_model.js'

export function initProteinSubsystem({ scene, store, controls, camera, canvas }) {
  // Protein renderer (imported proteins; independent of the DNA atomistic
  // mode so proteins coexist with cylinders/beads/atomistic DNA).
  const proteinRenderer = initAtomisticRenderer(scene)
  const _proteinCentroid = (id) =>
    proteinRenderer.centroidOf(a => a.helix_id === `__protein__${id}`)

  // Transform gizmo for the selected protein. Live preview during drag; on
  // drag-end it commits a gizmo_move (which syncs the design → the currentDesign
  // subscription below re-renders + re-anchors the gizmo). No onCommitted needed.
  const proteinGizmo = initProteinGizmo(store, controls, {
    onLiveStart: (id) => proteinRenderer.beginLiveTransform(a => a.helix_id === `__protein__${id}`),
    onLive:      (m)  => proteinRenderer.applyLiveTransform(m),
    onLiveEnd:   ()   => proteinRenderer.endLiveTransform(),
  })

  // Re-apply the selection visual: highlight + (re)anchor the gizmo at the
  // selected protein's current centroid, or detach when nothing/none-existent
  // is selected. Called after every render so the gizmo follows moves and
  // drops away when the protein is deleted/undone.
  function _syncProteinSelectionVisual() {
    const ref = primaryRefOfKind(store.getState(), 'protein')
    const protId = ref?.id ?? null
    const c = protId ? _proteinCentroid(protId) : null
    if (protId && c) {
      proteinRenderer.highlight({ type: 'protein', id: protId, data: { attachment_id: protId } })
      proteinGizmo.attach(protId, scene, camera, canvas, c)
    } else {
      if (proteinGizmo.isAttached()) proteinGizmo.detach()
      proteinRenderer.highlight(null)
    }
  }

  // Re-render proteins from the server — the design's attachments are the single
  // source of truth. Coalesced so overlapping triggers don't double-fetch.
  let _protRefreshInFlight = false
  let _protRefreshPending = false
  async function _refreshProteins() {
    if (_protRefreshInFlight) { _protRefreshPending = true; return }
    _protRefreshInFlight = true
    try {
      const resp = await fetch('/api/design/protein/atomistic', { headers: docHeaders() })
      if (!resp.ok) return
      const data = await resp.json()
      if (data?.atoms?.length) {
        proteinRenderer.setMode('vdw')
        proteinRenderer.update(data)
      } else {
        proteinRenderer.setMode('off')
        proteinRenderer.update({ atoms: [] })   // clear any existing meshes
      }
      _syncProteinSelectionVisual()
    } catch (e) {
      console.error('Protein atomistic fetch error:', e)
    } finally {
      _protRefreshInFlight = false
      if (_protRefreshPending) { _protRefreshPending = false; _refreshProteins() }
    }
  }

  // Single source of truth: any change to the design (import, move, delete,
  // undo, redo, attach/detach) re-renders proteins from its attachments.
  store.subscribe((newState, prevState) => {
    if (newState.currentDesign === prevState.currentDesign) return
    const hasProteins = (newState.currentDesign?.protein_attachments?.length ?? 0) > 0
    // Refresh when proteins exist now, or when the renderer is showing some
    // (so a removal — undo/delete — clears them).
    if (hasProteins || proteinRenderer.getMode() !== 'off') _refreshProteins()
  })

  // Selection change → update the gizmo/highlight (without a server round-trip).
  store.subscribe((newState, prevState) => {
    if (newState.selection !== prevState.selection) _syncProteinSelectionVisual()
  })

  if (window.__NADOC_DBG__) {
    window.__NADOC_DBG__.proteinRenderer = proteinRenderer
    window.__NADOC_DBG__.proteinGizmo = proteinGizmo
    window.__NADOC_DBG__.refreshProteins = _refreshProteins
  }

  return {
    renderer: proteinRenderer,
    gizmo: proteinGizmo,
    refresh: _refreshProteins,
    syncSelectionVisual: _syncProteinSelectionVisual,
  }
}
