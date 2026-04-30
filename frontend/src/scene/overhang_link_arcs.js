/**
 * Overhang Link Arcs.
 *
 * Draws a white tube arc in 3D for every entry in design.overhang_connections.
 * The arc anchors at the LINKER complement strand (`__lnk__<conn>__a` / `__b`),
 * not at the overhang itself — it emerges from the freshly-paired complement
 * nucleotide that sits at the user-specified attach end of the overhang.
 *
 * Pure visualisation — no interaction in v1.
 *
 * Usage:
 *   const arcs = initOverhangLinkArcs(scene)
 *   arcs.rebuild(design, geometry)
 *   arcs.dispose()
 */

import * as THREE from 'three'

const ARC_COLOR        = 0xffffff
const ARC_TUBE_RADIUS  = 0.30   // nm — visibly thicker than backbone beads (0.10)
const ARC_TUBE_SEGS    = 48
const ARC_TUBE_RADSEG  = 10
const ARC_HEIGHT_FRAC  = 0.30   // Bézier control offset = chord_length × this, perpendicular to chord
const DEBUG = true   // logs to console when rebuild runs; toggle off when stable

export function initOverhangLinkArcs(scene) {
  const group = new THREE.Group()
  group.name = 'overhangLinkArcs'
  scene.add(group)

  function rebuild(design, geometry) {
    _clear()
    if (!design || !geometry) {
      if (DEBUG) console.debug('[overhangLinkArcs] skip rebuild — design=%o geometry=%o', !!design, !!geometry)
      return
    }
    // geometry from the store is the bare nucleotides array, not a wrapped object.
    const nucs = Array.isArray(geometry) ? geometry : (geometry.nucleotides ?? [])
    const conns = design.overhang_connections ?? []
    if (DEBUG) console.debug('[overhangLinkArcs] rebuild: %d connection(s), %d nucs in geometry', conns.length, nucs.length)
    if (conns.length === 0) return
    const nucsByOvhg   = _indexNucsByOverhang(nucs)
    const nucsByStrand = _indexNucsByStrand(nucs)

    for (const conn of conns) {
      const a = _linkerAttachPos(nucsByOvhg, nucsByStrand, conn.id, 'a',
                                 conn.overhang_a_id, conn.overhang_a_attach)
      const b = _linkerAttachPos(nucsByOvhg, nucsByStrand, conn.id, 'b',
                                 conn.overhang_b_id, conn.overhang_b_attach)
      if (!a || !b) {
        if (DEBUG) console.debug('[overhangLinkArcs] conn %s: missing positions  a=%o  b=%o', conn.name ?? conn.id, !!a, !!b)
        continue
      }
      if (DEBUG) console.debug('[overhangLinkArcs] conn %s: arc from (%s,%s,%s) to (%s,%s,%s)',
        conn.name ?? conn.id,
        a.x.toFixed(2), a.y.toFixed(2), a.z.toFixed(2),
        b.x.toFixed(2), b.y.toFixed(2), b.z.toFixed(2))
      const mesh = _makeArcMesh(a, b)
      mesh.userData.connId = conn.id
      group.add(mesh)
    }
    if (DEBUG) console.debug('[overhangLinkArcs] rebuild done — group has %d children', group.children.length)
  }

  function dispose() {
    _clear()
    if (group.parent) group.parent.remove(group)
  }

  function _clear() {
    while (group.children.length) {
      const m = group.children[0]
      group.remove(m)
      m.geometry?.dispose?.()
      m.material?.dispose?.()
    }
  }

  return { rebuild, dispose, group }
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function _indexNucsByOverhang(nucs) {
  const map = new Map()
  for (const n of nucs) {
    if (!n.overhang_id) continue
    let arr = map.get(n.overhang_id)
    if (!arr) { arr = []; map.set(n.overhang_id, arr) }
    arr.push(n)
  }
  return map
}

function _indexNucsByStrand(nucs) {
  const map = new Map()
  for (const n of nucs) {
    if (!n.strand_id) continue
    let arr = map.get(n.strand_id)
    if (!arr) { arr = []; map.set(n.strand_id, arr) }
    arr.push(n)
  }
  return map
}

function _vec3(p) {
  return p ? new THREE.Vector3(p[0], p[1], p[2]) : null
}

/**
 * Find the OH nucleotide that sits at the user-chosen attach end:
 *   free_end → the strand-terminal nucleotide (5'/3' tip of the overhang).
 *   root     → the OH nucleotide farthest from the tip in bp space
 *              (= the one nearest the bundle junction).
 * Returns the nuc object (so we can read both its position and bp_index), or
 * null if the OH has no nucs in geometry yet.
 */
function _ohAttachNuc(nucsByOvhg, ovhgId, attach) {
  const nucs = nucsByOvhg.get(ovhgId)
  if (!nucs || nucs.length === 0) return null
  const tip = nucs.find(n => n.is_five_prime || n.is_three_prime) ?? nucs[0]
  if (attach !== 'root' || nucs.length < 2) return tip
  let target = tip, bestDist = -1
  for (const n of nucs) {
    const d = Math.abs((n.bp_index ?? 0) - (tip.bp_index ?? 0))
    if (d > bestDist) { bestDist = d; target = n }
  }
  return target
}

/**
 * Anchor position for one side of the arc, picked off the LINKER complement
 * strand rather than the overhang itself.
 *
 * Strategy: locate the OH nucleotide at the chosen attach end (helix_id +
 * bp_index); then find the linker complement nucleotide at the same helix
 * and bp (the antiparallel partner). The arc thus emerges from the linker
 * strand bead instead of the overhang bead.
 *
 * Falls back to the OH nucleotide position when the linker strand has no
 * geometry (e.g. synthetic test seed where the OverhangSpec lacks a backing
 * domain), so the arc still draws something useful.
 */
function _linkerAttachPos(nucsByOvhg, nucsByStrand, connId, side, ovhgId, attach) {
  const ohNuc = _ohAttachNuc(nucsByOvhg, ovhgId, attach)
  if (!ohNuc) return null

  const linkerStrandId = `__lnk__${connId}__${side}`
  const linkerNucs = nucsByStrand.get(linkerStrandId) ?? []
  // Match the linker complement nuc at the same (helix_id, bp_index).
  // Direction differs (antiparallel), which is exactly why the linker strand
  // produces a separate bead at this position — the arc attaches there.
  const partner = linkerNucs.find(n =>
    n.helix_id === ohNuc.helix_id && n.bp_index === ohNuc.bp_index
  )
  return _vec3((partner ?? ohNuc).backbone_position ?? (partner ?? ohNuc).base_position)
}

function _makeArcMesh(a, b) {
  const chord = b.clone().sub(a)
  const len   = chord.length() || 1
  // Pick a perpendicular: cross with +Z (or +X if chord is parallel to Z) to
  // get a stable arc plane. Bend the curve away from the structure.
  const up = new THREE.Vector3(0, 0, 1)
  let perp = chord.clone().cross(up)
  if (perp.lengthSq() < 1e-6) perp = chord.clone().cross(new THREE.Vector3(1, 0, 0))
  perp.normalize().multiplyScalar(len * ARC_HEIGHT_FRAC)
  const mid = a.clone().add(b).multiplyScalar(0.5).add(perp)

  const curve = new THREE.QuadraticBezierCurve3(a, mid, b)
  const tube  = new THREE.TubeGeometry(curve, ARC_TUBE_SEGS, ARC_TUBE_RADIUS, ARC_TUBE_RADSEG, false)
  const mat   = new THREE.MeshBasicMaterial({ color: ARC_COLOR, transparent: true, opacity: 0.85 })
  return new THREE.Mesh(tube, mat)
}
