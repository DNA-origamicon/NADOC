import * as THREE from 'three'
import { initAtomisticRenderer } from './atomistic_renderer.js'

/** Render imported PDB atoms once, sharing GPU geometry across rigid tetramers.
 * A cloned prototype shares immutable geometry/material/instance buffers. Each
 * tetramer moves as a group, so atom AND bond transforms remain identical.
 */
export function createStreptavidinAtomicRenderer(parent, coating) {
  const root = new THREE.Group(); root.name = 'streptavidin-atoms'
  parent.add(root)
  const prototype = new THREE.Group()
  const renderer = initAtomisticRenderer(prototype)
  const atoms = coating.protein.atoms.map((a, serial) => ({
    serial, name: a.name, element: a.element, residue: a.res_name,
    chain_id: a.chain_id, seq_num: a.res_seq,
    x: a.x, y: a.y, z: a.z,
    strand_id: `__strep__${a.chain_id}`, helix_id: `__strep__${a.chain_id}`, bp_index: a.res_seq, direction: 'FORWARD',
  }))
  // Analytic sphere impostors preserve radii/depth with two triangles per atom.
  // Dense PDB coatings otherwise add millions of sphere triangles. The global
  // ?impostors=0 diagnostic override still selects the standard mesh path.
  renderer.update({ atoms, bonds: coating.protein.bonds ?? [], sphereImpostors: true, unitSphereImpostors: true })
  let mode = 'off'
  const restPoses = coating.poses.map(p => new THREE.Matrix4().fromArray(p.values).transpose())
  const groups = restPoses.map(pose => {
    const group = new THREE.Group()
    group.matrixAutoUpdate = false; group.matrix.copy(pose)
    root.add(group)
    return group
  })
  let currentPrototype = []
  function syncInstances() {
    if (currentPrototype.length === prototype.children.length && currentPrototype.every((m, i) => m === prototype.children[i])) return
    currentPrototype = [...prototype.children]
    for (const group of groups) {
      for (const child of group.children) child.dispose?.()
      group.clear()
      for (const original of currentPrototype) {
        // Object3D.clone copies instance buffers. Share them explicitly: coating
        // atoms never deform individually in this native rigid representation.
        const instance = original.isInstancedMesh
          ? new THREE.InstancedMesh(original.geometry, original.material, 0)
          : new THREE.Mesh(original.geometry, original.material)
        if (original.isInstancedMesh) {
          instance.count = original.count
          instance.instanceMatrix = original.instanceMatrix
          instance.instanceColor = original.instanceColor
          instance.morphTexture = original.morphTexture
          instance.boundingBox = original.boundingBox
          instance.boundingSphere = original.boundingSphere
        }
        instance.name = original.name
        instance.userData = { ...original.userData }
        instance.frustumCulled = false
        instance.raycast = () => {} // particle owns selection/manipulation
        group.add(instance)
      }
    }
  }
  return {
    root, atomCount: atoms.length * coating.poses.length,
    bondCount: (coating.protein.bonds?.length ?? 0) * coating.poses.length,
    setMode(next) {
      const atomic = ['vdw', 'ballstick', 'stick'].includes(next) ? next : 'off'
      root.visible = atomic !== 'off'
      if (atomic === 'off' || atomic === mode) return
      mode = atomic
      renderer.setMode(mode)
      syncInstances()
    },
    applyTransforms(deltas) {
      groups.forEach((group, i) => {
        group.matrix.copy(deltas[i] ?? new THREE.Matrix4()).multiply(restPoses[i])
        group.matrixWorldNeedsUpdate = true
      })
    },
    dispose() {
      root.removeFromParent()
      for (const group of groups) for (const child of group.children) child.dispose?.()
      root.clear()
      renderer.dispose()
    },
  }
}
