/**
 * Belt-rider math extracted from main.js (parameterized: the assembly and the
 * rider's instance size are arguments, so these are pure). Uses the pure belt
 * geometry helpers. Unit-tested in belt_rider.test.js.
 */
import * as THREE from 'three'
import { beltCurvePoints, beltLoopLength, beltFrameAt } from './belt_geometry.js'

/** Resolve a rider's belt context (belt, joints, curve points, loop length), or null. */
export function beltRiderCtx(asm, riderId) {
  const rider = (asm?.belt_riders ?? []).find(r => r.id === riderId)
  if (!rider || !rider.local_transform) return null
  const belt = (asm?.belt_paths ?? []).find(b => b.id === rider.belt_path_id)
  if (!belt) return null
  const jointById = new Map((asm.joints ?? []).map(j => [j.id, j]))
  const ja = jointById.get(belt.pulley_a?.joint_id)
  const points = beltCurvePoints(belt, jointById)
  if (!ja || !points) return null
  return { asm, rider, belt, jointById, ja, points,
           L: beltLoopLength(points), planeNormal: ja.axis_direction }
}

/**
 * How many evenly-spaced copies fit around the belt loop given the seed part's
 * footprint along the belt tangent. `instanceSize` is the seed's bbox {x,y,z} (or
 * null → fall back to L/4). Returns { count, spacingNm, footprintNm } or null.
 */
export function beltRiderFill(ctx, instanceSize) {
  if (!ctx) return null
  const frame = beltFrameAt(ctx.points, ctx.rider.arc_param ?? 0, ctx.planeNormal)
  const tan = new THREE.Vector3().setFromMatrixColumn(frame, 0).normalize()
  let footprint = instanceSize
    ? Math.abs(instanceSize.x * tan.x) + Math.abs(instanceSize.y * tan.y) + Math.abs(instanceSize.z * tan.z)
    : 0
  if (!(footprint > 1e-3)) footprint = ctx.L / 4   // fallback when no bbox
  const count = Math.max(2, Math.round(ctx.L / footprint))
  return { count, spacingNm: ctx.L / count, footprintNm: footprint }
}
