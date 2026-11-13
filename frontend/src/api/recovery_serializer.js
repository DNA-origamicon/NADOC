// Preserve the exact complete document while avoiding repeated JSON escaping of
// unchanged compressed history bodies. Cache is bounded to the current history.
const bodyKeys = new Set(['design_snapshot_gz_b64', 'pre_state_gz_b64', 'post_state_gz_b64',
  'diff_added_b64', 'diff_removed_b64', 'diff_modified_b64'])
export function createRecoverySerializer() {
  let cache = new Map()
  return design => {
    if (!Array.isArray(design.feature_log)) return JSON.stringify(design)
    const next = new Map()
    const rows = design.feature_log.map(entry => {
      const bodies = []
      const metadata = JSON.stringify(entry, (key, value) => {
        if (bodyKeys.has(key)) { bodies.push(value); return { bodyIndex: bodies.length - 1 } }
        return value
      })
      const previous = cache.get(entry.id)
      const same = previous?.metadata === metadata && bodies.length === previous.bodies.length
        && bodies.every((value, i) => value === previous.bodies[i])
      const row = same ? previous : { metadata, bodies, json: JSON.stringify(entry) }
      next.set(entry.id, row)
      return row.json
    })
    cache = next
    const rest = JSON.stringify({ ...design, feature_log: undefined })
    return `${rest.slice(0, -1)}${rest === "{}" ? "" : ","}"feature_log":[${rows.join(',')}]}`
  }
}
