// Base-level selection identity — one nucleotide, addressed by a STRING KEY.
//
// The `base` selection level picks a single backbone bead. Those beads come from
// five different renderers (helix_renderer's iSpheres/iCubes/iFluoros,
// crossover_connections' extra-base mesh, flexible_arcs, overhang_link_arcs), so
// the pool needs one identity that spans all of them.
//
// We reuse the key format the app ALREADY has rather than inventing a tagged union:
//
//   helix:bp:dir[:copy]   the 4-part nucleotide key (helix_renderer's _copyKeyToEntry,
//                         applyScalarColors, the backend's (helix_id, bp_index, direction)
//                         tuple). `copy` disambiguates loop beads, which share a bp_index.
//   __xb__:<xoId>:<k>     an extra crossover base. This 3-part form is NOT ours — it is
//                         the repo's existing pseudo-nucleotide address (see
//                         crossover_connections.js `__xb__:${xoId}:${k}`, design_renderer's
//                         scalar-colour path, and backend/core/atomistic.py). Keep it
//                         verbatim so those consumers keep working.
//
// Extension bases (`__ext_<extension_id>` helix) and ss-linker bridge bases
// (`__lnk__<connId>` helix) fit the 4-part form unchanged — they already carry synthetic
// helix ids in the geometry payload.
//
// WHY strings and not objects: the store key becomes `string[]`, the same shape as
// `multiSelectedStrandIds`/`multiSelectedOverhangIds` — trivially serialisable, cheap to
// Set-dedupe, and immediately parseable by the eight-plus sites that already read these
// formats.
//
// Everything here is pure (no THREE / DOM / store) so it unit-tests directly.

/** The extra-crossover-base pseudo-helix. Reserved — never a real helix id. */
export const XB_HELIX = '__xb__'

/**
 * Key for a real nucleotide. `copy` (the loop-bead ordinal) is emitted ONLY when
 * non-zero, so ordinary beads keep the 3-part form the rest of the app writes.
 *
 * @param {{helix_id:string, bp_index:number, direction:string}} nuc
 * @param {number} [copy=0]
 */
export function baseKey(nuc, copy = 0) {
  if (!nuc?.helix_id) return null
  const c = copy || 0
  return c ? `${nuc.helix_id}:${nuc.bp_index}:${nuc.direction}:${c}`
           : `${nuc.helix_id}:${nuc.bp_index}:${nuc.direction}`
}

/**
 * Key for an extra crossover base. `k` is the SIMULATION insert index (5′→3′), not the
 * geometric bead slot — callers must run the slot through `simBeadIndex` first (see
 * crossover_connections.js). Getting that backwards silently mislabels every bead on a
 * B→A crossover.
 */
export function xbKey(crossoverId, k) {
  if (!crossoverId && crossoverId !== 0) return null
  return `${XB_HELIX}:${crossoverId}:${k}`
}

/**
 * Parse a key back into its parts.
 *
 * Splits from the RIGHT, because helix ids legitimately contain the separator and
 * underscores: `__ext_<uuid>`, `__lnk__<connId>`, and `__xb__`'s middle field is a
 * crossover-id string. A left-to-right split mangles all three.
 *
 * @returns {{helix_id:string, bp_index:number, direction:string, copy:number}
 *          | {helix_id:'__xb__', crossover_id:string, k:number}
 *          | null}
 */
export function parseBaseKey(key) {
  if (typeof key !== 'string' || !key) return null
  if (key.startsWith(`${XB_HELIX}:`)) {
    const rest = key.slice(XB_HELIX.length + 1)
    const i = rest.lastIndexOf(':')
    if (i < 0) return null
    const k = Number(rest.slice(i + 1))
    if (!Number.isFinite(k)) return null
    return { helix_id: XB_HELIX, crossover_id: rest.slice(0, i), k }
  }
  const parts = key.split(':')
  if (parts.length < 3) return null
  // Trailing numeric field = the loop-copy ordinal (4-part form).
  let copy = 0
  let tail = parts.length
  if (parts.length >= 4 && /^\d+$/.test(parts[parts.length - 1])) {
    copy = Number(parts[parts.length - 1])
    tail -= 1
  }
  const direction = parts[tail - 1]
  const bp_index  = Number(parts[tail - 2])
  const helix_id  = parts.slice(0, tail - 2).join(':')
  if (!helix_id || !Number.isFinite(bp_index)) return null
  return { helix_id, bp_index, direction, copy }
}

/**
 * Which renderer family a key belongs to — used to route the glow/position lookup.
 * `'backbone'` covers ordinary beads, 5′ cubes, extension tails and fluorophore tips
 * (all real nucleotides in helix_renderer's meshes).
 *
 * @returns {'xover'|'sslink'|'extension'|'backbone'|null}
 */
export function baseFamily(key) {
  const p = parseBaseKey(key)
  if (!p) return null
  if (p.helix_id === XB_HELIX) return 'xover'
  if (p.helix_id.startsWith('__lnk__')) return 'sslink'
  if (p.helix_id.startsWith('__ext_')) return 'extension'
  return 'backbone'
}

/** Toggle a key in/out of a pool. Returns a NEW array; a null key is a no-op. */
export function toggleBaseKey(keys = [], key) {
  if (!key) return [...keys]
  return keys.includes(key) ? keys.filter(k => k !== key) : [...keys, key]
}

/** Dedupe, preserving first-seen order, dropping nulls. */
export function dedupeBaseKeys(keys = []) {
  const seen = new Set()
  const out = []
  for (const k of keys) {
    if (!k || seen.has(k)) continue
    seen.add(k)
    out.push(k)
  }
  return out
}

/** Union of two pools (additive lasso / multi-select), first-seen order preserved. */
export function mergeBaseKeys(existing = [], incoming = []) {
  return dedupeBaseKeys([...existing, ...incoming])
}

/**
 * Drop keys whose owning object no longer exists in the design.
 *
 * DELIBERATELY CONSERVATIVE: a key survives unless its owner is *positively* known to be
 * gone. Pass only the id sets you actually have — an omitted set means "can't tell", and
 * keys of that family are kept.
 *
 * This is not the same as a mesh rebuild. A rebuild replaces the InstancedMeshes while the
 * bases still exist, and the pool is key-based precisely so it survives that (the glow
 * re-resolves). This prunes the other case: the helix/crossover/extension/linker was
 * actually deleted, so the key can never resolve again and would otherwise sit in the pool
 * as a phantom.
 *
 * @param {string[]} keys
 * @param {{helixIds?:Set<string>, crossoverIds?:Set<string>,
 *          extensionIds?:Set<string>, connectionIds?:Set<string>}} live
 */
export function pruneBaseKeys(keys = [], live = {}) {
  const { helixIds, crossoverIds, extensionIds, connectionIds } = live
  return keys.filter((key) => {
    const p = parseBaseKey(key)
    if (!p) return false                       // unparseable → never resolvable
    if (p.helix_id === XB_HELIX) {
      return !crossoverIds || crossoverIds.has(p.crossover_id)
    }
    if (p.helix_id.startsWith('__ext_')) {
      return !extensionIds || extensionIds.has(p.helix_id.slice('__ext_'.length))
    }
    if (p.helix_id.startsWith('__lnk__')) {
      return !connectionIds || connectionIds.has(p.helix_id.slice('__lnk__'.length))
    }
    return !helixIds || helixIds.has(p.helix_id)
  })
}
