// Assembly transform engine — the shared rigid-body transform state + live-apply
// + commit-queue that group_gizmo, the Move/Rotate panel shell, and the
// Translate/Rotate tool all lean on. Lifted verbatim out of main.js's closure
// (carve-up keystone campaign) so those three consumers stop sharing state via
// the closure and take it as an injected dependency instead.
//
// Owns the file-wide pending-transform Maps (touched by dev hooks, exit-cleanup,
// keyboard-commit, and the gizmo/panel commit paths). The Three-Layer Law still
// holds: these are display-state transforms; nothing here mutates topology.
import { matrixFromInstance } from './assembly_diff.js'
import { isGroupAnchored, getRigidBodyGroup } from './assembly_constraint_graph.js'

/**
 * @param {Object} deps
 * @param {Object} deps.store                 - global store (getState().currentAssembly)
 * @param {Object} deps.api                   - backend api (patchInstanceClusterTransform, propagateFk)
 * @param {Object} deps.assemblyRenderer      - shared instance renderer (setLiveTransform)
 * @param {Object} deps.assemblyJointRenderer - joint indicator renderer (setLiveJointTransform)
 * @param {Function} deps.applyFKLive         - forward-kinematics live propagation (still in main.js for now)
 */
export function initAssemblyTransform({
  store, api, assemblyRenderer, assemblyJointRenderer, applyFKLive,
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

  return {
    pendingTransforms,
    pendingPartJoints,
    effectiveInstanceMatrix,
    createAssemblyTransformContext,
    applyAssemblyPrimaryLive,
    queueAssemblyPrimaryCommit,
    commitAssemblyPending,
    hasAssemblyPending,
  }
}
