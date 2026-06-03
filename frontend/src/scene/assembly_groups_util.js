/**
 * Assembly group utilities extracted from main.js. Pure: read a plain assembly
 * object, return a Set. Unit-tested in assembly_groups_util.test.js.
 */

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
