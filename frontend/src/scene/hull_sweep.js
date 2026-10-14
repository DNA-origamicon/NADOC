/** Exact swept hull frames, with per-build reuse of the common bundle spine. */
import * as THREE from 'three'

// MUST match backend deformation._AXIS_SAMPLE_STEP. No resampling or smoothing.
const _AXIS_SAMPLE_STEP = 7

/** Scoped to one immutable design/axes build. Centroid addition order is kept;
 * frames still propagate to each box's own endpoint, whose tangent differs.
 */
export function createHullSweepFrame(design, helixAxes, frameHelixIds) {
  const sampled = frameHelixIds.filter(hid => (helixAxes[hid]?.samples?.length ?? 0) > 2)
  const bpStart = design.helices.find(h => h.id === sampled[0])?.bp_start ?? 0
  const minSamples = sampled.reduce((min, hid) => Math.min(min, helixAxes[hid].samples.length), Infinity)
  const centers = []
  return { sampled, bpStart, minSamples,
    centersThrough(last) {
      for (let i = centers.length; i <= last; i++) {
        const center = new THREE.Vector3()
        for (const hid of sampled) {
          const s = helixAxes[hid].samples[i]
          center.x += s[0]; center.y += s[1]; center.z += s[2]
        }
        centers.push(center.divideScalar(sampled.length))
      }
      return centers.slice(0, last + 1)
    },
  }
}

export function boxSweptSections(design, helixAxes, boxHelixIds, bpLo, bpHi, wCol, wRow, frameHelixIds = boxHelixIds, frameContext = null) {
  const sampled = boxHelixIds.filter(hid => (helixAxes[hid]?.samples?.length ?? 0) > 2)
  if (!sampled.length) return null
  const frameSampled = frameContext?.sampled ?? frameHelixIds.filter(hid => (helixAxes[hid]?.samples?.length ?? 0) > 2)
  if (!frameSampled.length) return null
  const bs = frameContext?.bpStart ?? design.helices.find(h => h.id === frameSampled[0])?.bp_start ?? 0
  let nMin = frameContext?.minSamples ?? Infinity
  for (const hid of frameContext ? sampled : [...new Set([...sampled, ...frameSampled])]) nMin = Math.min(nMin, helixAxes[hid].samples.length)
  if (nMin < 2) return null
  const idxLo = Math.max(0, Math.min(nMin - 1, Math.round((bpLo - bs) / _AXIS_SAMPLE_STEP)))
  const idxHi = Math.max(0, Math.min(nMin - 1, Math.round((bpHi - bs) / _AXIS_SAMPLE_STEP)))
  if (idxHi - idxLo < 1) return null

  const Yv = new THREE.Vector3(0, 1, 0)
  const Zv = new THREE.Vector3(0, 0, 1)
  // Rectangle in the cross-section (U,V) plane — corner.x → U, corner.z → V.
  const corners = [
    { x:  wCol / 2, z:  wRow / 2 }, { x: -wCol / 2, z:  wRow / 2 },
    { x: -wCol / 2, z: -wRow / 2 }, { x:  wCol / 2, z: -wRow / 2 },
  ]
  // Build the centroid spine for the FULL range [0, idxHi] — NOT just the box's
  // [idxLo, idxHi].  The parallel-transport frame below must be anchored at the
  // bundle START (idx 0, tangent ≈ +Z, well-conditioned), so EVERY extrusion box
  // shares ONE consistent frame.  Seeding each box independently from its own
  // first section put the LAST box's seed right at the −Y pole (90° bend) →
  // degenerate → the whole final block was mis-rolled (the residual flip seen
  // even after the per-box smoothing fix).  We propagate from 0 but EMIT sections
  // only for idxLo..idxHi below.
  const centers = frameContext?.centersThrough(idxHi) ?? [], sectionCenters = []
  for (let i = 0; i <= idxHi; i++) {
    if (!frameContext) {
      const c = new THREE.Vector3()
      for (const hid of frameSampled) { const s = helixAxes[hid].samples[i]; c.x += s[0]; c.y += s[1]; c.z += s[2] }
      centers.push(c.divideScalar(frameSampled.length))
    }
    const sc = new THREE.Vector3()
    for (const hid of sampled) { const s = helixAxes[hid].samples[i]; sc.x += s[0]; sc.y += s[1]; sc.z += s[2] }
    sectionCenters.push(sc.divideScalar(sampled.length))
  }
  const M = centers.length
  // Rotation-minimizing (parallel-transport) cross-section frame.  The original
  // code rebuilt the box axes from `tangent × worldY` at EVERY section, which is
  // SINGULAR when the spine tangent nears the vertical axis: a bend that drives
  // the bundle toward world-up (teeth.nadoc: 90° bend at direction 270° → final
  // tangent ≈ −Y, verified) made the U axis collapse and flip ~90° on the last
  // box — the "sudden twist, wrong degree + direction" on the final segment.
  // Instead, seed U once at the bundle start, then carry it forward by the
  // minimal rotation between consecutive tangents.  No world-up reference → no
  // pole → no flip; for a planar bend U stays constant straight through the
  // formerly-singular end.  NOTE: this is a smooth swept envelope — it does NOT
  // roll by the bundle's material twist (the axis `samples` carry only spine
  // centers, no per-bp orientation); the visible coil comes from the spine path.
  const sections = []
  let prevT = null
  let U = null
  for (let k = 0; k < M; k++) {
    let tangent
    if (k === 0)          tangent = new THREE.Vector3().subVectors(centers[1], centers[0])
    else if (k === M - 1) tangent = new THREE.Vector3().subVectors(centers[k], centers[k - 1])
    else                  tangent = new THREE.Vector3().subVectors(centers[k + 1], centers[k - 1])
    if (tangent.lengthSq() < 1e-12) continue
    tangent.normalize()
    if (!U) {
      // Seed: any unit vector ⟂ tangent.  world-Y, falling back to world-Z when
      // the start tangent is itself near the Y pole.
      U = new THREE.Vector3().crossVectors(tangent, Yv)
      if (U.lengthSq() < 1e-4) U = new THREE.Vector3().crossVectors(tangent, Zv)
      U.normalize()
    } else {
      // Parallel-transport U across the tangent change: rotate about
      // (prevT × tangent) by the angle between the tangents, then re-orthogonalize.
      const axis = new THREE.Vector3().crossVectors(prevT, tangent)
      const sin  = axis.length()
      if (sin > 1e-9) {
        U.applyAxisAngle(axis.divideScalar(sin), Math.atan2(sin, prevT.dot(tangent)))
      }
      U.addScaledVector(tangent, -U.dot(tangent)).normalize()   // re-project ⟂ tangent
    }
    prevT = tangent
    // Propagate the frame through [0, idxLo) but only EMIT the box's own sections.
    if (k < idxLo) continue
    const V = new THREE.Vector3().crossVectors(U, tangent).normalize()
    sections.push({ center: sectionCenters[k], U: U.clone(), V, tangent, corners })
  }
  return sections.length >= 2 ? sections : null
}

