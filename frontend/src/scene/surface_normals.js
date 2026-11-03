import { BufferAttribute } from 'three'

/** Indexed Float32 surface fast path; same arithmetic/order as Three's normals. */
export function computeSurfaceNormals(geometry) {
  const position = geometry.getAttribute('position'), index = geometry.index
  let normal = geometry.getAttribute('normal')
  if (!position || position.isInterleavedBufferAttribute || position.normalized
      || position.itemSize !== 3 || !(position.array instanceof Float32Array)
      || !index || index.isInterleavedBufferAttribute || index.normalized || index.itemSize !== 1
      || !(index.array instanceof Uint32Array || index.array instanceof Uint16Array)
      || (normal && (normal.isInterleavedBufferAttribute || normal.normalized
        || normal.itemSize !== 3 || normal.count !== position.count || !(normal.array instanceof Float32Array)))) {
    geometry.computeVertexNormals()
    return
  }
  if (!normal) {
    normal = new BufferAttribute(new Float32Array(position.count * 3), 3)
    geometry.setAttribute('normal', normal)
  } else normal.array.fill(0)
  const p = position.array, n = normal.array, faces = index.array
  for (let i = 0; i < faces.length; i += 3) {
    const a = faces[i] * 3, b = faces[i + 1] * 3, c = faces[i + 2] * 3
    const cx = p[c] - p[b], cy = p[c + 1] - p[b + 1], cz = p[c + 2] - p[b + 2]
    const ax = p[a] - p[b], ay = p[a + 1] - p[b + 1], az = p[a + 2] - p[b + 2]
    const x = cy * az - cz * ay, y = cz * ax - cx * az, z = cx * ay - cy * ax
    // Read all three old values before writing, as Three does for repeated indices.
    const nax = n[a] + x, nay = n[a + 1] + y, naz = n[a + 2] + z
    const nbx = n[b] + x, nby = n[b + 1] + y, nbz = n[b + 2] + z
    const ncx = n[c] + x, ncy = n[c + 1] + y, ncz = n[c + 2] + z
    n[a] = nax; n[a + 1] = nay; n[a + 2] = naz
    n[b] = nbx; n[b + 1] = nby; n[b + 2] = nbz
    n[c] = ncx; n[c + 1] = ncy; n[c + 2] = ncz
  }
  for (let i = 0; i < n.length; i += 3) {
    const x = n[i], y = n[i + 1], z = n[i + 2]
    const inverse = 1 / (Math.sqrt(x * x + y * y + z * z) || 1)
    n[i] = x * inverse; n[i + 1] = y * inverse; n[i + 2] = z * inverse
  }
  normal.needsUpdate = true
}
