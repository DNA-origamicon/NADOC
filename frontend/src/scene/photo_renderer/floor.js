/**
 * Photo mode — resting-surface "floor" plane.
 *
 * A configurable ground plane that can sit on any of six axis-aligned sides
 * (±X, ±Y, ±Z) of the scene's bounding box. Supports five material modes:
 *   - matte / glossy / metallic  → MeshPhysicalMaterial (PBR)
 *   - mirror                     → three Reflector (real per-frame reflection)
 *   - shadow-catcher             → ShadowMaterial (transparent except where lit)
 *
 * Also draws an optional grid overlay (THREE.GridHelper re-oriented to the
 * chosen axis) and exposes the world-space bounding box used for plane
 * placement so the caller can fit directional-light shadow cameras to it.
 *
 * Usage:
 *   const floor = createFloor({ scene })
 *   floor.build(settings)            // (re)build with current settings
 *   floor.dispose()                  // tear down on photo-mode exit
 */

import * as THREE from 'three'
import { Reflector } from 'three/addons/objects/Reflector.js'

// Each axis maps to the outward-pointing plane normal. '-y' means the floor
// is BELOW the scene with its visible face pointing UP (+Y).
const AXIS_NORMALS = {
  '-y': new THREE.Vector3( 0,  1,  0),
  '+y': new THREE.Vector3( 0, -1,  0),
  '-x': new THREE.Vector3( 1,  0,  0),
  '+x': new THREE.Vector3(-1,  0,  0),
  '-z': new THREE.Vector3( 0,  0,  1),
  '+z': new THREE.Vector3( 0,  0, -1),
}

const FLOOR_GROUP_NAME = 'photoFloor'
const FLOOR_MESH_NAME  = 'photoFloorMesh'
const FLOOR_GRID_NAME  = 'photoFloorGrid'

// The plane is sized to run past the camera's render horizon at any sane
// framing → reads as infinite. It extends at least this many bbox-diameters,
// AND never less than ABSOLUTE_MIN_REACH nm, so even a tiny structure still
// gets a floor that reaches the far-clip plane (part-mode far clip = 2000 nm,
// see main.js). The far clip itself crops the floor into a distant horizon.
const INFINITE_FACTOR = 80
const ABSOLUTE_MIN_REACH = 4000   // nm (half-extent 2000 ≈ part-mode far clip)
// Cap on grid line subdivisions so a very dense grid over the huge plane can't
// explode the line count. At the cap the effective cell gets coarser than
// requested rather than spawning hundreds of thousands of segments. 4000 keeps
// the whole density slider exact for typical (tens-of-nm) structures.
const MAX_GRID_DIVISIONS = 4000

