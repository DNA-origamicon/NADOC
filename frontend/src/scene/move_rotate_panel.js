import * as THREE from 'three'
import { posEulerFromMatrix, eulerDegToQuat, stepEulerDeg } from './rotation_math.js'
import { showToast } from '../ui/toast.js'
import { canonicalSelection } from './selection_model.js'

export function moveRotateSelectionLabels(state) {
  const design = state.currentDesign
  const labels = canonicalSelection(state).items.map(ref => {
    if (ref.kind === 'base' || ref.kind === 'end') return `${ref.kind === 'base' ? 'Base' : 'End'} · ${ref.key}`
    if (ref.kind === 'cluster') {
      const name = design?.cluster_transforms?.find(c => c.id === ref.id)?.name ?? ref.id
      return `Cluster · ${name}`
    }
    if (ref.kind === 'strand') return `Strand · ${ref.id}`
    if (ref.kind === 'domain') return `Domain · ${ref.strandId} [${ref.domainIndex}]`
    return `${ref.kind} · ${ref.id ?? ref.key}`
  })
  if (labels.length) return labels

  if (state.assemblyActive && state.activeInstanceId) {
    const name = state.currentAssembly?.instances?.find(i => i.id === state.activeInstanceId)?.name
    return [`Part · ${name ?? state.activeInstanceId}`]
  }
  return []
}

/**
 * Move/Rotate right-sidebar panel — numeric transform inputs (tx/ty/tz, rx/ry/rz,
 * joint-angle) + pivot dropdown and a read-only current-selection box. Drives the
 * design cluster gizmo (clusterGizmo) and the assembly instance gizmo
 * (instanceGizmo) depending on store.assemblyActive.
 *
 * This is the panel "shell": its view setters + commit controller + dropdown
 * handlers. The tool gesture fns (_activateTranslateRotateTool /
 * _confirmTranslateRotateTool / _cancelTranslateRotateTool, the pointerdown ring
 * pick) stay in main.js and drive this via the returned API. Lifted verbatim from
 * the closure (main.js carve-up: Move/Rotate panel shell). The internal `_mr*`
 * function bodies are unchanged; injected deps replace the former closure refs.
 *
 * @param {object} deps
 * @param deps.store
 * @param deps.scene
 * @param deps.camera
 * @param deps.canvas
 * @param deps.clusterGizmo
 * @param deps.instanceGizmo
 * @param deps.flexRelax                       scene/flex_relax.js factory API
 * @param deps.applyAssemblyPrimaryLive        from scene/assembly_transform.js
 * @param deps.queueAssemblyPrimaryCommit      from scene/assembly_transform.js
 */
