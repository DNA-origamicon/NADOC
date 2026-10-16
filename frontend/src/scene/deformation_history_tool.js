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
      return { type: operation.type, plane_a_bp: Math.min(a, b), plane_b_bp: Math.max(a, b),
        cluster_ids: [...clusterIds], ...(params === undefined ? {} : { params }) }
    },
  })
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
