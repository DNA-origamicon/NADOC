import * as THREE from 'three'
import { honeycombCellWorldPos, squareCellWorldPos } from '../scene/slice_plane/lattice_math.js'
import { HONEYCOMB_COL_PITCH, HONEYCOMB_ROW_PITCH, SQUARE_HELIX_SPACING } from '../constants.js'

const vector = p => Array.isArray(p) ? new THREE.Vector3(...p) : new THREE.Vector3(p.x, p.y, p.z)
const cell = (type, row, col) => (type === 'SQUARE' ? squareCellWorldPos : honeycombCellWorldPos)(row, col, 'XY', 0)
export const latticeAligned = (frame, direction) => !!frame && direction.every(Number.isFinite)
  && new THREE.Vector3(...direction).lengthSq() > 1e-16
  && Math.abs(frame.normal.dot(new THREE.Vector3(...direction).normalize())) > 1 - 1e-6

/** Resolve a rigid lattice from actual helix axes, with its cell origin preserved.
 * Inconsistent/mixed/deformed frames intentionally do not offer lattice snapping. */
export function clusterLattice(state, target) {
  const design = state.currentDesign
  const helices = design.helices?.filter(h => target.cluster.helix_ids.includes(h.id)) ?? []
  if (!helices.length || !['SQUARE', 'HONEYCOMB'].includes(design.lattice_type)
      || helices.some(h => !h.grid_pos || h.lattice_frame_id !== helices[0].lattice_frame_id)) return null
  const h = helices[0]
  const declared = design.lattice_frames?.find(f => f.id === h.lattice_frame_id)
  const restNormal = vector(h.axis_end).sub(vector(h.axis_start)).normalize()
  const plane = declared?.plane ?? (Math.abs(restNormal.z) > .999999 ? 'XY' : Math.abs(restNormal.y) > .999999 ? 'XZ' : Math.abs(restNormal.x) > .999999 ? 'YZ' : null)
  if (!plane) return null
  let u = new THREE.Vector3(...(plane === 'YZ' ? [0, 1, 0] : [1, 0, 0]))
  let v = new THREE.Vector3(...(plane === 'XY' ? [0, 1, 0] : [0, 0, 1]))
  // Existing geometry applies child rigid transforms before root transforms.
  const transforms = [...(design.cluster_transforms ?? [])].sort((a, b) => Number(!a.parent_cluster_id) - Number(!b.parent_cluster_id))
  for (const transform of transforms) {
    if (!transform.helix_ids?.includes(h.id)) continue
    if (transform.domain_ids?.length && (transform.rotation?.some((x, i) => Math.abs(x - (i === 3 ? 1 : 0)) > 1e-8) || transform.translation?.some(x => Math.abs(x) > 1e-8))) return null
    const q = new THREE.Quaternion(...(transform.rotation ?? [0, 0, 0, 1])).normalize()
    u.applyQuaternion(q); v.applyQuaternion(q)
  }
  const normal = u.clone().cross(v).normalize()
  const axes = helices.map(helix => state.currentHelixAxes?.[helix.id])
  if (axes.some(axis => !axis?.start || !axis?.end)) return null
  const base = vector(axes[0].start).sub(vector(target.center))
  const local = cell(design.lattice_type, ...h.grid_pos)
  const origin = base.clone().addScaledVector(u, -local.x).addScaledVector(v, -local.y)
  for (let i = 0; i < helices.length; i++) {
    const axis = axes[i], start = vector(axis.start), axisDirection = vector(axis.end).sub(start)
    if (!latticeAligned({ normal }, axisDirection.toArray())) return null
    // Curved axes cannot define a single rigid snap lattice.
    if (axis.samples?.some(sample => vector(sample).sub(start).cross(normal).length() > .01)) return null
    const expected = cell(design.lattice_type, ...helices[i].grid_pos)
    const relative = start.sub(vector(target.center)).sub(origin)
    if (Math.abs(relative.dot(u) - expected.x) > .02 || Math.abs(relative.dot(v) - expected.y) > .02) return null
  }
  return { u, v, normal, origin, type: design.lattice_type }
}

export function latticeCoordinates(frame, point) {
  const delta = vector(point).sub(frame.origin)
  const x = delta.dot(frame.u), y = delta.dot(frame.v)
  const col = Math.round(x / (frame.type === 'SQUARE' ? SQUARE_HELIX_SPACING : HONEYCOMB_COL_PITCH))
  const row = Math.round(y / (frame.type === 'SQUARE' ? SQUARE_HELIX_SPACING : HONEYCOMB_ROW_PITCH))
  return { row, col }
}
export function latticePoint(frame, row, col, depthPoint) {
  const p = cell(frame.type, row, col)
  const depth = vector(depthPoint).sub(frame.origin).dot(frame.normal)
  return frame.origin.clone().addScaledVector(frame.u, p.x).addScaledVector(frame.v, p.y).addScaledVector(frame.normal, depth)
}
export function snapToLattice(frame, point) {
  const { row, col } = latticeCoordinates(frame, point)
  const input = vector(point)
  let nearest, distance = Infinity
  // Honeycomb staggering makes independent row/column rounding insufficient.
  for (let r = row - 2; r <= row + 2; r++) for (let c = col - 2; c <= col + 2; c++) {
    const p = latticePoint(frame, r, c, point), d = p.distanceToSquared(input)
    if (d < distance) { nearest = p; distance = d }
  }
  return nearest.toArray()
}
export function patternAngles(count, degrees) {
  if (!Number.isInteger(count) || count < 1 || count > 128 || !Number.isFinite(degrees) || degrees <= 0 || degrees > 360) return null
  const divisor = degrees === 360 ? count : Math.max(1, count - 1)
  return Array.from({ length: count }, (_, i) => i * degrees * Math.PI / 180 / divisor)
}
