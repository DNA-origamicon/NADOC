/**
 * scene/md_overlay.js — P-atom bead overlay for "Beads Only" MD mode.
 *
 * Creates an InstancedMesh of spheres, one per P atom in the trajectory.
 * Positions are in nm (NADOC world frame, centroid-corrected by the backend).
 *
 * Usage:
 *   const mdOverlay = initMdOverlay(scene)
 *   mdOverlay.update(positions, beadRadius, opacity)   // positions: [{x,y,z}] nm
 *   mdOverlay.setOpacity(v)
 *   mdOverlay.dispose()
 */

import * as THREE from 'three'

const _DEFAULT_RADIUS  = 0.15   // nm — roughly P-atom VDW radius
const _DEFAULT_COLOR   = 0x58a6ff
const _SEG_W           = 8
const _SEG_H           = 6

// Shared base geometry (unit sphere, scaled per-instance via matrix)
const _BASE_GEO = new THREE.SphereGeometry(1, _SEG_W, _SEG_H)
const _dummy    = new THREE.Object3D()

export function initMdOverlay(scene) {
  let _mesh    = null
  let _count   = 0
  let _radius  = _DEFAULT_RADIUS
  let _mat     = null

  function _buildMesh(n, radius, opacity) {
    if (_mesh) {
      scene.remove(_mesh)
      _mesh.material.dispose()
      _mesh.dispose()
      _mesh = null
    }
    if (n === 0) return

    _mat = new THREE.MeshStandardMaterial({
      color: _DEFAULT_COLOR,
      transparent: opacity < 1.0,
      opacity,
      roughness: 0.5,
      metalness: 0.1,
    })

    _mesh = new THREE.InstancedMesh(_BASE_GEO, _mat, n)
    _mesh.frustumCulled = false
    _mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage)
    scene.add(_mesh)
    _count  = n
    _radius = radius
  }

  return {
    /**
     * Set or update P-atom bead positions.
     *
     * @param {Array<{x:number, y:number, z:number}>} positions  nm, NADOC frame
     * @param {number} beadRadius  nm
     * @param {number} opacity     0–1
     */
    update(positions, beadRadius = _DEFAULT_RADIUS, opacity = 1.0) {
      const n = positions.length
      if (n !== _count || Math.abs(beadRadius - _radius) > 1e-6) {
        _buildMesh(n, beadRadius, opacity)
      }
      if (!_mesh) return

      for (let i = 0; i < n; i++) {
        const p = positions[i]
        _dummy.position.set(p.x, p.y, p.z)
        _dummy.scale.setScalar(beadRadius)
        _dummy.updateMatrix()
        _mesh.setMatrixAt(i, _dummy.matrix)
      }
      _mesh.instanceMatrix.needsUpdate = true

      if (_mat && Math.abs(_mat.opacity - opacity) > 1e-6) {
        _mat.opacity     = opacity
        _mat.transparent = opacity < 1.0
        _mat.needsUpdate = true
      }
    },

    setOpacity(v) {
      if (!_mat) return
      _mat.opacity     = v
      _mat.transparent = v < 1.0
      _mat.needsUpdate = true
    },

    dispose() {
      if (_mesh) {
        scene.remove(_mesh)
        _mesh.material.dispose()
        _mesh.dispose()
        _mesh  = null
        _count = 0
      }
    },
  }
}
