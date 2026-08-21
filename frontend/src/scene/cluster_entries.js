/**
 * Cluster → nucleotide membership. One definition of "which nucleotides belong to
 * this cluster", in three shapes: a reusable predicate (`clusterMemberFilter`), the
 * entry-list convenience wrapper (`clusterBackboneEntries`), and the renderer's
 * nucKey string form (`clusterNucKeys` and friends).
 *
 * The predicate was a byte-identical second copy inside assembly_renderer.js
 * (`_clusterMemberFilter`) until that file's split, and the nucKey expansion was a
 * third copy inlined in main.js's visibility handler; all now share this one, so a
 * membership fix lands once. Pure — entries and design are arguments.
 * Unit-tested in cluster_entries.test.js.
 */

/**
 * Predicate deciding whether a nucleotide belongs to a cluster. A plain cluster =
 * all nucleotides on its helix_ids. A MIXED cluster (has domain_ids) = the
 * bridge-domain nucleotides plus nucleotides on helices it owns exclusively
 * (helix_ids not used by a bridge domain).
 *
 * Returns `null` for a cluster with no helix_ids — callers treat that as
 * "nothing selectable", which is distinct from a predicate matching nothing.
 *
 * @param {object} cluster  { helix_ids:[], domain_ids?:[{strand_id, domain_index}] }
 * @param {object} design   { strands:[{id, domains}] }
 * @returns {((nuc:{helix_id, strand_id, domain_index}) => boolean) | null}
 */
export function clusterMemberFilter(cluster, design) {
  if (!cluster?.helix_ids?.length) return null
  if (cluster.domain_ids?.length) {
    const domainKeySet = new Set(cluster.domain_ids.map(d => `${d.strand_id}:${d.domain_index}`))
    const strandMap = _strandMapForDesign(design)
    const bridgeHelixIds = new Set()
    for (const dr of cluster.domain_ids) {
      const dom = strandMap.get(dr.strand_id)?.domains?.[dr.domain_index]
      if (dom) bridgeHelixIds.add(dom.helix_id)
    }
    const exclusiveHelixSet = new Set(cluster.helix_ids.filter(hid => !bridgeHelixIds.has(hid)))
    return nuc =>
      domainKeySet.has(`${nuc.strand_id}:${nuc.domain_index}`) ||
      exclusiveHelixSet.has(nuc.helix_id)
  }
  const helixSet = new Set(cluster.helix_ids)
  return nuc => helixSet.has(nuc.helix_id)
}

// Designs are immutable snapshots in the store. Reuse their strand lookup across
// every cluster predicate/key expansion and let GC reclaim it with the snapshot.
const _designStrandMapCache = new WeakMap()
function _strandMapForDesign(design) {
  if (!design || typeof design !== 'object') return new Map()
  let strandMap = _designStrandMapCache.get(design)
  if (!strandMap) {
    strandMap = new Map((design.strands ?? []).map(strand => [strand.id, strand]))
    _designStrandMapCache.set(design, strandMap)
  }
  return strandMap
}

// Cluster membership predicates depend only on a design snapshot. Selection,
// hover, and VR targeting can resolve thousands of nucleotides against the same
// snapshot; rebuilding every cluster's strand/domain maps for every nucleotide
// turned that path into O(nucleotides × clusters × strands). Weak keys keep the
// cache bounded by the immutable design objects already owned by the store.
const _clusterMembershipCache = new WeakMap()

function _clusterMembership(design) {
  if (!design || typeof design !== 'object') return []
  let compiled = _clusterMembershipCache.get(design)
  if (compiled) return compiled
  compiled = (design.cluster_transforms ?? []).map(cluster => ({
    cluster,
    isMember: clusterMemberFilter(cluster, design),
  }))
  _clusterMembershipCache.set(design, compiled)
  return compiled
}

/** Resolve the same most-specific Cluster that desktop cluster picking uses.
 * Non-default Clusters win by smallest helix footprint, then the default Cluster,
 * then any containing Cluster. Array order is the deterministic tie-breaker.
 */
export function clusterIdForNucleotide(nucleotide, design) {
  const memberships = _clusterMembership(design)
  if (!nucleotide || !memberships.length) return null
  let best = null
  let bestSize = Infinity
  for (const { cluster, isMember } of memberships) {
    if (cluster.is_default) continue
    if (isMember?.(nucleotide)) {
      const size = cluster.helix_ids?.length ?? Infinity
      if (size < bestSize) {
        best = cluster
        bestSize = size
      }
    }
  }
  if (best) return best.id
  const fallback = memberships.find(({ cluster, isMember }) =>
    cluster.is_default && isMember?.(nucleotide)) ??
    memberships.find(({ isMember }) => isMember?.(nucleotide))
  return fallback?.cluster.id ?? null
}

