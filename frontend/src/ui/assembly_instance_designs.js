/**
 * Shared per-PartInstance Design cache for assembly sidebar panels.
 *
 * Assembly instances are file-backed after import (inline designs are spilled to
 * disk), so `inst.source.design` is usually absent client-side. Designs are
 * resolved via the renderer cache (sync fast-path) with an async
 * `GET /assembly/instances/{id}/design` fallback — the same pattern as the
 * Overhangs Manager popup's `_ensureDesignCache`. Both the sidebar "Overhangs"
 * list and the "Overhang Connections" panel use ONE implementation so per-instance
 * overhang resolution can't fork.
 *
 * @param {object} deps
 * @param {(instanceId:string)=>object|null} [deps.getInstanceDesign] — renderer-cached
 *        resolver (may be null before the renderer finishes building).
 * @param {(instanceId:string)=>Promise<{design?:object}>} [deps.fetchInstanceDesign] — async fallback.
 */
export function initInstanceDesignCache({ getInstanceDesign, fetchInstanceDesign } = {}) {
  const _cache = new Map()        // instanceId → Design
  const _attempted = new Set()    // instanceIds already fetched (don't retry on failure)

  /** Resolve one instance's design (cache → renderer → inline), caching hits. */
  function resolve(inst) {
    if (!inst) return null
    const cached = _cache.get(inst.id)
    if (cached) return cached
    const d = getInstanceDesign?.(inst.id) ?? inst?.source?.design ?? null
    if (d) _cache.set(inst.id, d)
    return d
  }

  /** Fetch (once) any instance whose design isn't resolvable yet; calls `onReady`
   *  after any fetches land so the caller can re-render. */
  async function ensure(assembly, onReady) {
    if (!fetchInstanceDesign) return
    const missing = (assembly?.instances ?? [])
      .filter(i => !resolve(i) && !_attempted.has(i.id))
    if (!missing.length) return
    missing.forEach(i => _attempted.add(i.id))
    await Promise.all(missing.map(i =>
      fetchInstanceDesign(i.id)
        .then(json => { if (json?.design) _cache.set(i.id, json.design) })
        .catch(() => { /* leave unresolved */ })))
    onReady?.()
  }

  /** Drop cache entries for instances no longer in the assembly. */
  function prune(liveInstanceIds) {
    const live = new Set(liveInstanceIds ?? [])
    for (const id of [..._cache.keys()]) if (!live.has(id)) _cache.delete(id)
    for (const id of [..._attempted]) if (!live.has(id)) _attempted.delete(id)
  }

  /** Overwrite a cached design (e.g. from a mutation response) so lists refresh
   *  without a round-trip. */
  function set(instanceId, design) { if (instanceId && design) _cache.set(instanceId, design) }

  const designFor = (instanceId) => _cache.get(instanceId) ?? null
  const overhangsFor = (instanceId) => designFor(instanceId)?.overhangs ?? []

  return { resolve, ensure, prune, set, designFor, overhangsFor }
}
