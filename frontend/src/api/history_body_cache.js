const tags = new WeakMap()
export function receiveHistoryBodyDigests(design, digests) {
  for (const entry of design?.feature_log ?? []) {
    if (digests?.[entry.id]) tags.set(entry, digests[entry.id])
  }
}
// Hash exact recovery bodies, not entry IDs or metadata revisions. Undo may
// restore a different body under the same ID. Cache immutable string references.
const keys = ['design_snapshot_gz_b64', 'pre_state_gz_b64', 'post_state_gz_b64']
const childKeys = ['diff_added_b64', 'diff_removed_b64', 'diff_modified_b64']
const values = entry => [
  ...keys.map(key => entry[key] || ''),
  ...(entry.children ?? []).flatMap((child, i) => [child.id ?? i, ...childKeys.map(key => child[key] || '')]),
]
function encodedBody(body) {
  const encoder = new TextEncoder()
  const chunks = body.flatMap(value => {
    const bytes = encoder.encode(String(value))
    return [encoder.encode(`${bytes.length}:`), bytes]
  })
  const result = new Uint8Array(chunks.reduce((sum, bytes) => sum + bytes.length, 0))
  let offset = 0
  for (const bytes of chunks) { result.set(bytes, offset); offset += bytes.length }
  return result
}
export function createHistoryBodyCache() {
  let cache = new Map()
  let retained = null
  const digest = async design => {
    if (!globalThis.crypto?.subtle || !design) return {}
    const next = new Map(), result = {}
    await Promise.all((design.feature_log ?? []).map(async entry => {
      const body = values(entry), previous = cache.get(entry.id)
      const same = previous && body.length === previous.body.length && body.every((v, i) => v === previous.body[i])
      const tag = tags.get(entry)
      const tagged = tag && (!previous || tag !== previous.tag)
      const digest = same ? previous.digest : tagged ? Promise.resolve(tag) : crypto.subtle.digest('SHA-256', encodedBody(body))
        .then(bytes => Array.from(new Uint8Array(bytes), b => b.toString(16).padStart(2, '0')).join(''))
      next.set(entry.id, { body, digest, tag })
      result[entry.id] = await digest
    }))
    cache = next
    return result
  }
  // Keep only the immediately preceding request's original history. In
  // particular, undo removes the edit entry that redo will need again. Never
  // attach these retained entries to the actual document or its saved history.
  digest.source = (design, scope) => {
    const previous = retained
    retained = design ? { id: design.id, scope, entries: design.feature_log ?? [] } : null
    if (!design || !previous || previous.id !== design.id || previous.scope !== scope) return design
    const entries = new Map(previous.entries.map(entry => [entry.id, entry]))
    for (const entry of design.feature_log ?? []) entries.set(entry.id, entry)
    return { feature_log: [...entries.values()] }
  }
  return digest
}

export function inheritHistoryBodyDigest(entry, previous) {
  if (tags.has(entry) || !tags.has(previous)) return
  const a = values(entry), b = values(previous)
  if (a.length === b.length && a.every((v, i) => v === b[i])) tags.set(entry, tags.get(previous))
}
