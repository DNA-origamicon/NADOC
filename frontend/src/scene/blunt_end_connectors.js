/**
 * Blunt-end connector candidates for "Define Mate" — pure geometry.
 *
 * Extracted from assembly_renderer.js, where two byte-identical copies of this
 * computation had drifted apart in maintenance (legacy per-instance path and
 * shared-instancing path).  Both now call this one function, so a fix lands once.
 *
 * Emits three kinds of connector, all shaped alike:
 *   1. Free helix endpoints    — label `blunt:<helixId>:start|end`
 *   2. Interior strand termini — label `blunt:<helixId>:bp<N>`  (overhang tips)
 *   3. Overhang crossover junctions on the main helix — same bp label form
 *
 * ── ovhg_axes convention (load-bearing) ──────────────────────────────────────
 * The backend emits, per overhang: {bp_min, bp_max, start, end} where `start` is
 * the axis position of base `bp_min` and `end` is the position of base
 * `bp_max + 1` — i.e. `end` is a duplex EXTENT, one B-DNA rise past the last
 * base, not the last base's position.  See `_apply_ovhg_rotations_to_axes`
 * (backend/core/deformation.py) and the matching readers in domain_ends.js /
 * helix_renderer.js, which divide by `bp_max - bp_min + 1`.
 * A connector must sit ON a base, so the bp_max tip is interpolated back to that
 * base's center here (`_tipAtBpMax`).  Do not "fix" this by changing the backend
 * — three other renderer sites depend on the extent convention.
 */
import * as THREE from 'three'
import { BDNA_RISE_PER_BP } from '../constants.js'

/**
 * Axis position of base `bp_max` given an ovhg_axes entry whose `end` is one
 * rise past it.  span = number of bases the entry covers; the entry spans
 * `span` rises from start to end, so base bp_max sits at (span-1)/span.
 * Single-base domains (span 1) collapse onto `start`.
 */
export function _tipAtBpMax(start3, end3, bpMin, bpMax) {
  const span = (bpMax - bpMin) + 1
  if (!(span > 1)) return start3.clone()
  return start3.clone().lerp(end3, (span - 1) / span)
}

/**
 * bp keys (`helixId:bp`) where an overhang domain JOINS its main helix — i.e.
 * the overhang-side foot of an overhang↔main crossover.  An extruded overhang
 * lives on its own stub helix one lattice cell away, so its root endpoint
 * touches no other helix endpoint and would otherwise be mistaken for a free
 * blunt end (a spurious connector at the base of every extrude overhang).
 *
 * Traversal order gives which end is the foot: for a 3' overhang the strand
 * runs main → stub so the foot is the overhang domain's start_bp; for a 5'
 * overhang it runs stub → main so the foot is its end_bp.  Matches the
 * backend's `junction_bp = domain.end_bp if dom_idx == 0 else domain.start_bp`.
 *
 * Shared-inline overhangs (tail collinear on the parent helix) are skipped —
 * both domains share a helix, so there is no stub root to suppress.
 *
 * NOTE this set is bp-keyed, not strand-keyed, so a bp can be a foot for one
 * strand and a free tip for another — see `_strandTerminusBps`, which wins.
 */
export function _overhangJunctionBps(strands) {
  const out = new Set()
  for (const strand of strands ?? []) {
    const doms = strand.domains ?? []
    for (let i = 0; i < doms.length - 1; i++) {
      const d0 = doms[i], d1 = doms[i + 1]
      if (d0.helix_id === d1.helix_id) continue
      const d0IsOH = d0.overhang_id != null
      const d1IsOH = d1.overhang_id != null
      if (!d0IsOH && d1IsOH) out.add(`${d1.helix_id}:${d1.start_bp}`)
      else if (d0IsOH && !d1IsOH) out.add(`${d0.helix_id}:${d0.end_bp}`)
    }
  }
  return out
}

/**
 * `helixId:bp` for every strand 5'/3' terminus — a real free end of DNA.
 *
 * Overrides the crossover-foot suppression above, because one bp can be both.
 * Two antiparallel overhangs sharing a stub each terminate where the other
 * crosses off (2x2_OH_test: h_XY_2_0 bp 40 and 55 are each one staple's 5' tip
 * and the other's foot), so suppressing on foot-ness alone deletes connectors
 * the user needs.  A terminus is never merely a foot.
 */
