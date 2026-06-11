/**
 * Selection bounding-box extracted from main.js (parameterized: geometry + the
 * selected id sets are arguments, so this is pure). Unit-tested in
 * selection_bbox.test.js.
 */
import * as THREE from 'three'

/**
 * THREE.Box3 around the backbone of the current selection, or null if nothing is
 * selected / no geometry matches.
 * @param {Array} geom  nucleotide geometry ({strand_id, domain_id, backbone_position:[x,y,z]})
 * @param {object} sel  { strandIds:Set, domainIds:Set, selStrandId:string|null }
 */
export function selectionBBox(geom, { strandIds = new Set(), domainIds = new Set(), selStrandId = null } = {}) {
  if (!geom?.length) return null
  if (!strandIds.size && !domainIds.size && !selStrandId) return null
  const box = new THREE.Box3()
  let count = 0
  for (const n of geom) {
    const hit = (strandIds.size && strandIds.has(n.strand_id))
      || (domainIds.size && domainIds.has(n.domain_id))
      || (selStrandId && n.strand_id === selStrandId)
    if (!hit) continue
    const [x, y, z] = n.backbone_position
    if (count === 0) box.set(new THREE.Vector3(x, y, z), new THREE.Vector3(x, y, z))
    else             box.expandByPoint(new THREE.Vector3(x, y, z))
    count++
  }
  return count > 0 ? box : null
}

/**
 * Union AABB (THREE.Box3) of the assembly instance centers whose id is in
 * `wanted`, or null if none match / all matches are sizeless / the union is
 * empty. Each center is `{ id, center: THREE.Vector3, size: {x,y,z} }` (the
 * shape returned by `assemblyRenderer.getInstanceCenters()`). Pure — geometry
 * + selection in, box out. Used for the multi-select / active-group purple
 * union BoxHelper.
 * @param {Array} centers  instance centers ({id, center:Vector3, size:{x,y,z}})
 * @param {Set}   wanted   instance ids to include in the union
 */
export function instanceUnionBox(centers, wanted) {
  if (!centers?.length || !wanted || wanted.size === 0) return null
  const union = new THREE.Box3(); union.makeEmpty()
  let count = 0
  for (const c of centers) {
    if (!wanted.has(c.id) || !c.size) continue
    const half = new THREE.Vector3(c.size.x * 0.5, c.size.y * 0.5, c.size.z * 0.5)
    union.expandByPoint(c.center.clone().sub(half))
    union.expandByPoint(c.center.clone().add(half))
    count++
  }
  return count > 0 && !union.isEmpty() ? union : null
}

/**
 * Local-space AABB (THREE.Box3) over every positioned nucleotide backbone, or
 * null if none are positioned. Unlike a per-helix or LOD-cylinder *chord* box
 * (endpoint-to-endpoint), this follows the ACTUAL geometry — including a bend
 * deformation that curves a helix between its two endpoints — so a bent (arc)
 * part is bounded correctly instead of collapsing in the bulge direction. Pure:
 * nucleotides in, box out. This is the source of `instBoundingBox` for the
 * shared assembly renderer (the part / group selection box). Includes overhang
 * nucleotides so protruding overhangs stay inside the box.
 * @param {Array} nucleotides  [{ backbone_position:[x,y,z], ... }]
 */
export function nucleotideLocalBox(nucleotides) {
  if (!nucleotides?.length) return null
  const box = new THREE.Box3()
  const v = new THREE.Vector3()
  let n = 0
  for (const nuc of nucleotides) {
    const p = nuc?.backbone_position
    if (!p) continue
    box.expandByPoint(v.set(p[0], p[1], p[2])); n++
  }
  return n > 0 && !box.isEmpty() ? box : null
}

/**
 * Largest distance any nucleotide backbone lies OUTSIDE `box` — 0 when every
 * nucleotide is contained. Optional `transform` (THREE.Matrix4) is applied to
 * each backbone position first: pass an instance matrix to validate a placed
 * part, or a group-member matrix to validate against a world-space union box.
 *
 * This is the geometry-fits-its-box validation: a positive return means the
 * selection box fails to bound the visible geometry (the bent-part chord-box
 * bug this guards against). `tol` (nm) is the allowed slack before a point
 * counts as outside.
 * @param {Array} nucleotides
 * @param {THREE.Box3} box
 * @param {{ transform?: THREE.Matrix4, tol?: number }} [opts]
 * @returns {number} worst overflow distance in nm (0 if all contained within tol)
 */
export function nucleotideBoxOverflow(nucleotides, box, { transform = null, tol = 0 } = {}) {
  if (!nucleotides?.length || !box || box.isEmpty()) return 0
  const v = new THREE.Vector3()
  let worst = 0
  for (const nuc of nucleotides) {
    const p = nuc?.backbone_position
    if (!p) continue
    v.set(p[0], p[1], p[2])
    if (transform) v.applyMatrix4(transform)
    const d = box.distanceToPoint(v)        // 0 when inside, else nearest-face distance
    if (d > worst) worst = d
  }
  return worst > tol ? worst : 0
}
