import * as THREE from 'three'

/** Bounded world-space obstacles from the actual guest buffers, including moving atoms. */
export function createSharedAnnotationOccupancy(scene) {
  const matrix = new THREE.Matrix4(), sphere = new THREE.Sphere()
  const limit = 4096
  return () => {
    const meshes = []
    let count = 0
    scene.traverseVisible(object => {
      // Annotation highlights and selection points/sprites are not structure.
      if (!object.isMesh || !object.geometry) return
      meshes.push(object); count += object.isInstancedMesh ? object.count : 1
    })
    const stride = Math.max(1, Math.ceil(count / limit)), discs = []
    let offset = 0
    for (const object of meshes) {
      const geometry = object.geometry
      if (!geometry.boundingSphere) geometry.computeBoundingSphere()
      if (!geometry.boundingSphere) continue
      const size = object.isInstancedMesh ? object.count : 1
      for (let i = (stride - offset % stride) % stride; i < size; i += stride) {
        if (object.isInstancedMesh) { object.getMatrixAt(i, matrix); matrix.premultiply(object.matrixWorld) }
        else matrix.copy(object.matrixWorld)
        sphere.copy(geometry.boundingSphere).applyMatrix4(matrix)
        if (!Number.isFinite(sphere.radius) || sphere.radius <= 0) continue
        discs.push({ x: sphere.center.x, y: sphere.center.y, z: sphere.center.z, radius: sphere.radius })
      }
      offset += size
    }
    return discs
  }
}
