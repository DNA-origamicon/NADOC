import { quatToEulerDeg } from './rotation_math.js'
import { showToast } from '../ui/toast.js'
import { showOpProgress, hideOpProgress } from '../ui/op_progress.js'
import { registerShortcut } from '../input/shortcuts.js'

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
export function initTranslateRotateTool(deps) {
  const {
    store, scene, camera, canvas,
    designRenderer,
    getJointRenderer,
    clusterGizmo, instanceGizmo,
    assemblyRenderer, assemblyJointRenderer,
    api,
    moveRotatePanel,
    mrPanel, mrClusterSel, mrPivotSel,
    setTransformValues, setTransformValuesFromMatrix,
    setPivotOptions, setSelectedPivot, setClusterOptions,
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
  const _mrClusterSel = mrClusterSel
  const _mrPivotSel = mrPivotSel
  const _mrSetTransformValues = setTransformValues
  const _mrSetTransformValuesFromMatrix = setTransformValuesFromMatrix
  const _mrSetPivotOptions = setPivotOptions
  const _mrSetSelectedPivot = setSelectedPivot
  const _mrSetClusterOptions = setClusterOptions
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
      setActive(true)
      document.getElementById('mode-indicator').textContent = 'MOVE — Tab: move/rotate · click elsewhere: commit · Esc: cancel'
      _attachGroupGizmo(activeInstanceId, ctx)
      _mrSetClusterOptions([{ id: activeInstanceId, name: _instForGizmo?.name ?? 'Selected part' }], activeInstanceId)
      if (_mrClusterSel) _mrClusterSel.disabled = true
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
    if (!clusters.length) {
      showToast('No movable clusters exist. Create a cluster first by multi-selecting strands, then using the Movable Clusters panel.', { severity: 'error' })
      return
    }
    setClusterDirty(false)
    setActive(true)
    document.getElementById('mode-indicator').textContent = 'MOVE/ROTATE — Esc: cancel'

    // Attach gizmo to the target cluster (from Rotate button), the active cluster, or the last cluster.
    const { activeClusterId } = store.getState()
    const first = (targetClusterId && clusters.find(c => c.id === targetClusterId))
      ?? (activeClusterId && clusters.find(c => c.id === activeClusterId))
      ?? clusters[clusters.length - 1]
    await _refreshClusterPivotForAttach(first.id)
    clusterGizmo.attach(first.id, scene, camera, canvas)

    canvas.addEventListener('pointerdown', _onToolPickPointerDown)

    // Populate and show the right-sidebar move/rotate panel
    _moveRotatePanel.setAssemblyCtx(null)
    if (_mrClusterSel) _mrClusterSel.disabled = false
    if (_mrPivotSel) _mrPivotSel.disabled = false
    _mrSetClusterOptions(clusters, first.id)
    await _flexRelax.refreshFlexGates()
    const initJoints = store.getState().currentDesign?.cluster_joints?.filter(j => j.cluster_id === first.id) ?? []
    _mrSetPivotOptions(initJoints, first.id)
    _mrSetSelectedPivot('centroid')
    const [irx, iry, irz] = quatToEulerDeg(first.rotation)
    _mrSetTransformValues(first.translation[0], first.translation[1], first.translation[2], irx, iry, irz)
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
      _mrSetClusterOptions(clusters, joint.cluster_id)
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
      setEditContext(null)
      _showProgress('Applying Change', 'Updating transformed geometry…', { indeterminate: true })
      await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))
      try {
        const pending = clusterGizmo.getPendingTransform(editCtx.clusterId)
        if (pending) {
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
    const hadLocalPreview = getClusterDirty()
    setActive(false)
    _confirmBtn.style.display = 'none'
    if (_mrPanel) _mrPanel.style.display = 'none'
    // Drop any cluster_op edit context so the next gizmo session takes the
    // standard "append a new cluster_op" path.
    if (getEditContext()?.editingFeatureType === 'cluster_op') setEditContext(null)

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
  }

  _confirmBtn.addEventListener('click', _confirmTranslateRotateTool)
  document.getElementById('mr-apply-btn')?.addEventListener('click', _confirmTranslateRotateTool)
  document.getElementById('mr-cancel-btn')?.addEventListener('click', _cancelTranslateRotateTool)

  document.getElementById('menu-tools-translate-rotate')?.addEventListener('click', () => {
    _activateTranslateRotateTool()
  })

  registerShortcut({
    key: 't', ctrl: false,
    description: 'Activate move/rotate tool',
    blockedInInput: true,
    handler() {
      if (getActive()) {
        _confirmTranslateRotateTool()
      } else {
        _activateTranslateRotateTool()
      }
    },
  })

  return {
    activate: _activateTranslateRotateTool,
    confirm: _confirmTranslateRotateTool,
    cancel: _cancelTranslateRotateTool,
    rotateJoint: _rotateJoint,
    removeToolPickListeners: _removeToolPickListeners,
    hideConfirmBtn: () => { _confirmBtn.style.display = 'none' },
  }
}
