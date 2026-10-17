/** Private adapter for the existing native placement and residue gestures. */
import * as THREE from 'three'
import { initClusterGizmo, composeGroupMemberTransform, rebaseClusterTranslationForPivot } from './cluster_gizmo.js'
import { initNucleotideTransformTool } from './nucleotide_transform_tool.js'
import { eulerDegToQuat, quatToEulerDeg, stepEulerDeg, extractJointAngleDeg } from './rotation_math.js'
import { buildTetherPayload, makeWorldPosResolver } from './flex_relax.js'
import { simBeadIndex } from './crossover_connections.js'
import { DEFORMATION_PREVIEW_LAYER } from './deformation_preview_camera.js'

const copy = value => structuredClone(value)
const bodyKey = value => JSON.stringify(value.kind === 'extra_base'
  ? ['extra_base', value.crossover_id, value.extra_base_k]
  : ['base', value.helix_id, value.bp_index, value.direction, value.copy_k ?? 0])
const jointLocked = value => !!value && value.min_angle_deg === value.max_angle_deg
const pose = value => ({ pivot: [...value.pivot], translation: [...value.translation], rotation: [...value.rotation] })
const parsedTarget = value => value.kind === 'extra_base'
  ? { helix_id: '__xb__', crossover_id: value.crossover_id, k: value.extra_base_k }
  : { helix_id: value.helix_id, bp_index: value.bp_index, direction: value.direction, copy: value.copy_k ?? 0 }

/** Keep recorded target/compose semantics while composing an existing native gesture delta. */
export function composeHistoricalResidueDraft(baseline, deltas) {
  if (!Array.isArray(deltas) || deltas.length !== baseline.length) throw new Error('Historical residue targets changed')
  return baseline.map((body, i) => {
    const delta = deltas[i]
    if (bodyKey(body) !== bodyKey(delta)) throw new Error('Historical residue target changed')
    const position = delta.pivot.map((value, axis) => value + delta.translation[axis])
    return { ...copy(body), ...composeGroupMemberTransform(body, delta.pivot, delta.rotation, position) }
  })
}

