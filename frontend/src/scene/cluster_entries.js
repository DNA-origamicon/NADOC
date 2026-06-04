/**
 * Cluster → backbone-entry selection extracted from main.js (parameterized: the
 * backbone entries are an argument, so this is pure). Mirrors the active-cluster
 * glow so picking matches the highlighted body. Unit-tested in cluster_entries.test.js.
 */

/**
 * Backbone entries belonging to a cluster. A plain cluster = all entries on its
 * helix_ids. A MIXED cluster (has domain_ids) = the bridge-domain entries plus
 * entries on helices it owns exclusively (helix_ids not used by a bridge domain).
 * @param {object} cluster  { helix_ids:[], domain_ids?:[{strand_id, domain_index}] }
 * @param {object} design   { strands:[{id, domains}] }
 * @param {Array}  backboneEntries  [{ nuc:{helix_id, strand_id, domain_index} }]
 */
export function clusterBackboneEntries(cluster, design, backboneEntries) {
  if (!cluster?.helix_ids?.length || !backboneEntries?.length) return []

  if (cluster.domain_ids?.length) {
    const domainKeySet = new Set(cluster.domain_ids.map(d => `${d.strand_id}:${d.domain_index}`))
    const strandMap = new Map((design?.strands ?? []).map(s => [s.id, s]))
    const bridgeHelixIds = new Set()
    for (const dr of cluster.domain_ids) {
      const dom = strandMap.get(dr.strand_id)?.domains?.[dr.domain_index]
      if (dom) bridgeHelixIds.add(dom.helix_id)
    }
    const exclusiveHelixSet = new Set(cluster.helix_ids.filter(hid => !bridgeHelixIds.has(hid)))
    return backboneEntries.filter(entry =>
      domainKeySet.has(`${entry.nuc.strand_id}:${entry.nuc.domain_index}`) ||
      exclusiveHelixSet.has(entry.nuc.helix_id))
  }

  const helixSet = new Set(cluster.helix_ids)
  return backboneEntries.filter(entry => helixSet.has(entry.nuc.helix_id))
}
