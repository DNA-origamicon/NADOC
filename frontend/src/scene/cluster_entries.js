/**
 * Cluster → nucleotide membership. One definition of "which nucleotides belong to
 * this cluster", in two shapes: a reusable predicate (`clusterMemberFilter`) and
 * the entry-list convenience wrapper (`clusterBackboneEntries`) main.js uses.
 *
 * The predicate was a byte-identical second copy inside assembly_renderer.js
 * (`_clusterMemberFilter`) until that file's split; both now share this one, so a
 * membership fix lands once. Pure — the backbone entries are an argument.
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
    const strandMap = new Map((design?.strands ?? []).map(s => [s.id, s]))
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
