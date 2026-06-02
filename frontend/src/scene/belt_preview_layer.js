/**
 * Belt preview layer — a glowing tube drawn along the belt-path polyline.
 *
 * Display-only overlay used while the user is defining a belt path. Mirrors the
 * additive-blend glow style of glow_layer.js. Rebuilds its geometry on every
 * `setPath()`; `clear()`/`dispose()` remove it from the scene.
 */
import * as THREE from 'three'

const BELT_COLOUR  = 0x3fb950 // green, matches the assembly active-ring / glow colour
const TUBE_RADIUS  = 0.7      // nm (scene unit = 1 nm)
const HALO_RADIUS  = 1.5      // fatter, lower-opacity halo
const RADIAL_SEGS  = 8

export function createBeltPreviewLayer(scene) {
  const group = new THREE.Group()
  group.name = 'beltPreview'
  group.renderOrder = 1
  group.frustumCulled = false
  scene.add(group)

  const coreMat = new THREE.MeshBasicMaterial({
    color: BELT_COLOUR, transparent: true, opacity: 0.85,
    blending: THREE.AdditiveBlending, depthWrite: false,
  })
  const haloMat = new THREE.MeshBasicMaterial({
    color: BELT_COLOUR, transparent: true, opacity: 0.18,
    blending: THREE.AdditiveBlending, depthWrite: false,
  })

  let _core = null
  let _halo = null

  function _disposeMeshes() {
    for (const m of [_core, _halo]) {
      if (!m) continue
      group.remove(m)
      m.geometry?.dispose()
    }
    _core = null
    _halo = null
  }

  return {
    /**
     * @param {THREE.Vector3[]|null} points  closed-loop polyline, or null/empty to clear.
     */
    setPath(points) {
      _disposeMeshes()
      if (!points || points.length < 3) return
      const curve = new THREE.CatmullRomCurve3(points, true)
      const segs  = Math.max(16, points.length * 2)
      const coreGeo = new THREE.TubeGeometry(curve, segs, TUBE_RADIUS, RADIAL_SEGS, true)
      const haloGeo = new THREE.TubeGeometry(curve, segs, HALO_RADIUS, RADIAL_SEGS, true)
      _core = new THREE.Mesh(coreGeo, coreMat)
      _halo = new THREE.Mesh(haloGeo, haloMat)
      for (const m of [_halo, _core]) { m.renderOrder = 1; m.frustumCulled = false; group.add(m) }
    },
    clear() { _disposeMeshes() },
    dispose() {
      _disposeMeshes()
      coreMat.dispose()
      haloMat.dispose()
      scene.remove(group)
    },
  }
}
