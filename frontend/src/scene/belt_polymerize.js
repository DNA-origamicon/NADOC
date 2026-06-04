// Belt-loop polymerize: grow count-1 evenly-spaced copies of a seed belt rider
// around its closed belt path. The seed rider's local seating transform is
// re-seated at evenly-spaced arc params so copies sit edge-to-edge around the
// loop. Geometry is JS-side (belt frames); the backend just records the copies.
//
// Extracted from main.js (Tier-3 "Polymerize / kinematics / joint-pick" region).
// Three-Layer Law: this only produces PartInstance transforms for the assembly
// (display/topology of the assembly graph) — it never touches per-part DNA topology.

import * as THREE from 'three'
import { beltRiderCtx, beltRiderFill } from './belt_rider.js'
import { beltFrameAt } from './belt_geometry.js'
import { showToast } from '../ui/toast.js'

// Pure core: given a belt-rider context (loop points + plane normal + the seed
// rider's arc_param/local_transform) and a requested copy count, build the
// count-1 evenly-spaced copy descriptors. Returns { n, copies } where each copy
// is { arc_param, transform: { values: <16-float row-major matrix> } }.
//
// n is clamped to >= 2 (a single copy is a no-op). The seed itself is NOT
// included — only the k = 1..n-1 additional copies.
export function buildBeltPolymerizeCopies(ctx, count) {
  const n = Math.max(2, Math.floor(count) || 2)
  const base = ctx.rider.arc_param ?? 0
  const local = new THREE.Matrix4().fromArray(ctx.rider.local_transform).transpose()
  const copies = []
  for (let k = 1; k < n; k++) {
    const arc = ((base + k / n) % 1 + 1) % 1
    const world = beltFrameAt(ctx.points, arc, ctx.planeNormal).multiply(local)
    copies.push({ arc_param: arc, transform: { values: world.clone().transpose().toArray() } })
  }
  return { n, copies }
}

// Factory: wires the belt-polymerize helpers to the live store / api / renderer.
// Returns { beltCtxForRider, beltFillInfo, polymerizeBelt }.
//   - getAssemblyRenderer: () => assemblyRenderer (lazy — resolved per call).
export function initBeltPolymerize({ store, api, getAssemblyRenderer }) {
  // Build the per-belt geometry context for a rider, or null if unavailable.
  function beltCtxForRider(riderId) {
    return beltRiderCtx(store.getState().currentAssembly, riderId)
  }

  // Auto fill count from the seed part's footprint along the belt tangent, so
  // copies sit edge-to-edge. Returns { count, spacingNm, footprintNm } or null.
  function beltFillInfo(riderId) {
    const ctx = beltCtxForRider(riderId)
    if (!ctx) return null
    const entry = getAssemblyRenderer().getInstanceCenters?.()?.find(c => c.id === ctx.rider.instance_id)
    return beltRiderFill(ctx, entry?.size)
  }

  // Create count-1 evenly-spaced copies of the seed rider around the loop.
  async function polymerizeBelt(riderId, count) {
    const ctx = beltCtxForRider(riderId)
    if (!ctx) { showToast('Belt geometry unavailable — re-attach the part first.', { severity: 'error' }); return }
    const { n, copies } = buildBeltPolymerizeCopies(ctx, count)
    const res = await api.polymerizeBelt({ rider_id: riderId, copies })
    if (res === null) showToast(`Polymerize failed: ${store.getState().lastError?.message ?? ''}`, { severity: 'error' })
    else showToast(`Polymerized ${n} copies around the belt.`)
  }

  return { beltCtxForRider, beltFillInfo, polymerizeBelt }
}
