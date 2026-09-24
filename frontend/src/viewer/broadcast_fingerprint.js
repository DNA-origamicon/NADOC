// Upload versions are not scene revisions: render helpers can mark unchanged
// buffers dirty every frame. Cache a content signature per uploaded buffer.
const buffers = new WeakMap()
function bufferSignature(attribute) {
  if (!attribute) return null
  const buffer = attribute.isInterleavedBufferAttribute ? attribute.data : attribute
  const array = buffer.array
  if (!array) return null
  const previous = buffers.get(buffer)
  if (previous?.array === array && previous.version === buffer.version) return previous.signature
  const bytes = new Uint8Array(array.buffer, array.byteOffset, array.byteLength)
  let a = 2166136261, b = 5381
  for (let i = 0; i < bytes.length; i++) {
    a = Math.imul(a ^ bytes[i], 16777619)
    b = Math.imul(b, 33) ^ bytes[i]
  }
  const signature = [array.constructor.name, bytes.length, a >>> 0, b >>> 0]
  buffers.set(buffer, { array, version: buffer.version, signature })
  return signature
}

/** Observe visible content and settings, excluding redundant GPU upload work. */
export function broadcastFingerprint({ scene, view, pane }, { coordinates = true } = {}) {
  const rows = [view, pane], materials = new Set()
  function visit(o) {
    if (!o.visible || o.isTransformControlsRoot) return
    rows.push([o.uuid, o.layers?.mask, coordinates ? o.position?.toArray() : null, coordinates ? o.quaternion?.toArray() : null, coordinates ? o.scale?.toArray() : null,
      coordinates && o.matrixAutoUpdate === false ? o.matrix?.toArray() : null, o.renderOrder, o.count,
      coordinates ? bufferSignature(o.instanceMatrix) : o.instanceMatrix?.array.length, coordinates ? bufferSignature(o.instanceColor) : o.instanceColor?.array.length, o.geometry?.uuid,
      o.geometry && Object.entries(o.geometry.attributes).map(([k, a]) => [k, coordinates ? [a.count, a.itemSize, a.normalized, a.offset, bufferSignature(a)] : [a.count, a.itemSize, a.normalized]]),
      o.geometry?.instanceCount, bufferSignature(o.geometry?.index), o.geometry?.drawRange, o.color?.getHex(), o.intensity])
    for (const m of Array.isArray(o.material) ? o.material : o.material ? [o.material] : []) {
      rows.push(m.uuid, m.userData?.hullCutouts)
      if (materials.has(m)) continue
      materials.add(m)
      if (m.isLineMaterial) rows.push([m.linewidth, m.worldUnits, m.dashed, m.dashScale, m.dashSize, m.gapSize, m.dashOffset, m.color.toArray(), m.opacity])
      rows.push(Object.entries(m).flatMap(([k, v]) => {
        // needsUpdate bumps the GPU upload counter even when the material is unchanged.
        if (k === 'version') return []
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
