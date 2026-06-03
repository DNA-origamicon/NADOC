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
