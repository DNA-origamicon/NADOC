import * as THREE from 'three'

// Geometry bounds include the visible radius/extent, not just an element's centre.
export function projectBox(box, matrix, camera, { width, height }) {
  const bounds = { x1: Infinity, y1: Infinity, x2: -Infinity, y2: -Infinity, clipped: false }
  const p = new THREE.Vector3()
  let visible = false
  for (let i = 0; i < 8; i++) {
    p.set(i & 1 ? box.max.x : box.min.x, i & 2 ? box.max.y : box.min.y,
      i & 4 ? box.max.z : box.min.z).applyMatrix4(matrix).project(camera)
    if (p.z < -1 || p.z > 1) bounds.clipped = true
    else visible = true
    const x = (p.x + 1) * width / 2, y = (1 - p.y) * height / 2
    bounds.x1 = Math.min(bounds.x1, x); bounds.x2 = Math.max(bounds.x2, x)
    bounds.y1 = Math.min(bounds.y1, y); bounds.y2 = Math.max(bounds.y2, y)
  }
  return visible ? bounds : null
}

export function instanceBounds(entry, camera, size) {
  const mesh = entry.instMesh
  if (!mesh?.geometry) return null
  if (!mesh.geometry.boundingBox) mesh.geometry.computeBoundingBox()
  const matrix = new THREE.Matrix4()
  mesh.getMatrixAt(entry.id, matrix)
  matrix.premultiply(mesh.matrixWorld)
  return projectBox(mesh.geometry.boundingBox, matrix, camera, size)
}

export function boundsInRect(bounds, rect, crossing = false) {
  if (!bounds) return false
  if (crossing) return bounds.x2 >= rect.x1 && bounds.x1 <= rect.x2 &&
    bounds.y2 >= rect.y1 && bounds.y1 <= rect.y2
  return !bounds.clipped && bounds.x1 >= rect.x1 && bounds.x2 <= rect.x2 &&
    bounds.y1 >= rect.y1 && bounds.y2 <= rect.y2
}

// A logical element may span many beads/atoms. Window selection requires ALL
// its pieces; crossing selection requires ANY piece to intersect the rectangle.
export function createRectangleCollector(rect, crossing) {
  const hits = new Set(), excluded = new Set()
  return {
    add(key, bounds) {
      if (boundsInRect(bounds, rect, crossing)) hits.add(key)
      else excluded.add(key)
    },
    has: key => hits.has(key) && (crossing || !excluded.has(key)),
    keys: () => [...hits].filter(key => crossing || !excluded.has(key)),
  }
}

export function segmentInRect(a, b, rect) {
  let lo = 0, hi = 1
  for (const [start, delta, min, max] of [
    [a.x1, b.x1 - a.x1, rect.x1, rect.x2],
    [a.y1, b.y1 - a.y1, rect.y1, rect.y2],
  ]) {
    if (delta === 0) { if (start < min || start > max) return false; continue }
    const t1 = (min - start) / delta, t2 = (max - start) / delta
    lo = Math.max(lo, Math.min(t1, t2)); hi = Math.min(hi, Math.max(t1, t2))
    if (lo > hi) return false
  }
  return true
}