export function _strandTerminusBps(strands) {
  const out = new Set()
  for (const strand of strands ?? []) {
    const doms = strand.domains ?? []
    const first = doms[0], last = doms.at(-1)
    if (first?.helix_id != null && first.start_bp != null) out.add(`${first.helix_id}:${first.start_bp}`)
    if (last?.helix_id != null && last.end_bp != null) out.add(`${last.helix_id}:${last.end_bp}`)
  }
  return out
}

/**
 * Per-(helix, polarity) set of covered bp.  Polarity matters: the nick-
 * suppression test below asks "is this terminus flanked by duplex on both
 * sides?", and only a domain of the SAME polarity can continue a strand
 * through a bp.  Keying by helix alone let an overhang's antiparallel binder
 * domain (same helix, same bp range) suppress the tip of the very overhang it
 * binds.
 */
export function _coverageByHelixAndDirection(strands) {
  const cov = new Map()
  for (const strand of strands ?? []) {
    for (const d of strand.domains ?? []) {
      const key = `${d.helix_id}:${d.direction}`
      let s = cov.get(key)
      if (!s) { s = new Set(); cov.set(key, s) }
      const lo = Math.min(d.start_bp, d.end_bp)
      const hi = Math.max(d.start_bp, d.end_bp)
      for (let b = lo; b <= hi; b++) s.add(b)
    }
  }
  return cov
}