export function createTransformHistoryTool({ scene, camera, canvas, controls, panel, preview,
  onChange, onReset, onApply, onCancel, onError = () => {},
  createClusterGizmo = initClusterGizmo, createNucleotideTool = initNucleotideTransformTool }) {
  let original = null, packet = null, state = null, binding = null, gizmo = null, residues = null
  let disposed = false, locked = false, upgraded = false, primary = null, selected = [], pivotId = 'centroid'
  let geometry = null, baselineBodies = null, groupBaseline = null, groupDelta = null, scheduled = null, motionError = null
  let status = {}, lastPose = null, residueDraft = null
  const priorControls = controls?.enabled
  const privateStore = { getState: () => state, setState: patch => { state = { ...state, ...patch } } }
  const currentKind = () => packet?.evaluated_command_kind ?? packet?.command_kind
  const isPlacement = () => ['cluster_op', 'placement-poses'].includes(currentKind()) || upgraded
  const owner = id => state.currentDesign.cluster_transforms.find(value => value.id === id)
  const constraint = () => packet.control_state.placement_constraints.find(value => value.cluster_id === primary)
  const joint = () => packet.control_state.cluster_joints.find(value => value.id === pivotId && value.cluster_id === primary)
  const error = failure => { motionError = failure; onError(failure) }
  const editable = () => !disposed && !!binding && !locked && !!geometry
  function receive(value) {
    packet = value
    geometry = value.candidate === null ? null : preview.candidateGeometry()
    const c = copy(value.control_state)
    state = { ...state, currentDesign: { ...(geometry?.design ?? {}), ...c },
      currentGeometry: geometry?.records ?? [], currentHelixAxes: geometry?.helixAxes ?? {} }
    if (value.evaluated_command_kind === 'placement-poses') upgraded = true
  }
  function updatePanel() {
    if (!binding || !packet) return
    const kind = currentKind(), inputs = packet.control_state.inputs
    if (!isPlacement()) {
      binding.update({ role: kind.endsWith('-delete') ? 'reset' : 'nucleotide',
        labels: [kind.endsWith('-delete') ? `Saved pose reset · ${inputs.transform_id}`
          : `${baselineBodies?.length ?? 1} saved residue target${baselineBodies?.length === 1 ? '' : 's'}`] })
      return
    }
    const c = owner(primary), j = joint(), options = [{ id: 'centroid', label: 'Centroid' }]
    const details = constraint()
    if (selected.length === 1) {
      for (const point of details?.rotation_points ?? []) if (point.kind === 'overhang_root')
        options.push({ id: `dup:root:${point.overhang_id}`, label: point.label })
      for (const value of packet.control_state.cluster_joints.filter(value => value.cluster_id === primary))
        options.push({ id: value.id, label: `Joint: ${value.name}${jointLocked(value) ? ' (locked)' : ''}` })
      if (c.overhang_duplex_driver_id) options.push({ id: 'dup:taut', label: 'Constrained (taut bonds)' })
      else if (packet.control_state.flexible_gates[primary]?.gate || details?.tethers.length || details?.movable_links.length)
        options.push({ id: 'ssdna', label: 'Constrained (tethers)' })
    }
    const shown = selected.length > 1 ? groupDelta : lastPose ?? c
    binding.update({ role: 'placement', labels: selected.map(id => `Placement · ${owner(id)?.name ?? id}`),
      translation: shown.translation, euler: quatToEulerDeg(shown.rotation),
      jointMode: !!j, jointAngle: j ? extractJointAngleDeg(new THREE.Quaternion(...shown.rotation), j) : undefined,
      pivots: options, pivot: pivotId, placement_upgrade: upgraded ? null : original.control_context.placement_upgrade,
      hint: selected.length > 1 ? 'Explicit saved placements move together in global axes. Joint and tether controls require one selected owner.'
        : jointLocked(j) ? 'This historical joint is locked.' : undefined })
  }
  function tetherPayload() {
    const details = constraint(), key = a => `${a.helix_id}:${a.bp}:${a.direction}`
    const flexible = buildTetherPayload(packet.control_state.flexible_connections, primary,
      state.currentDesign, geometry?.backboneEntries ?? [])
    return { connections: [...flexible.connections, ...(details?.tethers ?? []).map(t => ({
      movingKey: key(t.moving), fixedKey: key(t.fixed), contour: t.contour_nm, rigid: !!t.rigid }))],
      links: (details?.movable_links ?? []).map(link => ({ linkClusterId: link.link_cluster_id,
        helixIds: link.helix_ids, domainIds: link.domain_ids.length ? link.domain_ids : null,
        tethers: link.tethers.map(t => ({ linkKey: key(t.l), partKey: key(t.part), contour: t.contour_nm, partDragged: t.part_dragged })) })),
      resolveWorldPos: makeWorldPosResolver(geometry?.backboneEntries ?? []) }
  }
  function setConstraint() {
    if (!gizmo?.isActive()) return
    const j = joint()
    if (j) gizmo.setConstraint('joint', j)
    else if (['ssdna', 'dup:taut'].includes(pivotId)) gizmo.setConstraint('ssdna', tetherPayload())
    else gizmo.setConstraint('centroid', null)
  }
  function attachPlacements() {
    if (locked || jointLocked(joint())) return
    if (selected.length > 1) {
      groupBaseline = selected.map(id => ({ id, ...pose({ ...owner(id), ...gizmo.getPendingTransform(id) }) }))
      gizmo.attachGroup(selected, scene, camera, canvas); gizmo.setSpace('world')
      groupDelta = { pivot: [...gizmo.getPivot()], translation: [0, 0, 0], rotation: [0, 0, 0, 1] }
    } else gizmo.attach(primary, scene, camera, canvas)
    setConstraint()
  }
  function completeDefinition(pending) {
    const originalInputs = original.control_context.inputs
    const existing = original.command_kind === 'placement-poses' ? copy(originalInputs) : {
      _proof_version: 1, primary_cluster_id: primary, selected_cluster_ids: [...selected], poses: [],
      authoring: { mode: 'free', joint_id: null, fixed_cluster_ids: [], pivot_id: 'centroid' } }
    const byId = new Map(existing.poses.map(value => [value.cluster_id, value]))
    for (const id of selected) if (!byId.has(id)) byId.set(id, { cluster_id: id, ...pose(owner(id)) })
    for (const value of pending) byId.set(value.clusterId, { cluster_id: value.clusterId, ...pose(value) })
    existing.poses = state.currentDesign.cluster_transforms.filter(c => byId.has(c.id)).map(c => ({
      ...byId.get(c.id), parent_cluster_id: c.parent_cluster_id, overhang_duplex_driver_id: c.overhang_duplex_driver_id }))
    if (existing.poses.length !== byId.size) throw new Error('A moved placement is missing from the fixed prefix')
    existing.authoring = { ...existing.authoring, pivot_id: pivotId,
      mode: joint() ? 'joint' : ['ssdna', 'dup:taut'].includes(pivotId) ? 'tethers' : 'free', joint_id: joint()?.id ?? null }
    if (existing.authoring.fixed_cluster_ids.some(id => byId.has(id))) throw new Error('A fixed historical placement received native pending motion. Reset the draft before continuing.')
    return existing
  }
  function flush() {
    if (!scheduled || !editable()) { scheduled = null; return }
    const transform = scheduled; scheduled = null
    try {
      const pending = new Map(gizmo.getAllPendingTransforms().map(value => [value.clusterId, value]))
      if (selected.length > 1) {
        for (const base of groupBaseline) pending.set(base.id, { clusterId: base.id,
          ...composeGroupMemberTransform(base, transform.pivot, transform.rotation,
            transform.pivot.map((value, i) => value + transform.translation[i])) })
      } else pending.set(primary, { clusterId: primary, ...transform })
      const values = [...pending.values()]
      if (original.command_kind === 'cluster_op' && !upgraded) {
        if (values.some(value => value.clusterId !== primary)) throw new Error('Linked placement motion requires the explicit “Record linked placements” upgrade before Apply.')
        motionError = null; onChange(pose(values.find(value => value.clusterId === primary)))
      } else {
        const definition = completeDefinition(values)
        const patch = original.command_kind === 'cluster_op' ? { ...original.control_context.placement_upgrade, definition } : definition
        motionError = null; onChange(patch)
      }
    } catch (failure) { error(failure) }
  }
  function moved(translation, quaternion) {
    if (!editable()) return
    const rotation = quaternion.toArray ? quaternion.toArray() : [...quaternion]
    const transform = { pivot: [...gizmo.getPivot()], translation: [...translation], rotation }
    if (selected.length > 1) groupDelta = transform
    else lastPose = transform
    scheduled = copy(transform); updatePanel(); queueMicrotask(flush)
  }
  function extraInfo(target) {
    const xovers = geometry?.extraBases, arc = xovers?.arcData.find(value => value.xoId === target.crossover_id)
    if (!arc || target.k < 0 || target.k >= arc.beadCount) return null
    const index = arc.beadStartIdx + simBeadIndex(target.k, arc.beadCount, arc.simReversed), matrix = new THREE.Matrix4()
    xovers.beadsMesh.getMatrixAt(index, matrix)
    return { centroid: new THREE.Vector3().setFromMatrixPosition(matrix) }
  }
  function attachResidues() {
    if (locked || currentKind().endsWith('-delete')) return
    const designRenderer = { residueTransformInfo: target => geometry?.native.residueTransformInfo(target), xoverResidueInfo: extraInfo }
    residues = createNucleotideTool({ store: privateStore, scene, camera, canvas, controls, designRenderer,
      historySession: { targets: baselineBodies.map(parsedTarget), displayLayer: DEFORMATION_PREVIEW_LAYER, onCancel,
        onChange: deltas => {
          if (!editable()) return
          try {
            const bodies = composeHistoricalResidueDraft(baselineBodies, deltas)
            residueDraft = currentKind() === 'nucleotide-transform-batch' ? { transforms: bodies } : bodies[0]
            motionError = null; onChange(residueDraft)
          } catch (failure) { error(failure) }
        } } })
    if (!residues.activate()) throw new Error('The exact historical residue targets are unavailable in the native preview')
  }
  function pickPivot(id) {
    if (!editable() || !isPlacement()) return
    if (selected.length > 1 && id !== 'centroid') throw new Error('Choose one placement to use a native joint or tether frame')
    const details = constraint(), j = packet.control_state.cluster_joints.find(value => value.id === id && value.cluster_id === primary)
    const point = details?.rotation_points.find(value => id === (value.kind === 'centroid' ? 'centroid' : `dup:root:${value.overhang_id}`))
    if (!j && !point && !['centroid', 'ssdna', 'dup:taut'].includes(id)) throw new Error('The historical pivot is unavailable')
    pivotId = id
    if (jointLocked(j)) { gizmo.detach(); updatePanel(); return }
    if (!gizmo.isActive()) attachPlacements()
    if (point) {
      const c = { ...owner(primary), ...(lastPose ?? gizmo.getPendingTransform(primary)) }
      lastPose = { pivot: [...point.point], translation: rebaseClusterTranslationForPivot(c, point.point), rotation: [...c.rotation] }
      gizmo.setPendingTransform(primary, lastPose); gizmo.attach(primary, scene, camera, canvas)
      scheduled = copy(lastPose); flush()
    }
    setConstraint(); updatePanel()
  }
  function callbacks() {
    return {
      onTransform(translation, euler) { if (editable() && !jointLocked(joint())) gizmo?.setTransform(translation, eulerDegToQuat(...euler)) },
      onJointAngle(angle) { if (editable() && joint() && !jointLocked(joint())) gizmo?.setJointRotation(joint(), angle) },
      onStep(axis, degrees, space) { if (editable() && !jointLocked(joint())) {
        const value = selected.length > 1 ? groupDelta : lastPose ?? owner(primary)
        gizmo?.setTransform(value.translation, eulerDegToQuat(...stepEulerDeg(quatToEulerDeg(value.rotation), axis, degrees, space)))
      } },
      onPivot: pickPivot,
      onFrame(space) { if (editable()) gizmo?.setSpace(selected.length > 1 ? 'world' : space) },
      onSnap(value) { if (editable()) gizmo?.setRotationSnap(value) },
      onUpgrade() {
        if (!editable() || upgraded || original.command_kind !== 'cluster_op' || !original.control_context.placement_upgrade) return
        upgraded = true; motionError = null; updatePanel()
        scheduled = lastPose ?? pose(owner(primary)); flush()
      },
      onReset: () => { if (editable()) return onReset() },
      onApply() { if (!disposed && binding) { flush(); if (!motionError) return onApply() } },
      onCancel: () => { if (!disposed && binding) return onCancel() },
    }
  }
  function start(value) {
    receive(value)
    const inputs = original.control_context.inputs
    if (['cluster_op', 'placement-poses'].includes(original.command_kind)) {
      primary = original.command_kind === 'cluster_op' ? inputs.cluster_id : inputs.primary_cluster_id
      selected = original.command_kind === 'cluster_op' ? [primary] : [...inputs.selected_cluster_ids]
      pivotId = inputs.authoring?.pivot_id ?? 'centroid'
      upgraded = original.command_kind === 'placement-poses'
      gizmo = createClusterGizmo(privateStore, controls, () => {}, null, moved, null, { displayLayer: DEFORMATION_PREVIEW_LAYER })
      attachPlacements()
    } else if (!original.command_kind.endsWith('-delete')) {
      baselineBodies = copy(original.command_kind.endsWith('-batch') ? inputs.transforms : [inputs])
      attachResidues()
    }
    updatePanel()
  }
  function clearGestures() {
    scheduled = null; gizmo?.discardPendingTransforms(); gizmo?.detach(); residues?.detach(false)
    gizmo = residues = null
    if (controls) controls.enabled = priorControls
  }
  function keydown(event) {
    if (event.key === 'Escape' && !residues?.isActive()) { event.preventDefault(); onCancel() }
  }
  function setStatus(value) {
    if (!binding || disposed) return
    const wasLocked = locked
    status = value; locked = !!(!geometry || status.expired || status.publicationUnknown || status.refreshNeeded
      || ['apply', 'cancel', 'status', 'refresh'].includes(status.busy))
    if (locked && !wasLocked) {
      scheduled = null; gizmo?.setConstraint('centroid', null); gizmo?.detach(); residues?.detach(false)
      if (controls) controls.enabled = priorControls
    }
    if (!locked && wasLocked) {
      if (isPlacement()) attachPlacements()
      else if (!currentKind().endsWith('-delete')) {
        if (residueDraft) baselineBodies = copy(residueDraft.transforms ?? [residueDraft])
        attachResidues()
      }
      updatePanel()
    }
    binding.setStatus({ ...value, inputsUnavailable: !geometry })
  }
  return {
    open(value) {
      if (disposed || binding) throw new Error('Transform tool is already owned or disposed')
      original = copy(value)
      binding = panel.bindHistorySession(callbacks())
      try { start(value); document.addEventListener('keydown', keydown) }
      catch (failure) { clearGestures(); binding.release(); binding = null; throw failure }
    },
    update(value) { if (!disposed && binding) {
      receive(value); setStatus(status); updatePanel()
      if (gizmo?.isActive() && !gizmo.isDragging?.()) setConstraint()
    } },
    reset(value) {
      if (!binding || disposed) return
      clearGestures(); motionError = null; upgraded = false; lastPose = residueDraft = groupDelta = null; start(value)
    },
    setStatus,
    dispose() {
      if (disposed) return
      disposed = true; document.removeEventListener('keydown', keydown)
      try { clearGestures() } finally {
        binding?.release(); binding = null
        original = packet = state = geometry = baselineBodies = groupBaseline = groupDelta = residueDraft = lastPose = null
        selected = []; status = {}; motionError = null
      }
    },
  }
}
