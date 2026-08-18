import * as THREE from 'three'
import { quatToEulerDeg } from './rotation_math.js'
import { showToast } from '../ui/toast.js'
import { showOpProgress, hideOpProgress } from '../ui/op_progress.js'
import { registerShortcut } from '../input/shortcuts.js'
import { canonicalSelection, selectedClusterIds } from './selection_model.js'
import { parseBaseKey } from './base_ref.js'

/**
 * Translate/Rotate tool — the design-mode cluster gizmo + assembly-mode instance
 * gizmo "Move/Rotate" session: activate / confirm / cancel / rotate-joint, the
 * pointer-pick handler for joint rotation rings, and the floating ✓ confirm button.
 *
 * Lifted verbatim from main.js (#81). The session flag `_translateRotateActive`
 * (read/written from 22 sites incl. the lifecycle spine), `_clusterDirty`, and the
 * deform-editor-shared `_editContext` stay main-owned `let`s — the factory reaches
 * them via getActive/setActive, getClusterDirty/setClusterDirty,
 * getEditContext/setEditContext shims. `jointRenderer` is declared AFTER this
 * factory in main(), so it is injected lazily via getJointRenderer().
 */
/**
 * Pure decision for the selection→tool bridge. Selection never activates or closes
 * Move/Rotate; it can only retarget an explicitly active tool to another cluster.
 *
 * Parts-editor only: open/retarget/close are gated so nothing fires in assembly / cadnano
 * / unfold modes.
 *
 * @returns {{ action: 'retarget'|'none', clusterId: string|null }}
 */
export function decideSelectionAction({ newSel, toolActive, activeClusterId, mode }) {
  const partsEditor = !!mode && !mode.assemblyActive && !mode.cadnanoActive && !mode.unfoldActive
  const newCid = newSel?.kind === 'cluster' ? newSel.id ?? null : null
  // Selection never arms or closes the tool. Once explicitly armed, a cluster click
  // may still retarget the live gizmo; this keeps selection and tool activation as
  // separate user actions while preserving the useful in-tool switching gesture.
  if (!partsEditor || !toolActive || !newCid) return { action: 'none', clusterId: null }
  if (newCid !== activeClusterId) return { action: 'retarget', clusterId: newCid }
  return { action: 'none', clusterId: null }
}

/** Resolve the current selection to an existing rigid-transform scope.
 *
 * This is the first entity-neutral seam in the cluster-centric tool. Exact
 * domain membership wins over a helix-level cluster, so a selected base/domain
 * in a child or sub-cluster targets the narrowest transform already represented
 * by the design model. It intentionally does not invent a persistent cluster:
 * ClusterRigidTransform currently bottoms out at domains, not individual beads.
 */
export function resolveSelectionClusterId(ref, design) {
  const clusters = design?.cluster_transforms ?? []
  if (!ref || !clusters.length) return null
  if (ref.kind === 'cluster') {
    const id = ref.id ?? null
    return clusters.some(c => c.id === id) ? id : null
  }

  const strandId = ref.kind === 'strand' ? ref.id : ref.kind === 'domain' ? ref.strandId : null
  const domainIndex = ref.kind === 'domain' ? ref.domainIndex : null
  const base = (ref.kind === 'base' || ref.kind === 'end') ? parseBaseKey(ref.key) : null
  let helixId = base?.helix_id !== '__xb__' ? base?.helix_id ?? null : null
  if (strandId && domainIndex != null) {
    const exact = clusters.find(c => (c.domain_ids ?? []).some(
      d => d.strand_id === strandId && d.domain_index === domainIndex))
    if (exact) return exact.id
  }

  const strand = design?.strands?.find(s => s.id === strandId)
  if (!helixId && domainIndex != null) helixId = strand?.domains?.[domainIndex]?.helix_id ?? null
  const helixIds = new Set(helixId ? [helixId] : (strand?.domains ?? []).map(d => d.helix_id).filter(Boolean))
  if (!helixIds.size) return null
  return clusters.find(c => (c.helix_ids ?? []).some(id => helixIds.has(id)))?.id ?? null
}

