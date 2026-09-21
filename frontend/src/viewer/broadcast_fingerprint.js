/** Observe display revisions/settings without hashing vertex buffers or encoding textures. */
export function broadcastFingerprint({ scene, view, pane }) {
  const rows = [view, pane], materials = new Set()
  function visit(o) {
    if (!o.visible || o.isTransformControlsRoot) return
    rows.push([o.uuid, o.layers?.mask, o.position?.toArray(), o.quaternion?.toArray(), o.scale?.toArray(),
      o.matrixAutoUpdate === false ? o.matrix?.toArray() : null, o.renderOrder, o.count,
      o.instanceMatrix?.version, o.instanceColor?.version, o.geometry?.uuid,
      o.geometry && Object.entries(o.geometry.attributes).map(([k, a]) => [k, a.version ?? a.data?.version]),
      o.geometry?.index?.version, o.geometry?.drawRange, o.color?.getHex(), o.intensity])
    for (const m of Array.isArray(o.material) ? o.material : o.material ? [o.material] : []) {
      rows.push(m.uuid)
      if (materials.has(m)) continue
      materials.add(m)
      rows.push(Object.entries(m).flatMap(([k, v]) => {
        if (typeof v === 'number' || typeof v === 'boolean' || typeof v === 'string') return [[k, v]]
        if (v?.isColor) return [[k, v.toArray()]]
        if (v?.isTexture) return [[k, v.uuid, v.version]]
        return []
      }), m.clippingPlanes?.map(p => [...p.normal.toArray(), p.constant]))
    }
    o.children?.forEach(visit)
  }
  rows.push(scene.background?.getHex?.())
  visit(scene)
  return JSON.stringify(rows)
}

export function broadcastDocument(state) {
  const document = state.assemblyActive ? state.currentAssembly : state.currentDesign
  return document ? `${state.assemblyActive ? 'assembly' : 'part'}:${document.id}` : null
}
