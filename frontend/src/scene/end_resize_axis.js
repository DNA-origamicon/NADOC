import * as THREE from 'three'
import { BDNA_RISE_PER_BP } from '../constants.js'

// Matches backend/core/deformation.py::_AXIS_SAMPLE_STEP. The final interval
// can be shorter; two samples are the backend's straight-axis fast path.
const SAMPLE_STEP = 7

/** Read-only preview path in displayed coordinates, anchored at the end bead. */
export function createEndResizeAxis(helix, axis, bp, beadPosition, cadnano = false) {
  const first = helix.bp_start ?? 0
  const last = first + Math.max(1, (helix.length_bp ?? 2) - 1)
  const samples = cadnano ? null : axis?.samples
  const points = samples?.length >= 2
    ? samples.map(p => new THREE.Vector3(...p))
    : [new THREE.Vector3(...(axis?.start ?? [helix.axis_start.x, helix.axis_start.y, helix.axis_start.z])),
       new THREE.Vector3(...(axis?.end ?? [helix.axis_end.x, helix.axis_end.y, helix.axis_end.z]))]
  const bps = points.length === 2 ? [first, last]
    : points.map((_, i) => i === points.length - 1 ? last : first + i * SAMPLE_STEP)
  const segment = value => {
    let i = 0
    while (i < bps.length - 2 && value >= bps[i + 1]) i++
    return i
  }
  const tangent = value => {
    if (cadnano) return new THREE.Vector3(0, 0, 1)
    const i = segment(value)
    return points[i + 1].clone().sub(points[i]).normalize()
  }
  const rawPoint = value => {
    if (cadnano) return new THREE.Vector3(0, 0, value * BDNA_RISE_PER_BP)
    if (value < first) return points[0].clone().addScaledVector(tangent(first), (value - first) * BDNA_RISE_PER_BP)
    if (value > last) return points.at(-1).clone().addScaledVector(tangent(last), (value - last) * BDNA_RISE_PER_BP)
    const i = segment(value)
    return points[i].clone().lerp(points[i + 1], (value - bps[i]) / (bps[i + 1] - bps[i]))
  }
  // Keep the preview attached to the selected backbone, including expanded and
  // flat views, instead of snapping it onto the helix's endpoint chord.
  const offset = beadPosition.clone().sub(rawPoint(bp))
  const point = value => rawPoint(value).add(offset)
  const path = (from, to) => {
    const inside = cadnano ? [] : bps.filter(v => v > Math.min(from, to) && v < Math.max(from, to))
    if (to < from) inside.reverse()
    return [from, ...inside, to].map(value => ({ bp: value, position: point(value) }))
  }
  return { point, tangent, path }
}

/** Closest point on the displayed polyline, returned in base-pair coordinates. */
export function projectRayToResizeAxis(ray, axis, from, to) {
  const vertices = axis.path(from, to)
  const onSegment = new THREE.Vector3()
  let bestDistance = Infinity, bestBp = from
  for (let i = 1; i < vertices.length; i++) {
    const a = vertices[i - 1], b = vertices[i]
    const distance = ray.distanceSqToSegment(a.position, b.position, undefined, onSegment)
    if (distance >= bestDistance) continue
    const lengthSq = a.position.distanceToSquared(b.position)
    if (lengthSq < 1e-16) continue
    const t = onSegment.clone().sub(a.position).dot(b.position.clone().sub(a.position)) / lengthSq
    bestDistance = distance
    bestBp = a.bp + (b.bp - a.bp) * t
  }
  return bestBp
}