export function initTranslateRotateTool(deps) {
  const {
    store, scene, camera, canvas,
    designRenderer,
    getJointRenderer,
    clusterGizmo, instanceGizmo, nucleotideTransformTool,
    assemblyRenderer, assemblyJointRenderer,
    api,
    moveRotatePanel,
    mrPanel, mrPivotSel,
    setTransformValues, setTransformValuesFromMatrix,
    setPivotOptions, setSelectedPivot, refreshCurrentSelection,
    createAssemblyTransformContext,
    hasAssemblyPending, commitAssemblyPending,
    assemblyPendingTransforms, assemblyPendingPartJoints,
    attachGroupGizmo,
    flexRelax,
    refreshClusterPivotForAttach,
    pickActiveClusterEntry,
    syncAssemblyBluntEnds,
    rebakeHelixAxesForClusterDelta,
    reemitClusterBridges,
    refreshClusterOverlays,
    getActive, setActive,
    getClusterDirty, setClusterDirty,
    getEditContext, setEditContext,
  } = deps

  // Internal aliases keep the lifted fn bodies byte-for-byte verbatim.
  const _showProgress = showOpProgress
  const _hideProgress = hideOpProgress
  const _mrPanel = mrPanel
  const _mrPivotSel = mrPivotSel
  const _mrSetTransformValues = setTransformValues
  const _mrSetTransformValuesFromMatrix = setTransformValuesFromMatrix
  const _mrSetPivotOptions = setPivotOptions
  const _mrSetSelectedPivot = setSelectedPivot
  const _mrRefreshCurrentSelection = refreshCurrentSelection
  const _moveRotatePanel = moveRotatePanel
  const _createAssemblyTransformContext = createAssemblyTransformContext
  const _hasAssemblyPending = hasAssemblyPending
  const _commitAssemblyPending = commitAssemblyPending
  const _assemblyPendingTransforms = assemblyPendingTransforms
  const _assemblyPendingPartJoints = assemblyPendingPartJoints
  const _attachGroupGizmo = attachGroupGizmo
  const _flexRelax = flexRelax
  const _refreshClusterPivotForAttach = refreshClusterPivotForAttach
  const _pickActiveClusterEntry = pickActiveClusterEntry
  const _syncAssemblyBluntEnds = syncAssemblyBluntEnds
  const _rebakeHelixAxesForClusterDelta = rebakeHelixAxesForClusterDelta
  const _reemitClusterBridges = reemitClusterBridges
  const _refreshClusterOverlays = refreshClusterOverlays

  let _vrPreview = null
  let _vrQueuedMatrix = null
  let _vrStarting = null

  function _applyVRPreviewMatrix(matrixValues) {
    if (!Array.isArray(matrixValues) || matrixValues.length !== 16 ||
        !matrixValues.every(Number.isFinite)) return false
    if (!_vrPreview) {
      _vrQueuedMatrix = [...matrixValues]
      return false
    }
    const delta = new THREE.Matrix4().fromArray(matrixValues)
    const deltaRotation = new THREE.Quaternion().setFromRotationMatrix(delta).normalize()
    const targetPosition = _vrPreview.basePosition.clone().applyMatrix4(delta)
    const targetRotation = deltaRotation.multiply(_vrPreview.baseRotation.clone()).normalize()
    const translation = targetPosition.sub(_vrPreview.pivot).toArray()
    clusterGizmo.setTransform(translation, targetRotation.toArray())
    return true
  }

  async function _beginVRPreview(clusterId) {
    if (_vrPreview?.clusterId === clusterId) return { accepted: true }
    if (_vrStarting) return _vrStarting
    if (getActive()) return { accepted: false, reason: 'desktop_tool_active' }
    const cluster = store.getState().currentDesign?.cluster_transforms?.find(
      candidate => candidate.id === clusterId)
    if (!cluster) return { accepted: false, reason: 'cluster_missing' }
    _vrStarting = (async () => {
      await _activateTranslateRotateTool(clusterId)
      const current = store.getState().currentDesign?.cluster_transforms?.find(
        candidate => candidate.id === clusterId)
      const pending = clusterGizmo.getPendingTransform(clusterId)
      const baseline = pending ?? current
      if (!baseline) return { accepted: false, reason: 'cluster_missing' }
      const pivot = new THREE.Vector3(...baseline.pivot)
      const translation = new THREE.Vector3(...baseline.translation)
      _vrPreview = {
        clusterId,
        pivot,
        basePosition: pivot.clone().add(translation),
        baseRotation: new THREE.Quaternion(...baseline.rotation).normalize(),
      }
      if (_vrQueuedMatrix) {
        const queued = _vrQueuedMatrix
        _vrQueuedMatrix = null
        _applyVRPreviewMatrix(queued)
      }
      return { accepted: true }
    })()
    try {
      return await _vrStarting
    } finally {
      _vrStarting = null
    }
  }

  async function _cancelVRPreview() {
    _vrQueuedMatrix = null
    if (_vrStarting) await _vrStarting
    if (!_vrPreview) return false
    _vrPreview = null
    await _cancelTranslateRotateTool()
    return true
  }

  async function _onToolPickPointerDown(e) {
    if (e.button != null && e.button !== 0) return

    // Check for a drag start on a joint rotation ring (pointerdown, not click,
    // so setPointerCapture works correctly).
    const ringJointId = getJointRenderer().pickJointRing(e)
    if (!ringJointId) {
      if (!clusterGizmo.isJointConstraintActive?.()) return
      const joint = clusterGizmo.getActiveJoint?.()
      if (!joint || !_pickActiveClusterEntry(e)) return
      e.stopImmediatePropagation()
      clusterGizmo.beginConstrainedRotation(joint, e)
      return
    }
    const design = store.getState().currentDesign
    const joint  = design?.cluster_joints?.find(j => j.id === ringJointId)
    if (!joint) return

    // Ensure the joint's cluster is the active one before starting the drag.
    const { activeClusterId, currentDesign: cd } = store.getState()
    if (joint.cluster_id !== activeClusterId) {
      const cluster = cd?.cluster_transforms?.find(c => c.id === joint.cluster_id)
      if (!cluster) {
        // Cluster not ready — just switch cluster; user can drag on next pointerdown.
        store.setState({ activeClusterId: joint.cluster_id })
        return
      }
      await _refreshClusterPivotForAttach(joint.cluster_id)
      clusterGizmo.attach(joint.cluster_id, scene, camera, canvas)
    }

    _mrSetSelectedPivot(ringJointId)
    clusterGizmo.beginConstrainedRotation(joint, e)
  }

  // Checkmark confirm button (bottom-left, shown only when tool is active)
  const _confirmBtn = document.createElement('div')
  _confirmBtn.style.cssText = [
    'position:fixed;bottom:24px;left:24px;display:none',
    'width:56px;height:56px;border-radius:50%',
    'background:#1a6b2a;border:3px solid #2ea043',
    'cursor:pointer;align-items:center;justify-content:center',
    'font-size:30px;color:#fff;z-index:9000',
    'box-shadow:0 2px 16px rgba(46,160,67,0.5)',
    'transition:background 0.12s,transform 0.1s;user-select:none',
  ].join(';')
  _confirmBtn.textContent = '✓'
  _confirmBtn.title = 'Confirm transforms and exit tool'
  _confirmBtn.addEventListener('mouseenter', () => { _confirmBtn.style.background = '#2ea043'; _confirmBtn.style.transform = 'scale(1.08)' })
  _confirmBtn.addEventListener('mouseleave', () => { _confirmBtn.style.background = '#1a6b2a'; _confirmBtn.style.transform = 'scale(1)' })
  document.body.appendChild(_confirmBtn)

  async function _activateTranslateRotateTool(targetClusterId = null) {
    const { assemblyActive, activeInstanceId, currentDesign } = store.getState()

    // ── Assembly mode: attach instance gizmo ────────────────────────────────
    if (assemblyActive) {
      if (!activeInstanceId) {
        showToast('Select an instance first by clicking it in the viewport or its row in the Assembly panel.', { severity: 'error' })
        return
      }
      const _instForGizmo = store.getState().currentAssembly?.instances?.find(i => i.id === activeInstanceId)
      if (_instForGizmo?.fixed) {
        showToast('This part is marked as Fixed and cannot be moved. Uncheck Fixed in the right-click menu to enable movement.', { severity: 'error' })
        return
      }
      const ctx = _createAssemblyTransformContext(activeInstanceId)
      if (!ctx) return
      _moveRotatePanel.setAssemblyCtx(ctx)
      _moveRotatePanel.setSessionMode?.('assembly')
      setActive(true)
      document.getElementById('mode-indicator').textContent = 'MOVE — Tab: move/rotate · click elsewhere: commit · Esc: cancel'
      _attachGroupGizmo(activeInstanceId, ctx)
      _mrRefreshCurrentSelection?.()
      if (_mrPivotSel) _mrPivotSel.disabled = true
      _mrSetPivotOptions([])
      _mrSetSelectedPivot('centroid')
      _mrSetTransformValuesFromMatrix(ctx.primaryStart)
      if (_mrPanel) _mrPanel.style.display = ''
      // No confirm checkmark in assembly mode — committing happens by
      // clicking anywhere other than the selected instance (see
      // _onAssemblyClick), or via Esc to cancel.  The checkmark is still
      // used by the design-mode cluster gizmo path below.
      _confirmBtn.style.display = 'none'
      return
    }

    // ── Design mode: attach cluster gizmo ───────────────────────────────────
    const clusters = currentDesign?.cluster_transforms ?? []
    setClusterDirty(false)
    setActive(true)
    document.getElementById('mode-indicator').textContent = 'MOVE/ROTATE — Esc: cancel'

    // ── Multi-selected clusters → drive them all as one rigid body ──────────────
    // Only when the caller did NOT pre-target a specific cluster (Rotate button,
    // joint rotate, strand-click retarget all pass one). Keep only canonical ids
    // that are real movable clusters.
    if (!targetClusterId) {
      const groupIds = selectedClusterIds(store.getState())
        .filter(id => clusters.some(c => c.id === id))
      if (groupIds.length > 1) {
        await _showClusterGroup(groupIds, clusters)
        return
      }
    }

    // With no target, arm the tool and wait. Selection remains independent from
    // activation; the first compatible entity selected below becomes the target.
    const first = targetClusterId && clusters.find(c => c.id === targetClusterId)
    if (!first) {
      _moveRotatePanel.setAssemblyCtx(null)
      _moveRotatePanel.setSessionMode?.('waiting')
      if (_mrPivotSel) _mrPivotSel.disabled = true
      _mrSetPivotOptions([])
      _mrSetSelectedPivot('centroid')
      _mrRefreshCurrentSelection?.()
      if (_mrPanel) _mrPanel.style.display = ''
      _confirmBtn.style.display = 'flex'
      document.getElementById('mode-indicator').textContent =
        'MOVE/ROTATE — select an entity · Esc: cancel'
      return
    }
    await _refreshClusterPivotForAttach(first.id)
    clusterGizmo.attach(first.id, scene, camera, canvas)

    canvas.addEventListener('pointerdown', _onToolPickPointerDown)

    // Populate and show the right-sidebar move/rotate panel
    _moveRotatePanel.setAssemblyCtx(null)
    _moveRotatePanel.setSessionMode?.('cluster')
    if (_mrPivotSel) _mrPivotSel.disabled = false
    _mrRefreshCurrentSelection?.()
    await _flexRelax.refreshFlexGates()
    const initJoints = store.getState().currentDesign?.cluster_joints?.filter(j => j.cluster_id === first.id) ?? []
    _mrSetPivotOptions(initJoints, first.id)
    _mrSetSelectedPivot('centroid')
    // Read from the gizmo's pending (pivot-rebased) transform when present so the number
    // boxes match the pivot the gizmo actually uses (duplex pivot teleport fix — see
    // move_rotate_panel / cluster P2 notes).
    const _pend = clusterGizmo.getPendingTransform(first.id)
    const _t = _pend?.translation ?? first.translation
    const _r = _pend?.rotation ?? first.rotation
    const [irx, iry, irz] = quatToEulerDeg(_r)
    _mrSetTransformValues(_t[0], _t[1], _t[2], irx, iry, irz)
    if (_mrPanel) _mrPanel.style.display = ''
  }

  // Activate (or switch) the move/rotate tool targeting a specific joint's cluster and axis.
  async function _rotateJoint(joint) {
    const { currentDesign } = store.getState()
    const clusters = currentDesign?.cluster_transforms ?? []

    if (!getActive()) {
      await _activateTranslateRotateTool(joint.cluster_id)
    } else if (joint.cluster_id !== store.getState().activeClusterId) {
      // Tool already active but pointing at a different cluster — switch it.
      await _refreshClusterPivotForAttach(joint.cluster_id)
      clusterGizmo.attach(joint.cluster_id, scene, camera, canvas)
      const joints = currentDesign?.cluster_joints?.filter(j => j.cluster_id === joint.cluster_id) ?? []
      _mrSetPivotOptions(joints)
    }

    // Point the gizmo at this joint — overrides whatever centroid default was just set.
    _mrSetSelectedPivot(joint.id)
    clusterGizmo.setConstraint('joint', joint)
  }

  function _removeToolPickListeners() {
    canvas.removeEventListener('pointerdown', _onToolPickPointerDown)
  }

  async function _restoreTransformPreviewFromStore() {
    const { currentDesign, currentGeometry, currentHelixAxes } = store.getState()
    if (!currentGeometry) return

    // Force local renderers back to the committed store geometry. Dragging only
    // mutates scene objects and pending gizmo state, so no backend undo is needed.
    store.setState({
      currentGeometry: [...currentGeometry],
      currentHelixAxes: currentHelixAxes ? { ...currentHelixAxes } : currentHelixAxes,
      lastPartialChangedHelixIds: null,
    })
    getJointRenderer().rebuild(currentDesign)
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))
  }

  async function _confirmTranslateRotateTool() {
    if (!getActive()) return
    if (_vrPreview) {
      showToast('VR Move / Rotate is preview-only; use Cancel to restore the design.')
      return
    }
    setActive(false)
    _confirmBtn.style.display = 'none'
    if (_mrPanel) _mrPanel.style.display = 'none'

    if (store.getState().assemblyActive) {
      instanceGizmo.detach()
      if (_hasAssemblyPending()) {
        _showProgress('Updating Assembly', 'Applying part transform…', { indeterminate: true })
        try {
          await _commitAssemblyPending()
        } finally {
          _hideProgress()
        }
      }
      _moveRotatePanel.setAssemblyCtx(null)
      if (_mrPanel) _mrPanel.style.display = 'none'
      document.getElementById('mode-indicator').textContent = 'ASSEMBLY MODE'
      return
    }

    // Edit-in-place for cluster_op feature_log entries: instead of letting
    // commitPendingTransforms append a new ClusterOpLogEntry, route the
    // pending transform for the edited cluster through api.editFeature so
    // the existing entry's translation/rotation/pivot are updated in place.
    //
    // Important: the gizmo's live drag has ALREADY painted the new positions
    // into the renderer (Plan B's whole point). The editFeature response
    // identifies a cluster_only diff (old → new transform), but applying
    // that delta here would double-move the cluster — the visual is already
    // at "new". We mirror the standard cluster-commit post-processing
    // (commitClusterPositions, refreshBridges, overlay rebuilds) instead of
    // calling _applyResponseDelta.
    const editCtx = getEditContext()
    if (getClusterDirty() && editCtx?.editingFeatureType === 'cluster_op') {
      // null = editing the LATEST op (in-place path); a number = editing an
      // EARLIER op, restore the cursor to this position (the latest pose) after.
      const restoreCursor = editCtx.seekRestoreCursor ?? null
      setEditContext(null)
      _showProgress('Applying Change', 'Updating transformed geometry…', { indeterminate: true })
      await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))
      try {
        const pending = clusterGizmo.getPendingTransform(editCtx.clusterId)
        if (pending && restoreCursor !== null) {
          // Earlier-op edit: rewrite just this step's stored pose, then (after
          // the gizmo tears down in `finally`) seek back to the latest pose. The
          // seek — same path as the feature-log slider — re-derives + renders the
          // final state, so the in-place post-processing below is skipped.
          api.skipNextResponseDelta()
          await api.editFeature(editCtx.featureIndex, pending)
          clusterGizmo.clearPendingTransform(editCtx.clusterId)
        } else if (pending) {
          // Snapshot pre-edit transform so we can rebake helix axes after
          // commit (matches the standard commit path).
          const preDesign = store.getState().currentDesign
          const preCt = preDesign?.cluster_transforms?.find(c => c.id === editCtx.clusterId)
          const oldCt = preCt ? {
            pivot:       [...preCt.pivot],
            translation: [...preCt.translation],
            rotation:    [...preCt.rotation],
            helix_ids:   [...(preCt.helix_ids ?? [])],
          } : null
          // The gizmo's live drag has already moved beads/joints/hulls to
          // the post-edit state. Ask the client.js layer NOT to apply the
          // cluster_only delta this response will carry — applying it on
          // top of the gizmo's already-applied transform would double-move
          // the cluster.
          api.skipNextResponseDelta()
          await api.editFeature(editCtx.featureIndex, pending)
          clusterGizmo.clearPendingTransform(editCtx.clusterId)

          const helixCtrl = designRenderer.getHelixCtrl()
          if (helixCtrl) {
            const design = store.getState().currentDesign
            const ct = design?.cluster_transforms?.find(c => c.id === editCtx.clusterId)
            const helixIds = ct?.helix_ids ?? []
            if (helixIds.length) {
              helixCtrl.commitClusterPositions(helixIds)
              // Sub-cluster (domain_ids) moves don't rigidly transform the
              // helix, so skip the axis rebake for those.
              if (oldCt && ct && !ct.domain_ids?.length) {
                _rebakeHelixAxesForClusterDelta(oldCt.helix_ids, oldCt, ct)
              }
              getJointRenderer().rebuildHulls(store.getState().currentDesign)
              // Same Plan B bridge refresh as the standard commit path.
              await _reemitClusterBridges([editCtx.clusterId])
              // Same overlay refresh as the standard commit path.
              _refreshClusterOverlays({ withFlexibleArcs: false })
            }
          }
        }
      } finally {
        _hideProgress()
        setClusterDirty(false)
        clusterGizmo.detach()
        _removeToolPickListeners()
        document.getElementById('mode-indicator').textContent = 'NADOC · WORKSPACE'
      }
      // Earlier-op edit: now that the gizmo is detached, seek back to the cursor
      // we left (the latest pose) so the scene returns from this step to "now".
      if (restoreCursor !== null) await api.seekFeatures(restoreCursor)
      return
    }

    if (getClusterDirty()) {
      _showProgress('Applying Change', 'Updating transformed geometry…', { indeterminate: true })
      await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))
      try {
        // Snapshot pre-commit cluster_transforms so we can compute the
        // OLD→NEW delta after commit and rebake currentHelixAxes (which
        // Plan B's skipGeometry leaves stale). Without this, hull-prism
        // rebuilds (e.g. on next repr toggle or topology mutation) place
        // the hull at the pre-move position.
        const preDesign = store.getState().currentDesign
        const oldCtById = new Map()
        for (const ct of preDesign?.cluster_transforms ?? []) {
          oldCtById.set(ct.id, {
            pivot:       [...ct.pivot],
            translation: [...ct.translation],
            rotation:    [...ct.rotation],
            helix_ids:   [...(ct.helix_ids ?? [])],
          })
        }
        const { clusterIds } = await clusterGizmo.commitPendingTransforms({ log: true })
        // Plan B: patchCluster no longer refreshes backend geometry. Reconcile
        // currentGeometry with the rendered state for each committed cluster
        // so downstream consumers (oxDNA / atomistic / surface mesh /
        // save-and-reload / undo) see the post-cluster-transform positions.
        if (clusterIds.length) {
          const helixCtrl = designRenderer.getHelixCtrl()
          if (helixCtrl) {
            const design = store.getState().currentDesign
            const allHelixIds = new Set()
            for (const cid of clusterIds) {
              const ct = design?.cluster_transforms?.find(c => c.id === cid)
              if (ct?.helix_ids?.length) {
                for (const hid of ct.helix_ids) allHelixIds.add(hid)
              }
            }
            if (allHelixIds.size) {
              helixCtrl.commitClusterPositions([...allHelixIds])
              // Rebake currentHelixAxes for each moved cluster so any
              // subsequent rebuild from helix_axes (jointRenderer.rebuildHulls,
              // overhang locations, etc.) reads post-commit positions.
              // Skip sub-cluster moves: domain_ids means only PART of the
              // helix was transformed, so its axis isn't rigidly rotatable.
              for (const cid of clusterIds) {
                const oldCt = oldCtById.get(cid)
                const newCt = design?.cluster_transforms?.find(c => c.id === cid)
                if (newCt?.domain_ids?.length) continue
                if (oldCt && newCt) _rebakeHelixAxesForClusterDelta(oldCt.helix_ids, oldCt, newCt)
              }
              // Hull prism: live drag has already moved the outer group
              // rigidly, but rebuilding from the now-fresh axes gives a
              // hull whose orientation also reflects any cluster rotation.
              getJointRenderer().rebuildHulls(store.getState().currentDesign)
              // Re-emit ds-linker bridge nucs for the moved clusters (Plan B
              // skips backend geometry, so bridge midpoints go stale). Shared
              // single source of truth in response_delta.js. We want it before
              // the overlay rebuilds below.
              await _reemitClusterBridges(clusterIds)
              // Refresh overlays whose subscribers fired during patchCluster's
              // setState (with currentGeometry's nuc.backbone_position still
              // stale) and rebuilt themselves at pre-cluster-transform
              // positions. commitClusterPositions has now synced
              // backbone_position in-place, so re-rebuild explicitly here.
              _refreshClusterOverlays({ withFlexibleArcs: false })
            }
          }
        }
      } finally {
        _hideProgress()
      }
    }
    setClusterDirty(false)
    clusterGizmo.detach()
    _removeToolPickListeners()
    document.getElementById('mode-indicator').textContent = 'NADOC · WORKSPACE'
  }

  async function _cancelTranslateRotateTool() {
    if (!getActive()) return
    _vrPreview = null
    _vrQueuedMatrix = null
    const hadLocalPreview = getClusterDirty()
    setActive(false)
    _confirmBtn.style.display = 'none'
    if (_mrPanel) _mrPanel.style.display = 'none'
    // Drop any cluster_op edit context so the next gizmo session takes the
    // standard "append a new cluster_op" path. Capture the earlier-op seek-back
    // cursor first (null = latest-op edit / no seek to undo).
    const _editCtx = getEditContext()
    const cancelRestoreCursor = _editCtx?.editingFeatureType === 'cluster_op'
      ? (_editCtx.seekRestoreCursor ?? null)
      : null
    if (_editCtx?.editingFeatureType === 'cluster_op') setEditContext(null)

    if (store.getState().assemblyActive) {
      instanceGizmo.detach()
      _assemblyPendingTransforms.clear()
      _assemblyPendingPartJoints.clear()
      _moveRotatePanel.setAssemblyCtx(null)
      if (_mrPanel) _mrPanel.style.display = 'none'
      const assembly = store.getState().currentAssembly
      if (assembly) {
        await assemblyRenderer.rebuild(assembly)
        assemblyRenderer.rebuildLinkers(assembly)
        assemblyJointRenderer.rebuild(assembly)
        _syncAssemblyBluntEnds()
      }
      document.getElementById('mode-indicator').textContent = 'ASSEMBLY MODE'
      return
    }

    setClusterDirty(false)
    clusterGizmo.discardPendingTransforms?.()
    clusterGizmo.detach()
    _removeToolPickListeners()
    document.getElementById('mode-indicator').textContent = 'NADOC · WORKSPACE'

    if (hadLocalPreview) {
      _showProgress('Cancelling Transform', 'Restoring previous geometry…', { indeterminate: true })
      await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))
      try {
        await _restoreTransformPreviewFromStore()
      } finally {
        _hideProgress()
      }
    }
    // Earlier-op edit cancelled: the log entry is untouched; seek back to the
    // cursor we left so the scene returns from this step to the latest pose.
    if (cancelRestoreCursor !== null) await api.seekFeatures(cancelRestoreCursor)
  }

  // Attach the gizmo across `groupIds` as one rigid body and switch the panel into
  // group mode (dropdowns disabled, fields show the group delta = 0). Shared by tool
  // activation and the live multi-select subscriber, so a group can be entered either
  // by pressing `t` with a multi-selection OR by adding a cluster while the tool is open.
  async function _showClusterGroup(groupIds, clusters) {
    for (const id of groupIds) await _refreshClusterPivotForAttach(id)
    clusterGizmo.attachGroup(groupIds, scene, camera, canvas)
    _removeToolPickListeners()   // group mode has no joint picking
    document.getElementById('mode-indicator').textContent =
      `MOVE/ROTATE (${groupIds.length} clusters) — Tab: move/rotate · Esc: cancel`
    _moveRotatePanel.setAssemblyCtx(null)
    _moveRotatePanel.setSessionMode?.('cluster')
    if (_mrPivotSel) _mrPivotSel.disabled = true       // pivot is the combined centroid
    _mrRefreshCurrentSelection?.()
    _mrSetPivotOptions([])
    _mrSetSelectedPivot('centroid')
    _mrSetTransformValues(0, 0, 0, 0, 0, 0)   // fields show the group delta, starting at identity
    await _flexRelax.refreshFlexGates()
    if (_mrPanel) _mrPanel.style.display = ''
  }

  // Re-attach the gizmo to a SINGLE cluster (e.g. a group shrank back to one member).
  // attach() re-sets activeClusterId → the main.js active-cluster subscriber repopulates
  // the number boxes / pivot options / centroid constraint (it early-outs while a group
  // is active, so it only runs once we're back in single mode).
  async function _showClusterSingle(clusterId, clusters) {
    _moveRotatePanel.setSessionMode?.('cluster')
    if (_mrPivotSel) _mrPivotSel.disabled = false
    document.getElementById('mode-indicator').textContent = 'MOVE/ROTATE — Esc: cancel'
    _mrRefreshCurrentSelection?.()
    canvas.addEventListener('pointerdown', _onToolPickPointerDown)   // dedup by the browser
    await _refreshClusterPivotForAttach(clusterId)
    clusterGizmo.attach(clusterId, scene, camera, canvas)
  }

  // Selection→tool bridge: opening/re-targeting/closing the tool in response to cluster
  // selection (3D cluster-filter click OR Movable Clusters sidebar row — both surface as a
  // canonical cluster ref). Registered from main.js beside the other tool
  // subscribers so subscription order is explicit.
  async function _handleSelectionChange(newState, prevState) {
    if (newState.selection === prevState.selection) return
    if (selectedClusterIds(newState).length !== 1) return
    const { action, clusterId } = decideSelectionAction({
      newSel:          canonicalSelection(newState).primary,
      toolActive:      getActive(),
      activeClusterId: newState.activeClusterId,
      mode: {
        assemblyActive: newState.assemblyActive,
        cadnanoActive:  newState.cadnanoActive,
        unfoldActive:   newState.unfoldActive,
      },
    })
    if (action === 'retarget') {
      // attach() re-sets activeClusterId, which fires the active-cluster subscriber in
      // main.js (repopulates fields / pivot options / centroid constraint).
      const clusters = newState.currentDesign?.cluster_transforms ?? []
      await _showClusterSingle(clusterId, clusters)
    }
  }

  // Live multi-select bridge: while the design-mode tool is active, follow canonical
  // cluster refs so the gizmo stays up and re-centers as clusters are
  // ctrl/shift-clicked or lassoed in/out. >=2 → group; exactly 1 → single (only when
  // leaving a group or landing on a different cluster); 0 → leave it to _handleSelectionChange.
  async function _handleMultiClusterSelectionChange(newState, prevState) {
    if (newState.selection === prevState.selection) return
    if (!getActive()) return
    if (newState.assemblyActive || newState.cadnanoActive || newState.unfoldActive) return
    const clusters = newState.currentDesign?.cluster_transforms ?? []
    const groupIds = selectedClusterIds(newState).filter(id => clusters.some(c => c.id === id))
    if (groupIds.length >= 2) {
      await _showClusterGroup(groupIds, clusters)
    } else if (groupIds.length === 1) {
      // Re-attach single only if we were a group (or somehow point elsewhere) — otherwise
      // the gizmo is already on this cluster (e.g. the promote seed) and re-attaching flickers.
      if (clusterGizmo.isGroupActive?.() || groupIds[0] !== newState.activeClusterId) {
        await _showClusterSingle(groupIds[0], clusters)
      }
    }
  }

  // "Reset" — discard the in-progress (uncommitted) move and restore the affected clusters to
  // their currently-SAVED positions, WITHOUT leaving the tool: exactly what exiting and
  // re-entering Move/Rotate would show. (Contrast the old behavior, which zeroed to the
  // identity/creation pose.) Reuses the cancel path's pending-discard + geometry-restore, then
  // re-attaches the gizmo at the committed pose so the user can keep working.
  async function _resetActiveClusterToSaved() {
    if (!getActive()) return

    if (store.getState().assemblyActive) {
      const { activeInstanceId, currentAssembly } = store.getState()
      instanceGizmo.detach()
      _assemblyPendingTransforms.clear()
      _assemblyPendingPartJoints.clear()
      if (currentAssembly) {
        await assemblyRenderer.rebuild(currentAssembly)
        assemblyRenderer.rebuildLinkers(currentAssembly)
        assemblyJointRenderer.rebuild(currentAssembly)
        _syncAssemblyBluntEnds()
      }
      // Re-attach at the saved instance matrix so the user can keep moving.
      if (activeInstanceId) {
        const ctx = _createAssemblyTransformContext(activeInstanceId)
        if (ctx) {
          _moveRotatePanel.setAssemblyCtx(ctx)
          _attachGroupGizmo(activeInstanceId, ctx)
          _mrSetTransformValuesFromMatrix(ctx.primaryStart)
        }
      }
      return
    }

    // Design mode: drop pending transforms (dragged cluster + any movable-link bodies), revert
    // the live-paint preview to the committed geometry, then re-attach at the saved pose.
    const clusterId = store.getState().activeClusterId
    if (!clusterId) return
    const hadPreview = getClusterDirty()
    setClusterDirty(false)
    clusterGizmo.discardPendingTransforms?.()
    if (hadPreview) {
      _showProgress('Resetting', 'Restoring saved positions…', { indeterminate: true })
      await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))
      try {
        await _restoreTransformPreviewFromStore()
      } finally {
        _hideProgress()
      }
    }
    await _refreshClusterPivotForAttach(clusterId)
    clusterGizmo.attach(clusterId, scene, camera, canvas)
  }

  _confirmBtn.addEventListener('click', _confirmTranslateRotateTool)
  document.getElementById('mr-apply-btn')?.addEventListener('click', () => {
    if (nucleotideTransformTool?.isActive()) nucleotideTransformTool.confirm()
    else _confirmTranslateRotateTool()
  })
  document.getElementById('mr-cancel-btn')?.addEventListener('click', () => {
    if (nucleotideTransformTool?.isActive()) nucleotideTransformTool.cancel()
    else _cancelTranslateRotateTool()
  })
  document.getElementById('mr-reset-btn')?.addEventListener('click', () => {
    if (nucleotideTransformTool?.isActive()) nucleotideTransformTool.reset()
    else _resetActiveClusterToSaved()
  })

  function _activateFromCurrentSelection() {
    if (nucleotideTransformTool?.canActivate()) return nucleotideTransformTool.activate()
    const st = store.getState()
    const target = st.assemblyActive
      ? null
      : resolveSelectionClusterId(canonicalSelection(st).primary, st.currentDesign)
    return _activateTranslateRotateTool(target)
  }

  document.getElementById('menu-tools-translate-rotate')?.addEventListener('click', () => {
    if (nucleotideTransformTool?.isActive() || getActive()) {
      if (_mrPanel) _mrPanel.style.display = ''
      return
    }
    _activateFromCurrentSelection()
  })

  registerShortcut({
    key: 'm', ctrl: false, shift: false,
    description: 'Activate move/rotate tool',
    blockedInInput: true,
    handler() {
      if (nucleotideTransformTool?.isActive()) {
        nucleotideTransformTool.confirm()
        return
      }
      if (getActive()) {
        _confirmTranslateRotateTool()
      } else {
        _activateFromCurrentSelection()
      }
    },
  })

  return {
    activate: _activateTranslateRotateTool,
    confirm: _confirmTranslateRotateTool,
    cancel: _cancelTranslateRotateTool,
    resetToSaved: _resetActiveClusterToSaved,
    rotateJoint: _rotateJoint,
    handleSelectionChange: _handleSelectionChange,
    handleMultiClusterSelectionChange: _handleMultiClusterSelectionChange,
    removeToolPickListeners: _removeToolPickListeners,
    hideConfirmBtn: () => { _confirmBtn.style.display = 'none' },
    beginVRPreview: _beginVRPreview,
    applyVRPreviewMatrix: _applyVRPreviewMatrix,
    cancelVRPreview: _cancelVRPreview,
  }
}
