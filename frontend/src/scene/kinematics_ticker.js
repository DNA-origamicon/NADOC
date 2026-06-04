/**
 * Per-frame integrator for continuous-spin revolute joints + gear relations.
 *
 * THREE-LAYER LAW: this module only mutates AssemblyJoint.current_value
 * (via silent PATCH) and the derived PartInstance.transform (via the
 * renderer's setLiveTransform path). It never writes to any field of an
 * embedded Design — spinning gears never modify scaffolds, strands,
 * helices, crossovers, or design-internal cluster joints.
 *
 * Kinematics:
 *   - DRIVERS: each tick, for every revolute joint with non-zero RPM, we
 *     integrate `current_value += ω · dt` and rotate the joint's child
 *     instance_b together with its entire rigid-body group (parts attached
 *     by rigid joints — stops at `fixed` instances).
 *   - GEAR PROPAGATION: after driver integration, every GearRelation is
 *     resolved: θ_b = anchor_b + sign · (θ_a − anchor_a) · ratio. The
 *     driven joint's rigid-body group is rotated to match. Cycles in the
 *     gear graph are detected and broken (one-time console warn); if two
 *     relations both target the same driven joint, the first one in
 *     assembly.gear_relations order wins and the rest log a one-time warn.
 *
 * Backend forward-kinematic propagation handles deeper chains (kinematic
 * descendants through further revolute / prismatic joints) on each silent
 * patch.
 *
 * Snapshot model: every revolute joint's rigid-body group is captured on
 * assembly-ref change. Between rebuilds we apply `R(axis, current − vSnapshot)`
 * to the snapshotted base transforms; this avoids accumulation error.
 *
 * Backend persistence: throttled silent patch (~5 Hz) keeps reloads and
 * configuration snapshots within a tick of live state.
 */

import { computeRevoluteTransform } from './assembly_revolute_math.js'
import { getRigidBodyGroup }         from './assembly_constraint_graph.js'
import { beltCouplingRelations, applyBeltRiders } from './belt_geometry.js'

const FLUSH_INTERVAL_SEC = 0.2   // ~5 Hz persistence to backend
const MAX_DT_SEC         = 1 / 15 // cap on a single integration step (background-tab return)
const TWO_PI_OVER_60     = Math.PI / 30  // rpm → rad/s