// Compute blunt-end + free-strand-terminus + overhang-crossover connectors
// for ONE instance.  Pure given (design, helixAxes, world matrix); used by
// both the legacy per-instance path and the shared-instancing path so the
// "Define Mate" connector candidates are identical regardless of renderer.
// Returns Array<{ instanceId, instanceName, label, worldPos, worldNorm,
// localPos, localNorm, clusterId, clusterIds, isBluntEnd }>.
export function computeInstanceBluntEnds(design, helixAxes, mat4, instId, instName) {
  const TOL = 0.001
  const results = []
  const helices = design?.helices ?? []
  if (!helices.length) return results
  helixAxes = helixAxes ?? {}
  const strands = design?.strands ?? []

  const localEps = {}
  for (const h of helices) {
    const ax = helixAxes[h.id]
    localEps[h.id] = {
      start: ax
        ? new THREE.Vector3(ax.start[0], ax.start[1], ax.start[2])
        : new THREE.Vector3(h.axis_start.x, h.axis_start.y, h.axis_start.z),
      end: ax
        ? new THREE.Vector3(ax.end[0], ax.end[1], ax.end[2])
        : new THREE.Vector3(h.axis_end.x, h.axis_end.y, h.axis_end.z),
    }
  }

  function _isFree(hId, testPos) {
    for (const h of helices) {
      if (h.id === hId) continue
      const ep = localEps[h.id]
      if (ep.start.distanceTo(testPos) < TOL) return false
      if (ep.end.distanceTo(testPos)   < TOL) return false
    }
    return true
  }

  const helixById = new Map(helices.map(h => [h.id, h]))
  const clusterIdsForHelix = helixId => {
    const clusters = design?.cluster_transforms ?? []
    const jointClusterIds = new Set((design?.cluster_joints ?? []).map(j => j.cluster_id).filter(Boolean))
    return clusters
      .filter(c => c.helix_ids?.includes(helixId))
      .sort((a, b) => {
        const aj = jointClusterIds.has(a.id) ? 0 : 1
        const bj = jointClusterIds.has(b.id) ? 0 : 1
        if (aj !== bj) return aj - bj
        const ad = a.is_default ? 1 : 0
        const bd = b.is_default ? 1 : 0
        if (ad !== bd) return ad - bd
        return (a.helix_ids?.length ?? 0) - (b.helix_ids?.length ?? 0)
      })
      .map(c => c.id)
  }

  function _physLen(h) {
    const ax = helixAxes[h.id]
    let nm
    if (ax) {
      const dx = ax.end[0] - ax.start[0], dy = ax.end[1] - ax.start[1], dz = ax.end[2] - ax.start[2]
      nm = Math.sqrt(dx * dx + dy * dy + dz * dz)
    } else {
      const dx = h.axis_end.x - h.axis_start.x, dy = h.axis_end.y - h.axis_start.y, dz = h.axis_end.z - h.axis_start.z
      nm = Math.sqrt(dx * dx + dy * dy + dz * dz)
    }
    return Math.max(1, Math.round(nm / BDNA_RISE_PER_BP) + 1)
  }

  function _posAlongHelix(h, tFrac) {
    const ax = helixAxes[h.id]
    if (ax?.samples?.length >= 2) {
      const n   = ax.samples.length - 1
      const sf  = tFrac * n
      const si  = Math.min(Math.floor(sf), n - 1)
      const sfr = sf - si
      const sA  = new THREE.Vector3(...ax.samples[si])
      const sB  = new THREE.Vector3(...ax.samples[si + 1])
      return { pos: sA.clone().lerp(sB, sfr), dir: sB.clone().sub(sA).normalize() }
    }
    const start3 = ax ? new THREE.Vector3(...ax.start) : new THREE.Vector3(h.axis_start.x, h.axis_start.y, h.axis_start.z)
    const end3   = ax ? new THREE.Vector3(...ax.end)   : new THREE.Vector3(h.axis_end.x,   h.axis_end.y,   h.axis_end.z)
    return { pos: start3.clone().lerp(end3, tFrac), dir: end3.clone().sub(start3).normalize() }
  }

  // Per-domain overhang axis lookup (rotated tip positions).
  // Keyed BOTH by `helixId:bp:overhangId` (exact — several overhangs can share
  // one stub helix at identical bp ranges, and a bare helixId:bp key let the
  // last one silently win, dropping the other's connector onto the wrong shaft)
  // and by bare `helixId:bp` as a first-wins fallback for lookups with no
  // overhang in hand.
  const ovhgBpToPos = new Map()
  const _setOvhg = (key, val) => {
    if (!ovhgBpToPos.has(key)) ovhgBpToPos.set(key, val)
  }
  for (const [hid, ax] of Object.entries(helixAxes)) {
    if (!ax?.ovhgAxes) continue
    for (const [ovhgId, ovhgAx] of Object.entries(ax.ovhgAxes)) {
      const s3  = new THREE.Vector3(...ovhgAx.start)
      const e3  = new THREE.Vector3(...ovhgAx.end)
      const d   = e3.clone().sub(s3)
      const dl  = d.length()
      const dir = dl > 0.001 ? d.clone().divideScalar(dl) : new THREE.Vector3(0, 1, 0)
      // `end` is one rise past bp_max (extent convention) — walk it back to the
      // base itself so the connector sits on the terminal nucleotide.
      const tip = _tipAtBpMax(s3, e3, ovhgAx.bp_min, ovhgAx.bp_max)
      // isBpMin: outward direction at bp_min is -dir (strand exits toward lower bp),
      // at bp_max it is +dir (strand exits toward higher bp).
      const atMin = { pos: s3,  dir, isBpMin: true }
      const atMax = { pos: tip, dir, isBpMin: false }
      ovhgBpToPos.set(`${hid}:${ovhgAx.bp_min}:${ovhgId}`, atMin)
      ovhgBpToPos.set(`${hid}:${ovhgAx.bp_max}:${ovhgId}`, atMax)
      _setOvhg(`${hid}:${ovhgAx.bp_min}`, atMin)
      _setOvhg(`${hid}:${ovhgAx.bp_max}`, atMax)
    }
  }
  // Patch localEps for stubs whose physical endpoints coincide with an ovhgAx
  // bp endpoint.  Remember WHICH entry patched each end: its per-domain
  // direction is the only correct normal for that connector (see below).
  const epPatch = new Map()
  for (const h of helices) {
    const ax = helixAxes[h.id]
    if (!ax?.ovhgAxes) continue
    const bpStart = h.bp_start ?? 0
    const bpEnd   = bpStart + _physLen(h) - 1
    const sOvhg = ovhgBpToPos.get(`${h.id}:${bpStart}`)
    const eOvhg = ovhgBpToPos.get(`${h.id}:${bpEnd}`)
    if (sOvhg) { localEps[h.id].start = sOvhg.pos.clone(); epPatch.set(`${h.id}:start`, sOvhg) }
    if (eOvhg) { localEps[h.id].end   = eOvhg.pos.clone(); epPatch.set(`${h.id}:end`,   eOvhg) }
  }

  const ohJunctionBps = _overhangJunctionBps(strands)
  const strandTipBps  = _strandTerminusBps(strands)

  // ── Free helix endpoints ──────────────────────────────────────────────
  for (const h of helices) {
    const ep = localEps[h.id]
    const bpStart = h.bp_start ?? 0
    const bpEnd   = bpStart + _physLen(h) - 1
    for (const [localPos, isStart] of [[ep.start, true], [ep.end, false]]) {
      if (!_isFree(h.id, localPos)) continue
      // An overhang stub's root is not a blunt end — it is the crossover foot.
      // Unless a strand actually terminates there: on a stub shared by two
      // antiparallel overhangs, each end is one staple's foot AND the other's
      // free 5' tip, and the tip wins.
      const epKey = `${h.id}:${isStart ? bpStart : bpEnd}`
      if (ohJunctionBps.has(epKey) && !strandTipBps.has(epKey)) continue

      const ax = helixAxes[h.id]
      const patch = epPatch.get(`${h.id}:${isStart ? 'start' : 'end'}`)
      let localAxisDir
      let localNorm
      if (patch) {
        // This endpoint's POSITION came from one overhang domain's rotated axis,
        // so its DIRECTION must come from the same domain.  `end - start` would
        // be the line between two independently-rotated domains, and the
        // samples branch reads the shared, un-rotated stub axis — both wrong.
        localAxisDir = patch.dir.clone()
        localNorm    = patch.isBpMin ? localAxisDir.clone().negate() : localAxisDir.clone()
      } else {
        if (ax?.samples?.length >= 2) {
          const n = ax.samples.length
          const s0 = isStart ? ax.samples[0] : ax.samples[n - 2]
          const s1 = isStart ? ax.samples[1] : ax.samples[n - 1]
          localAxisDir = new THREE.Vector3(s1[0] - s0[0], s1[1] - s0[1], s1[2] - s0[2]).normalize()
        } else {
          localAxisDir = ep.end.clone().sub(ep.start).normalize()
        }
        // Outward normal: start → negate (away from helix body), end → along axis
        localNorm = isStart ? localAxisDir.clone().negate() : localAxisDir.clone()
      }
      const worldPos   = localPos.clone().applyMatrix4(mat4)
      const worldNorm  = localNorm.clone().transformDirection(mat4).normalize()
      results.push({
        instanceId: instId, instanceName: instName,
        label: `blunt:${h.id}:${isStart ? 'start' : 'end'}`,
        worldPos: [worldPos.x, worldPos.y, worldPos.z],
        worldNorm: [worldNorm.x, worldNorm.y, worldNorm.z],
        localPos: [localPos.x, localPos.y, localPos.z],
        localNorm: [localNorm.x, localNorm.y, localNorm.z],
        clusterId: clusterIdsForHelix(h.id)[0] ?? null,
        clusterIds: clusterIdsForHelix(h.id),
        isBluntEnd: true,
      })
    }
  }

  // ── Interior overhang strand termini ──────────────────────────────────
  const seenInterior = new Set()
  const _covMap = _coverageByHelixAndDirection(strands)
  for (const strand of strands) {
    const doms = strand.domains ?? []
    const checks = [
      { dom: doms[0],     bp: doms[0]?.start_bp },
      { dom: doms.at(-1), bp: doms.at(-1)?.end_bp },
    ]
    for (const { dom, bp } of checks) {
      const helixId = dom?.helix_id
      if (helixId == null || bp == null) continue
      const h = helixById.get(helixId)
      if (!h) continue
      const key = `${helixId}:${bp}`
      if (seenInterior.has(key)) continue
      const physLen = _physLen(h)
      const localBp = bp - (h.bp_start ?? 0)
      const tArc    = physLen > 1 ? localBp / (physLen - 1) : 0
      if (tArc <= 0 || tArc >= 1) continue
      seenInterior.add(key)
      // Nick suppression: skip if both adjacent bps are covered by the same
      // polarity — no gap between strands, so this is an internal nick.
      // An overhang's free tip is never a nick, however abutted: stubs
      // routinely carry several overhang domains back to back, and the flanking
      // bp belongs to the neighbouring overhang, not to a continuing duplex.
      const isOverhangTip = dom.overhang_id != null
      const _cov = _covMap.get(`${helixId}:${dom.direction}`)
      if (!isOverhangTip && _cov?.has(bp - 1) && _cov?.has(bp + 1)) continue

      // Prefer this domain's OWN overhang entry — several overhangs may share
      // the helix at the same bp.
      const _ovhgPos = (dom.overhang_id != null
        ? ovhgBpToPos.get(`${helixId}:${bp}:${dom.overhang_id}`)
        : null) ?? ovhgBpToPos.get(`${helixId}:${bp}`)
      const { pos: localPos, dir: localAxisDir } = _ovhgPos
        ? { pos: _ovhgPos.pos.clone(), dir: _ovhgPos.dir.clone() }
        : _posAlongHelix(h, tArc)
      // At bp_min the free strand exits in -dir (away from helix body toward lower bp);
      // at bp_max it exits in +dir. Matches the isStart convention in the endpoint section.
      const localNorm = (_ovhgPos?.isBpMin) ? localAxisDir.clone().negate() : localAxisDir.clone()
      const worldPos  = localPos.clone().applyMatrix4(mat4)
      const worldNorm = localNorm.clone().transformDirection(mat4).normalize()
      results.push({
        instanceId: instId, instanceName: instName,
        label: `blunt:${helixId}:bp${bp}`,
        worldPos: [worldPos.x, worldPos.y, worldPos.z],
        worldNorm: [worldNorm.x, worldNorm.y, worldNorm.z],
        localPos: [localPos.x, localPos.y, localPos.z],
        localNorm: [localNorm.x, localNorm.y, localNorm.z],
        clusterId: clusterIdsForHelix(helixId)[0] ?? null,
        clusterIds: clusterIdsForHelix(helixId),
        isBluntEnd: true,
      })
    }
  }

  // ── Overhang crossover junctions on the main helix ────────────────────
  const seenXover = new Set()
  for (const strand of strands) {
    const doms = strand.domains ?? []
    for (let i = 0; i < doms.length - 1; i++) {
      const d0 = doms[i], d1 = doms[i + 1]
      if (d0.helix_id === d1.helix_id) continue
      const d0IsOH = d0.overhang_id != null
      const d1IsOH = d1.overhang_id != null
      let mainHelixId = null, crossBp = null
      if (!d0IsOH && d1IsOH) { mainHelixId = d0.helix_id; crossBp = d0.end_bp }
      else if (d0IsOH && !d1IsOH) { mainHelixId = d1.helix_id; crossBp = d1.start_bp }
      if (mainHelixId == null) continue
      const key = `${mainHelixId}:${crossBp}`
      if (seenXover.has(key) || seenInterior.has(key)) continue
      const h = helixById.get(mainHelixId)
      if (!h) continue
      const physLen = _physLen(h)
      const localBp = crossBp - (h.bp_start ?? 0)
      const tX      = physLen > 1 ? localBp / (physLen - 1) : 0
      if (tX < 0 || tX > 1) continue
      seenXover.add(key)
      const { pos: localPos, dir: localAxisDir } = _posAlongHelix(h, tX)
      const localNorm = localAxisDir.clone()
      const worldPos  = localPos.clone().applyMatrix4(mat4)
      const worldNorm = localNorm.clone().transformDirection(mat4).normalize()
      results.push({
        instanceId: instId, instanceName: instName,
        label: `blunt:${mainHelixId}:bp${crossBp}`,
        worldPos: [worldPos.x, worldPos.y, worldPos.z],
        worldNorm: [worldNorm.x, worldNorm.y, worldNorm.z],
        localPos: [localPos.x, localPos.y, localPos.z],
        localNorm: [localNorm.x, localNorm.y, localNorm.z],
        clusterId: clusterIdsForHelix(mainHelixId)[0] ?? null,
        clusterIds: clusterIdsForHelix(mainHelixId),
        isBluntEnd: true,
      })
    }
  }

  return results
}

