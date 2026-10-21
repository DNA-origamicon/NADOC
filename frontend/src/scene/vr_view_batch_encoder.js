import * as THREE from 'three'

// Cache only local mesh records. Instance poses/colors/visibility are always read
// anew. Attribute identity and upload versions follow Three's mutation contract.
export function createVRBatchEncoder() {
  const cache = new WeakMap()
  const pos = new THREE.Vector3(), normal = new THREE.Vector3(), color = new THREE.Color()
  const matrix = new THREE.Matrix4(), instance = new THREE.Matrix4(), radius = new THREE.Vector3()
  function vertices(geometry, material, group, uv, slot = 0) {
    const p = geometry.attributes.position, n = geometry.attributes.normal
    const c = geometry.attributes.color, a = geometry.attributes.uv, index = geometry.index
    const start = Math.max(group.start, geometry.drawRange.start)
    const end = Math.min(group.start + group.count, index?.count ?? p.count, geometry.drawRange.start + geometry.drawRange.count)
    const key = [material, start, end, material.color?.r ?? 1, material.color?.g ?? 1,
      material.color?.b ?? 1, material.opacity, material.vertexColors, ...(uv ?? [])]
    for (const attr of [p, n, c, a, index]) key.push(attr, attr?.version, attr?.data, attr?.data?.version)
    let slots = cache.get(geometry)
    if (!slots) { slots = new Map(); cache.set(geometry, slots) }
    const previous = slots.get(slot)
    if (previous && key.length === previous.key.length && key.every((v, i) => v === previous.key[i])) return previous.records
    const records = new Float32Array(Math.max(0, Math.ceil((end - start - 2) / 3)) * 36)
    let offset = 0
    for (let k = start; k + 2 < end; k += 3) for (let j = k; j < k + 3; j++) {
      const i = index ? index.getX(j) : j
      pos.fromBufferAttribute(p, i)
      color.copy(material.color ?? new THREE.Color(1, 1, 1))
      if (material.vertexColors && c) color.multiply(new THREE.Color(c.getX(i), c.getY(i), c.getZ(i)))
      records[offset++] = pos.x; records[offset++] = pos.y; records[offset++] = pos.z
      records[offset++] = color.r; records[offset++] = color.g; records[offset++] = color.b
      records[offset++] = material.opacity
      records[offset++] = uv && a ? uv[0] + a.getX(i) * (uv[2] - uv[0]) : -1
      records[offset++] = uv && a ? uv[1] + (1 - a.getY(i)) * (uv[3] - uv[1]) : -1
      if (n) normal.fromBufferAttribute(n, i); else normal.set(0, 0, 0)
      records[offset++] = normal.x; records[offset++] = normal.y; records[offset++] = normal.z
    }
    // A changing group layout cannot accumulate unbounded historical templates.
    if (slots.size >= 64 && !slots.has(slot)) slots.clear()
    slots.set(slot, { key, records })
    return records
  }
  function instances(mesh, spec) {
    const records = new Float32Array(mesh.count * 20)
    let offset = 0
    for (let i = 0; i < mesh.count; i++) {
      const alpha = mesh.geometry.attributes.instanceAlpha?.getX(i) ?? 1
      if (alpha <= 0) continue
      mesh.getMatrixAt(i, instance); matrix.copy(mesh.matrixWorld).multiply(instance)
      if (!matrix.elements.every(Number.isFinite) || Math.abs(matrix.determinant()) < 1e-14) continue
      if (spec) matrix.scale(radius.setScalar(spec.radius))
      color.setRGB(1, 1, 1); if (mesh.instanceColor) mesh.getColorAt(i, color)
      records.set(matrix.elements, offset); offset += 16
      records[offset++] = color.r; records[offset++] = color.g; records[offset++] = color.b; records[offset++] = alpha
    }
    return records.subarray(0, offset)
  }
  return { vertices, instances }
}
