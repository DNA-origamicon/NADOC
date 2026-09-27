/** Stable assembly annotation identities and supported selection targets. */
export function normalizeAssemblyAnnotationRef(ref) {
  if (!ref || typeof ref.instanceId !== 'string' || !ref.instanceId) return null
  if (ref.kind === 'assembly-part') return { kind: ref.kind, instanceId: ref.instanceId }
  if (ref.kind === 'assembly-overhang' && typeof ref.overhangId === 'string' && ref.overhangId)
    return { kind: ref.kind, instanceId: ref.instanceId, overhangId: ref.overhangId }
  return null
}

export function assemblyAnnotationSelection(state) {
  const ids = new Set((state.currentAssembly?.instances ?? []).map(i => i.id))
  const overhangs = (state.assemblyOverhangSelection ?? []).filter(r => ids.has(r.instanceId))
  if (overhangs.length) return overhangs.map(r => ({ kind: 'assembly-overhang', instanceId: r.instanceId, overhangId: r.overhangId }))
  const multi = (state.multiSelectedInstanceIds ?? []).filter(id => ids.has(id))
  if (multi.length) return multi.map(instanceId => ({ kind: 'assembly-part', instanceId }))
  if (state.activeGroupId) return []
  return ids.has(state.activeInstanceId) ? [{ kind: 'assembly-part', instanceId: state.activeInstanceId }] : []
}

