// Group / instance gizmo subsystem extracted from main.js's assembly transform
// region (the "Rigid-body group gizmo attachment" + "PartGroup gizmo" banners).
//
// Owns the live revolute-drag angle accumulator + the gear/belt live-coupling
// engine + the single-instance and whole-group TransformControls attach wiring.
// Shared helpers that other subsystems also use (the pending-transform Maps, the
// transform-context builder, the Move/Rotate live-apply + commit-queue, motion
// analysis + chip) stay in main.js and are injected as deps.
//
// `revoluteCommitValue` (below) is the PURE commit-value math, kept exported so
// it can be unit-tested in isolation; `initGroupGizmo` is the stateful factory.

import * as THREE from 'three'
import {
  clampJointValue, rotationDeltaMatrix,
  signedAngleFromWorldDelta, movingSideSignForRevolute, gearEndpointSide,
} from './gear_math.js'
import { computeRevoluteTransform } from './assembly_revolute_math.js'
import { beltCouplingRelations, applyBeltRiders } from './belt_geometry.js'
import { summarizeConstraint } from './assembly_diff.js'
import { getRigidBodyGroup } from './assembly_constraint_graph.js'

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

/**
 * Stateful gizmo subsystem. Returns the attach entry points + the live-coupling
 * helpers the (still-in-main) whole-group path calls until it's lifted in too.
 *
 * @param {Object} deps
 * @param {Object} deps.store
 * @param {THREE.Scene}  deps.scene
 * @param {THREE.Camera} deps.camera
 * @param {HTMLElement}  deps.canvas
 * @param {Object} deps.instanceGizmo          the TransformControls wrapper (initInstanceGizmo)
 * @param {Object} deps.assemblyRenderer
 * @param {Object} deps.assemblyJointRenderer
 * @param {Object} deps.api
 * @param {Function} deps.analyzeMotionConstraints  (target) => constraint descriptor
 * @param {Function} deps.setMotionChip             (text, severity) => void
 * @param {Function} deps.createAssemblyTransformContext  (instanceId) => ctx | null
 * @param {Function} deps.applyAssemblyPrimaryLive        (ctx, mat4) => delta (THREE.Matrix4)
 * @param {Function} deps.queueAssemblyPrimaryCommit      (ctx, mat4) => void
 * @param {Function} deps.getMrAssemblyCtx          () => the Move/Rotate fields' active ctx (or null)
 * @param {Function} deps.setMrTransformValuesFromMatrix  (mat4) => void
 */