export function createFloor({ scene }) {
  let _group = null
  let _mesh  = null   // either a Mesh (PBR/Shadow) or a Reflector
  let _grid  = null
  let _lastBBox = null
  let _lastReach  = 0      // world half-extent of the plane (planeSize / 2)
  let _lastCenter = null   // world-space plane centre (for camera far-clip fit)

  // Walk the scene and tally a Box3 over everything that should "rest on" the
  // floor. Excludes: photo helper groups, additive blending sprites, lines,
  // and the floor itself.
  function _computeSceneBBox() {
    const box = new THREE.Box3()
    let any = false
    scene.traverse(obj => {
      if (!obj.isMesh && !obj.isInstancedMesh) return
      if (!obj.visible) return
      if (obj.material?.isLineBasicMaterial || obj.material?.isLineDashedMaterial) return
      if (obj.material?.blending === THREE.AdditiveBlending) return

      // Skip anything under photo helper groups (lights / floor / fluoro).
      let p = obj.parent
      let underHelper = false
      while (p) {
        if (p.name === 'photoLights' || p.name === FLOOR_GROUP_NAME || p.name === 'photoFluoroLights') {
          underHelper = true; break
        }
        p = p.parent
      }
      if (underHelper) return

      const tmp = new THREE.Box3().setFromObject(obj)
      if (Number.isFinite(tmp.min.x) && Number.isFinite(tmp.max.x) && !tmp.isEmpty()) {
        box.union(tmp)
        any = true
      }
    })
    return any ? box : null
  }

  function _makeMaterial(settings) {
    const op = settings.floorOpacity ?? 1.0
    const color = new THREE.Color(settings.floorColor ?? '#888888')

    if (settings.floorMaterial === 'shadow-catcher') {
      return new THREE.ShadowMaterial({
        color: 0x000000,
        opacity: op,
        transparent: true,
      })
    }

    const params = {
      matte:    { roughness: 1.0, metalness: 0.0 },
      glossy:   { roughness: 0.25, metalness: 0.0, clearcoat: 1.0, clearcoatRoughness: 0.08 },
      metallic: { roughness: 0.15, metalness: 1.0 },
    }[settings.floorMaterial] ?? { roughness: 1.0, metalness: 0.0 }

    return new THREE.MeshPhysicalMaterial({
      color, ...params,
      opacity: op,
      transparent: op < 1,
      side: THREE.DoubleSide,
    })
  }

  function _disposeChildren() {
    if (_mesh) {
      _mesh.geometry?.dispose?.()
      // Reflector exposes a dispose() that cleans up its render target.
      if (typeof _mesh.dispose === 'function') _mesh.dispose()
      _mesh.material?.dispose?.()
      _mesh = null
    }
    if (_grid) {
      _grid.geometry?.dispose?.()
      _grid.material?.dispose?.()
      _grid = null
    }
  }

  function dispose() {
    _disposeChildren()
    if (_group) {
      scene.remove(_group)
      _group = null
    }
    _lastBBox = null
    _lastReach = 0
    _lastCenter = null
  }

  // (Re)build the floor from the given settings snapshot. Returns the scene
  // bounding box used so the caller can fit shadow cameras to it.
  function build(settings) {
    dispose()
    if (!settings.floor || settings.floor === 'off') return null

    const bbox = _computeSceneBBox()
    if (!bbox) return null
    _lastBBox = bbox

    const size      = bbox.getSize(new THREE.Vector3())
    const center    = bbox.getCenter(new THREE.Vector3())
    const diameter  = Math.max(size.length(), 1.0)
    // Effectively-infinite plane: large enough to reach the camera's far-clip
    // horizon at any framing. (The old per-floor "Size" slider was replaced by
    // the grid-density control below.)
    const planeSize = Math.max(diameter * INFINITE_FACTOR, ABSOLUTE_MIN_REACH)
    _lastReach  = planeSize * 0.5
    _lastCenter = center.clone()

    _group = new THREE.Group()
    _group.name = FLOOR_GROUP_NAME
    _group.userData.photoFloor = true
    scene.add(_group)

    // Position the floor at the bbox face on the chosen axis, then push out
    // along the outward normal by `floorOffset` (in scene units = nm).
    const axis     = settings.floor
    const normal   = AXIS_NORMALS[axis]
    const offset   = settings.floorOffset ?? 0
    const position = new THREE.Vector3()
    switch (axis) {
      case '-y': position.set(center.x, bbox.min.y - offset, center.z); break
      case '+y': position.set(center.x, bbox.max.y + offset, center.z); break
      case '-x': position.set(bbox.min.x - offset, center.y, center.z); break
      case '+x': position.set(bbox.max.x + offset, center.y, center.z); break
      case '-z': position.set(center.x, center.y, bbox.min.z - offset); break
      case '+z': position.set(center.x, center.y, bbox.max.z + offset); break
      default:   position.copy(center)
    }

    const planeGeo = new THREE.PlaneGeometry(planeSize, planeSize)

    if (settings.floorMaterial === 'mirror') {
      _mesh = new Reflector(planeGeo, {
        clipBias: 0.003,
        textureWidth:  Math.min(window.innerWidth  * (window.devicePixelRatio ?? 1), 2048),
        textureHeight: Math.min(window.innerHeight * (window.devicePixelRatio ?? 1), 2048),
        color: new THREE.Color(settings.floorColor ?? '#888888'),
      })
    } else {
      const mat = _makeMaterial(settings)
      _mesh = new THREE.Mesh(planeGeo, mat)
    }

    // PlaneGeometry's default normal is +Z. Rotate so it points along `normal`.
    const defaultNormal = new THREE.Vector3(0, 0, 1)
    const q = new THREE.Quaternion().setFromUnitVectors(defaultNormal, normal)
    _mesh.quaternion.copy(q)
    _mesh.position.copy(position)
    _mesh.receiveShadow = !!settings.floorShadows
    _mesh.castShadow    = false
    _mesh.name          = FLOOR_MESH_NAME
    _mesh.userData.photoFloor = true
    _group.add(_mesh)

    // Optional GridHelper. Default plane is XZ (normal=+Y); re-orient to match.
    if (settings.floorGrid) {
      // Grid density = number of cells per bbox diameter → cell size =
      // diameter / density (nm). Subdivisions = planeSize / cellSize, capped so
      // a fine grid over the huge plane can't explode the line count. Higher
      // slider = finer grid.
      const density   = Math.max(0.5, settings.floorGridDensity ?? 10)
      const cellSize  = diameter / density
      const divisions = Math.min(
        MAX_GRID_DIVISIONS,
        Math.max(4, Math.round(planeSize / cellSize)),
      )
      // Neon mode: HDR-boost the grid colour so Bloom catches it as a glow.
      // GridHelper stores per-vertex colours, and three's LineBasicMaterial
      // honours values >1 when `toneMapped` is false — they reach the bloom
      // high-pass intact and bloom into a halo.
      const neon = !!settings.floorGridNeon
      const boost = neon ? (settings.floorGridGlow ?? 3.0) : 1.0
      const primaryHex = neon
        ? (settings.floorGridColor ?? '#ff00ff')
        : 0x666666
      const secondaryHex = neon
        ? (settings.floorGridColor ?? '#ff00ff')   // both lines same colour in neon
        : 0x3a3a3a
      const primary   = new THREE.Color(primaryHex).multiplyScalar(boost)
      const secondary = new THREE.Color(secondaryHex).multiplyScalar(neon ? boost * 0.6 : 1.0)
      _grid = new THREE.GridHelper(planeSize, divisions, primary, secondary)
      _grid.material.transparent = true
      _grid.material.opacity     = neon ? 1.0 : 0.5
      _grid.material.depthWrite  = false
      _grid.material.toneMapped  = !neon   // off in neon so HDR magnitudes survive
      const gridDefaultNormal = new THREE.Vector3(0, 1, 0)
      const gq = new THREE.Quaternion().setFromUnitVectors(gridDefaultNormal, normal)
      _grid.quaternion.copy(gq)
      // Lift slightly off the floor along the normal to avoid z-fighting.
      const lift = normal.clone().multiplyScalar(diameter * 0.0008)
      _grid.position.copy(position).add(lift)
      _grid.name = FLOOR_GRID_NAME
      _grid.userData.photoFloor = true
      _grid.castShadow    = false
      _grid.receiveShadow = false
      _group.add(_grid)
    }

    return { bbox, center, diameter, position, normal: normal.clone() }
  }

  function getLastBBox() { return _lastBBox }
  function getMesh()     { return _mesh }
  function isActive()    { return _mesh != null }
  // World-space reach of the floor plane so the caller can extend the camera's
  // far clip to include it (otherwise the far clip crops the floor near the
  // content — especially in assembly mode where far brackets the content tight).
  function getReach() {
    return _mesh ? { center: _lastCenter, reach: _lastReach } : null
  }

  return { build, dispose, getLastBBox, getMesh, isActive, getReach }
}
