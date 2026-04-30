/**
 * Constraint graph utilities for assembly mate-based movement.
 *
 * Pure functions — no Three.js, no DOM, no side effects.
 */

/**
 * BFS over rigid joints to find all instances in the same rigid body group.
 *
 * @param {Object} assembly   - currentAssembly from store
 * @param {string} instanceId - starting instance
 * @returns {string[]}        - all instance IDs in the rigid group (includes input)
 *
 * Rules:
 *  - Only traverses joints with joint_type === 'rigid'
 *  - Stops at instances where fixed === true (they anchor the group boundary
 *    but are NOT included in the returned group)
 *  - World-anchored rigid joints (instance_a_id = null) are skipped
 */
export function getRigidBodyGroup(assembly, instanceId) {
  if (!assembly) return [instanceId]

  const instances = assembly.instances ?? []
  const joints    = assembly.joints    ?? []

  const fixedIds = new Set(instances.filter(i => i.fixed).map(i => i.id))

  // Build adjacency list from rigid joints
  const adj = new Map()
  for (const j of joints) {
    if (j.joint_type !== 'rigid') continue
    if (!j.instance_a_id || !j.instance_b_id) continue
    if (!adj.has(j.instance_a_id)) adj.set(j.instance_a_id, [])
    if (!adj.has(j.instance_b_id)) adj.set(j.instance_b_id, [])
    adj.get(j.instance_a_id).push(j.instance_b_id)
    adj.get(j.instance_b_id).push(j.instance_a_id)
  }

  // BFS from instanceId; do not enter fixed nodes
  const visited = new Set([instanceId])
  const queue   = [instanceId]
  while (queue.length) {
    const cur = queue.shift()
    for (const nbr of (adj.get(cur) ?? [])) {
      if (visited.has(nbr)) continue
      if (fixedIds.has(nbr)) continue
      visited.add(nbr)
      queue.push(nbr)
    }
  }

  return [...visited]
}

/**
 * Find the first revolute joint for which this instance is the child (instance_b).
 *
 * @param {Object} assembly
 * @param {string} instanceId
 * @returns {Object|null}  AssemblyJoint, or null if none
 */
export function findRevoluteJoint(assembly, instanceId) {
  if (!assembly) return null
  return (assembly.joints ?? []).find(
    j => j.joint_type === 'revolute' && j.instance_b_id === instanceId,
  ) ?? null
}

/**
 * Find the first prismatic joint for which this instance is the child (instance_b).
 *
 * @param {Object} assembly
 * @param {string} instanceId
 * @returns {Object|null}  AssemblyJoint, or null if none
 */
export function findPrismaticJoint(assembly, instanceId) {
  if (!assembly) return null
  return (assembly.joints ?? []).find(
    j => j.joint_type === 'prismatic' && j.instance_b_id === instanceId,
  ) ?? null
}

/**
 * Get all direct kinematic children of an instance — joints where instanceId is
 * the parent (instance_a_id) and the joint is non-rigid (rigid groups are handled
 * separately by getRigidBodyGroup).
 *
 * @param {Object} assembly
 * @param {string} instanceId
 * @returns {{ joint: Object, childId: string }[]}
 */
export function getKinematicChildren(assembly, instanceId) {
  if (!assembly) return []
  return (assembly.joints ?? [])
    .filter(j => j.instance_a_id === instanceId && j.instance_b_id && j.joint_type !== 'rigid')
    .map(j => ({ joint: j, childId: j.instance_b_id }))
}

/**
 * Check whether an instance (or its rigid body group) is anchored — i.e. has a
 * rigid joint to a fixed instance, meaning the whole group is immovable.
 *
 * @param {Object} assembly
 * @param {string} instanceId
 * @returns {{ anchored: boolean, fixedIds: string[] }}
 *   anchored  — true if the group cannot be moved
 *   fixedIds  — IDs of fixed instances that anchor it (empty when anchored only by
 *               instanceId itself being fixed, in which case instanceId IS the anchor)
 */
/**
 * BFS over rigid joints from every fixed instance to compute the minimum rigid-
 * chain depth for all anchored instances.
 *
 * Depth 0  = the fixed instance itself
 * Depth 1  = directly rigidly connected to a fixed instance
 * Depth N  = N rigid hops from the nearest fixed anchor
 *
 * Only instances reachable via rigid joints from a fixed instance are included
 * in the returned Map.  Instances that are free (no rigid path to a fixed anchor)
 * are absent.
 *
 * @param {Object} assembly
 * @returns {Map<string, number>}  instanceId → depth
 */
export function computeFixedDepths(assembly) {
  const depths = new Map()
  if (!assembly) return depths

  const instances = assembly.instances ?? []
  const joints    = assembly.joints    ?? []

  const adj = new Map()
  for (const j of joints) {
    if (j.joint_type !== 'rigid') continue
    if (!j.instance_a_id || !j.instance_b_id) continue
    if (!adj.has(j.instance_a_id)) adj.set(j.instance_a_id, [])
    if (!adj.has(j.instance_b_id)) adj.set(j.instance_b_id, [])
    adj.get(j.instance_a_id).push(j.instance_b_id)
    adj.get(j.instance_b_id).push(j.instance_a_id)
  }

  const queue = []
  for (const inst of instances) {
    if (inst.fixed) { depths.set(inst.id, 0); queue.push(inst.id) }
  }

  while (queue.length) {
    const cur = queue.shift()
    const d   = depths.get(cur)
    for (const nbr of (adj.get(cur) ?? [])) {
      if (depths.has(nbr)) continue
      depths.set(nbr, d + 1)
      queue.push(nbr)
    }
  }

  return depths
}

export function isGroupAnchored(assembly, instanceId) {
  if (!assembly) return { anchored: false, fixedIds: [] }

  const inst = (assembly.instances ?? []).find(i => i.id === instanceId)
  if (inst?.fixed) return { anchored: true, fixedIds: [instanceId] }

  const group   = new Set(getRigidBodyGroup(assembly, instanceId))
  const fixedIds = []

  for (const j of (assembly.joints ?? [])) {
    if (j.joint_type !== 'rigid') continue
    if (!j.instance_a_id || !j.instance_b_id) continue

    const aIn = group.has(j.instance_a_id)
    const bIn = group.has(j.instance_b_id)
    if (!aIn && !bIn) continue
    if (aIn && bIn) continue   // both in group — internal joint

    const outsideId = aIn ? j.instance_b_id : j.instance_a_id
    if (group.has(outsideId)) continue
    const outside = (assembly.instances ?? []).find(i => i.id === outsideId)
    if (outside?.fixed && !fixedIds.includes(outsideId)) fixedIds.push(outsideId)
  }

  return { anchored: fixedIds.length > 0, fixedIds }
}