export function initGroupGizmo({
  store, scene, camera, canvas,
  instanceGizmo, assemblyRenderer, assemblyJointRenderer, api,
  analyzeMotionConstraints, setMotionChip,
  createAssemblyTransformContext, applyAssemblyPrimaryLive, queueAssemblyPrimaryCommit,
  getMrAssemblyCtx, setMrTransformValuesFromMatrix,
}) {
  // Unwrapped angle accumulator for the current revolute gizmo drag (so the
  // committed value is continuous past ±π and the rotation commits as a joint
  // current_value rather than a transform the backend re-derives + wraps).
  let _revoluteGizmoAngle = null

  // The committed { current_value, endpoint_side } for a finished revolute gizmo
  // drag, or null if the gizmo wasn't rotating a revolute joint. Consumes +
  // clears the accumulator.
  function revoluteGizmoCommitValue(constraint) {
    const seedJoint = store.getState().currentAssembly?.joints?.find(j => j.id === constraint.jointId)
    const out = revoluteCommitValue({ constraint, gizmoAngle: _revoluteGizmoAngle, seedJoint })
    if (out != null) _revoluteGizmoAngle = null   // consume the accumulator on commit
    return out
  }

  function resetRevoluteAngle() { _revoluteGizmoAngle = null }

  function _applyGearLiveJointValue(assembly, joint, value, movingIds, endpointSide = 'b') {
    if (!assembly || !joint) return
    const seedId = endpointSide === 'a' ? joint.instance_a_id : joint.instance_b_id
    if (!seedId) return
    const groupIds = getRigidBodyGroup(assembly, seedId)
    for (const memberId of groupIds) {
      if (movingIds?.has(memberId)) continue
      const inst = assembly.instances?.find(i => i.id === memberId)
      const values = inst?.transform?.values
      if (!Array.isArray(values) || values.length !== 16) continue
      let mat
      if (endpointSide === 'a') {
        const delta = rotationDeltaMatrix(
          joint.axis_origin ?? [0, 0, 0],
          joint.axis_direction ?? [0, 0, 1],
          (joint.current_value ?? 0) - value,
        )
        mat = delta.multiply(new THREE.Matrix4().fromArray(values).transpose())
      } else {
        mat = computeRevoluteTransform(
          values,
          joint.axis_origin ?? [0, 0, 0],
          joint.axis_direction ?? [0, 0, 1],
          value - (joint.current_value ?? 0),
        )
      }
      assemblyRenderer.setLiveTransform(memberId, mat)
      assemblyJointRenderer.setLiveJointTransform(memberId, mat, assembly)
    }
  }

  function applyGearLiveForRevoluteDrag(assembly, constraint, movingIds, delta) {
    if (!assembly || constraint?.dof !== 'revolute' || !delta) return
    const joints = assembly.joints ?? []
    const seedJoint = joints.find(j => j.id === constraint.jointId)
    if (!seedJoint) return

    // Unwrap the gizmo's live rotation angle across frames: signedAngleFromWorldDelta
    // is atan2 (±π), so past half a turn it wraps and a belt rider would teleport.
    // Accumulate the shortest step from the previous sample. State persists for
    // the commit (which sends current_value, not a transform).
    const sideSign = movingSideSignForRevolute(seedJoint, movingIds)
    const raw = signedAngleFromWorldDelta(delta, constraint.axis)
    if (!_revoluteGizmoAngle || _revoluteGizmoAngle.jointId !== constraint.jointId) {
      _revoluteGizmoAngle = { jointId: constraint.jointId, lastRaw: raw, accum: raw, sideSign }
    } else {
      let step = raw - _revoluteGizmoAngle.lastRaw
      if (step >  Math.PI) step -= 2 * Math.PI
      if (step < -Math.PI) step += 2 * Math.PI
      _revoluteGizmoAngle.accum += step
      _revoluteGizmoAngle.lastRaw = raw
      _revoluteGizmoAngle.sideSign = sideSign
    }
    const seedDelta = _revoluteGizmoAngle.accum * sideSign

    // Gears + belts share the live-drag coupling graph (belts modelled as
    // gear-shaped edges with ratio r_a/r_b and open-belt direction).
    const rels = [...(assembly.gear_relations ?? []), ...beltCouplingRelations(assembly)]
    if (!rels.length) return

    const values = new Map(joints.map(j => [j.id, j.current_value ?? 0]))
    values.set(seedJoint.id, clampJointValue(seedJoint, (seedJoint.current_value ?? 0) + seedDelta))

    const queue = [seedJoint.id]
    const changed = new Set([seedJoint.id])
    const byId = new Map(joints.map(j => [j.id, j]))
    const endpointSideByJoint = new Map()
    let guard = 0
    const maxSteps = Math.max(1, rels.length * 2 + 1)
    while (queue.length && guard++ < maxSteps) {
      const sourceId = queue.shift()
      const sourceValue = values.get(sourceId)
      if (sourceValue == null) continue
      for (const rel of rels) {
        const sign = rel.invert ? -1 : 1
        let targetId = null
        let targetValue = null
        if (sourceId === rel.joint_a_id) {
          targetId = rel.joint_b_id
          const anchorSrc = rel.joint_a_anchor ?? 0
          const anchorTgt = rel.joint_b_anchor ?? 0
          const factor = rel.ratio
          const rawTarget = anchorTgt + sign * (sourceValue - anchorSrc) * factor
          targetValue = rawTarget
          endpointSideByJoint.set(targetId, gearEndpointSide(rel, 'b', byId.get(targetId)))
          const targetJoint = byId.get(targetId)
          const clampedTarget = clampJointValue(targetJoint, rawTarget)
          if (Math.abs(clampedTarget - rawTarget) > 1e-9 && Math.abs(factor) > 1e-12) {
            values.set(sourceId, clampJointValue(byId.get(sourceId), anchorSrc + sign * (clampedTarget - anchorTgt) / factor))
            changed.add(sourceId)
          }
        } else if (sourceId === rel.joint_b_id) {
          if (!Number.isFinite(rel.ratio) || Math.abs(rel.ratio) < 1e-9) continue
          targetId = rel.joint_a_id
          const anchorSrc = rel.joint_b_anchor ?? 0
          const anchorTgt = rel.joint_a_anchor ?? 0
          const factor = 1 / rel.ratio
          const rawTarget = anchorTgt + sign * (sourceValue - anchorSrc) * factor
          targetValue = rawTarget
          endpointSideByJoint.set(targetId, gearEndpointSide(rel, 'a', byId.get(targetId)))
          const targetJoint = byId.get(targetId)
          const clampedTarget = clampJointValue(targetJoint, rawTarget)
          if (Math.abs(clampedTarget - rawTarget) > 1e-9 && Math.abs(factor) > 1e-12) {
            values.set(sourceId, clampJointValue(byId.get(sourceId), anchorSrc + sign * (clampedTarget - anchorTgt) / factor))
            changed.add(sourceId)
          }
        } else {
          continue
        }
        const targetJoint = byId.get(targetId)
        if (!targetJoint || targetJoint.joint_type !== 'revolute') continue
        targetValue = clampJointValue(targetJoint, targetValue)
        if (Math.abs((values.get(targetId) ?? 0) - targetValue) < 1e-9) continue
        values.set(targetId, targetValue)
        changed.add(targetId)
        queue.push(targetId)
      }
    }

    for (const jointId of changed) {
      if (jointId === seedJoint.id) continue
      const joint = byId.get(jointId)
      _applyGearLiveJointValue(
        assembly,
        joint,
        values.get(jointId),
        movingIds,
        endpointSideByJoint.get(jointId) ?? 'b',
      )
    }
    // Belt riders follow live during a gizmo/group drag — use the freshly
    // computed coupled joint values (seed included).
    applyBeltRiders(
      assembly,
      (id, j) => values.get(id) ?? (j.current_value ?? 0),
      (iid, mat) => assemblyRenderer.setLiveTransform(iid, mat),
    )
  }

  function attachGroupGizmo(instanceId, ctx = null) {
    ctx ??= createAssemblyTransformContext(instanceId)
    if (!ctx) {
      setMotionChip(null)
      return
    }

    // Pre-flight constraint analysis. If the part can't move (anchored or
    // over-constrained), don't attach a gizmo at all — surface a chip with
    // the reason. For a single revolute/prismatic/spherical mate, anchor the
    // gizmo at the joint origin so the user rotates/translates about the
    // joint, not the part centroid.
    const constraint = analyzeMotionConstraints({ kind: 'instance', id: instanceId })
    const summary = summarizeConstraint(constraint)
    if (summary) setMotionChip(summary.text, summary.severity)
    else         setMotionChip(null)
    if (constraint.dof === 'anchored' || constraint.dof === 'over-constrained') {
      instanceGizmo.detach()
      return
    }

    const centerEntry = assemblyRenderer.getInstanceCenters?.()?.find(c => c.id === instanceId)
    const fallbackCentroid = centerEntry?.center ?? null
    const centroidWorld =
      (constraint.dof === 'revolute' || constraint.dof === 'prismatic' || constraint.dof === 'spherical')
        ? constraint.origin
        : fallbackCentroid

    instanceGizmo.attach(
      instanceId, scene, camera, canvas,
      // onLiveTransform: apply delta to ALL group members + FK descendants each frame
      (primaryMat4) => {
        const delta = applyAssemblyPrimaryLive(ctx, primaryMat4)
        applyGearLiveForRevoluteDrag(
          store.getState().currentAssembly,
          constraint,
          new Set(ctx.groupStartTransforms.keys()),
          delta,
        )
        if (getMrAssemblyCtx()?.instanceId === instanceId) setMrTransformValuesFromMatrix(primaryMat4)
      },
      // onCommit (drag end). For a revolute joint, commit the UNWRAPPED rotation
      // as the joint's current_value (the continuous-angle path) instead of a
      // transform the backend re-derives via atan2 (which wraps past ±π and
      // teleports belt riders). Other DOFs keep the transform-commit path.
      (primaryMat4) => {
        const rev = revoluteGizmoCommitValue(constraint)
        if (rev != null) api.patchAssemblyJoint(constraint.jointId, rev)
        else queueAssemblyPrimaryCommit(ctx, primaryMat4)
      },
      ctx.primaryStart,
      centroidWorld,
    )

    _revoluteGizmoAngle = null   // fresh accumulator for this attach

    if (constraint.dof === 'revolute') {
      instanceGizmo.applyConstraint({
        mode: 'rotate', axis: constraint.axis,
        showX: false, showY: false, showZ: true,
      })
    } else if (constraint.dof === 'prismatic') {
      instanceGizmo.applyConstraint({
        mode: 'translate', axis: constraint.axis,
        showX: false, showY: false, showZ: true,
      })
    } else if (constraint.dof === 'spherical') {
      instanceGizmo.applyConstraint({
        mode: 'rotate', spherical: true,
        showX: true, showY: true, showZ: true,
      })
    }
  }

  return {
    attachGroupGizmo,
    // Exposed for the still-in-main whole-group path (lifted in a follow-up):
    applyGearLiveForRevoluteDrag,
    revoluteGizmoCommitValue,
    resetRevoluteAngle,
  }
}
