const changed = (a, b) => a !== b && JSON.stringify(a) !== JSON.stringify(b)

/** Autosave returns fresh objects; only rendering inputs warrant a rebuild. */
export function nanoparticleRenderInputsChanged(next, previous) {
  const a = next.currentDesign, b = previous.currentDesign
  if (changed(a?.nanoparticles, b?.nanoparticles)) return true
  const linked = [a, b].some(d => d?.nanoparticle_conjugations?.length ||
    d?.nanoparticle_connection_versions?.length || d?.nanoparticles?.some(p => p.biotin_dna?.length))
  if (!linked) return false
  return ['nanoparticle_conjugations', 'nanoparticle_connection_versions', 'cluster_transforms']
    .some(key => changed(a?.[key], b?.[key])) || changed(next.currentGeometry, previous.currentGeometry)
}
