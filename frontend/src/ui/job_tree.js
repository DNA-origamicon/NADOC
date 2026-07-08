/**
 * ui/job_tree.js — shared job-list hierarchy helpers for the oxDNA and MD panels.
 *
 * Both panels render a parent→child job tree indented by depth (an oxDNA
 * relaxation with its field/production child runs; an MD relaxation with its
 * refit/retry-derived jobs). These pure helpers flatten the job set into a
 * pre-order render list and compute the delete-cascade descendant set.  They are
 * engine-agnostic: they key only off `job_id`, `parent_job_id`, and `created_at`.
 */

/** Pure: flatten the job set into a pre-order render list, following the
 *  parent_job_id chain to ANY depth (relax → child1 → child2 → …).  Returns
 *  [{ job, depth, index, childCount }] where depth 0 = a root and depth≥1 = a derived
 *  child (indent by depth); `index` is the GLOBAL run number (1..N) of a child among
 *  all non-root jobs in created_at order, so chained runs read Run 1 → Run 2 → …
 *  regardless of nesting; `childCount` is the number of direct children a node has
 *  (drives the expand/collapse chevron).  Roots are newest first; children oldest
 *  first (run order).  An orphan child (parent absent) is treated as its own root.
 *
 *  Pass `{ collapsedIds }` (a Set of job ids) to NOT recurse into those parents —
 *  their subtree is hidden but the parent row still reports its `childCount`, so an
 *  ensemble of N production replicas can render as one collapsible item. */
export function flattenJobTree(jobs, { collapsedIds = null } = {}) {
  const list = jobs || []
  const ids = new Set(list.map(j => j.job_id))
  const collapsed = collapsedIds || new Set()
  const childrenOf = new Map()
  const roots = []
  for (const j of list) {
    const pid = j.parent_job_id
    if (pid && ids.has(pid)) {
      if (!childrenOf.has(pid)) childrenOf.set(pid, [])
      childrenOf.get(pid).push(j)
    } else {
      roots.push(j)
    }
  }
  // Global run numbering: every non-root job by created_at ascending.
  const runNo = new Map()
  list.filter(j => j.parent_job_id && ids.has(j.parent_job_id))
    .slice().sort((a, b) => (a.created_at || 0) - (b.created_at || 0))
    .forEach((j, i) => runNo.set(j.job_id, i + 1))
  const out = []
  const visit = (job, depth) => {
    const kids = (childrenOf.get(job.job_id) || [])
    out.push({ job, depth, index: runNo.get(job.job_id) || 0, childCount: kids.length })
    if (collapsed.has(job.job_id)) return   // hide this node's subtree
    for (const k of kids.slice().sort((a, b) => (a.created_at || 0) - (b.created_at || 0))) {
      visit(k, depth + 1)
    }
  }
  roots.slice().sort((a, b) => (b.created_at || 0) - (a.created_at || 0)).forEach(r => visit(r, 0))
  return out
}

/** Pure: the set of ALL descendant job ids (children, grandchildren, …) of jobId,
 *  for the delete-cascade warning count. */
export function descendantIds(jobs, jobId) {
  const childrenOf = new Map()
  for (const j of jobs || []) {
    const pid = j.parent_job_id
    if (pid) {
      if (!childrenOf.has(pid)) childrenOf.set(pid, [])
      childrenOf.get(pid).push(j.job_id)
    }
  }
  const out = new Set()
  const stack = [...(childrenOf.get(jobId) || [])]
  while (stack.length) {
    const id = stack.pop()
    if (out.has(id)) continue
    out.add(id)
    for (const c of (childrenOf.get(id) || [])) stack.push(c)
  }
  return out
}
