// Group / instance gizmo helpers extracted from main.js's assembly transform
// region (the "Rigid-body group gizmo attachment" + "PartGroup gizmo" banners).
//
// This module is being grown incrementally (see main_js_carveup.md Tier 3). The
// first piece lifted is the PURE commit-value math for a finished revolute-joint
// gizmo drag — the part that decides what `current_value` (and which endpoint
// side) to POST when the user lets go of a rotation gizmo. The stateful attach /
// live-drag wiring stays in main.js for now.

import { clampJointValue } from './gear_math.js'

/**
 * Compute the committed { current_value, endpoint_side } for a finished revolute
 * gizmo drag, or null if the gizmo wasn't rotating a revolute joint (or the
 * accumulated angle doesn't belong to this joint).
 *
 * Pure: callers pass the live unwrapped-angle accumulator + the seed joint
 * snapshot; this returns the value without reading the store or mutating the
 * accumulator (the caller clears it when a non-null result is returned).
 *
 * `endpoint_side` tells the backend WHICH body actually moves ('a' = parent,
 * 'b' = child) so a joint authored "backward" (moving body = parent, fixed axle
 * = child) rotates the right part instead of the fixed axle.
 *
 * @param {Object}      args
 * @param {Object|null} args.constraint  motion-constraint descriptor (has `dof`, `jointId`)
 * @param {Object|null} args.gizmoAngle  the live accumulator: { jointId, accum, sideSign }
 * @param {Object|null} args.seedJoint   the joint snapshot (has `current_value`, bounds)
 * @returns {{ current_value: number, endpoint_side: 'a'|'b' } | null}
 */
export function revoluteCommitValue({ constraint, gizmoAngle, seedJoint }) {
  if (constraint?.dof !== 'revolute') return null
  if (!gizmoAngle || gizmoAngle.jointId !== constraint.jointId) return null
  const sideSign = gizmoAngle.sideSign
  const v = (seedJoint?.current_value ?? 0) + gizmoAngle.accum * sideSign
  return { current_value: clampJointValue(seedJoint, v), endpoint_side: sideSign < 0 ? 'a' : 'b' }
}
