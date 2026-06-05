import * as THREE from 'three'
import { posEulerFromMatrix, eulerDegToQuat } from './rotation_math.js'
import { showToast } from '../ui/toast.js'

/**
 * Move/Rotate right-sidebar panel — numeric transform inputs (tx/ty/tz, rx/ry/rz,
 * joint-angle) + pivot/cluster dropdowns for the Translate/Rotate tool. Drives the
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
 * @param deps.refreshClusterPivotForAttach    main.js (tool-shared gizmo-attach infra)
 * @param deps.isTranslateRotateActive         () => boolean (the tool's active flag)
 */
export function initMoveRotatePanel({
  store, scene, camera, canvas,
  clusterGizmo, instanceGizmo, flexRelax,
  applyAssemblyPrimaryLive, queueAssemblyPrimaryCommit,
  refreshClusterPivotForAttach, isTranslateRotateActive,
}) {
  const _mrPanel         = document.getElementById('move-rotate-panel')
  const _mrClusterSel    = document.getElementById('mr-cluster-sel')
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
  let   _mrPivotIsJoint  = false
  let   _mrAssemblyCtx   = null


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

  function _mrSetPivotOptions(joints, clusterId = null) {
    if (!_mrPivotSel) return
    while (_mrPivotSel.options.length > 1) _mrPivotSel.remove(1)
    for (const j of (joints ?? [])) {
      const opt = document.createElement('option')
      opt.value = j.id
      opt.textContent = `Joint: ${j.name}`
      _mrPivotSel.appendChild(opt)
    }
    // "ssDNA constrained" — only when every inter-cluster connection from this
    // cluster passes through a flexible segment (free-until-taut drag).
    if (flexRelax.hasGate(clusterId)) {
      const opt = document.createElement('option')
      opt.value = 'ssdna'
      opt.textContent = 'ssDNA constrained'
      _mrPivotSel.appendChild(opt)
    }
  }

  function _mrSetSelectedPivot(id) {
    if (_mrPivotSel) _mrPivotSel.value = id ?? 'centroid'
    _mrShowJointMode(id !== 'centroid' && id != null)
  }

  function _mrSetClusterOptions(clusters, selectedId) {
    if (!_mrClusterSel) return
    _mrClusterSel.innerHTML = ''
    for (const c of clusters) {
      const opt = document.createElement('option')
      opt.value = c.id
      opt.textContent = c.name
      _mrClusterSel.appendChild(opt)
    }
    _mrClusterSel.value = selectedId ?? clusters[clusters.length - 1]?.id ?? ''
  }

  function _mrSyncClusterDropdown(clusterId) {
    if (_mrClusterSel) _mrClusterSel.value = clusterId
  }

  function _mrCommitInputs() {
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

  // Pivot dropdown change
  _mrPivotSel?.addEventListener('change', () => {
    const val = _mrPivotSel.value
    if (val === 'centroid') {
      _mrShowJointMode(false)
      clusterGizmo.setConstraint('centroid', null)
    } else if (val === 'ssdna') {
      _mrShowJointMode(false)
      const clusterId = store.getState().activeClusterId
      clusterGizmo.setConstraint('ssdna', flexRelax.buildSsdnaPayload(clusterId))
      showToast('ssDNA constrained: drag the arm — tethers won’t overstretch')
    } else {
      const joint = store.getState().currentDesign?.cluster_joints?.find(j => j.id === val)
      if (joint) { _mrShowJointMode(true); clusterGizmo.setConstraint('joint', joint) }
    }
  })

  // Cluster dropdown change — switch gizmo to chosen cluster
  _mrClusterSel?.addEventListener('change', async () => {
    const clusterId = _mrClusterSel.value
    if (!clusterId || !isTranslateRotateActive()) return
    if (clusterId === store.getState().activeClusterId) return
    await refreshClusterPivotForAttach(clusterId)
    clusterGizmo.attach(clusterId, scene, camera, canvas)
    // Repopulate pivot options (joints + ssDNA-constrained gate) for this cluster.
    await flexRelax.refreshFlexGates()
    const joints = store.getState().currentDesign?.cluster_joints?.filter(j => j.cluster_id === clusterId) ?? []
    _mrSetPivotOptions(joints, clusterId)
    _mrSetSelectedPivot('centroid')
    clusterGizmo.setConstraint('centroid', null)
  })

  return {
    panel:                        _mrPanel,
    clusterSel:                   _mrClusterSel,
    pivotSel:                     _mrPivotSel,
    setTransformValues:           _mrSetTransformValues,
    setTransformValuesFromMatrix: _mrSetTransformValuesFromMatrix,
    setJointAngle:                _mrSetJointAngle,
    setPivotOptions:              _mrSetPivotOptions,
    setSelectedPivot:             _mrSetSelectedPivot,
    setClusterOptions:            _mrSetClusterOptions,
    syncClusterDropdown:          _mrSyncClusterDropdown,
    showJointMode:                _mrShowJointMode,
    commitInputs:                 _mrCommitInputs,
    getAssemblyCtx:               () => _mrAssemblyCtx,
    setAssemblyCtx:               (ctx) => { _mrAssemblyCtx = ctx },
    getPivotIsJoint:              () => _mrPivotIsJoint,
  }
}
