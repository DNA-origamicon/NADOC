const detail = { full: 0, beads: 1, cylinders: 2, 'hull-prism': 2 }

export const fullOnlyAssemblyMeshes = new Set([
  'baseSlabs', 'slabBackboneConnectors', 'xoverExtraSlabs', 'xoverExtraSlabConnectors',
])

export function canPrepareFullAssemblySource(design, instances) {
  if (design.protein_attachments?.length) return false
  if (design.helices?.some(helix => helix.id?.startsWith('__lnk__'))) return false
  if (design.strands?.some(strand => ['linker', 'oh_binder'].includes(strand.strand_type)
    || strand.domains?.some(domain => domain.binds_overhang_id != null))) return false
  return instances.every(instance => detail[instance.representation ?? 'full'] != null)
}

export function assemblyMemberSignature(instances) {
  return JSON.stringify(instances.map(instance => [instance.id, instance.mode]).sort())
}

/** Retain the highest prepared CG detail. Auxiliary representations keep their
 * rebuild path until they have equally complete reusable resources. */
export function canReuseAssemblyRepresentation(source, instances) {
  if (!source?.cgRepresentationReusable || source.isAtomistic || source.isSurface) return false
  if (source.memberSignature !== assemblyMemberSignature(instances)) return false
  const built = detail[source.rep]
  return built != null && instances.every(instance => {
    const wanted = detail[instance.representation ?? 'full']
    return wanted != null && built <= wanted
  })
}

export function applyAssemblyRepresentation(source, instances) {
  const buildCap = source.rep === 'cylinders' ? 1 : 0
  source.representationById = new Map()
  source.hasFullRepresentation = instances.some(instance => (instance.representation ?? 'full') === 'full')
  for (const instance of instances) {
    const rep = instance.representation ?? 'full'
    source.representationById.set(instance.id, rep)
    const row = source.instanceIndex.get(instance.id)
    if (row == null) continue
    let cap = rep === 'full' || rep === 'beads' ? 0 : rep === 'cylinders' ? 1 : 3
    if (cap === 3 && !source.hullLod) cap = 1
    source.instanceLodCap[row] = Math.max(buildCap, cap)
    // G is the Full-only primitive mask. R retains combined instance/group
    // visibility; both channels follow the same LOD row permutation.
    source.visData[row * 16 + 1] = rep === 'full' ? 1 : 0
    source.dirtyVisRows.add(row)
  }
}
