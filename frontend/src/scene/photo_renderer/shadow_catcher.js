/**
 * Photo-mode shadow catcher — a ground plane that shows NOTHING except the
 * shadow that lands on it.
 *
 * Not a floor in the photo-mode-v1 sense. v1 had a visible ground plane (matte /
 * mirror / neon grid) and gated the whole shadow rig behind it, which is exactly
 * why it could never do helix-on-helix shadowing. This is the opposite: a
 * `THREE.ShadowMaterial`, which is transparent everywhere the shadow map says
 * "lit" and only tints where it says "occluded". The structure keeps floating on
 * the flat background; all that appears is its contact shadow. That is the
 * standard figure convention for "this object sits on something", and it is
 * additive to the key shadow rather than a precondition for it.
 *
 * The mesh carries `userData.photoFloor`, which the rest of photo mode already
 * knows about: `swapToFlatMaterials` leaves its material alone, `isShadowExcluded`
 * keeps it out of the fitted shadow frustum and the geometry fingerprint (a plane
 * this large would otherwise set the frustum and put the whole design inside one
 * texel), and `FigurePass._hideNonSurfaces` keeps it out of the silhouette
 * pre-pass so no contour is drawn along the horizon.
 *
 * Display-layer only — reads the fitted bounds, writes nothing back.
 */

import * as THREE from 'three'

/**
 * How far the plane extends, as a multiple of the design's bounding-box
 * diagonal. The key light's shadow frustum is an ortho box of half-width R
 * (the bounding radius) around the design, so no shadow can ever land further
 * than ~R from the centre — anything past that is wasted plane. The diagonal is
 * already ≈2R, so 1.25× covers the whole shadow footprint with margin to spare
 * while keeping the far clip modest.
 */
export const DEFAULT_SIZE_FACTOR = 1.25

/**
 * Which face of the design's bounding box the plane sits against. `-y` is the
 * floor proper; the others turn it into a ceiling or a back wall, which is what
 * you want when the interesting silhouette is not the one cast downward.
 *
 * World axes, not screen axes — deliberately. The key light is camera-pinned, so
 * if the plane were pinned to the screen too there would be no fixed surface for
 * the shadow to sweep across as you orbit, which is the whole effect.
 */
export const FLOOR_AXES = ['-y', '+y', '-x', '+x', '-z', '+z']
export const DEFAULT_FLOOR_AXIS = '-y'

/** '-y' → {key:'y', sign:-1}. Unknown input falls back to the floor. */
export function parseFloorAxis(axis) {
  const a = String(axis ?? '').toLowerCase()
  const key  = a.includes('x') ? 'x' : a.includes('z') ? 'z' : 'y'
  const sign = a.includes('+') ? 1 : -1
  return FLOOR_AXES.includes(`${sign > 0 ? '+' : '-'}${key}`)
    ? { key, sign }
    : { key: 'y', sign: -1 }
}

/**
 * Where the catcher goes for a given set of fitted bounds. Pure — this is the
 * whole placement policy, so it can be asserted without a scene.
 *
 * Auto-fit: centred on the design in the two axes it spans, and flush with the
 * chosen FACE of its bounding box — touching the outermost atom on that side at
 * `offset = 0`. `offset` pushes it further OUT, away from the structure, always:
 * a flush plane gives a hard contact shadow, a pushed-out one gives a detached,
 * softer pool. Positive offset never buries the plane inside the design.
 *
 * The normal points back INWARD, toward the structure — that is the side the
 * shadow arrives from, and `LightShadow.normalBias` offsets along the normal, so
 * an outward-facing plane would bias the wrong way.
 *
 * Uses the bounding BOX, not the sphere: the sphere is orientation-blind, so a
 * long flat platform would put the plane half its length below itself.
 *
 * @param {{box: THREE.Box3, diagonal: number, radius: number}|null} bounds
 *        the object `computeShadowBounds()` returns
 * @param {{offset?: number, sizeFactor?: number, axis?: string}} [opts]
 * @returns {{x:number, y:number, z:number, normal: THREE.Vector3,
 *            axis:string, halfExtent:number, size:number}|null}
 */
export function shadowCatcherPlacement(
  bounds,
  { offset = 0, sizeFactor = DEFAULT_SIZE_FACTOR, axis = DEFAULT_FLOOR_AXIS } = {},
) {
  const box = bounds?.box
  if (!box || box.isEmpty?.()) return null
  const span = bounds.diagonal || 2 * (bounds.radius || 0)
  if (!(span > 0) || !Number.isFinite(span)) return null

  const { key, sign } = parseFloorAxis(axis)
  const gap = Number.isFinite(offset) ? offset : 0
  const halfExtent = span * (sizeFactor > 0 ? sizeFactor : DEFAULT_SIZE_FACTOR)

  // Centre of the box on every axis, then slide the chosen one out to the face.
  const pos = {
    x: (box.min.x + box.max.x) / 2,
    y: (box.min.y + box.max.y) / 2,
    z: (box.min.z + box.max.z) / 2,
  }
  pos[key] = (sign < 0 ? box.min[key] : box.max[key]) + sign * gap

  const normal = new THREE.Vector3()
  normal[key] = -sign

  return {
    ...pos,
    normal,
    axis: `${sign > 0 ? '+' : '-'}${key}`,
    halfExtent,
    size: halfExtent * 2,
  }
}