/**
 * Convert one backend bend_centers record (instance-LOCAL frame) to a world-frame
 * mate connector record shaped exactly like `computeInstanceBluntEnds()` output.
 * Used by Define-Mate to expose bend center-of-curvature points as pickable
 * connectors (CAD-style "mate two arcs by their circle centers").
 *
 * Moved here verbatim from assembly_renderer.js during that file's split — both
 * render paths called it, and it emits this module's record shape.
 */
export function bendCenterRecordToWorld(bc, mat4, instId, instName) {
  const localPos  = new THREE.Vector3(bc.position[0], bc.position[1], bc.position[2])
  const localNorm = new THREE.Vector3(bc.normal[0],   bc.normal[1],   bc.normal[2]).normalize()
  const worldPos  = localPos.clone().applyMatrix4(mat4)
  const worldNorm = localNorm.clone().transformDirection(mat4).normalize()
  return {
    instanceId:    instId,
    instanceName:  instName,
    instanceLabel: instName,  // dropdown reads .instanceLabel (parity with InterfacePoint records)
    label:         bc.label,
    worldPos:      [worldPos.x,  worldPos.y,  worldPos.z],
    worldNorm:     [worldNorm.x, worldNorm.y, worldNorm.z],
    localPos:      [localPos.x,  localPos.y,  localPos.z],
    localNorm:     [localNorm.x, localNorm.y, localNorm.z],
    clusterId:     bc.cluster_id ?? null,
    clusterIds:    bc.cluster_id ? [bc.cluster_id] : [],
    isBluntEnd:    false,
    isBendCenter:  true,
    bendIndex:     bc.bend_index,
    radiusNm:      bc.radius_nm,
  }
}
