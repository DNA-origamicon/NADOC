/**
 * glow_layer.js — Radioactive green glow halo for selected strands.
 *
 * Renders a second InstancedMesh of spheres at each selected backbone bead
 * position using additive blending and a semi-transparent green material.
 * The underlying bead color is completely unchanged; the glow sits on top
 * as a separate draw call.
 */

import * as THREE        from 'three'
import { BEAD_RADIUS }   from './helix_renderer.js'

const GLOW_SCALE   = 2.8        // glow sphere radius relative to BEAD_RADIUS
const GLOW_OPACITY = 0.45

const _geo   = new THREE.SphereGeometry(BEAD_RADIUS, 8, 6)
const _dummy = new THREE.Object3D()

export function createGlowLayer(scene, color = 0x3fb950) {
  const mat = new THREE.MeshBasicMaterial({
    color,
    transparent: true,
    opacity:     GLOW_OPACITY,
    blending:    THREE.AdditiveBlending,
    depthWrite:  false,
  })
  let mesh = new THREE.InstancedMesh(_geo, mat, 1)
  mesh.count       = 0
  mesh.renderOrder = 1   // draw after the main geometry so additive blending composites correctly
  mesh.frustumCulled = false
  scene.add(mesh)

  function _ensureCapacity(needed) {
    if (needed <= mesh.instanceMatrix.count) return
    scene.remove(mesh)
    mesh = new THREE.InstancedMesh(_geo, mat, needed)
    mesh.count       = 0
    mesh.renderOrder = 1
    mesh.frustumCulled = false
    scene.add(mesh)
  }

  return {
    /** Position glow spheres over the given backbone entries. */
    setEntries(entries) {
      const count = entries.length
      _ensureCapacity(count)
      for (let i = 0; i < count; i++) {
        _dummy.position.copy(entries[i].pos)
        _dummy.scale.setScalar(GLOW_SCALE)
        _dummy.updateMatrix()
        mesh.setMatrixAt(i, _dummy.matrix)
      }
      mesh.count = count
      mesh.instanceMatrix.needsUpdate = true
    },

    /** Hide all glow spheres. */
    clear() {
      if (mesh.count === 0) return
      mesh.count = 0
      mesh.instanceMatrix.needsUpdate = true
    },

    dispose() {
      scene.remove(mesh)
    },
  }
}
