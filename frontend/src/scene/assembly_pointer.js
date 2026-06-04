// Assembly canvas pointer handlers — extracted from main.js (carve-up Tier 3,
// sub-part (b): instance / cluster selection click). Verbatim-equivalent lift of
// `_onAssemblyClick` + its single-use helper `_toggleAssemblyOverhangSelection`.
//
// The handler reads/writes four pieces of mutable state that sibling handlers
// (pointer-down, contextmenu, cluster-context) in main.js also touch, so those
// are passed in as get/set shims rather than owned here. `clusterPanel` is wired
// after this factory in main(), so it comes in as a lazy getter. Everything else
// is a stable dep defined before construction.
//
// Behaviour is identical to the in-closure original; the gesture is covered by
// e2e/assembly_select.spec.js (real raycast) and the branch logic by
// scene/assembly_pointer.test.js (jsdom + mock deps).
import * as THREE from 'three'
import { showToast } from '../ui/toast.js'
import { resolveGroupClickThrough } from './assembly_groups_util.js'

export function initAssemblyPointer({
  store,
  camera,
  assemblyRenderer,
  assemblyJointRenderer,
  instanceGizmo,
  clusterGlowLayer,
  overhangHoverPicker,
  getClusterPanel,
  canvasNdc,
  clusterBackboneEntries,
  confirmTranslateRotateTool,
  activateTranslateRotateTool,
  hasAssemblyPending,
  commitAssemblyPending,
  showProgress,
  hideProgress,
  // shared mutable state (owned by main.js, also touched by sibling handlers)
  getAssemblyPtrDownAt,
  setAssemblyPtrDownAt,
  getTranslateRotateActive,
  setSelectedAssemblyCluster,
  setAssemblySelectedPartJoint,
}) {
  // Toggle an overhang into/out of the ordered assembly overhang selection.
  // First two entries become the Overhangs Manager's Side A / Side B on open.
  function _toggleAssemblyOverhangSelection(oh) {
    const cur = store.getState().assemblyOverhangSelection ?? []
    const idx = cur.findIndex(s => s.instanceId === oh.instanceId && s.overhangId === oh.overhangId)
    const name = oh.label ? `“${oh.label}” ` : ''
    let next
    if (idx >= 0) {
      next = cur.filter((_, i) => i !== idx)
      showToast(`Overhang ${name}deselected`)
    } else {
      next = [...cur, { instanceId: oh.instanceId, overhangId: oh.overhangId, label: oh.label }]
      const side = next.length === 1 ? 'A' : next.length === 2 ? 'B' : `#${next.length}`
      showToast(`Overhang ${name}→ Side ${side}`)
    }
    store.setState({ assemblyOverhangSelection: next })
  }

  async function onAssemblyClick(e) {
    if (e.button !== 0) return
    // Belt-define mode owns the canvas (revolute-marker + rim-connector picks).
    // Suppress normal part/group selection so picking a rim doesn't box-select
    // the part underneath it.
    if (assemblyJointRenderer.isBeltMode() || assemblyJointRenderer.isAttachMode()) { setAssemblyPtrDownAt(null); return }
    const ptrDownAt = getAssemblyPtrDownAt()
    if (!ptrDownAt) return
    const dx = e.clientX - ptrDownAt.x
    const dy = e.clientY - ptrDownAt.y
    setAssemblyPtrDownAt(null)
    if (dx * dx + dy * dy > 25) return   // was a drag, not a click

    // (Ctrl/Meta-click multi-select toggle now lives in the assembly-lasso
    // factory's onClick: a tiny Ctrl-drag finalizes as a click → toggle. The
    // former branch here was unreachable — Ctrl-pointerdown starts the lasso and
    // never sets _assemblyPtrDownAt, so this handler never saw a Ctrl-click.)

    // ── PartGroup click-through (PowerPoint-style) ─────────────────────────
    // Behavior:
    //  - Click a part that belongs to a group whose group is NOT currently
    //    selected → select the GROUP (not the individual part). Visual: purple
    //    union BoxHelper + group gizmo at centroid.
    //  - Click a part inside the currently-selected group → "enter" the group:
    //    push the gid onto groupDiveStack, clear activeGroupId, and fall
    //    through to the regular single-instance selection below.
    //  - Click an ungrouped part → falls through.
    // The dive stack lets Escape (future) pop one level back to the group.
    {
      const sNow = store.getState()
      const earlyHit = assemblyRenderer.pickInstance(canvasNdc(e), camera)
      const decision = resolveGroupClickThrough({
        assembly:       sNow.currentAssembly,
        hitInstanceId:  earlyHit?.id ?? null,
        activeGroupId:  sNow.activeGroupId,
        groupDiveStack: sNow.groupDiveStack ?? [],
      })
      // selectGroup → first click on a grouped part: select the group, no
      // fallthrough. enterGroup → second click on a member of the active group:
      // push the dive stack and fall through so the part gets selected below.
      if (decision.action === 'selectGroup') { store.setState(decision.patch); return }
      if (decision.action === 'enterGroup') { store.setState(decision.patch) }
    }

    // Non-Ctrl click — always collapses any active multi-select back to either
    // a fresh single-select (click on a part) or no selection (click on empty
    // space). Without this, the purple union box stays painted after the user
    // moves on and tries to interact with something else.
    {
      const s = store.getState()
      if ((s.multiSelectedInstanceIds ?? []).length || s.activeGroupId) {
        store.setState({ multiSelectedInstanceIds: [], activeGroupId: null, groupDiveStack: [] })
      }
    }

    // Overhang selection — a click within a medium radius of an overhang
    // toggles it into the ordered selection (which prefills the Overhangs
    // Manager's Side A / Side B on open) and shows a green ring + persistent
    // label, rather than selecting/moving the part. Gated on the overhang tool
    // (the "ovhg" button → toolFilters.overhangLocations): when the tool is
    // off, clicks ignore overhangs entirely and fall through to part selection.
    // When on, a click that lands on anything that ISN'T an overhang (part body
    // or empty space) clears the overhang selection, then falls through.
    if (store.getState().toolFilters?.overhangLocations) {
      const oh = overhangHoverPicker.nearestAt(e.clientX, e.clientY)
      if (oh) { _toggleAssemblyOverhangSelection(oh); return }
      if ((store.getState().assemblyOverhangSelection ?? []).length)
        store.setState({ assemblyOverhangSelection: [] })
    }

    // While the move/rotate gizmo is active, a click ON the selected
    // instance is left to the gizmo (it intercepts its own handle hits at
    // pointerdown; a click on the instance body is a no-op so the user can
    // grab handles freely).  A click ANYWHERE ELSE — empty space or a
    // different instance — commits the pending transform, then falls
    // through to normal selection (which may select + re-arm the gizmo on
    // the new target, or clear the selection).  Replaces the green-check
    // confirm button.
    if (getTranslateRotateActive()) {
      // A click that landed on a gizmo handle (translate arrow / rotate
      // ring) must not commit — the user is grabbing the gizmo.  The
      // TransformControls `axis` is non-null while the cursor is over a
      // handle.  Likewise a drag that just finished is handled by the
      // gizmo's own dragging-changed → onCommit path.
      if (instanceGizmo.getActiveAxis() || instanceGizmo.isDragging()) return
      const hitDuringGizmo = assemblyRenderer.pickInstance(canvasNdc(e), camera)
      if (hitDuringGizmo && hitDuringGizmo.id === store.getState().activeInstanceId) {
        return  // click on the active instance body → leave the gizmo alone
      }
      await confirmTranslateRotateTool()
      // Fall through: this same click now (re)selects whatever was under it.
    }

    const inst   = assemblyRenderer.pickInstance(canvasNdc(e), camera)
    const prevId = store.getState().activeInstanceId

    // Re-clicking the already-active instance → pick cluster and highlight
    if (inst && inst.id === prevId) {
      const clusterHit = assemblyRenderer.pickInstanceCluster(canvasNdc(e), camera, { scopeInstId: inst.id })
      if (clusterHit?.cluster) {
        const { entries, matrixWorld } = assemblyRenderer.getInstanceBackboneEntries(inst.id)
        const design = assemblyRenderer.getInstanceDesign(inst.id)
        const localEntries = clusterBackboneEntries(clusterHit.cluster, design, entries)
        const worldEntries = localEntries.map(e2 => ({ ...e2, pos: e2.pos.clone().applyMatrix4(matrixWorld) }))
        clusterGlowLayer.setEntries(worldEntries)
        getClusterPanel()?.selectAssemblyCluster?.(inst.id, clusterHit.cluster.id)
        setSelectedAssemblyCluster({ instanceId: inst.id, clusterId: clusterHit.cluster.id })
        instanceGizmo.detach()
      }
      return
    }

    const newId = inst ? inst.id : null
    if (newId !== prevId && hasAssemblyPending()) {
      showProgress('Updating Assembly', 'Applying part transform…', { indeterminate: true })
      await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))
      try {
        await commitAssemblyPending()
      } finally {
        hideProgress()
      }
    }
    if (newId !== prevId) setAssemblySelectedPartJoint(null)
    store.setState({ activeInstanceId: newId })
    // Selecting an instance by click immediately attaches the move/rotate
    // gizmo so the user can manipulate it without an extra menu step.
    // Skipped when the click cleared the selection (newId == null).
    if (newId && newId !== prevId) {
      await activateTranslateRotateTool()
    }
  }

  return { onAssemblyClick }
}