export function initKinematicsTicker({
  store,
  api,
  getAssemblyRenderer,
  getAssemblyJointRenderer,
} = {}) {
  let _shadow      = new Map()    // jointId → integrated current_value (radians)
  let _rigidGroups = new Map()    // jointId → array of { instanceId, baseValues, vSnapshot }
  let _gearEdges   = []           // [{ a, b, ratio, sign, da, dna }] precomputed gear graph
  let _gearDrivenBy = new Map()   // driven_joint_id → driver_joint_id (first wins; rest warned)
  let _gearWarned  = false        // one-time warn for cycles / shadowed targets per rebuild
  let _lastAssembly = null
  const _suspended    = new Set() // jointIds frozen this segment (animation player hook)
  const _pendingFlush = new Set() // jointIds with un-flushed shadow values
  let _lastFlushSec = 0

  function _rebuildIfNeeded(assembly) {
    if (assembly === _lastAssembly) return
    _lastAssembly = assembly

    // Preserve our locally-integrated shadow across rebuilds when the gap from
    // the backend's authoritative `current_value` looks like a normal in-flight
    // silent patch (worst case: ~1 second of RPM integration since last flush).
    // When the gap is larger — ring drag committed, backend gear propagation,
    // or a manual edit elsewhere — adopt the backend value so the next tick
    // doesn't snap the joint (and any gear-driven follower) back to a stale
    // shadow.
    const fresh = new Map()
    for (const j of assembly.joints ?? []) {
      const prev    = _shadow.get(j.id)
      const backend = j.current_value ?? 0
      if (prev == null) {
        fresh.set(j.id, backend)
        continue
      }
      const omega     = Math.abs(j.angular_velocity_rpm || 0) * TWO_PI_OVER_60
      const tolerance = omega * 1.0 + 0.01  // 1 s buffer for an in-flight silent patch
      fresh.set(j.id, Math.abs(prev - backend) > tolerance ? backend : prev)
    }
    _shadow = fresh

    // Snapshot every revolute joint's rigid-body group. `baseValues` is each
    // member's world transform at the moment we capture (which is the
    // backend's FK output at current_value = vSnapshot). On each tick we apply
    // R(axis, shadow - vSnapshot) to baseValues to compute the live transform.
    _rigidGroups.clear()
    const instById = new Map()
    for (const inst of assembly.instances ?? []) instById.set(inst.id, inst)

    for (const j of assembly.joints ?? []) {
      if (j.joint_type !== 'revolute') continue
      const membersBySide = { a: [], b: [] }
      const vSnapshot = j.current_value ?? 0
      for (const side of ['a', 'b']) {
        const seedId = side === 'a' ? j.instance_a_id : j.instance_b_id
        if (!seedId) continue
        for (const id of getRigidBodyGroup(assembly, seedId)) {
          const inst = instById.get(id)
          const values = inst?.transform?.values
          if (Array.isArray(values) && values.length === 16) {
            membersBySide[side].push({
              instanceId: id,
              baseValues: values.slice(),
              vSnapshot,
            })
          }
        }
      }
      _rigidGroups.set(j.id, membersBySide)
    }

    // Build the gear-relation propagation graph.
    _gearEdges = []
    _gearDrivenBy.clear()
    _gearWarned = false
    const jointIds = new Set((assembly.joints ?? []).map(j => j.id))
    // Belts couple their two pulley joints like a gear (ratio r_a/r_b, same world
    // sense); fold them into the same edge graph so RPM + propagation drive them.
    const couplings = [...(assembly.gear_relations ?? []), ...beltCouplingRelations(assembly)]
    for (const rel of couplings) {
      if (!jointIds.has(rel.joint_a_id) || !jointIds.has(rel.joint_b_id)) continue
      if (_gearDrivenBy.has(rel.joint_b_id)) continue   // first wins
      _gearDrivenBy.set(rel.joint_b_id, rel.joint_a_id)
      _gearEdges.push({
        a:     rel.joint_a_id,
        b:     rel.joint_b_id,
        ratio: rel.ratio,
        sign:  rel.invert ? -1 : 1,
        da:    rel.joint_a_anchor ?? 0,
        dna:   rel.joint_b_anchor ?? 0,
        sideA: rel.endpoint_a_side || 'b',
        sideB: rel.endpoint_b_side || 'b',
      })
    }
    // Cycle break: if a sequence of edges loops back, drop the offending edge.
    // Simple DFS three-color over the edge list.
    const adj = new Map()
    for (const e of _gearEdges) {
      if (!adj.has(e.a)) adj.set(e.a, [])
      adj.get(e.a).push(e)
    }
    const WHITE = 0, GRAY = 1, BLACK = 2
    const color = new Map()
    const cycleEdges = new Set()
    function dfs(node) {
      color.set(node, GRAY)
      for (const e of (adj.get(node) ?? [])) {
        const c = color.get(e.b) ?? WHITE
        if (c === GRAY) { cycleEdges.add(e) }
        else if (c === WHITE) dfs(e.b)
      }
      color.set(node, BLACK)
    }
    for (const e of _gearEdges) if ((color.get(e.a) ?? WHITE) === WHITE) dfs(e.a)
    if (cycleEdges.size) {
      _gearEdges = _gearEdges.filter(e => !cycleEdges.has(e))
      if (!_gearWarned) {
        console.warn(`[kinematics] Dropped ${cycleEdges.size} gear-relation edge(s) to break a cycle.`)
        _gearWarned = true
      }
    }
  }

  function _propagateGearRelations(assembly) {
    if (!_gearEdges.length) return
    // BIDIRECTIONAL propagation: each gear relation provides two edges in
    // the graph (forward: a→b at factor=ratio; inverse: b→a at factor=1/ratio).
    // Per pass, we first try forward then inverse for every edge, with a
    // first-wins set so a joint already updated this pass isn't re-driven by
    // the opposite direction (prevents oscillation in steady state).
    //
    // In normal operation the backend's bidirectional propagation has
    // already synced both joints, so both passes are no-ops. The ticker
    // matters during RPM-driven spin (forward) and as a defensive
    // re-sync when the backend response window leaves shadows out of sync.
    const MAX_PASSES = _gearEdges.length * 2 + 1
    const _clampValue = (joint, value) => {
      if (!joint) return value
      let next = value
      const lo = joint.min_limit, hi = joint.max_limit
      if (lo != null && next < lo) next = lo
      if (hi != null && next > hi) next = hi
      return next
    }
    const _applyEdge = (src, srcId, tgt, target, tgtId, endpointSide, sourceEndpointSide, anchorSrc, anchorTgt, factor, sign) => {
      if (!tgt) return false
      const raw = target
      const next = _clampValue(tgt, raw)
      if (Math.abs(next - raw) > 1e-9 && src && Math.abs(factor) > 1e-12) {
        const sourceRaw = anchorSrc + sign * (next - anchorTgt) / factor
        const sourceNext = _clampValue(src, sourceRaw)
        const sourcePrev = _shadow.get(srcId)
        if (sourcePrev == null || Math.abs(sourcePrev - sourceNext) >= 1e-9) {
          _shadow.set(srcId, sourceNext)
          _applyToRenderer(src, sourceNext, assembly, sourceEndpointSide)
          _pendingFlush.add(srcId)
        }
      }
      const prev = _shadow.get(tgtId)
      if (prev != null && Math.abs(prev - next) < 1e-9) return false
      _shadow.set(tgtId, next)
      _applyToRenderer(tgt, next, assembly, endpointSide)
      _pendingFlush.add(tgtId)
      return true
    }
    const joints = assembly.joints ?? []
    for (let pass = 0; pass < MAX_PASSES; pass++) {
      let anyChanged = false
      const writtenThisPass = new Set()

      // Forward pass: drivers (a) → driven (b)
      for (const e of _gearEdges) {
        if (writtenThisPass.has(e.b)) continue
        const srcVal = _shadow.get(e.a)
        if (srcVal == null) continue
        const target  = e.dna + e.sign * (srcVal - e.da) * e.ratio
        const driver  = joints.find(j => j.id === e.a)
        const driven  = joints.find(j => j.id === e.b)
        if (_applyEdge(driver, e.a, driven, target, e.b, e.sideB, e.sideA, e.da, e.dna, e.ratio, e.sign)) {
          writtenThisPass.add(e.b)
          anyChanged = true
        }
      }

      // Inverse pass: driven (b) → driver (a). θ_a = anchor_a + sign · (θ_b − anchor_b) / ratio
      for (const e of _gearEdges) {
        if (writtenThisPass.has(e.a)) continue
        if (!Number.isFinite(e.ratio) || Math.abs(e.ratio) < 1e-9) continue
        const srcVal = _shadow.get(e.b)
        if (srcVal == null) continue
        const target  = e.da + e.sign * (srcVal - e.dna) / e.ratio
        const driven  = joints.find(j => j.id === e.b)
        const driver  = joints.find(j => j.id === e.a)
        if (_applyEdge(driven, e.b, driver, target, e.a, e.sideA, e.sideB, e.dna, e.da, 1 / e.ratio, e.sign)) {
          writtenThisPass.add(e.a)
          anyChanged = true
        }
      }

      if (!anyChanged) break
    }
  }

  function _applyToRenderer(joint, value, assembly, endpointSide = 'b') {
    const members = _rigidGroups.get(joint.id)?.[endpointSide]
    if (!members?.length) return

    const renderer      = getAssemblyRenderer?.()
    const jointRenderer = getAssemblyJointRenderer?.()
    for (const m of members) {
      const deltaAngle = endpointSide === 'a'
        ? m.vSnapshot - value
        : value - m.vSnapshot
      const mat = computeRevoluteTransform(
        m.baseValues,
        joint.axis_origin,
        joint.axis_direction,
        deltaAngle,
      )
      renderer?.setLiveTransform?.(m.instanceId, mat)
      jointRenderer?.setLiveJointTransform?.(m.instanceId, mat, assembly)
    }
  }

  function _maybeFlush() {
    if (!_pendingFlush.size) return
    const nowSec = performance.now() / 1000
    if (nowSec - _lastFlushSec < FLUSH_INTERVAL_SEC) return
    _lastFlushSec = nowSec
    _flushNow()
  }

  function _flushNow() {
    if (!_pendingFlush.size) return
    const ids = [..._pendingFlush]
    _pendingFlush.clear()
    for (const id of ids) {
      const v = _shadow.get(id)
      if (v == null) continue
      try {
        api?.patchAssemblyJoint?.(id, { current_value: v, silent: true })
      } catch {
        // network errors are non-fatal for spin persistence
      }
    }
  }

  function tick(dtSec) {
    if (!Number.isFinite(dtSec) || dtSec <= 0) return
    const dt = Math.min(dtSec, MAX_DT_SEC)

    const { currentAssembly } = store.getState()
    if (!currentAssembly?.joints?.length) return

    _rebuildIfNeeded(currentAssembly)

    let spun = false
    for (const joint of currentAssembly.joints) {
      if (joint.joint_type !== 'revolute') continue
      if (joint.spin_paused) continue
      if (!joint.angular_velocity_rpm) continue
      if (_suspended.has(joint.id)) continue
      // Driven joints get their value from a GearRelation, not directly from
      // RPM — skip the integration step here. (If a user later wants an RPM
      // on a driven joint, the relation can override.)
      if (_gearDrivenBy.has(joint.id)) continue

      const omega = joint.angular_velocity_rpm * TWO_PI_OVER_60
      const prev  = _shadow.get(joint.id) ?? (joint.current_value ?? 0)
      let next    = prev + omega * dt

      const lo = joint.min_limit
      const hi = joint.max_limit
      if (lo != null && next < lo) next = lo
      if (hi != null && next > hi) next = hi

      _shadow.set(joint.id, next)
      _applyToRenderer(joint, next, currentAssembly)
      _pendingFlush.add(joint.id)
      spun = true
    }

    _propagateGearRelations(currentAssembly)

    // Belt riders ride along the loop, driven by the spinning pulley angle.
    // ONLY when this tick actually integrated a joint (RPM spin) — otherwise
    // `_shadow` may hold a stale angle (preserved across rebuilds for in-flight
    // patches) and would fight the store-driven update path (subscription /
    // live-drag), making riders flicker. For manual rotation those paths own it.
    if (spun) {
      applyBeltRiders(
        currentAssembly,
        (id, j) => _shadow.get(id) ?? (j.current_value ?? 0),
        (iid, mat) => {
          getAssemblyRenderer?.()?.setLiveTransform?.(iid, mat)
          getAssemblyJointRenderer?.()?.setLiveJointTransform?.(iid, mat, currentAssembly)
        },
      )
    }

    _maybeFlush()
  }

  function suspendJoints(ids) {
    for (const id of ids ?? []) _suspended.add(id)
  }

  function resumeJoints(ids) {
    const { currentAssembly } = store.getState()
    for (const id of ids ?? []) {
      _suspended.delete(id)
      const j = currentAssembly?.joints?.find(x => x.id === id)
      if (j) _shadow.set(id, j.current_value ?? 0)
    }
  }

  function flushNow() { _flushNow() }

  function dispose() {
    _flushNow()
    _shadow.clear()
    _rigidGroups.clear()
    _gearEdges = []
    _gearDrivenBy.clear()
    _suspended.clear()
    _pendingFlush.clear()
    _lastAssembly = null
  }

  // Console diagnostic for gear mates (wired to window.nadocGearDebug in main.js).
  // Prints + returns the current gear-relation state, the ticker's gear graph,
  // shadow values, and a per-joint summary — so you can confirm a gear was
  // created, see its ratio, and verify the ticker's shadow agrees with the
  // backend's `current_value`.
  function gearDebug() {
    const a = store.getState().currentAssembly
    const out = {
      assembly_id: a?.id,
      joints: (a?.joints ?? []).map(j => ({
        id: j.id, name: j.name, type: j.joint_type,
        current_value: j.current_value,
        angular_velocity_rpm: j.angular_velocity_rpm,
        instance_a_id: j.instance_a_id,
        instance_b_id: j.instance_b_id,
      })),
      gear_relations: a?.gear_relations ?? [],
      ticker: debugState(),
    }
    // eslint-disable-next-line no-console
    console.log('[nadocGearDebug]', out)
    return out
  }

  function debugState() {
    const { currentAssembly } = store.getState() ?? {}
    return {
      hasAssembly: !!currentAssembly,
      gearRelationsOnAssembly: currentAssembly?.gear_relations ?? null,
      gearEdges: _gearEdges.map(e => ({ ...e })),
      gearDrivenBy: Object.fromEntries(_gearDrivenBy),
      shadow: Object.fromEntries(_shadow),
      rigidGroupSizes: Object.fromEntries(
        Array.from(_rigidGroups.entries()).map(([k, v]) => [k, v.length]),
      ),
      suspended: [..._suspended],
      pendingFlush: [..._pendingFlush],
      lastAssemblyRef: _lastAssembly,
    }
  }

  return {
    tick,
    suspendJoints,
    resumeJoints,
    flushNow,
    dispose,
    debugState,
    gearDebug,
  }
}
