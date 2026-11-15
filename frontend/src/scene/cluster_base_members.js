import { baseKey } from './base_ref.js'

export const clusterBaseKey = ref => baseKey(ref, ref?.copy_k ?? 0)
export function clusterBaseKeys(cluster) {
  return new Set((cluster?.base_ids ?? []).map(clusterBaseKey))
}
/** Exact base membership takes precedence over the supporting helix list. */
export function clusterBaseFilter(cluster) {
  if (!cluster?.base_ids?.length) return null
  const keys = clusterBaseKeys(cluster)
  return nuc => keys.has(clusterBaseKey(nuc))
}

export function claimedBaseKeys(design, cluster) {
  let exact = (design?.cluster_transforms ?? []).filter(c => c.base_ids?.length)
  if (cluster.base_ids?.length) exact = exact.slice(exact.findIndex(c => c.id === cluster.id) + 1)
  return new Set(exact.filter(c => c.id !== cluster.id).flatMap(c => c.base_ids.map(clusterBaseKey)))
}
