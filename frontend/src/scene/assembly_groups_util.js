/**
 * Assembly group utilities extracted from main.js. Pure: read a plain assembly
 * object. Unit-tested in assembly_groups_util.test.js.
 */

/** Id of the (top-level) group directly containing `instanceId`, or null. */
export function findOwningGroupId(assembly, instanceId) {
  for (const g of (assembly?.groups ?? [])) {
    if ((g.instance_ids ?? []).includes(instanceId)) return g.id
  }
  return null
}

/** Ordered instance ids belonging to a group, recursing into its subgroups. */
export function collectGroupMemberInstanceIds(assembly, groupId) {
  const groups = assembly?.groups ?? []
  const byId = new Map(groups.map(g => [g.id, g]))
  const out = []
  const stack = [groupId]
  while (stack.length) {
    const gid = stack.pop()
    const cur = byId.get(gid)
    if (!cur) continue
    for (const iid of (cur.instance_ids ?? [])) out.push(iid)
    for (const sgid of (cur.subgroup_ids ?? [])) stack.push(sgid)
  }
  return out
}

/**
 * Decide how a plain (non-Ctrl) assembly click on a part affects PartGroup
 * selection state, BEFORE individual-part selection runs. Pure: reads the
 * picked instance + current group-selection state, returns the action the
 * caller must take. The scene raycast (which instance was hit) stays at the
 * call site; only the PowerPoint-style click-through logic lives here.
 *
 * Semantics (see project-assembly-groups):
 *  - Click a grouped part whose group is NOT active → select the GROUP, stop
 *    (no fallthrough to part selection).
 *  - Click a member of the already-active group → "enter" the group (push the
 *    gid onto groupDiveStack, clear activeGroupId) and fall through so the part
 *    gets selected.
 *  - Click an ungrouped part (or no part) → fall through, no state change.
 *
 * @param {object} args
 * @param {object|null} args.assembly        currentAssembly (or null)
 * @param {string|null} args.hitInstanceId   instance under the click, or null
 * @param {string|null} args.activeGroupId   currently-selected group id, or null
 * @param {string[]}    [args.groupDiveStack] current dive stack
 * @returns {{action:'selectGroup'|'enterGroup'|'none', patch?:object}}
 *   `selectGroup` → apply patch + return (stop). `enterGroup` → apply patch +
 *   fall through. `none` → fall through, no patch.
 */
export function resolveGroupClickThrough({ assembly, hitInstanceId, activeGroupId, groupDiveStack = [] }) {
  const owningGid = hitInstanceId ? findOwningGroupId(assembly, hitInstanceId) : null
  if (!hitInstanceId || !owningGid) return { action: 'none' }
  if (activeGroupId !== owningGid) {
    return {
      action: 'selectGroup',
      patch: { activeGroupId: owningGid, activeInstanceId: null, multiSelectedInstanceIds: [], groupDiveStack: [] },
    }
  }
  return {
    action: 'enterGroup',
    patch: { activeGroupId: null, groupDiveStack: [...groupDiveStack, owningGid] },
  }
}

/** Set of instance ids hidden by any `visible:false` group (recursing subgroups). */
export function computeGroupHiddenInstanceIds(assembly) {
  const out = new Set()
  const groups = assembly?.groups ?? []
  if (!groups.length) return out
  const byId = new Map(groups.map(g => [g.id, g]))
  for (const g of groups) {
    if (g.visible === false) {
      const stack = [g.id]
      while (stack.length) {
        const gid = stack.pop()
        const cur = byId.get(gid)
        if (!cur) continue
        for (const iid of (cur.instance_ids ?? [])) out.add(iid)
        for (const sgid of (cur.subgroup_ids ?? [])) stack.push(sgid)
      }
    }
  }
  return out
}
