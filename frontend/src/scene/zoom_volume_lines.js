import * as THREE from 'three'

const cross = (a, b, c) => (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x)

function convexHull(points) {
  const sorted = [...points].sort((a, b) => a.x - b.x || a.y - b.y)
    .filter((p, i, all) => !i || p.x !== all[i - 1].x || p.y !== all[i - 1].y)
  if (sorted.length < 3) return sorted
  const half = input => {
    const out = []
    for (const p of input) {
      while (out.length > 1 && cross(out.at(-2), out.at(-1), p) <= 0) out.pop()
      out.push(p)
    }
    return out.slice(0, -1)
  }
  return [...half(sorted), ...half([...sorted].reverse())]
}

/** Common outer tangents connect actual box silhouette vertices to actual inset
 * corners. Screen-aligned min/max combinations are not points on a rotated box. */
export function zoomVolumeConnectors(bounds, camera, viewport, inset) {
  if (bounds.isEmpty() || viewport.width <= 0 || viewport.height <= 0) return []
  // Frame callbacks run before the main renderer updates camera matrices.
  camera.updateWorldMatrix(true, false)
  const projected = []
  for (const x of [bounds.min.x, bounds.max.x]) for (const y of [bounds.min.y, bounds.max.y]) for (const z of [bounds.min.z, bounds.max.z]) {
    const p = new THREE.Vector3(x, y, z).project(camera)
    if (![p.x, p.y, p.z].every(Number.isFinite) || p.z < -1 || p.z > 1) return []
    projected.push(p)
  }
  if (['x', 'y'].some(axis => projected.every(p => p[axis] < -1) || projected.every(p => p[axis] > 1))) return []
  const points = projected.map(p => ({ x: viewport.left + (p.x + 1) * viewport.width / 2,
    y: viewport.top + (1 - p.y) * viewport.height / 2, volume: true }))
  for (const x of [inset.left, inset.right]) for (const y of [inset.top, inset.bottom]) points.push({ x, y, volume: false })
  const hull = convexHull(points), connectors = []
  for (let i = 0; i < hull.length; i++) {
    const a = hull[i], b = hull[(i + 1) % hull.length]
    if (a.volume === b.volume) continue
    const from = a.volume ? a : b, to = a.volume ? b : a
    connectors.push({ x1: from.x, y1: from.y, x2: to.x, y2: to.y })
  }
  // A contained or substantially overlapping inset has no unambiguous pair of tangents.
  return connectors.length === 2 ? connectors : []
}