export function initMoveRotatePanel({
  store, scene, camera, canvas,
  clusterGizmo, instanceGizmo, flexRelax,
  applyAssemblyPrimaryLive, queueAssemblyPrimaryCommit,
  setClusterRotationPoint,
}) {
  const _mrPanel         = document.getElementById('move-rotate-panel')
  const _mrSelectionBox  = document.getElementById('mr-current-selection')
  const _mrSessionHint   = document.getElementById('mr-session-hint')
  const _mrTxInp         = document.getElementById('mr-tx')
  const _mrTyInp         = document.getElementById('mr-ty')
  const _mrTzInp         = document.getElementById('mr-tz')
  const _mrRxInp         = document.getElementById('mr-rx')
  const _mrRyInp         = document.getElementById('mr-ry')
  const _mrRzInp         = document.getElementById('mr-rz')
  const _mrJaInp         = document.getElementById('mr-ja')
  const _mrPivotSel      = document.getElementById('mr-pivot-sel')
  const _mrRotSection    = document.getElementById('mr-rotation-section')
  const _mrJaSection     = document.getElementById('mr-joint-angle-section')
  const _mrSnapChk       = document.getElementById('mr-snap-45')
  let   _mrPivotIsJoint  = false
  let   _mrAssemblyCtx   = null
  let   _proteinController = null

  function _mrSetSessionMode(sessionMode = 'cluster') {
    const gizmoOnly = sessionMode === 'nucleotide' || sessionMode === 'waiting'
    const fieldIds = ['mr-tx', 'mr-ty', 'mr-tz', 'mr-rx', 'mr-ry', 'mr-rz', 'mr-ja',
      'mr-rx-dec', 'mr-rx-inc', 'mr-ry-dec', 'mr-ry-inc', 'mr-rz-dec', 'mr-rz-inc',
      'mr-snap-45', 'mr-pivot-sel']
    for (const id of fieldIds) {
      const el = document.getElementById(id)
      if (el) el.disabled = gizmoOnly
    }
    const reset = document.getElementById('mr-reset-btn')
    if (reset) reset.disabled = sessionMode === 'waiting'
    const apply = document.getElementById('mr-apply-btn')
    if (apply) apply.textContent = sessionMode === 'waiting' ? 'Done' : 'Apply'
    if (_mrSessionHint) {
      _mrSessionHint.textContent = sessionMode === 'waiting'
        ? 'Select a cluster or nucleotide to attach the gizmo.'
        : sessionMode === 'nucleotide'
          ? 'Drag the gizmo. Press Tab to switch move/rotate.'
          : sessionMode === 'protein'
            ? 'Translate or rotate the protein about its centroid. Tethers remain constrained live.'
          : 'Drag the gizmo or enter an exact transform below.'
    }
    if (_mrPivotSel) _mrPivotSel.disabled = sessionMode === 'protein' || gizmoOnly
  }


  function _mrShowJointMode(on) {
    _mrPivotIsJoint = on
    if (_mrRotSection) _mrRotSection.style.display = on ? 'none' : ''
    if (_mrJaSection)  _mrJaSection.style.display  = on ? '' : 'none'
  }

  function _mrSetTransformValues(tx, ty, tz, rx, ry, rz) {
    if (_mrTxInp && document.activeElement !== _mrTxInp) _mrTxInp.value = tx.toFixed(3)
    if (_mrTyInp && document.activeElement !== _mrTyInp) _mrTyInp.value = ty.toFixed(3)
    if (_mrTzInp && document.activeElement !== _mrTzInp) _mrTzInp.value = tz.toFixed(3)
    if (_mrRxInp && document.activeElement !== _mrRxInp) _mrRxInp.value = rx.toFixed(3)
    if (_mrRyInp && document.activeElement !== _mrRyInp) _mrRyInp.value = ry.toFixed(3)
    if (_mrRzInp && document.activeElement !== _mrRzInp) _mrRzInp.value = rz.toFixed(3)
  }

  function _mrSetTransformValuesFromMatrix(matrix4) {
    if (!matrix4) return
    const { pos, euler } = posEulerFromMatrix(matrix4)
    _mrSetTransformValues(pos[0], pos[1], pos[2], euler[0], euler[1], euler[2])
  }

  function _mrSetJointAngle(deg) {
    if (_mrJaInp && document.activeElement !== _mrJaInp) _mrJaInp.value = deg.toFixed(1)
  }

  // The DRIVEN overhang of a duplex cluster = the non-driver overhang whose domain is in
  // the cluster's domain_ids.
  function _duplexDrivenOverhang(design, cluster) {
    const driver = cluster.overhang_duplex_driver_id
    for (const dr of (cluster.domain_ids ?? [])) {
      const s = design.strands?.find(x => x.id === dr.strand_id)
      const oid = s?.domains?.[dr.domain_index]?.overhang_id
      if (oid && oid !== driver) return oid
    }
    return null
  }

  function _mrSetPivotOptions(joints, clusterId = null) {
    if (!_mrPivotSel) return
    // Preserve the current selection across a rebuild. A pivot-point change round-trips
    // to the server, whose fresh design makes cluster_joints a new array reference →
    // the joints-changed subscriber re-runs this fn, which would otherwise reset the
    // <select> to option[0] (centroid) and revert the user's chosen root pivot.
    const _prevPivot = _mrPivotSel.value
    while (_mrPivotSel.options.length > 1) _mrPivotSel.remove(1)
    // Overhang-DUPLEX cluster: offer each participating overhang's ROOT bead as a rotation
    // point (the default option-0 "centroid" already covers the duplex centroid).
    const design = store.getState().currentDesign
    const dc = design?.cluster_transforms?.find(
      c => c.id === clusterId && c.overhang_duplex_driver_id)
    if (dc) {
      const ohById = new Map((design.overhangs ?? []).map(o => [o.id, o]))
      const driven = _duplexDrivenOverhang(design, dc)
      for (const oid of [dc.overhang_duplex_driver_id, driven].filter(Boolean)) {
        const opt = document.createElement('option')
        opt.value = `dup:root:${oid}`
        opt.textContent = `Rotate about ${ohById.get(oid)?.label ?? oid.slice(0, 8)} root`
        _mrPivotSel.appendChild(opt)
      }
      // Free-until-taut drag against the connection bonds (like the ssDNA-constrained flex drag).
      const taut = document.createElement('option')
      taut.value = 'dup:taut'
      taut.textContent = 'Constrained (taut bonds)'
      _mrPivotSel.appendChild(taut)
    }
    for (const j of (joints ?? [])) {
      const opt = document.createElement('option')
      opt.value = j.id
      opt.textContent = `Joint: ${j.name}`
      _mrPivotSel.appendChild(opt)
    }
    // "Constrained (tethers)" — free-until-taut drag against the cluster's tethers:
    // ssDNA flexible segments AND/OR applied overhang connections (direct duplex / ss-ds
    // linker bridge). Offered when either kind of tether constrains this cluster.
    if (flexRelax.hasTetherOption(clusterId)) {
      const opt = document.createElement('option')
      opt.value = 'ssdna'
      opt.textContent = 'Constrained (tethers)'
      _mrPivotSel.appendChild(opt)
    }
    // Restore the prior selection if it still exists after the rebuild (see comment above).
    if (_prevPivot && [..._mrPivotSel.options].some(o => o.value === _prevPivot)) {
      _mrPivotSel.value = _prevPivot
    }
  }

  function _mrSetSelectedPivot(id) {
    if (_mrPivotSel) _mrPivotSel.value = id ?? 'centroid'
    _mrShowJointMode(id !== 'centroid' && id != null)
  }

  function _mrSetCurrentSelection(labels = []) {
    if (!_mrSelectionBox) return
    _mrSelectionBox.replaceChildren()
    const items = labels.filter(Boolean)
    if (!items.length) {
      const empty = document.createElement('div')
      empty.className = 'mr-selection-empty'
      empty.textContent = 'Nothing selected'
      _mrSelectionBox.appendChild(empty)
      return
    }
    for (const label of items) {
      const item = document.createElement('div')
      item.className = 'mr-selection-item'
      item.textContent = label
      _mrSelectionBox.appendChild(item)
    }
  }

  function _mrCommitInputs() {
    if (_proteinController?.isAttached?.()) {
      const t = [parseFloat(_mrTxInp?.value) || 0, parseFloat(_mrTyInp?.value) || 0, parseFloat(_mrTzInp?.value) || 0]
      const q = eulerDegToQuat(
        parseFloat(_mrRxInp?.value) || 0,
        parseFloat(_mrRyInp?.value) || 0,
        parseFloat(_mrRzInp?.value) || 0,
      )
      _proteinController.setTransform(t, q)
      return
    }
    if (store.getState().assemblyActive) {
      if (!_mrAssemblyCtx) return
      const tx = parseFloat(_mrTxInp?.value) || 0
      const ty = parseFloat(_mrTyInp?.value) || 0
      const tz = parseFloat(_mrTzInp?.value) || 0
      const rx = parseFloat(_mrRxInp?.value) || 0
      const ry = parseFloat(_mrRyInp?.value) || 0
      const rz = parseFloat(_mrRzInp?.value) || 0
      const q = eulerDegToQuat(rx, ry, rz)
      const mat = new THREE.Matrix4().compose(
        new THREE.Vector3(tx, ty, tz),
        new THREE.Quaternion(q[0], q[1], q[2], q[3]),
        new THREE.Vector3(1, 1, 1),
      )
      applyAssemblyPrimaryLive(_mrAssemblyCtx, mat)
      instanceGizmo.setMatrix(mat)
      queueAssemblyPrimaryCommit(_mrAssemblyCtx, mat)
      return
    }
    if (_mrPivotIsJoint) {
      if (!clusterGizmo.isActive()) return
      const joint = clusterGizmo.getActiveJoint()
      if (!joint) return
      const deg = parseFloat(_mrJaInp?.value)
      if (!isNaN(deg)) clusterGizmo.setJointRotation(joint, deg)
      return
    }
    if (!clusterGizmo.isActive()) return
    const tx = parseFloat(_mrTxInp?.value) || 0
    const ty = parseFloat(_mrTyInp?.value) || 0
    const tz = parseFloat(_mrTzInp?.value) || 0
    const rx = parseFloat(_mrRxInp?.value) || 0
    const ry = parseFloat(_mrRyInp?.value) || 0
    const rz = parseFloat(_mrRzInp?.value) || 0
    clusterGizmo.setTransform([tx, ty, tz], eulerDegToQuat(rx, ry, rz))
  }

  // Wire translation/rotation text inputs
  for (const inp of [_mrTxInp, _mrTyInp, _mrTzInp, _mrRxInp, _mrRyInp, _mrRzInp].filter(Boolean)) {
    inp.addEventListener('keydown', e => { e.stopPropagation(); if (e.key === 'Enter') { e.preventDefault(); inp.blur(); _mrCommitInputs() } })
    inp.addEventListener('change', _mrCommitInputs)
  }
  if (_mrJaInp) {
    _mrJaInp.addEventListener('keydown', e => { e.stopPropagation(); if (e.key === 'Enter') { e.preventDefault(); _mrJaInp.blur(); _mrCommitInputs() } })
    _mrJaInp.addEventListener('change', _mrCommitInputs)
  }

  // ── Relative 45° rotation buttons (per world axis) ──────────────────────────
  // Compose a `deg`-about-axis increment onto the current pose, then commit the
  // resulting absolute Euler (see rotation_math.stepEulerDeg). Mirrors the overhang
  // orientation panel's step buttons.
  function _mrStepAxis(axis, deg) {
    const cur = [
      parseFloat(_mrRxInp?.value) || 0,
      parseFloat(_mrRyInp?.value) || 0,
      parseFloat(_mrRzInp?.value) || 0,
    ]
    const [rx, ry, rz] = stepEulerDeg(cur, axis, deg)
    if (_mrRxInp) _mrRxInp.value = rx.toFixed(3)
    if (_mrRyInp) _mrRyInp.value = ry.toFixed(3)
    if (_mrRzInp) _mrRzInp.value = rz.toFixed(3)
    _mrCommitInputs()
  }

  for (const axis of ['x', 'y', 'z']) {
    document.getElementById(`mr-r${axis}-dec`)?.addEventListener('click', () => _mrStepAxis(axis, -45))
    document.getElementById(`mr-r${axis}-inc`)?.addEventListener('click', () => _mrStepAxis(axis, +45))
  }

  // Reset ("restore saved positions") is a tool-lifecycle action (discard the in-progress
  // move + revert geometry + re-attach at the committed pose) — handled in translate_rotate_tool.js
  // alongside Cancel/Apply, which own the gizmo + geometry-restore context.

  // ── Snap 45° toggle — snap the rotate-gizmo drag to 45° increments ──────────
  function _mrApplySnap() {
    clusterGizmo.setRotationSnap?.(_mrSnapChk?.checked ? 45 : null)
    _proteinController?.setRotationSnap?.(_mrSnapChk?.checked ? 45 : null)
  }
  _mrSnapChk?.addEventListener('change', _mrApplySnap)

  // Re-pivot a duplex cluster to a rotation point (overhang root or centroid): the backend
  // sets the pivot + rebases the translation, then we re-attach the gizmo so it rotates
  // about the new point. [[overhang-duplex-cluster]] P2.
  //
  // NOTE: do not recompute the cluster pivot here. That would use the visual centroid
  // from the cluster's VISUAL CENTROID and queues it as a pending transform — exactly the
  // centroid we're overriding. It would silently drag the pivot back to the centroid (the
  // "always rotates about centroid" bug). Instead drop any pending (centroid) transform and
  // attach directly so the gizmo reads the server-set root pivot verbatim.
  async function _setDuplexRotationPoint(clusterId, spec) {
    if (!setClusterRotationPoint) return
    await setClusterRotationPoint(clusterId, spec)
    clusterGizmo.clearPendingTransform?.(clusterId)
    clusterGizmo.attach(clusterId, scene, camera, canvas)
    // attach() re-sets activeClusterId (detach→null, then →clusterId). That change fires
    // main.js's activeClusterId subscriber, which repopulates the pivot dropdown and
    // hardcodes the selection back to 'centroid'. Re-assert the intended pivot AFTER the
    // attach so the dropdown reflects the point the user actually chose.
    if (_mrPivotSel) {
      const want = spec.kind === 'overhang_root' ? `dup:root:${spec.overhangId}` : 'centroid'
      if ([..._mrPivotSel.options].some(o => o.value === want)) _mrPivotSel.value = want
    }
  }

  function _activeDuplexCluster() {
    const st = store.getState()
    return st.currentDesign?.cluster_transforms?.find(
      c => c.id === st.activeClusterId && c.overhang_duplex_driver_id) ?? null
  }

  // Pivot dropdown change
  _mrPivotSel?.addEventListener('change', async () => {
    const val = _mrPivotSel.value
    if (val.startsWith('dup:root:')) {
      _mrShowJointMode(false)
      const clusterId = store.getState().activeClusterId
      await _setDuplexRotationPoint(clusterId, {
        kind: 'overhang_root', overhangId: val.slice('dup:root:'.length) })
      return
    }
    if (val === 'dup:taut') {
      // Free-until-taut drag: constrain the duplex against its connection bonds so a drag
      // never overstretches a bond past its contour (~0.67 nm). [[overhang-duplex-cluster]] P3.
      _mrShowJointMode(false)
      const clusterId = store.getState().activeClusterId
      const payload = await flexRelax.buildDuplexTautPayload(clusterId)
      if (payload) {
        clusterGizmo.setConstraint('ssdna', payload)
        showToast('Constrained: drag the duplex — connection bonds won’t overstretch')
      } else {
        clusterGizmo.setConstraint('centroid', null)
        showToast('No applied connection bonds to constrain this duplex.', { severity: 'warning' })
      }
      return
    }
    if (val === 'centroid') {
      _mrShowJointMode(false)
      const dc = _activeDuplexCluster()
      if (dc) { await _setDuplexRotationPoint(dc.id, { kind: 'centroid' }); return }
      clusterGizmo.setConstraint('centroid', null)
    } else if (val === 'ssdna') {
      _mrShowJointMode(false)
      const clusterId = store.getState().activeClusterId
      const payload = await flexRelax.buildTethersPayload(clusterId)
      if (payload) {
        clusterGizmo.setConstraint('ssdna', payload)
        showToast('Constrained: drag the cluster — ssDNA tethers & connections won’t overstretch')
      } else {
        clusterGizmo.setConstraint('centroid', null)
        showToast('No tethers to constrain this cluster.', { severity: 'warning' })
      }
    } else {
      const joint = store.getState().currentDesign?.cluster_joints?.find(j => j.id === val)
      if (joint) { _mrShowJointMode(true); clusterGizmo.setConstraint('joint', joint) }
    }
  })

  return {
    panel:                        _mrPanel,
    selectionBox:                 _mrSelectionBox,
    pivotSel:                     _mrPivotSel,
    setTransformValues:           _mrSetTransformValues,
    setTransformValuesFromMatrix: _mrSetTransformValuesFromMatrix,
    setJointAngle:                _mrSetJointAngle,
    setPivotOptions:              _mrSetPivotOptions,
    setSelectedPivot:             _mrSetSelectedPivot,
    setCurrentSelection:          _mrSetCurrentSelection,
    setSessionMode:               _mrSetSessionMode,
    showJointMode:                _mrShowJointMode,
    commitInputs:                 _mrCommitInputs,
    stepAxis:                     _mrStepAxis,
    getAssemblyCtx:               () => _mrAssemblyCtx,
    setAssemblyCtx:               (ctx) => { _mrAssemblyCtx = ctx },
    getPivotIsJoint:              () => _mrPivotIsJoint,
    setProteinController:         controller => { _proteinController = controller },
    getProteinController:         () => _proteinController,
  }
}
