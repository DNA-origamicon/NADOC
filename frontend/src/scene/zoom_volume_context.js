import * as THREE from 'three'
import { baseKey } from './base_ref.js'
import { nanoparticlePoseMatrix } from './nanoparticle_display.js'

/** Keep the camera fitted to the selection; context occupies its immediate neighborhood. */
export function zoomContextBounds(selectionBounds) {
  return selectionBounds.clone().expandByScalar(Math.max(3, selectionBounds.getSize(new THREE.Vector3()).length() * .2))
}

export function nearbyZoomEntries(entries, selectedKeys, bounds, matrix = new THREE.Matrix4()) {
  const point = new THREE.Vector3()
  return entries.filter(e => !selectedKeys.has(baseKey(e.nuc, e.nuc.copy_k ?? 0))
    && bounds.containsPoint(point.copy(e.pos).applyMatrix4(matrix)))
}

export function nearbyZoomExternalRefs(design, atoms, selectedRefs, bounds, matrix = new THREE.Matrix4()) {
  const selected = new Set(selectedRefs.map(ref => `${ref.kind}:${ref.id}`)), refs = []
  for (const particle of design.nanoparticles ?? []) {
    if (selected.has(`nanoparticle:${particle.id}`)) continue
    const radius = particle.diameter_nm / 2
    const box = new THREE.Box3(new THREE.Vector3(-radius, -radius, -radius), new THREE.Vector3(radius, radius, radius))
      .applyMatrix4(nanoparticlePoseMatrix(particle)).applyMatrix4(matrix)
    if (bounds.intersectsBox(box)) refs.push({ kind: 'nanoparticle', id: particle.id })
  }
  const proteinBounds = new Map()
  for (const atom of atoms ?? []) {
    if (!atom.helix_id?.startsWith('__protein__')) continue
    const id = atom.helix_id.slice(11)
    if (selected.has(`protein:${id}`)) continue
    if (!proteinBounds.has(id)) proteinBounds.set(id, new THREE.Box3())
    proteinBounds.get(id).expandByPoint(new THREE.Vector3(atom.x, atom.y, atom.z).applyMatrix4(matrix))
  }
  for (const [id, box] of proteinBounds) if (bounds.intersectsBox(box)) refs.push({ kind: 'protein', id })
  return refs
}

/** Context transparency never changes the selection's materials or requires a rebuild. */
export function setZoomContextOpacity(root, opacity) {
  root.visible = opacity > 0
  root.traverse(object => {
    for (const material of Array.isArray(object.material) ? object.material : object.material ? [object.material] : []) {
      material.opacity = opacity
      material.transparent = true
      // Translucent neighbors must not write an opaque depth mask over the selection.
      material.depthWrite = false
    }
  })
}
