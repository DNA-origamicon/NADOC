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
