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
import { versionedAssemblySourceKey } from '../api/assembly_instance_design_cache.js'

export function initInstanceDesignCache({ getInstanceDesign, fetchInstanceDesign, waitForAssemblyReady } = {}) {
  const _cache = new Map()        // instanceId → Design
  const _attempted = new Set()    // instanceIds already fetched (don't retry on failure)
  const _sources = new Map()
  const _changed = new Set()
  let _assembly = null
  let _pending = null
  let _controller = null
  let _generation = 0

  function cancelPending() {
    _generation++
    _controller?.abort()
    _controller = null
    _pending = null
  }

  /** Resolve one instance's design (cache → renderer → inline), caching hits. */
  function resolve(inst) {
    if (!inst) return null
    const version = versionedAssemblySourceKey(inst)
    const source = version ?? inst.source
    if (_sources.has(inst.id) && _sources.get(inst.id) !== source) {
      _cache.delete(inst.id)
      _attempted.delete(inst.id)
      _changed.add(inst.id)
    }
    _sources.set(inst.id, source)
    const cached = _cache.get(inst.id)
    if (cached) return cached
    // A source edit can reach the store before the renderer finishes rebuilding.
    const d = inst?.source?.design
      ?? (version || !_changed.has(inst.id) ? getInstanceDesign?.(inst.id, version) : null) ?? null
    if (d) _cache.set(inst.id, d)
    return d
  }

  /** Fetch (once) any instance whose design isn't resolvable yet; calls `onReady`
   *  after any fetches land so the caller can re-render. */
  function ensure(assembly, onReady) {
    if (_assembly !== assembly) {
      cancelPending()
      _assembly = assembly
    }
    if (_pending) return _pending
    const missing = (assembly?.instances ?? [])
      .filter(i => !resolve(i) && !_attempted.has(i.id))
    if (!missing.length || (!fetchInstanceDesign && !waitForAssemblyReady)) return
    const generation = _generation
    const controller = new AbortController()
    _controller = controller
    const current = () => generation === _generation && !controller.signal.aborted
    async function load() {
      if (waitForAssemblyReady) {
        try { await waitForAssemblyReady(assembly, { signal: controller.signal }) }
        catch { return } // A failed or superseded renderer load must not launch background reads.
      }
      if (!current()) return
      // Geometry already includes the display Designs. Re-resolve after it lands
      // before considering a base-only API fallback for an unresolved source.
      const unresolved = missing.filter(i => !resolve(i) && !_attempted.has(i.id))
      if (fetchInstanceDesign) {
        unresolved.forEach(i => _attempted.add(i.id))
        const bySource = new Map()
        for (const i of unresolved) {
          // The fallback is a base Design read; same file sources share it even
          // for legacy snapshots without a live geometry version.
          const key = versionedAssemblySourceKey(i) ?? (i.source?.type === 'file' ? `file:${i.source.path}` : i.id)
          if (!bySource.has(key)) bySource.set(key, [])
          bySource.get(key).push({ instance: i, source: _sources.get(i.id) })
        }
        await Promise.all([...bySource.values()].map(group => {
          return fetchInstanceDesign(group[0].instance.id)
            .then(json => {
              if (!current() || !json?.design) return
              for (const { instance: i, source } of group) {
                if (_sources.has(i.id) && _sources.get(i.id) === source && !_cache.has(i.id)) _cache.set(i.id, json.design)
              }
            })
            .catch(() => { /* leave unresolved */ })
        }))
      }
      if (current()) onReady?.()
    }
    _pending = load().finally(() => {
      if (current()) { _pending = null; _controller = null }
    })
    return _pending
  }

  /** Drop cache entries for instances no longer in the assembly. */
  function prune(liveInstanceIds) {
    const live = new Set(liveInstanceIds ?? [])
    if (!live.size || (_assembly?.instances ?? []).some(i => !live.has(i.id))) cancelPending()
    for (const id of [..._cache.keys()]) if (!live.has(id)) _cache.delete(id)
    for (const id of [..._attempted]) if (!live.has(id)) _attempted.delete(id)
    for (const id of [..._sources.keys()]) if (!live.has(id)) { _sources.delete(id); _changed.delete(id) }
  }

  /** Overwrite a cached design (e.g. from a mutation response) so lists refresh
   *  without a round-trip. */
  function set(instanceId, design) { if (instanceId && design) _cache.set(instanceId, design) }

  const designFor = (instanceId) => _cache.get(instanceId) ?? null
  const overhangsFor = (instanceId) => designFor(instanceId)?.overhangs ?? []

  return { resolve, ensure, prune, set, designFor, overhangsFor }
}
