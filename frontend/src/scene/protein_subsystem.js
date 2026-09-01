// Protein subsystem — imported proteins rendered all-atom, independent of the DNA
// atomistic mode so proteins coexist with cylinders/beads/atomistic DNA. Owns a
// dedicated atomistic renderer instance, a transform gizmo for the selected
// protein, the coalesced server re-fetch, and the two store subscriptions that
// keep proteins + selection visual in sync.
//
// Lifted verbatim from main.js (extraction #85). Two atomistic renderer instances
// exist in main(): the global DNA `atomisticRenderer` and this `proteinRenderer` —
// distinct so proteins draw regardless of the DNA representation mode.
import * as THREE from 'three'
import { initAtomisticRenderer } from './atomistic_renderer.js'
import { initProteinTraceRenderer } from './protein_trace_renderer.js'
import { initProteinGizmo } from './protein_gizmo.js'
import { docHeaders } from '../shared/doc_id.js'
import { primaryRefOfKind } from './selection_model.js'

export function initProteinSubsystem({
  scene, store, controls, camera, canvas,
  designRenderer = null, overhangLocations = null, getBluntEnds = null,
  rightSidebar = null,
}) {
  // Protein renderer (imported proteins; independent of the DNA atomistic
  // mode so proteins coexist with cylinders/beads/atomistic DNA).
  const atomisticProteinRenderer = initAtomisticRenderer(scene)
  const traceProteinRenderer = initProteinTraceRenderer(scene)
  let _representation = 'full'
  const _activeRenderer = () => _representation === 'full' || _representation === 'cylinders'
    ? traceProteinRenderer : atomisticProteinRenderer
  // Stable public renderer contract consumed by picking, oxDNA display, and
  // the protein gizmo. Representation changes swap the active implementation
  // without making those callers representation-aware.
  const proteinRenderer = {
    update(data) {
      atomisticProteinRenderer.update(data)
      traceProteinRenderer.update(data)
    },
    setMode(mode) {
      if (mode === 'trace' || mode === 'ovoid') {
        atomisticProteinRenderer.setMode('off')
        traceProteinRenderer.setMode(mode)
      } else {
        traceProteinRenderer.setMode('off')
        atomisticProteinRenderer.setMode(mode)
      }
    },
    getMode: () => _activeRenderer().getMode(),
    centroidOf: (...args) => _activeRenderer().centroidOf(...args),
    raycastPick: (...args) => _activeRenderer().raycastPick(...args),
    highlight(selection) {
      atomisticProteinRenderer.highlight(selection)
      traceProteinRenderer.highlight(selection)
    },
    beginLiveTransform: (...args) => _activeRenderer().beginLiveTransform(...args),
    applyLiveTransform: (...args) => _activeRenderer().applyLiveTransform(...args),
    endLiveTransform: (...args) => _activeRenderer().endLiveTransform(...args),
    applyOxdnaTransforms(transforms) {
      atomisticProteinRenderer.applyOxdnaTransforms(transforms)
      traceProteinRenderer.applyOxdnaTransforms(transforms)
    },
    clearOxdnaTransforms() {
      atomisticProteinRenderer.clearOxdnaTransforms()
      traceProteinRenderer.clearOxdnaTransforms()
    },
    dispose() {
      atomisticProteinRenderer.dispose()
      traceProteinRenderer.dispose()
    },
  }
  const _proteinCentroid = (id) =>
    proteinRenderer.centroidOf(a => a.helix_id === `__protein__${id}`)
  let _constraints = new Map()
  let _moveRotatePanel = null

  function _captureConstraintGeometry(constraint) {
    const hid = constraint?.helix_id
    if (!hid) return
    const domainIds = constraint.domain_ids?.length ? constraint.domain_ids : null
    designRenderer?.getHelixCtrl?.()?.captureClusterBase(
      [hid], domainIds,
    )
    getBluntEnds?.()?.captureClusterBase?.(
      new Set([constraint.overhang_id]), false, domainIds,
    )
    // Deliberately do not append a helix-wide forceAxes capture here. A stub
    // helix may contain several overhang/conjugate domains even though it has
    // no scaffold. The old independent-shaft implementation (479e9e39) kept
    // those domains separate; appending an unfiltered capture reintroduced the
    // exact regression where every sibling axis segment followed one protein.
  }

  function _applyConstraintGeometry(meta) {
    const constraint = meta?.constraint
    const hid = constraint?.helix_id
    if (!hid) return
    const root = new THREE.Vector3(...constraint.root)
    const start = new THREE.Vector3(...constraint.joint).sub(root)
    const current = (meta.constrainedJoint ?? meta.position).clone().sub(root)
    if (start.lengthSq() <= 1e-24 || current.lengthSq() <= 1e-24) return
    const swing = new THREE.Quaternion().setFromUnitVectors(
      start.normalize(), current.normalize(),
    )
    const ids = [hid]
    const domainIds = constraint.domain_ids?.length ? constraint.domain_ids : null
    designRenderer?.getHelixCtrl?.()?.applyClusterTransform(
      ids, root, root, swing, domainIds,
    )
    getBluntEnds?.()?.applyClusterTransform?.(
      [constraint.overhang_id], root, root, swing, domainIds,
    )
    // Axis sticks and overhang cylinders are domain-owned. Never apply the
    // helix-wide overhangLocations transform during a protein drag: on a
    // shared stub it also moves labels/anchors for sibling domains.
  }

  // Transform gizmo for the selected protein. Drag/input changes stay in the
  // captured live preview until Apply commits one gizmo_move; Cancel/Reset use
  // the same snapshots so preview and saved coordinates share an exact basis.
  const proteinGizmo = initProteinGizmo(store, controls, {
    onCommitted: () => _refreshProteins(),
    onCancelled: () => _refreshProteins(),
    onLiveStart: (id) => {
      proteinRenderer.beginLiveTransform(a => a.helix_id === `__protein__${id}`)
      _captureConstraintGeometry(_constraints.get(id))
    },
    onLive:      (m, meta)  => {
      proteinRenderer.applyLiveTransform(m)
      _applyConstraintGeometry(meta)
    },
    onLiveEnd:   ()   => proteinRenderer.endLiveTransform(),
    onTransform: (translation, rotation) => {
      const e = new THREE.Euler().setFromQuaternion(new THREE.Quaternion(...rotation), 'XYZ')
      _moveRotatePanel?.setTransformValues?.(
        ...translation,
        THREE.MathUtils.radToDeg(e.x), THREE.MathUtils.radToDeg(e.y), THREE.MathUtils.radToDeg(e.z),
      )
    },
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
      // Switching directly between proteins implicitly cancels the previous
      // preview. cancel() restores its captured protein/DNA geometry and the
      // authoritative refresh below re-enters here for the new selection.
      const attachedId = proteinGizmo.getAttachmentId?.()
      if (attachedId && attachedId !== protId) {
        proteinGizmo.cancel?.()
        return
      }
      proteinRenderer.highlight({ type: 'protein', id: protId, data: { attachment_id: protId } })
      const constraint = _constraints.get(protId) ?? null
      proteinGizmo.attach(protId, scene, camera, canvas, c, constraint)
      _moveRotatePanel?.setProteinController?.(proteinGizmo)
      _moveRotatePanel?.setSessionMode?.('protein')
      _moveRotatePanel?.setTransformValues?.(0, 0, 0, 0, 0, 0)
      rightSidebar?.open?.('properties')
      const panel = document.getElementById('move-rotate-panel')
      if (panel) {
        panel.style.display = ''
        panel.dataset.proteinActive = 'true'
      }
      const selectionBox = document.getElementById('mr-current-selection')
      if (selectionBox) selectionBox.textContent = `Protein · ${protId}`
      const hint = document.getElementById('mr-session-hint')
      if (hint) hint.textContent = constraint
        ? 'Drag the protein joint. The conjugate oligo is constrained live.'
        : 'Drag the protein gizmo. Press T or R to change mode.'
    } else {
      // Clicking away is Cancel, never Apply. Restore the pre-move snapshot
      // before dropping the gizmo so an uncommitted preview cannot persist.
      if (proteinGizmo.isAttached()) proteinGizmo.cancel?.()
      _moveRotatePanel?.setProteinController?.(null)
      proteinRenderer.highlight(null)
      const panel = document.getElementById('move-rotate-panel')
      if (panel?.dataset.proteinActive === 'true') {
        panel.style.display = 'none'
        delete panel.dataset.proteinActive
      }
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
      _constraints = new Map(
        (data?.protein_constraints ?? []).map(item => [item.attachment_id, item])
      )
      if (data?.atoms?.length) {
        // Imported proteins participate in the scene representation.  The
        // molecular surface is owned by the global surface renderer (whose
        // backend payload now includes proteins); atom modes use this dedicated
        // renderer so protein picking and the transform gizmo keep working.
        const proteinMode = _representation === 'full'
          ? 'trace'
          : _representation === 'cylinders'
          ? 'ovoid'
          : ['vdw', 'ballstick', 'stick'].includes(_representation)
          ? _representation
          : (_representation === 'surface' ? 'off' : 'vdw')
        proteinRenderer.setMode(proteinMode)
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

  function _onRepresentationChange(event) {
    _representation = event?.detail?.representation ?? 'full'
    const mode = _representation === 'full'
      ? 'trace'
      : _representation === 'cylinders'
      ? 'ovoid'
      : ['vdw', 'ballstick', 'stick'].includes(_representation)
      ? _representation
      : (_representation === 'surface' ? 'off' : 'vdw')
    proteinRenderer.setMode(mode)
    _syncProteinSelectionVisual()
  }
  window.addEventListener('nadoc:representation-change', _onRepresentationChange)

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
    setMoveRotatePanel(panel) {
      _moveRotatePanel = panel
      _moveRotatePanel?.setProteinController?.(proteinGizmo.isAttached() ? proteinGizmo : null)
    },
    dispose() {
      window.removeEventListener('nadoc:representation-change', _onRepresentationChange)
      proteinRenderer.dispose?.()
      proteinGizmo.detach?.()
    },
  }
}
