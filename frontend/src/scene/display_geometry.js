import * as THREE from 'three'
import { baseKey } from './base_ref.js'

export const displayKey = n => typeof n === 'string' ? n : baseKey(n, n?.copy ?? n?.copy_k ?? 0)

// The geometry controller is the only writer of live bead poses. Instrument its
// mutation boundary once; callers never enumerate connection/overlay renderers.
export const POSITION_OPERATIONS = new Set([
  'updateStaticFullGeometry', 'patchNucleotides', 'applyResidueTransformMatrix',
  'revertToGeometry', 'setBeadOverrides', 'applyFemPositions', 'applyDeformLerp',
  'applyPositionLerp', 'applyClusterTransform', 'commitClusterPositions',
  'applyBridgeNucsUpdate', 'applyPositionsUpdate', 'applyUnfoldOffsets',
  'applyUnfoldOffsetsExtensions',
])

/** A document-local display frame and scene owner. Never writes authored records.
 * Bindings share the live vectors used by the mesh writers. Non-mesh nucleotides
 * (flexible runs, inserted bases) resolve through the same exact-key frame.
 * Producers run before consumers; a transaction publishes only its final pose.
 */
export function createDisplayGeometry(scene) {
  const root = new THREE.Group()
  root.name = 'designDisplay'
  scene?.add(root)
  const native = new Map(), bindings = new Map(), derived = new Map(), layers = new Map()
  let simulation = null, depth = 0, flushing = false, revision = 0
  const pending = new Set(), operations = new Map()
  let mutations = new Set()
  let reason = 'native', disposed = false
  const api = {
    root,
    get revision() { return revision },
    get reason() { return reason },
    operation(name) { return operations.get(name) },
    changed(operation) { return mutations.has(operation) },
    get simulated() { return simulation !== null },
    beginGeneration(nucleotides = []) {
      native.clear(); bindings.clear(); derived.clear(); simulation = null
      for (const n of nucleotides ?? []) if (n.backbone_position) native.set(displayKey(n), n)
    },
    bind(entries) {
      for (const e of entries ?? []) {
        const key = baseKey(e.nuc, e._copy ?? e.nuc?.copy ?? e.nuc?.copy_k ?? 0)
        if (!key || !e.pos) continue
        bindings.set(key, e.pos)
        if (!native.has(key)) native.set(key, { ...e.nuc, copy_k: e._copy ?? e.nuc.copy ?? e.nuc.copy_k ?? 0, backbone_position: e.nuc.backbone_position ?? e.pos.toArray() })
      }
    },
    // Derived producers publish the same vectors they upload to their meshes.
    publishDerived(owner, entries) {
      derived.set(owner, new Map(entries.map(([nuc, pos]) => [displayKey(nuc), pos])))
    },
    position(nuc, out = new THREE.Vector3()) {
      const key = displayKey(nuc), live = bindings.get(key)
      for (const sites of derived.values()) if (sites.has(key)) return out.copy(sites.get(key))
      if (live) return out.copy(live)
      const p = simulation?.get(key)?.backbone_position ?? native.get(key)?.backbone_position
      return p ? out.fromArray(p) : null
    },
    project(nuc) {
      const pos = api.position(nuc)
      if (!pos) return null
      return { ...nuc, ...simulation?.get(displayKey(nuc)), backbone_position: pos.toArray() }
    },
    simulationRecord(nuc) { return simulation?.get(displayKey(nuc)) ?? null },
    setSimulation(updates, amp = 1) {
      simulation = updates == null ? null : new Map()
      if (!simulation) {
        for (const [key, pos] of bindings) { const n = native.get(key); if (n?.backbone_position) pos.fromArray(n.backbone_position) }
        api.invalidate('simulation')
        return null
      }
      // A frame replaces a frame, including missing sites: no old frame may leak
      // through a partial update. All layers use the same native fallback policy.
      for (const u of updates) {
        const key = displayKey(u), n = native.get(key)
        const p = u.backbone_position
        if (!key || !p) continue
        const eq = n?.backbone_position
        const position = eq && amp !== 1 ? p.map((v, i) => eq[i] + amp * (v - eq[i])) : [...p]
        const projected = { ...u, backbone_position: position }
        for (const site of ['base_position', 'cm_position']) if (u[site] && amp !== 1) projected[site] = u[site].map((v, i) => v + position[i] - p[i])
        simulation.set(key, projected)
      }
      const resolved = [...simulation.values()]
      for (const [key, n] of native) {
        if (!simulation.has(key) && n.helix_id !== '__xb__') resolved.push({ ...n, copy: n.copy_k ?? 0, backbone_position: [...n.backbone_position] })
        const pos = bindings.get(key)
        if (pos) pos.fromArray(simulation.get(key)?.backbone_position ?? n.backbone_position)
      }
      api.invalidate('simulation')
      return resolved
    },
    register(id, { group = null, update = () => {}, phase = 1 } = {}) {
      if (layers.has(id)) throw new Error(`Duplicate display layer: ${id}`)
      if (group) root.add(group)
      const layer = { group, update, phase }
      layers.set(id, layer)
      return () => { if (layers.get(id) === layer) { layers.delete(id); derived.delete(id); group?.removeFromParent() } }
    },
    transaction(nextReason, mutate) {
      depth++
      try { return mutate() } finally { depth--; if (!depth && pending.size) api.invalidate(nextReason) }
    },
    invalidate(nextReason = reason) {
      if (disposed) return
      if (flushing) return
      reason = nextReason; pending.add(nextReason)
      if (depth) return
      flushing = true
      try {
        // Producer writes are part of this frame, not recursively new frames.
        mutations = new Set(pending); pending.clear(); revision++
        for (const layer of [...layers.values()].sort((a, b) => a.phase - b.phase)) layer.update(api)
      } finally { flushing = false }
    },
    observe(controller) {
      const cache = new Map()
      return new Proxy(controller, {
        get(target, key) {
          const value = target[key]
          if (typeof value !== 'function') return value
          if (!cache.has(key)) cache.set(key, POSITION_OPERATIONS.has(key)
            ? (...args) => api.transaction(key, () => { operations.set(key, args); const result = value.apply(target, args); api.invalidate(key); return result })
            : value.bind(target))
          return cache.get(key)
        },
      })
    },
    dispose() { disposed = true; layers.clear(); native.clear(); bindings.clear(); derived.clear(); simulation = null; root.removeFromParent() },
  }
  return api
}
