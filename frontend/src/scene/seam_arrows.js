/**
 * Periodic-boundary seam arrows — glowing yellow arrows in the 3D view marking
 * forced ligations that close an end-to-end polymerization seam.
 *
 * A seam ligation connects a far-end 3' terminus to a near-end 5' terminus, so
 * the arrow spans the structure from the 3' endpoint to the 5' endpoint,
 * pointing in the direction of backbone continuity (3' → 5' across the junction).
 *
 * RULE (mirrors crossover_connections.js): no topology reasoning. The
 * ForcedLigation record's `is_periodic_seam` flag is the single source of truth;
 * look up the two endpoint nucleotides by key and draw the arrow. The flag is set
 * mechanically in the 2D editor when the ligation is made across the periodic
 * boundary mirror — never inferred from geometry here.
 *
 * Returns a Group in the design's LOCAL coordinate frame (no transform applied),
 * so the single-design view adds it to the design root and the assembly view adds
 * it to each instance group — both inherit the correct transform for free.
 *
 * Geometries + materials are allocated PER CALL (not module singletons): both the
 * single-design renderer (_disposeRoot) and the assembly renderer dispose every
 * geometry/material in the group on teardown, so shared singletons would be
 * disposed out from under other instances. Seam ligations are few, so per-call
 * allocation is cheap.
 */

import * as THREE from 'three'

const ARROW_COLOR  = 0xffe000   // bright "glowing" yellow
const SHAFT_RADIUS = 0.16       // nm
const HEAD_RADIUS  = 0.45       // nm
const HEAD_LEN     = 1.1        // nm
const HALO_SCALE   = 2.4        // radius multiplier for the soft glow shell

const _UP = new THREE.Vector3(0, 1, 0)

/** Build one arrow (bright core + soft halo) from `a` (3') to `b` (5') using the
 *  shared per-call geometries/materials in `kit`. */
function _makeArrow(a, b, kit) {
  const arrow = new THREE.Group()
  const dir = new THREE.Vector3().subVectors(b, a)
  const len = dir.length()
  if (len < 1e-6) return arrow
  dir.divideScalar(len)
  const quat = new THREE.Quaternion().setFromUnitVectors(_UP, dir)
  const shaftLen = Math.max(0.01, len - HEAD_LEN)

  for (const [shaftGeo, headGeo, mat] of [
    [kit.shaft, kit.head, kit.core],
    [kit.shaftHalo, kit.headHalo, kit.halo],
  ]) {
    const shaft = new THREE.Mesh(shaftGeo, mat)
    shaft.scale.set(1, shaftLen, 1)
    shaft.quaternion.copy(quat)
    shaft.position.copy(a)
    arrow.add(shaft)

    const head = new THREE.Mesh(headGeo, mat)
    head.quaternion.copy(quat)
    head.position.copy(a).addScaledVector(dir, shaftLen)
    arrow.add(head)
  }
  return arrow
}

/**
 * Build a Group of glowing yellow arrows for every is_periodic_seam forced
 * ligation in `design`, using `nucleotides` (instance-local backbone positions)
 * to locate the endpoints. Returns null when there are no seam ligations or none
 * resolve to known nucleotides.
 */
export function buildSeamArrows(design, nucleotides) {
  const fls = (design?.forced_ligations ?? []).filter(f => f.is_periodic_seam)
  if (!fls.length || !nucleotides?.length) return null

  const nucMap = new Map()
  for (const n of nucleotides) nucMap.set(`${n.helix_id}:${n.bp_index}:${n.direction}`, n)

  // Per-call geometry/material kit (unit shaft along +Y, base at origin; cone head).
  // Unlit bright materials read as "glowing" regardless of scene lighting/bloom.
  const kit = {
    shaft:     new THREE.CylinderGeometry(SHAFT_RADIUS, SHAFT_RADIUS, 1, 12).translate(0, 0.5, 0),
    head:      new THREE.ConeGeometry(HEAD_RADIUS, HEAD_LEN, 16).translate(0, HEAD_LEN / 2, 0),
    shaftHalo: new THREE.CylinderGeometry(SHAFT_RADIUS * HALO_SCALE, SHAFT_RADIUS * HALO_SCALE, 1, 12).translate(0, 0.5, 0),
    headHalo:  new THREE.ConeGeometry(HEAD_RADIUS * HALO_SCALE, HEAD_LEN, 16).translate(0, HEAD_LEN / 2, 0),
    core:      new THREE.MeshBasicMaterial({ color: ARROW_COLOR }),
    halo:      new THREE.MeshBasicMaterial({ color: ARROW_COLOR, transparent: true, opacity: 0.22, depthWrite: false }),
  }

  const group = new THREE.Group()
  group.name = 'seamArrows'
  for (const fl of fls) {
    const nucA = nucMap.get(`${fl.three_prime_helix_id}:${fl.three_prime_bp}:${fl.three_prime_direction}`)
    const nucB = nucMap.get(`${fl.five_prime_helix_id}:${fl.five_prime_bp}:${fl.five_prime_direction}`)
    if (!nucA || !nucB) continue
    group.add(_makeArrow(
      new THREE.Vector3(...nucA.backbone_position),
      new THREE.Vector3(...nucB.backbone_position),
      kit,
    ))
  }
  if (!group.children.length) {
    // No endpoints resolved — dispose the unused kit so we don't leak.
    for (const g of [kit.shaft, kit.head, kit.shaftHalo, kit.headHalo]) g.dispose()
    kit.core.dispose(); kit.halo.dispose()
    return null
  }
  return group
}
