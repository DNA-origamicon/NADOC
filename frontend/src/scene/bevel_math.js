import * as THREE from 'three'
const vector = a => new THREE.Vector3(...a)

export function bevelPlane(paths, values) {
  const rows = paths.map(p => ({ p, i: p.bps.indexOf(values.positionBp) })).filter(r => r.i >= 0)
  if (!rows.length) throw new Error('Plane position must cross occupied bundle material.')
  const center = new THREE.Vector3()
  for (const { p, i } of rows) center.add(vector(p.points[i]))
  center.divideScalar(rows.length)
  const { p, i } = rows[0], tangent = vector(p.tangents[i]), right = vector(p.rights[i])
  const up = new THREE.Vector3().crossVectors(tangent, right)
  const angle = THREE.MathUtils.degToRad(values.angleDeg), direction = THREE.MathUtils.degToRad(values.directionDeg)
  const normal = tangent.clone().multiplyScalar(Math.cos(angle))
    .addScaledVector(right, Math.sin(angle) * Math.cos(direction))
    .addScaledVector(up, Math.sin(angle) * Math.sin(direction))
  return { center, normal, tangent, right, up }
}

export function bevelMask(paths, values, frame = bevelPlane(paths, values), allowEmpty = false) {
  const kept = new Map(), sign = values.trimEnd === 'end' ? 1 : -1
  let count = 0, total = 0
  for (const path of paths) {
    const sites = new Set()
    path.points.forEach((point, i) => {
      total++
      if (sign * vector(point).sub(frame.center).dot(frame.normal) <= 1e-9) { sites.add(path.bps[i]); count++ }
    })
    kept.set(path.helix_id, sites)
  }
  const hasCut = count > 0 && count < total
  if (!hasCut && !allowEmpty) throw new Error('Bevel needs material on both sides of the cutting plane.')
  const keep = nuc => !kept.has(nuc.helix_id) || kept.get(nuc.helix_id).has(nuc.bp_index)
  keep.hasCut = hasCut
  return keep
}

/** Bend's face-drag convention: camera billboard, closest sampled helix axis. */
export function nearestBevelBp(paths, point) {
  let bp = null, distance = Infinity
  for (const path of paths) for (let i = 1; i < path.points.length; i++) {
    const a = vector(path.points[i - 1]), delta = vector(path.points[i]).sub(a)
    const t = Math.max(0, Math.min(1, point.clone().sub(a).dot(delta) / (delta.lengthSq() || 1)))
    const d = point.distanceToSquared(a.addScaledVector(delta, t))
    if (d < distance) { distance = d; bp = Math.round(path.bps[i - 1] + t * (path.bps[i] - path.bps[i - 1])) }
  }
  return bp
}

export function bevelAngles(normal, frame) {
  let n = normal.clone().normalize()
  if (n.dot(frame.tangent) < 0) n.negate()
  return { angleDeg: Math.min(89.9, THREE.MathUtils.radToDeg(Math.acos(THREE.MathUtils.clamp(n.dot(frame.tangent), -1, 1)))),
    directionDeg: (THREE.MathUtils.radToDeg(Math.atan2(n.dot(frame.up), n.dot(frame.right))) + 360) % 360 }
}
