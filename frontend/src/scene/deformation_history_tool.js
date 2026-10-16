import { validateFrozenDeformationRange } from '../features/part_dna_comparison_model.js'
import { shape, list, text } from '../features/part_comparison_validation.js'

/** Fixed private control inputs and delegates; no store or network dependencies. */
export function createDeformationHistoryTool(operation, adapter) {
  if (!operation || !['bend', 'twist'].includes(operation.type)
      || !adapter?.design || !adapter.helixAxes
      || ['onPreview', 'onConfirm', 'onCancel'].some(key => typeof adapter[key] !== 'function')
      || (adapter.displayLayer != null && (!Number.isInteger(adapter.displayLayer) || adapter.displayLayer < 0 || adapter.displayLayer > 31))) {
    throw new Error('A prepared deformation control source and delegates are required')
  }
  return Object.freeze({ ...adapter, operation,
    patch(planes, clusterIds, params) {
      const a = planes.a?.bp, b = planes.b?.bp
      if (!Number.isSafeInteger(a) || !Number.isSafeInteger(b)) throw new Error('Both deformation planes are required')
      return { ...(adapter.mode === 'create' ? {} : { type: operation.type }), plane_a_bp: Math.min(a, b), plane_b_bp: Math.max(a, b),
        cluster_ids: [...clusterIds], ...(params === undefined ? {} : { params }) }
    },
  })
}

/** Creation owns selection and operation identity, but has no invented planes/params. */
export function createDeformationCreationTool(creation, adapter) {
  shape(creation, ['id', 'type', 'targets', 'cluster_ids']); text(creation.id)
  if (!(creation.targets === null || (Array.isArray(creation.targets) && creation.targets.length > 0))
      || !Array.isArray(creation.cluster_ids)) throw new Error('Explicit creation scope is required')
  deformationHistoryScope(creation, adapter.design, adapter.selectedScope)
  return createDeformationHistoryTool(creation, { ...adapter, mode: 'create' })
}

export function setDeformationGuideLayer(root, layer = 0) {
  root?.traverse(object => object.layers.set(layer))
}

/** These guides allocate their own geometry, materials and canvas textures. */
export function disposeDeformationGuide(root) {
  if (!root) return
  const owned = new Set()
  root.traverse(object => {
    // Three.Sprite uses a shared static quad, while its material/map are ours.
    if (object.geometry && !object.isSprite) owned.add(object.geometry)
    for (const material of Array.isArray(object.material) ? object.material : [object.material]) {
      if (material) { owned.add(material); if (material.map) owned.add(material.map) }
    }
  })
  root.removeFromParent()
  for (const resource of owned) resource.dispose()
}


/** Validate server-selected guide inputs against the fixed private prefix. */
export function deformationHistoryScope(operation, design, scope) {
  shape(scope, ['id', 'affected_helix_ids', 'target_ranges'])
  if (scope.id !== operation.id) throw new Error('Selected deformation scope changed identity')
  const helices = new Set(design.helices.map(helix => helix.id)), affected = new Set()
  list(scope.affected_helix_ids, 512)
  for (const id of scope.affected_helix_ids) {
    text(id)
    if (!helices.has(id) || affected.has(id)) throw new Error('Selected deformation scope has an unresolved helix')
    affected.add(id)
  }
  let ranges = null
  if (scope.target_ranges !== null) {
    list(scope.target_ranges, 512 - affected.size)
    ranges = scope.target_ranges.map(range => {
      validateFrozenDeformationRange(range, helices)
      return { helixId: range.helix_id, lo: range.start_bp, hi: range.end_bp }
    })
  }
  // A legacy unscoped window may currently cross no helices. Keep its prefix
  // guides usable so the user can move the planes back onto the structure.
  return { affected: ranges === null && affected.size === 0 ? null : affected, ranges }
}
