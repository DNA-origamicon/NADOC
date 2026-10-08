import * as THREE from 'three'

/** A temporary helix-path view, independent of topology and editable renderers. */
export function createFeatureSeekPreview(scene) {
  return function showPreview({ helix_axes = [], transform: worldTransform }) {
    const segments = []
    for (const axis of helix_axes) {
      const points = axis.samples?.length > 1 ? axis.samples : [axis.start, axis.end]
      for (let i = 1; i < points.length; i++) {
        if (points[i - 1]?.length === 3 && points[i]?.length === 3) segments.push([points[i - 1], points[i]])
      }
    }
    const root = new THREE.Group()
    root.name = 'feature-seek-preview'
    root.userData.displayOnly = true
    if (worldTransform?.length === 16) {
      root.matrix.fromArray(worldTransform).transpose()
      root.matrixAutoUpdate = false
    }
    const geometry = new THREE.CylinderGeometry(0.8, 0.8, 1, 6)
    const material = new THREE.MeshBasicMaterial({ color: 0x58a6ff })
    const mesh = new THREE.InstancedMesh(geometry, material, segments.length)
    const transform = new THREE.Object3D(), up = new THREE.Vector3(0, 1, 0)
    const a = new THREE.Vector3(), b = new THREE.Vector3(), delta = new THREE.Vector3()
    segments.forEach(([start, end], i) => {
      a.fromArray(start); b.fromArray(end); delta.subVectors(b, a)
      transform.position.copy(a).add(b).multiplyScalar(0.5)
      transform.scale.set(1, delta.length(), 1)
      transform.quaternion.setFromUnitVectors(up, delta.lengthSq() ? delta.normalize() : up)
      transform.updateMatrix()
      mesh.setMatrixAt(i, transform.matrix)
    })
    mesh.instanceMatrix.needsUpdate = true
    root.add(mesh)
    // Keep lights/cameras. Hide existing renderable roots so the previous stage
    // cannot be mistaken for part of the preview. Restore their exact visibility.
    const hidden = []
    for (const child of scene.children) {
      let renderable = false
      child.traverse(node => { if (node.isMesh || node.isLine || node.isPoints) renderable = true })
      if (renderable && child.visible) { hidden.push(child); child.visible = false }
    }
    scene.add(root)
    let cleared = false
    return () => {
      if (cleared) return
      cleared = true
      scene.remove(root)
      for (const child of hidden) child.visible = true
      geometry.dispose(); material.dispose()
    }
  }
}
