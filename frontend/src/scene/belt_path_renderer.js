/**
 * belt_path_renderer.js — persistent rendering of stored belt paths.
 *
 * Draws a glowing tube per BeltPath (one mesh + halo each), computed from the
 * belt's stored pulley geometry (cached center_world + radius + the joint axis).
 * Visibility is per-belt (driven by a hidden-id set) plus a global suppress flag
 * used while the define/edit panel is open (the panel shows its own live preview).
 *
 * Display-only. Geometry is rebuilt on demand (belt create/edit/delete) — it is
 * static while pulleys spin (a belt's wrap shape doesn't change as pulleys turn),
 * but uses cached centers, so moving a part requires re-editing the belt to
 * refresh, mirroring the cached-advisory-geometry model elsewhere.
 */
import * as THREE from 'three'
import { computeBeltPath } from './belt_geometry.js'

const BELT_COLOUR = 0x3fb950
const TUBE_RADIUS = 0.7
const HALO_RADIUS = 1.5

export function initBeltPathRenderer(scene) {
  const group = new THREE.Group()
  group.name = 'beltPaths'
  scene.add(group)

  const coreMat = new THREE.MeshBasicMaterial({
    color: BELT_COLOUR, transparent: true, opacity: 0.8,
    blending: THREE.AdditiveBlending, depthWrite: false,
  })
  const haloMat = new THREE.MeshBasicMaterial({
    color: BELT_COLOUR, transparent: true, opacity: 0.16,
    blending: THREE.AdditiveBlending, depthWrite: false,
  })

  function _clear() {
    for (const child of [...group.children]) {
      group.remove(child)
      child.geometry?.dispose()
    }
  }

  /**
   * @param {object|null} assembly
   * @param {object} opts  { hiddenIds: Set<string>, suppress: boolean }
   */
  function rebuild(assembly, { hiddenIds = new Set(), suppress = false } = {}) {
    _clear()
    if (suppress || !assembly) return
    const joints = new Map((assembly.joints ?? []).map(j => [j.id, j]))
    for (const belt of (assembly.belt_paths ?? [])) {
      if (hiddenIds.has(belt.id)) continue
      const pa = belt.pulley_a, pb = belt.pulley_b
      const ja = joints.get(pa?.joint_id), jb = joints.get(pb?.joint_id)
      if (!ja || !jb || !pa.center_world || !pb.center_world) continue
      const res = computeBeltPath(
        { center: new THREE.Vector3(...pa.center_world), radius: pa.radius, axisDir: ja.axis_direction },
        { center: new THREE.Vector3(...pb.center_world), radius: pb.radius, axisDir: jb.axis_direction },
      )
      if (res.error || !res.points?.length) continue
      const curve = new THREE.CatmullRomCurve3(res.points, true)
      const segs  = Math.max(16, res.points.length * 2)
      for (const [r, mat] of [[HALO_RADIUS, haloMat], [TUBE_RADIUS, coreMat]]) {
        const mesh = new THREE.Mesh(new THREE.TubeGeometry(curve, segs, r, 8, true), mat)
        mesh.renderOrder = 1
        mesh.frustumCulled = false
        mesh.userData.beltId = belt.id
        group.add(mesh)
      }
    }
  }

  return {
    rebuild,
    setVisible(v) { group.visible = v },
    dispose() {
      _clear()
      coreMat.dispose()
      haloMat.dispose()
      scene.remove(group)
    },
  }
}