/**
 * Own the catcher mesh's lifetime in `scene`.
 *
 * @param {THREE.Scene} scene
 * @returns {{update: Function, remove: Function, getReach: Function,
 *            getMesh: Function, invalidate: Function}}
 */
export function createShadowCatcher(scene) {
  let _mesh      = null
  let _placement = null
  const UP = new THREE.Vector3(0, 1, 0)   // the baked geometry normal

  function _ensure() {
    if (_mesh) return _mesh
    // The lie-flat rotation is baked into the geometry rather than set on the
    // mesh, so the mesh quaternion is free to carry the chosen face's normal and
    // `scale` still maps onto the plane's own two axes.
    const geo = new THREE.PlaneGeometry(1, 1)
    geo.rotateX(-Math.PI / 2)
    // DoubleSide: the plane can be a ceiling or a back wall, and a front-facing
    // plane seen from behind would be culled away entirely.
    const mat = new THREE.ShadowMaterial({ transparent: true, opacity: 1, side: THREE.DoubleSide })
    // An unlit region of the plane must not occlude anything, and depth-writing
    // overlays are precisely what `isShadowExcluded` uses to spot editor
    // geometry. Keeping it false also keeps the plane out of the depth buffer
    // the silhouette and depth cue read.
    mat.depthWrite = false
    _mesh = new THREE.Mesh(geo, mat)
    _mesh.name = 'photoFloor'
    _mesh.userData.photoFloor = true
    // Receives, never casts: a plane this size would shadow the entire scene,
    // and there is nothing below it to shadow anyway.
    _mesh.castShadow    = false
    _mesh.receiveShadow = true
    // Drawn before the structure so its transparency composites underneath.
    _mesh.renderOrder = -1
    scene.add(_mesh)
    return _mesh
  }

  /**
   * Reposition/resize for the current bounds, or drop the mesh when disabled.
   *
   * @param {object|null} bounds — from computeShadowBounds()
   * @param {{enabled?:boolean, opacity?:number, offset?:number, sizeFactor?:number}} settings
   * @returns {object|null} the placement in use, or null
   */
  function update(bounds, { enabled = false, opacity = 0.35, offset = 0, sizeFactor, axis } = {}) {
    const p = enabled ? shadowCatcherPlacement(bounds, { offset, sizeFactor, axis }) : null
    if (!p) { remove(); return null }
    const mesh = _ensure()
    mesh.position.set(p.x, p.y, p.z)
    // Geometry normal is +Y; swing it onto the chosen face's inward normal.
    // setFromUnitVectors handles the exactly-antiparallel case (+y → -y, i.e. a
    // ceiling) by picking a perpendicular axis itself.
    mesh.quaternion.setFromUnitVectors(UP, p.normal)
    mesh.scale.set(p.size, 1, p.size)
    mesh.material.opacity = Math.max(0, Math.min(1, opacity))
    mesh.updateMatrixWorld(true)
    _placement = p
    return p
  }

  /** Mark for recompile — `renderer.shadowMap.enabled` is baked into the
   *  program and three never re-checks it (same reason the mode force-recompiles
   *  its physical materials when the key shadow is toggled). */
  function invalidate() {
    if (_mesh) _mesh.material.needsUpdate = true
  }

  function remove() {
    if (!_mesh) return
    scene.remove(_mesh)
    _mesh.geometry.dispose()
    _mesh.material.dispose()
    _mesh = null
    _placement = null
  }

  /**
   * World centre + half-extent, for `main.js`'s adaptive camera clipping: the
   * far plane has to reach past the catcher or it gets cropped to a small square
   * near the content, which is what made photo mode v1's "infinite" floor look
   * small in assembly mode.
   *
   * @returns {{center: THREE.Vector3, reach: number}|null}
   */
  function getReach() {
    if (!_mesh || !_placement) return null
    return {
      center: new THREE.Vector3(_placement.x, _placement.y, _placement.z),
      // Half-DIAGONAL of the square, not its half-width — the corner is the
      // furthest point and the corner is what gets clipped first.
      reach: _placement.halfExtent * Math.SQRT2,
    }
  }

  return { update, remove, getReach, invalidate, getMesh: () => _mesh }
}
