// Assembly transform engine — the shared rigid-body transform state + live-apply
// + commit-queue that group_gizmo, the Move/Rotate panel shell, and the
// Translate/Rotate tool all lean on. Lifted verbatim out of main.js's closure
// (carve-up keystone campaign) so those three consumers stop sharing state via
// the closure and take it as an injected dependency instead.
//
// Owns the file-wide pending-transform Maps (touched by dev hooks, exit-cleanup,
// keyboard-commit, and the gizmo/panel commit paths). The Three-Layer Law still
// holds: these are display-state transforms; nothing here mutates topology.
import * as THREE from 'three'
import { matrixFromInstance } from './assembly_diff.js'
import { isGroupAnchored, getRigidBodyGroup, getKinematicChildren } from './assembly_constraint_graph.js'

/**
 * @param {Object} deps
 * @param {Object} deps.store                 - global store (getState().currentAssembly)
 * @param {Object} deps.api                   - backend api (patchInstanceClusterTransform, propagateFk)
 * @param {Object} deps.assemblyRenderer      - shared instance renderer (setLiveTransform, getConnectorClusterIds)
 * @param {Object} deps.assemblyJointRenderer - joint indicator renderer (setLiveJointTransform)
 */
export function initAssemblyTransform({
  store, api, assemblyRenderer, assemblyJointRenderer,
}) {
  const pendingTransforms = new Map()
  const pendingPartJoints = new Map()

  function effectiveInstanceMatrix(inst) {
    return pendingTransforms.get(inst.id)?.clone() ?? matrixFromInstance(inst)
  }

  function createAssemblyTransformContext(instanceId) {
    const assembly = store.getState().currentAssembly
    if (!assembly) return null

    const { anchored } = isGroupAnchored(assembly, instanceId)
    if (anchored) return null

    const groupIds = getRigidBodyGroup(assembly, instanceId)
    const groupStartTransforms = new Map()
    for (const id of groupIds) {
      const gi = assembly.instances.find(i => i.id === id)
      if (!gi) continue
      groupStartTransforms.set(id, effectiveInstanceMatrix(gi))
    }
    const primaryStart = groupStartTransforms.get(instanceId)
    if (!primaryStart) return null
    return { instanceId, assembly, groupStartTransforms, primaryStart }
  }

  function applyAssemblyPrimaryLive(ctx, primaryMat4) {
    if (!ctx || !primaryMat4) return
    const delta = primaryMat4.clone().multiply(ctx.primaryStart.clone().invert())
    const asm = store.getState().currentAssembly
    for (const [id, startMat] of ctx.groupStartTransforms) {
      const liveMat = delta.clone().multiply(startMat)
      assemblyRenderer.setLiveTransform(id, liveMat)
      assemblyJointRenderer.setLiveJointTransform(id, liveMat, asm)
    }
    applyFKLive(asm, delta, [...ctx.groupStartTransforms.keys()])
    return delta
  }

  function queueAssemblyPrimaryCommit(ctx, primaryMat4) {
    if (!ctx || !primaryMat4) return
    pendingTransforms.set(ctx.instanceId, primaryMat4.clone())
  }

  async function commitAssemblyPending() {
    const pendingJoints = [...pendingPartJoints.values()]
    pendingPartJoints.clear()
    for (const patch of pendingJoints) {
      await api.patchInstanceClusterTransform(patch.instanceId, patch.body)
    }

    const pending = [...pendingTransforms.entries()]
    pendingTransforms.clear()
    for (const [instanceId, mat] of pending) {
      await api.propagateFk(instanceId, mat.clone().transpose().toArray())
    }
  }

  function hasAssemblyPending() {
    return pendingTransforms.size > 0 || pendingPartJoints.size > 0
  }

  // ── Forward kinematics live visual propagation ───────────────────────────────
  /**
   * Apply a world-space delta to all kinematic descendants of rootIds.
   * Reads committed transforms from assembly (store snapshot captured at drag-start).
   * @param {Object}         assembly  - store's currentAssembly (captured at drag-start)
   * @param {THREE.Matrix4}  delta     - world-space transform delta
   * @param {string|string[]} rootIds  - instances already moved by caller (seed visited set)
   */
  function applyFKLive(assembly, delta, rootIds) {
    if (!assembly) return
    const visited = new Set(Array.isArray(rootIds) ? rootIds : [rootIds])
    const queue   = [...visited]
    while (queue.length) {
      const parentId = queue.shift()
      for (const { childId } of getKinematicChildren(assembly, parentId)) {
        if (visited.has(childId)) continue
        const childInst = assembly.instances?.find(i => i.id === childId)
        if (!childInst || childInst.fixed) continue
        const childOld = new THREE.Matrix4().fromArray(childInst.transform.values).transpose()
        const childLiveMat = delta.clone().multiply(childOld)
        assemblyRenderer.setLiveTransform(childId, childLiveMat)
        assemblyJointRenderer.setLiveJointTransform(childId, childLiveMat, assembly)
        visited.add(childId)
        // Expand child's rigid group so they all follow
        for (const memberId of getRigidBodyGroup(assembly, childId)) {
          if (visited.has(memberId)) continue
          const m = assembly.instances?.find(i => i.id === memberId)
          if (!m || m.fixed) continue
          const memberLiveMat = delta.clone().multiply(new THREE.Matrix4().fromArray(m.transform.values).transpose())
          assemblyRenderer.setLiveTransform(memberId, memberLiveMat)
          assemblyJointRenderer.setLiveJointTransform(memberId, memberLiveMat, assembly)
          visited.add(memberId)
          queue.push(memberId)
        }
        queue.push(childId)
      }
    }
  }

  function applyClusterMateFKLive(assembly, instanceId, clusterId, delta, startTransforms) {
    if (!assembly) return
    const visited = new Set([instanceId])
    const queue = []

    function _jointSideClusterIds(joint, side) {
      const ids = new Set()
      if (side === 'a') {
        if (joint.cluster_id_a) ids.add(joint.cluster_id_a)
        if (!joint.instance_a_id || !joint.connector_a_label) return ids
        const inst = assembly.instances?.find(i => i.id === joint.instance_a_id)
        const ipClusterId = inst?.interface_points?.find(p => p.label === joint.connector_a_label)?.cluster_id
        if (ipClusterId) ids.add(ipClusterId)
        for (const cid of assemblyRenderer.getConnectorClusterIds?.(joint.instance_a_id, joint.connector_a_label) ?? []) {
          if (cid) ids.add(cid)
        }
        return ids
      }
      if (joint.cluster_id_b) ids.add(joint.cluster_id_b)
      const inst = assembly.instances?.find(i => i.id === joint.instance_b_id)
      const ipClusterId = inst?.interface_points?.find(p => p.label === joint.connector_b_label)?.cluster_id
      if (ipClusterId) ids.add(ipClusterId)
      for (const cid of assemblyRenderer.getConnectorClusterIds?.(joint.instance_b_id, joint.connector_b_label) ?? []) {
        if (cid) ids.add(cid)
      }
      return ids
    }

    function _startMat(id) {
      const inst = assembly.instances?.find(i => i.id === id)
      return startTransforms.get(id) ?? (inst ? matrixFromInstance(inst) : null)
    }

    function _moveSeed(seedId) {
      if (!seedId || visited.has(seedId)) return
      const seedInst = assembly.instances?.find(i => i.id === seedId)
      if (!seedInst || seedInst.fixed) return
      const seedStart = _startMat(seedId)
      if (!seedStart) return
      const seedLiveMat = delta.clone().multiply(seedStart)
      assemblyRenderer.setLiveTransform(seedId, seedLiveMat)
      assemblyJointRenderer.setLiveJointTransform(seedId, seedLiveMat, assembly)
      visited.add(seedId)
      queue.push(seedId)

      for (const memberId of getRigidBodyGroup(assembly, seedId)) {
        if (visited.has(memberId)) continue
        const memberInst = assembly.instances?.find(i => i.id === memberId)
        if (!memberInst || memberInst.fixed) continue
        const memberStart = _startMat(memberId)
        if (!memberStart) continue
        const memberLiveMat = delta.clone().multiply(memberStart)
        assemblyRenderer.setLiveTransform(memberId, memberLiveMat)
        assemblyJointRenderer.setLiveJointTransform(memberId, memberLiveMat, assembly)
        visited.add(memberId)
        queue.push(memberId)
      }
    }

    for (const joint of assembly.joints ?? []) {
      if (joint.instance_a_id === instanceId && _jointSideClusterIds(joint, 'a').has(clusterId)) {
        _moveSeed(joint.instance_b_id)
      } else if (joint.instance_b_id === instanceId && _jointSideClusterIds(joint, 'b').has(clusterId)) {
        _moveSeed(joint.instance_a_id)
      }
    }

    while (queue.length) {
      const parentId = queue.shift()
      for (const { childId } of getKinematicChildren(assembly, parentId)) {
        _moveSeed(childId)
      }
    }
  }

  return {
    pendingTransforms,
    pendingPartJoints,
    effectiveInstanceMatrix,
    createAssemblyTransformContext,
    applyAssemblyPrimaryLive,
    queueAssemblyPrimaryCommit,
    commitAssemblyPending,
    hasAssemblyPending,
    applyFKLive,
    applyClusterMateFKLive,
  }
}
