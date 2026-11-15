import * as THREE from 'three'
import { isVisibleChain } from '../base_pick.js'

const boundsVersions = new WeakMap()

/** Pick displayed atom spheres / bond cylinders, retaining nucleotide identity. */
export function pickAtomistic(state, raycaster) {
  if (state.mode === 'off') return null
  const meshes = state.mode === 'stick' ? [] : Object.values(state.elementMeshes)
  if (state.bondMesh) meshes.push(state.bondMesh)
  const visible = meshes.filter(mesh => mesh.parent && isVisibleChain(mesh))
  for (const mesh of visible) {
    mesh.updateWorldMatrix(true, false)
    // InstancedMesh caches bounds, but live frames and transforms move instances.
    if (boundsVersions.get(mesh) !== mesh.instanceMatrix.version) {
      mesh.computeBoundingSphere()
      boundsVersions.set(mesh, mesh.instanceMatrix.version)
    }
  }
  for (const hit of raycaster.intersectObjects(visible, false)) {
    const mesh = hit.object
    const alpha = mesh.geometry.getAttribute('instanceAlpha')?.getX(hit.instanceId) ?? 1
    if (alpha * mesh.material.opacity < 0.02) continue
    const planes = mesh.material.clippingPlanes ?? []
    if (planes.length && (mesh.material.clipIntersection
      ? planes.every(p => p.distanceToPoint(hit.point) < 0)
      : planes.some(p => p.distanceToPoint(hit.point) < 0))) continue
    let row
    if (mesh === state.bondMesh) {
      // Cylinder local y runs from endpoint a (-0.5) to endpoint b (+0.5).
      // Use the live instance transform, including assembly/world transforms.
      const matrix = new THREE.Matrix4()
      mesh.getMatrixAt(hit.instanceId, matrix)
      matrix.premultiply(mesh.matrixWorld).invert()
      const endpoint = hit.point.clone().applyMatrix4(matrix).y > 0 ? 1 : 0
      row = state.bondAtomIdx[hit.instanceId * 2 + endpoint]
    } else {
      row = state.elementAtoms[mesh.userData.element]?.[hit.instanceId]
    }
    if (row !== undefined) return { atom: state.atoms.materialize(row), distance: hit.distance }
  }
  return null
}
