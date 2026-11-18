import { Vector3, Quaternion } from 'three'
import { buildContactBodies, createTetherContactGuard } from './tether_contacts.js'

/** One drag transaction: collision-clamp all participating bodies together, and
 * reject interpolated poses that would violate the existing tether constraints. */
export function createTetherContactController({ store, read, pending }) {
  let enabled = true, guard = null
  const poses = s => Object.fromEntries([
    [s.clusterId, { pos: s.dummy.position.toArray(), quat: s.dummy.quaternion.toArray() }],
    ...(s.links ?? []).map(l => [l.clusterId, { pos: [...l.resultPos], quat: [...l.resultQuat] }]),
  ])
  function apply(s, result) {
    const main = result[s.clusterId]
    s.dummy.position.fromArray(main.pos); s.dummy.quaternion.fromArray(main.quat)
    s.incrQuat.copy(s.dummy.quaternion).multiply(s.startQuat.clone().invert())
    for (const link of s.links ?? []) {
      link.resultPos = result[link.clusterId].pos
      link.resultQuat = result[link.clusterId].quat
    }
  }
  function violation(s, result) {
    const main = result[s.clusterId]
    const delta = new Quaternion(...main.quat).multiply(s.startQuat.clone().invert())
    const moved = point => point.clone().sub(s.startPos).applyQuaternion(delta).add(new Vector3(...main.pos))
    let excess = 0
    for (const t of s.tethers ?? []) {
      const d = moved(t.pM0).distanceTo(t.pF) - t.contour
      excess = Math.max(excess, t.rigid ? Math.abs(d) : d)
    }
    for (const link of s.links ?? []) for (const t of link.tethers) {
      const pose = result[link.clusterId]
      const p = new Vector3(...t.lStart).sub(new Vector3(...link.startPos))
        .applyQuaternion(new Quaternion(...link.baseQuat).invert())
        .applyQuaternion(new Quaternion(...pose.quat)).add(new Vector3(...pose.pos))
      const fixed = t.partDragged ? moved(new Vector3(...t.pStart)) : new Vector3(...t.pStart)
      excess = Math.max(excess, p.distanceTo(fixed) - t.contour)
    }
    return excess
  }
  let initialExcess = 0
  return {
    setEnabled(value) { enabled = !!value },
    arm() {
      guard = null
      const s = read()
      if (!enabled || s.type !== 'ssdna') return
      const state = store.getState(), initial = poses(s)
      guard = createTetherContactGuard(buildContactBodies(state.currentDesign, state.currentGeometry, pending()), initial)
      initialExcess = violation(s, initial)
    },
    clamp() {
      const s = read()
      if (!enabled || s.type !== 'ssdna' || !guard) return
      const target = poses(s)
      // Preserve the existing finite-iteration tether solver's tolerance. Contact
      // clipping must not make either the start or the proposed residual worse.
      const tolerance = Math.max(.001, initialExcess, violation(s, target))
      const result = guard.accept(target, true, candidate => violation(s, candidate) <= tolerance + 1e-9)
      apply(s, result)
    },
  }
}
