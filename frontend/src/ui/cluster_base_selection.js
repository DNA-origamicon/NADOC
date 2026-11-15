import { parseBaseKey } from '../scene/base_ref.js'
import { clusterBaseKey } from '../scene/cluster_base_members.js'

/** Resolve the actual selected nucleotides; never expand a strand to whole helices. */
export function clusterSelectionInput(refs, design, geometry) {
  const strandIds = new Set(refs.filter(r => r.kind === 'strand').map(r => r.id))
  const domains = new Set(refs.filter(r => r.kind === 'domain').map(r => `${r.strandId}:${r.domainIndex}`))
  const keys = new Set(refs.filter(r => r.kind === 'base').map(r => r.key))
  const helices = new Set((design?.helices ?? []).map(h => h.id))
  const bases = new Map()
  for (const n of geometry ?? []) {
    const key = clusterBaseKey(n)
    if (!keys.has(key) && !strandIds.has(n.strand_id) && !domains.has(`${n.strand_id}:${n.domain_index}`)) continue
    if (!helices.has(n.helix_id)) throw new Error('Cluster selection must contain lattice bases. Select extension or crossover inserts with their owning structure.')
    bases.set(key, { helix_id: n.helix_id, bp_index: n.bp_index, direction: n.direction, copy_k: n.copy_k ?? 0 })
  }
  for (const key of keys) {
    if (!parseBaseKey(key) || !bases.has(key)) throw new Error('A selected base is unavailable. Refresh the selection.')
  }
  if (!bases.size) throw new Error('Select strand, domain, or individual bases before creating a cluster.')
  return { helix_ids: [...new Set([...bases.values()].map(n => n.helix_id))], base_ids: [...bases.values()] }
}

export async function assignClusterSelection({ store, api, refs, clusterId = null }) {
  const state = store.getState()
  if (state.assemblyActive) throw new Error('Open the part to edit its base clusters.')
  const design = state.currentDesign
  const input = clusterSelectionInput(refs, design, state.currentGeometry)
  let result
  if (clusterId) {
    const { clusterMemberFilter } = await import('../scene/cluster_entries.js')
    const existing = design.cluster_transforms.find(c => c.id === clusterId)
    if (!existing) throw new Error('The target cluster no longer exists.')
    const contains = clusterMemberFilter(existing, design)
    const selected = new Map(input.base_ids.map(n => [clusterBaseKey(n), n]))
    for (const n of state.currentGeometry ?? []) {
      if (contains?.(n)) selected.set(clusterBaseKey(n), {
        helix_id: n.helix_id, bp_index: n.bp_index, direction: n.direction, copy_k: n.copy_k ?? 0,
      })
    }
    const base_ids = [...selected.values()]
    result = await api.patchCluster(clusterId, { domain_ids: [], base_ids,
      helix_ids: [...new Set(base_ids.map(n => n.helix_id))] })
  } else {
    result = await api.createCluster({ name: `Cluster ${(design.cluster_transforms?.length ?? 0) + 1}`, ...input })
  }
  if (!result) throw new Error(store.getState().lastError?.message ?? 'The operation was refused.')
  return result
}
