import * as THREE from 'three'

/**
 * Freeze visible preview meshes into a scene-level optimistic transaction.
 *
 * The clones share immutable geometry with their sources but own their pending
 * materials. Their world transforms are baked onto a root-level group, so tool
 * panels and temporary coordinate frames may disappear while backend work runs.
 * `settle()` is deliberately idempotent and never disposes shared geometry.
 */
export function freezeOptimisticPreview(scene, sourceMeshes, {
  name = 'optimistic-operation-pending',
  color = 0x00e5ff,
  // Opaque enough to read as the committed operation immediately, while the
  // cyan tint still communicates that canonical nucleotide detail is pending.
  opacity = 0.78,
  renderOrder = 5,
} = {}) {
  const group = new THREE.Group()
  group.name = name

  for (const source of sourceMeshes ?? []) {
    if (!source?.visible || !source.geometry) continue
    source.updateWorldMatrix?.(true, false)
    const material = source.material?.clone?.() ?? new THREE.MeshBasicMaterial()
    material.color?.setHex?.(color)
    material.transparent = true
    material.opacity = opacity
    material.depthWrite = false

    const mesh = new THREE.Mesh(source.geometry, material)
    mesh.renderOrder = renderOrder
    source.matrixWorld.decompose(mesh.position, mesh.quaternion, mesh.scale)
    group.add(mesh)
  }

  if (group.children.length) scene.add(group)
  let active = group.children.length > 0
  return {
    group,
    get active() { return active },
    settle() {
      if (!active) return
      active = false
      scene.remove(group)
      for (const child of group.children) child.material?.dispose?.()
      group.clear()
    },
  }
}