/**
 * Backbone entries belonging to a cluster. Mirrors the active-cluster glow so
 * picking matches the highlighted body.
 * @param {object} cluster  { helix_ids:[], domain_ids?:[{strand_id, domain_index}] }
 * @param {object} design   { strands:[{id, domains}] }
 * @param {Array}  backboneEntries  [{ nuc:{helix_id, strand_id, domain_index} }]
 */
export function clusterBackboneEntries(cluster, design, backboneEntries) {
  if (!cluster?.helix_ids?.length || !backboneEntries?.length) return []
  const isMember = clusterMemberFilter(cluster, design)
  return isMember ? backboneEntries.filter(entry => isMember(entry.nuc)) : []
}

// ── nucKey form ───────────────────────────────────────────────────────────────
// The renderer addresses nucleotides by string key, in two formats (documented at
// helix_renderer.js's _isNucHidden):
//     'h:<helix_id>'                  — every nucleotide on that helix
//     'd:<strand_id>:<domain_index>'  — one domain
// Extension beads live on synthetic helices named '__ext_<id>', so they are
// addressed as 'h:__ext_<id>'.

/**
 * The nucKeys covered by ONE cluster, extension beads included.
 *
 * Same membership rule as `clusterMemberFilter`: a plain cluster covers its whole
 * helix_ids; a MIXED cluster covers each bridge domain by domain key plus the
 * helices it owns exclusively (helix_ids no bridge domain sits on). An extension
 * is covered when its host strand is covered, or when its terminal domain sits on
 * a covered helix.
 *
 * @param {object} cluster { helix_ids:[], domain_ids?:[{strand_id, domain_index}] }
 * @param {object} design  { strands:[{id, domains}], extensions?:[{id, strand_id, end}] }
 * @returns {Set<string>}
 */
export function clusterNucKeys(cluster, design) {
  const keys = new Set()
  if (!cluster?.helix_ids?.length) return keys

  const strandIds = new Set()   // strands this cluster covers by domain key
  const helixIds  = new Set()   // helices this cluster covers whole
  // Extensions need their host strand's terminal domain. Resolve those hosts
  // through one O(strands) index instead of Array.find for every extension.
  const strandMap = _strandMapForDesign(design)

  if (cluster.domain_ids?.length) {
    const bridgeHelixIds = new Set()
    for (const d of cluster.domain_ids) {
      const dom = strandMap.get(d.strand_id)?.domains?.[d.domain_index]
      if (dom) bridgeHelixIds.add(dom.helix_id)
      keys.add(`d:${d.strand_id}:${d.domain_index}`)
      strandIds.add(d.strand_id)
    }
    // Helices the cluster lists but no bridge domain sits on are owned whole.
    for (const hid of cluster.helix_ids) {
      if (!bridgeHelixIds.has(hid)) { keys.add(`h:${hid}`); helixIds.add(hid) }
    }
  } else {
    for (const hid of cluster.helix_ids) { keys.add(`h:${hid}`); helixIds.add(hid) }
  }

  for (const ext of design?.extensions ?? []) {
    if (strandIds.has(ext.strand_id)) {
      keys.add('h:__ext_' + ext.id)
    } else if (helixIds.size) {
      const strand  = strandMap.get(ext.strand_id)
      const termDom = strand && (ext.end === 'five_prime'
        ? strand.domains[0]
        : strand.domains[strand.domains.length - 1])
      if (termDom && helixIds.has(termDom.helix_id)) keys.add('h:__ext_' + ext.id)
    }
  }
  return keys
}

/**
 * Union of `clusterNucKeys` over the clusters named in `idSet`. What the sidebar's
 * visibility toggle wants: hiding any cluster that covers a nucleotide hides it.
 * @param {object} design
 * @param {Set<string>|Array<string>} idSet
 * @returns {Set<string>}
 */
export function clusterNucKeysFor(design, idSet) {
  const want = idSet instanceof Set ? idSet : new Set(idSet ?? [])
  const keys = new Set()
  if (!want.size) return keys
  for (const c of design?.cluster_transforms ?? []) {
    if (!want.has(c.id)) continue
    for (const k of clusterNucKeys(c, design)) keys.add(k)
  }
  return keys
}

