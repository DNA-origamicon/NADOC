import { applyBeltRiders } from '../scene/belt_geometry.js'
import { computeFixedDepths } from '../scene/assembly_constraint_graph.js'
import { computeGroupHiddenInstanceIds } from '../scene/assembly_groups_util.js'
import { assemblyTransformOnlyChange, matrixFromInstance, sameInstanceTransform, constraintRelevantChanged } from '../scene/assembly_diff.js'

/** Build the consistent representation policy applied before an assembly load. */
export function createAssemblyLoadDefaults({ api, setColoringMode, updateReprRadio }) {
  return function applyAssemblyLoadDefaults(assembly) {
    const instances = assembly?.instances ?? []
    if (!instances.length) return
    setColoringMode('overhang-only')
    updateReprRadio('cylinders')
    if (instances.every(instance => instance.representation === 'cylinders')) return
    for (const instance of instances) instance.representation = 'cylinders'
    api.batchPatchInstances(
      instances.map(instance => ({ id: instance.id, representation: 'cylinders' })),
      { skipSync: true },
    ).catch(error => console.error('[assembly] default rep PATCH failed:', error))
  }
}

/** Owns assembly-mode transitions and incremental renderer updates. */
export function initAssemblyModeSync({
  store, animPanel, setDesignGeometryVisible: _setDesignGeometryVisible,
  assemblyPanel, applyAssemblyLoadDefaults: _applyAssemblyLoadDefaults,
  runAssemblyRebuild: _runAssemblyRebuild, controls,
  updateFixedLockPositions: _updateFixedLockPositions, canvas,
  onAssemblyPointerDown: _onAssemblyPointerDown, onAssemblyClick: _onAssemblyClick,
  overhangHoverPicker, onAssemblyContextMenu: _onAssemblyContextMenu,
  hasAssemblyPending: _hasAssemblyPending, commitAssemblyPending: _commitAssemblyPending,
  rebuildFixedLocks: _rebuildFixedLocks, assemblyContextMenu, instanceGizmo,
  assemblyPendingTransforms: _assemblyPendingTransforms,
  assemblyPendingPartJoints: _assemblyPendingPartJoints,
  assemblyRenderer, assemblyJointRenderer, beltPathRenderer,
  assemblyPointer: _assemblyPointer, assemblyLasso, assemblyMultiBox: _assemblyMultiBox,
  setMotionChip: _setMotionChip, isTranslateRotateActive, setTranslateRotateActive,
  translateRotateTool: _translateRotateTool, hideWelcome: _hideWelcome,
  getAssemblyLoadSettle, rebuildBeltPaths: _rebuildBeltPaths,
  attachGroupGizmoForGroup: _attachGroupGizmoForGroup,
  attachGroupGizmo: _attachGroupGizmo, clearSelectedAssemblyCluster,
  clusterGlowLayer, getClusterPanel,
}) {
  return store.subscribeSlice('assembly', (newState, prevState) => {
    const modeChanged     = newState.assemblyActive    !== prevState.assemblyActive
    const assemblyChanged = newState.currentAssembly   !== prevState.currentAssembly
    const activeChanged   = newState.activeInstanceId  !== prevState.activeInstanceId

    if (modeChanged) {
      animPanel?.setAssemblyMode(newState.assemblyActive)
      if (newState.assemblyActive) {
        _setDesignGeometryVisible(false)
        assemblyPanel.show()
        // Force the cylinders load-default + coloring BEFORE the panel rebuild AND
        // the geometry build: the renderer builds cylinders directly — never the
        // saved representation (a surface-saved assembly would otherwise pay a
        // ~24 s surface build here that's immediately discarded) — and the panel's
        // per-part Repr dropdown shows the rep that's actually on screen.
        if (newState.currentAssembly) _applyAssemblyLoadDefaults(newState.currentAssembly)
        assemblyPanel.rebuild(newState)
        if (newState.currentAssembly) {
          // _runAssemblyRebuild owns the build so the disk-load path doesn't ALSO
          // build separately.
          _runAssemblyRebuild(newState.currentAssembly, {
            fitOnDone: true,
            activeInstanceId: newState.activeInstanceId,
          })
        }
        controls.addEventListener('change', _updateFixedLockPositions)
        canvas.addEventListener('pointerdown',  _onAssemblyPointerDown)
        canvas.addEventListener('click',        _onAssemblyClick)
        canvas.addEventListener('pointermove',  overhangHoverPicker.onHoverMove)
        canvas.addEventListener('contextmenu',  _onAssemblyContextMenu)
      } else {
        if (_hasAssemblyPending()) {
          _commitAssemblyPending().catch(err => console.error('[assembly] pending commit on exit:', err))
        }
        _rebuildFixedLocks(null)
        controls.removeEventListener('change', _updateFixedLockPositions)
        _setDesignGeometryVisible(true)
        // Reset mixed-rep dot — only meaningful in assembly mode.
        document.getElementById('menu-view-repr-mixed-dot')?.style.setProperty('display', 'none')
        assemblyPanel.hide()
        assemblyContextMenu.hide()
        instanceGizmo.detach()
        _assemblyPendingTransforms.clear()
        _assemblyPendingPartJoints.clear()
        assemblyRenderer.dispose()
        assemblyJointRenderer.exitAttachMode()
        assemblyJointRenderer.rebuild(null)   // clear all joint indicators
        beltPathRenderer.rebuild(null)        // clear persistent belt tubes
        canvas.removeEventListener('pointerdown',  _onAssemblyPointerDown)
        canvas.removeEventListener('click',        _onAssemblyClick)
        canvas.removeEventListener('pointermove',  overhangHoverPicker.onHoverMove)
        canvas.removeEventListener('contextmenu',  _onAssemblyContextMenu)
        overhangHoverPicker.reset()
        // Clean up any in-flight free drag (handlers + state in assembly_pointer.js)
        _assemblyPointer.cancelDrag()
        assemblyLasso.cancel()
        // Drop the multi-select union box from the scene; setState below also
        // fires the subscriber which re-runs update() (which clears it), but
        // doing it inline keeps the scene clean even if the recursive setState
        // path is short-circuited. The factory stays reusable — a later
        // re-entry rebuilds the box on the next update().
        _assemblyMultiBox.dispose()
        _setMotionChip(null)
        // Mode exit should also drop any orphaned multi-selection so the
        // panel/contextmenu don't surface stale group-able candidates.
        if ((newState.multiSelectedInstanceIds ?? []).length || newState.activeGroupId) {
          store.setState({ multiSelectedInstanceIds: [], activeGroupId: null, groupDiveStack: [] })
        }
        // Gizmo exit: detach if the tool was active during mode switch
        if (isTranslateRotateActive()) {
          setTranslateRotateActive(false)
          store.setState({ translateRotateActive: false })
          instanceGizmo.detach()
          _translateRotateTool.hideConfirmBtn()
        }
      }
    }

    // ── Assembly menu item enable/disable ──────────────────────────────────
    if (modeChanged || activeChanged) {
      const hasActive = !!newState.activeInstanceId
      const inAssembly = newState.assemblyActive
      document.getElementById('menu-assembly-define-joint')
        ?.toggleAttribute('disabled', !(inAssembly && hasActive))
      document.getElementById('menu-assembly-define-mate')
        ?.toggleAttribute('disabled', !inAssembly)
    }

    // Belt path needs at least two revolute mates to wrap; re-evaluate whenever
    // the joint set may have changed (adding a mate fires assemblyChanged).
    if (modeChanged || activeChanged || assemblyChanged) {
      const inAssembly = newState.assemblyActive
      const revoluteCount = (newState.currentAssembly?.joints ?? [])
        .filter(j => j.joint_type === 'revolute').length
      document.getElementById('menu-assembly-define-belt')
        ?.toggleAttribute('disabled', !(inAssembly && revoluteCount >= 2))
    }

    if (!modeChanged && newState.assemblyActive) {
      if (assemblyChanged) {
        // Hide the assembly welcome when the first part is added
        const prevCount = prevState.currentAssembly?.instances?.length ?? 0
        const newCount  = newState.currentAssembly?.instances?.length ?? 0
        if (prevCount === 0 && newCount > 0) _hideWelcome()

        assemblyPanel.rebuild(newState)
        // A disk-load reload (already in assembly mode) must never take the
        // transform-only fast path: that skips the rebuild AND would leave
        // _openAssemblyFromServer's load promise unsettled (hang).  Force the
        // full rebuild whenever a load is in flight.
        const isLoad = !!getAssemblyLoadSettle()
        if (!isLoad && assemblyTransformOnlyChange(prevState.currentAssembly, newState.currentAssembly)) {
          // Transform-only change (e.g. a move/rotate commit via propagateFk):
          // push each instance's new world matrix straight into the renderer
          // instead of disposing + re-fetching geometry — avoids the whole
          // assembly blinking out and re-rendering.  Joint indicators are
          // cheap, so we still rebuild those to track moved anchors.
          //
          // Push ONLY instances whose transform actually changed.  A
          // connector-register / joint-add response carries unchanged
          // transforms; pushing all of them would snap a live mate preview
          // back to the stored pose (the "moves three times" jank) and
          // re-pack every row for nothing.  Diffing prev→next keeps the moved
          // part (and its FK children) live and leaves the rest untouched.
          const _prevById = new Map(
            (prevState.currentAssembly?.instances ?? []).map(i => [i.id, i]),
          )
          let _anyMoved = false
          for (const inst of newState.currentAssembly.instances) {
            const prev = _prevById.get(inst.id)
            if (prev && sameInstanceTransform(prev, inst)) continue
            assemblyRenderer.setLiveTransform(inst.id, matrixFromInstance(inst))
            _anyMoved = true
          }
          assemblyJointRenderer.rebuild(newState.currentAssembly)
          // Cross-part linkers are world-space geometry DERIVED from the part
          // transforms (binding-domain complements + connector arcs + ds bridge),
          // not GPU-instanced — so the setLiveTransform fast path moves the parts
          // but leaves every linker stale. If a part moved and the assembly
          // carries linkers, refetch + redraw them so the binding domains and
          // arcs track the new poses. Covers the indirect-linker relax (a
          // transform-only change) AND any plain part move that drags a linker —
          // and rebuilds ALL linkers, so others sharing the moved parts update too.
          if (_anyMoved && ((newState.currentAssembly?.assembly_strands?.length ?? 0) > 0
                            || (newState.currentAssembly?.overhang_connections?.length ?? 0) > 0)) {
            assemblyRenderer.rebuildLinkers?.(newState.currentAssembly)
          }
          // Re-apply the group visibility overlay — a transform-only patch
          // could have changed a group's `visible` flag without touching any
          // instance's `visible`. Cheap O(N) walk; no-op when no group is hidden.
          assemblyRenderer.applyGroupVisibilityOverlay?.(computeGroupHiddenInstanceIds(newState.currentAssembly))
          if (newState.activeInstanceId) {
            assemblyRenderer.setActiveInstance(newState.activeInstanceId)
            const depths = computeFixedDepths(newState.currentAssembly)
            if (depths.has(newState.activeInstanceId)) _rebuildFixedLocks(newState.currentAssembly)
          }
        } else {
          // Reload while already in assembly mode: apply the cylinders default +
          // frame the camera, same as a fresh mode-enter.  Ordinary edits
          // (isLoad false) keep their representation and camera untouched.
          if (isLoad) _applyAssemblyLoadDefaults(newState.currentAssembly)
          _runAssemblyRebuild(newState.currentAssembly, {
            fitOnDone: isLoad,
            activeInstanceId: newState.activeInstanceId,
          })
        }
        // Persistent belt-path tubes (create/edit/delete change belt_paths).
        _rebuildBeltPaths()
        // Drive belt riders to their live pose for the current pulley angles
        // (covers discrete rotations — ring/gizmo/group commits + load). Skip
        // while a joint is actively RPM-spinning: the ticker owns riders then,
        // and running both (store angle vs the ticker's live _shadow) would make
        // the rider hitch. Mutually exclusive with the ticker's gated update.
        const _spinning = (newState.currentAssembly?.joints ?? []).some(
          j => j.joint_type === 'revolute' && j.angular_velocity_rpm && !j.spin_paused)
        if (!_spinning) {
          applyBeltRiders(
            newState.currentAssembly,
            (id, j) => j.current_value ?? 0,
            (iid, mat) => assemblyRenderer.setLiveTransform(iid, mat),
          )
        }
      }
      // Multi-select union box: refresh whenever the multi-select set, the
      // active group, OR the assembly changed (move/rotate of a member shifts
      // the union extent). Run inside RAF so the renderer's per-instance
      // Three.js groups have their fresh matrixWorld + bounding boxes.
      if (
        assemblyChanged ||
        newState.multiSelectedInstanceIds !== prevState.multiSelectedInstanceIds ||
        newState.activeGroupId !== prevState.activeGroupId
      ) {
        requestAnimationFrame(() => _assemblyMultiBox.update())
      }

      // PartGroup gizmo lifecycle. Attach on group-select; re-attach when
      // the assembly mutates while a group is still selected (centroid +
      // member start transforms need recapture). Detach when group is
      // cleared AND no single instance is selected.
      const groupChanged = newState.activeGroupId !== prevState.activeGroupId
      if (groupChanged) {
        if (newState.activeGroupId) {
          _attachGroupGizmoForGroup(newState.activeGroupId)
        } else if (!newState.activeInstanceId) {
          instanceGizmo.detach()
          _setMotionChip(null)
        }
      } else if (assemblyChanged && newState.activeGroupId) {
        // Group still selected, members may have moved — re-anchor.
        _attachGroupGizmoForGroup(newState.activeGroupId)
      }

      // Single-instance gizmo re-evaluation when the assembly changes around
      // an already-selected part. Without this, editing a mate (joint type,
      // axis, or even `fixed` on a partner) leaves the gizmo locked to the
      // DOF the analyzer computed at original attach time. Guard against
      // mid-drag (skip during a live drag — TransformControls state would be
      // torn down) and against pending uncommitted moves (re-attach would
      // snap the gizmo back to the last committed pose, hiding the user's
      // in-flight edit). The group path above already does the same.
      if (
        assemblyChanged &&
        !groupChanged &&
        newState.activeInstanceId &&
        !newState.activeGroupId &&
        !instanceGizmo.isDragging() &&
        !_hasAssemblyPending() &&
        constraintRelevantChanged(prevState.currentAssembly, newState.currentAssembly, newState.activeInstanceId)
      ) {
        _attachGroupGizmo(newState.activeInstanceId)
      }

      if (activeChanged) {
        // Clear cluster glow and sidebar selection whenever the active instance changes
        clearSelectedAssemblyCluster()
        clusterGlowLayer.clear()
        getClusterPanel()?.selectAssemblyCluster?.(null, null)
        assemblyRenderer.setActiveInstance(newState.activeInstanceId)
        // Joint/connector indicators draw only for the selected part (scale fix).
        assemblyJointRenderer.setActiveInstance(newState.activeInstanceId)
        if (newState.activeInstanceId) {
          getClusterPanel()?.expandInstance?.(newState.activeInstanceId)
        }
        const newInst = newState.currentAssembly?.instances?.find(i => i.id === newState.activeInstanceId)
        if (newState.activeInstanceId && !newInst?.fixed) {
          _attachGroupGizmo(newState.activeInstanceId)
        } else if (!newState.activeGroupId) {
          // Guard: don't detach the group gizmo just because activeInstanceId
          // went null. The groupChanged branch above owns gizmo lifecycle
          // while a group is selected.
          instanceGizmo.detach()
          _setMotionChip(null)
        }
        // Show locks for all anchored parts when an anchored part is selected; hide otherwise
        const depths = computeFixedDepths(newState.currentAssembly)
        if (newState.activeInstanceId && depths.has(newState.activeInstanceId)) {
          _rebuildFixedLocks(newState.currentAssembly)
        } else {
          _rebuildFixedLocks(null)
        }
      }
    }
  })
}
