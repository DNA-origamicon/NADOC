/**
 * scene/mrdna_connections.js — CG bond overlay for the mrDNA "CG beads" mode.
 *
 * Draws the coarse ARBD connectivity (backbone chain + crossover links) as thin
 * cylinder STICKS through the bead cloud (an InstancedMesh, one cylinder per bond),
 * so the CG-beads representation reads as beads-and-sticks rather than a loose
 * point cloud.  Cylinders (not GL lines) so the bonds have real, zoom-stable
 * thickness and are lit like the beads.
 *
 * Usage:
 *   const conn = initMrdnaConnections(scene)
 *   conn.update(points, edges)   // points: [{x,y,z}] nm; edges: [[i,j], …]
 *   conn.clear()
 */

import * as THREE from 'three'

const _COLOR      = 0xcdd8ee   // pale blue-grey — contrasts with the blue beads
const _RADIUS_NM  = 0.13       // stick radius

// Unit cylinder aligned along +Y (height 1), scaled per-instance to each bond.
const _BASE_GEO = new THREE.CylinderGeometry(1, 1, 1, 6, 1)
const _Y = new THREE.Vector3(0, 1, 0)
const _a = new THREE.Vector3()
const _b = new THREE.Vector3()
const _mid = new THREE.Vector3()
const _dir = new THREE.Vector3()
const _quat = new THREE.Quaternion()
const _scale = new THREE.Vector3()
const _m = new THREE.Matrix4()

export function initMrdnaConnections(scene) {
  let _mesh = null
  let _mat = null

  function clear() {
    if (_mesh) {
      scene.remove(_mesh)
      _mat?.dispose()
      _mesh.dispose()
      _mesh = null
      _mat = null
    }
  }

  return {
    /**
     * Rebuild the stick InstancedMesh from bead points + edge index pairs.
     * @param {Array<{x:number,y:number,z:number}>} points  nm, NADOC frame
     * @param {Array<[number,number]>} edges  index pairs into `points`
     */
    update(points, edges) {
      clear()
      if (!points?.length || !edges?.length) return

      _mat = new THREE.MeshStandardMaterial({ color: _COLOR, roughness: 0.6, metalness: 0.05 })
      _mesh = new THREE.InstancedMesh(_BASE_GEO, _mat, edges.length)
      _mesh.frustumCulled = false
      _mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage)

      let n = 0
      for (let e = 0; e < edges.length; e++) {
        const p = points[edges[e][0]]
        const q = points[edges[e][1]]
        if (!p || !q) continue
        _a.set(p.x, p.y, p.z)
        _b.set(q.x, q.y, q.z)
        _dir.subVectors(_b, _a)
        const len = _dir.length()
        if (len < 1e-6) continue
        _dir.divideScalar(len)
        _mid.addVectors(_a, _b).multiplyScalar(0.5)
        _quat.setFromUnitVectors(_Y, _dir)
        _scale.set(_RADIUS_NM, len, _RADIUS_NM)
        _m.compose(_mid, _quat, _scale)
        _mesh.setMatrixAt(n++, _m)
      }
      _mesh.count = n
      _mesh.instanceMatrix.needsUpdate = true
      scene.add(_mesh)
    },

    clear,
  }
}