/**
 * nucKey → alpha, for the per-cluster opacity fade.
 *
 * Clusters at full opacity contribute nothing, so an unstyled design yields an
 * EMPTY map — that is what keeps the whole feature free (the renderer only installs
 * its per-instance alpha buffers when the map is non-empty).
 *
 * Where clusters OVERLAP the lowest opacity wins, matching the visibility toggle,
 * which already unions: fading a cluster must visibly fade it whatever else happens
 * to cover the same helices.
 *
 * @param {object} design
 * @returns {Map<string, number>}
 */
export function clusterAlphaKeys(design) {
  const out = new Map()
  for (const c of design?.cluster_transforms ?? []) {
    const a = typeof c.opacity === 'number' ? c.opacity : 1
    if (!(a < 1)) continue          // NaN-safe: only a real fade contributes
    const alpha = Math.max(0, a)
    for (const k of clusterNucKeys(c, design)) {
      const prev = out.get(k)
      if (prev === undefined || alpha < prev) out.set(k, alpha)
    }
  }
  return out
}

/**
 * Is this cluster one the app made by itself, rather than one the user built?
 *
 * COLOUR resolution ranks a hand-made cluster ABOVE an auto one, unconditionally: auto
 * clusters routinely blanket every helix (an imported design gets a "Scaffold Cluster"
 * and a "Geometry Cluster" each covering all of them), so without this an auto cluster
 * could silently win the colour on a nucleotide the user had deliberately clustered.
 *
 * `auto_created` is the backend's provenance flag. The name fallback is only for designs
 * saved before it existed and that the backend has not re-serialised yet — and only the
 * two autodetect PREFIXES are safe to infer from, because cluster_autodetect also emits
 * plain "Cluster N", exactly like the user-created default.
 *
 * OPACITY deliberately does NOT use this: overlapping fades take the minimum, so there is
 * no winner to pick.
 */
export function isAutoCluster(c) {
  if (typeof c?.auto_created === 'boolean') return c.auto_created
  return Boolean(c?.is_default) || Boolean(c?.overhang_duplex_driver_id) ||
    /^(Scaffold|Geometry) Cluster /.test(c?.name ?? '')
}

/**
 * Resolve one nucleotide's alpha out of a `clusterAlphaKeys` map. Domain-level
 * entries win over the helix-level fallback, matching `clusterMemberFilter` and
 * `buildClusterColorLookup`. Anything not covered is opaque.
 *
 * Shared so the helix meshes and the crossover extra-base meshes cannot drift —
 * they are separate InstancedMeshes driven from different modules.
 *
 * @param {Map<string, number>} map
 * @param {{helix_id, strand_id, domain_index}} nuc
 * @returns {number} 0..1
 */
export function clusterAlphaForNuc(map, nuc) {
  if (!map?.size || !nuc) return 1
  if (nuc.domain_index != null) {
    const d = map.get(`d:${nuc.strand_id}:${nuc.domain_index}`)
    if (d !== undefined) return d
  }
  return map.get(`h:${nuc.helix_id}`) ?? 1
}

/**
 * Cheap change detector for the cluster DISPLAY fields only.
 *
 * `cluster_transforms` gets a fresh array identity on every gizmo-drag patch (~60/s),
 * and repainting means an O(nucleotides) recolour sweep. Comparing identities would
 * therefore recolour the scene every frame of a drag; this signature is stable across
 * a pose-only change and moves only when colour/opacity/membership does.
 *
 * @param {object} design
 * @returns {string}
 */
export function clusterDisplaySignature(design) {
  return (design?.cluster_transforms ?? [])
    .map(c => `${c.id}:${c.color ?? ''}:${c.opacity ?? 1}`)
    .join('|')
}

/**
 * Shallow design copy with ONE cluster's display fields overridden — the zero-latency
 * live preview while the user drags the opacity slider, before any PATCH round-trips.
 * Never mutates the input; untouched clusters stay identity-equal.
 *
 * `color: ''` clears back to the auto palette, the same sentinel the PATCH body uses.
 *
 * @param {object} design
 * @param {string} clusterId
 * @param {{color?: string|null, opacity?: number}} patch
 */
export function withClusterDisplay(design, clusterId, patch) {
  if (!design?.cluster_transforms) return design
  return {
    ...design,
    cluster_transforms: design.cluster_transforms.map(c => {
      if (c.id !== clusterId) return c
      const next = { ...c }
      if (patch?.color !== undefined) next.color = patch.color === '' ? null : patch.color
      if (patch?.opacity !== undefined) next.opacity = patch.opacity
      return next
    }),
  }
}
