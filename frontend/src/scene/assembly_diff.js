/**
 * Assembly snapshot-diff / fast-path helpers extracted from main.js. Pure:
 * parameters + THREE/JSON/Map only — no store/assemblyRenderer. The subscribers
 * that ACT on these decisions (live-transform fast path, gizmo re-attach) stay in
 * main.js. Unit-tested in assembly_diff.test.js.
 */
import * as THREE from 'three'

/** Instance.transform.values (row-major) → THREE.Matrix4. */
export function matrixFromInstance(inst) {
  return new THREE.Matrix4().fromArray(inst.transform.values).transpose()
}

// Element-wise compare of two instances' 4×4 transform value arrays.
// Missing / mismatched arrays → treated as changed (safe: forces a push).
export function sameInstanceTransform(a, b) {
  const av = a?.transform?.values, bv = b?.transform?.values
  if (!av || !bv || av.length !== bv.length) return false
  for (let i = 0; i < av.length; i++) if (av[i] !== bv[i]) return false
  return true
}

// True when prev → next differs ONLY in per-instance transforms (same instance
// set, same geometry-affecting fields). Lets the assembly subscriber update
// transforms in place via setLiveTransform instead of a full dispose + re-fetch
// rebuild (which made the whole assembly blink on every move/rotate commit).
// Materialized linker topology (assembly_helices/strands) changing is NOT
// transform-only. A pure `visible` toggle IS allowed on the fast path — it goes
// through the cheap visibility overlay, not a geometry rebuild.
export function assemblyTransformOnlyChange(prev, next) {
  if (!prev || !next) return false
  const pi = prev.instances ?? [], ni = next.instances ?? []
  if (pi.length === 0 || pi.length !== ni.length) return false
  if (JSON.stringify(prev.assembly_helices ?? []) !== JSON.stringify(next.assembly_helices ?? [])) return false
  if (JSON.stringify(prev.assembly_strands ?? []) !== JSON.stringify(next.assembly_strands ?? [])) return false
  const pById = new Map(pi.map(i => [i.id, i]))
  for (const inst of ni) {
    const p = pById.get(inst.id)
    if (!p) return false
    if (p.representation !== inst.representation) return false
    if (p.mode          !== inst.mode)          return false
    if ((p.source?.type) !== (inst.source?.type)) return false
    if ((p.source?.path) !== (inst.source?.path)) return false
    if (JSON.stringify(p.cluster_transform_overrides ?? [])
        !== JSON.stringify(inst.cluster_transform_overrides ?? [])) return false
  }
  return true
}

/** Constraint-chip descriptor {text, severity} for a DOF result, or null when free/none. */
export function summarizeConstraint(c) {
  if (!c || c.dof === 'free') return null
  if (c.dof === 'anchored') return { text: `Anchored — ${c.reason ?? ''}`.trim(), severity: 'locked' }
  if (c.dof === 'over-constrained') return { text: c.reason, severity: 'warn' }
  if (c.dof === 'revolute')  return { text: `1-DOF rotation about joint${c.name ? ` "${c.name}"` : ''}`,    severity: 'ok' }
  if (c.dof === 'prismatic') return { text: `1-DOF translation along joint${c.name ? ` "${c.name}"` : ''}`, severity: 'ok' }
  if (c.dof === 'spherical') return { text: `3-DOF rotation at joint${c.name ? ` "${c.name}"` : ''}`,       severity: 'ok' }
  return null
}

// Did any constraint INPUT change between two assembly snapshots?
//   - any joint added / removed
//   - any joint's type / axis / endpoints / limits changed
//   - any instance's `fixed` flag changed
// Cheap heuristic — JSON-stringify the relevant fields per joint and the sorted
// (id, fixed) list of instances. Avoids re-attaching the gizmo on pure
// transform-only updates (a part moved, but its DOF didn't change).
export function constraintRelevantChanged(prev, next, _activeInstanceId) {
  if (!prev || !next) return prev !== next
  const sigJoints = (asm) => JSON.stringify(
    (asm.joints ?? []).map(j => [
      j.id, j.joint_type, j.instance_a_id, j.instance_b_id,
      j.axis_origin, j.axis_direction,
      j.min_limit ?? null, j.max_limit ?? null,
    ]).sort((a, b) => String(a[0]).localeCompare(String(b[0]))),
  )
  if (sigJoints(prev) !== sigJoints(next)) return true
  const sigFixed = (asm) => JSON.stringify(
    (asm.instances ?? []).map(i => [i.id, !!i.fixed])
      .sort((a, b) => String(a[0]).localeCompare(String(b[0]))),
  )
  if (sigFixed(prev) !== sigFixed(next)) return true
  return false
}
