import { describe, it, expect } from 'vitest'
import * as THREE from 'three'
import {
  shadowCatcherPlacement,
  createShadowCatcher,
  parseFloorAxis,
  DEFAULT_SIZE_FACTOR,
  DEFAULT_FLOOR_AXIS,
  FLOOR_AXES,
} from './shadow_catcher.js'
import { isShadowExcluded } from './shadow_bounds.js'

/** Stand-in for what computeShadowBounds() returns. */
function boundsFor(min, max) {
  const box = new THREE.Box3(new THREE.Vector3(...min), new THREE.Vector3(...max))
  const sphere = box.getBoundingSphere(new THREE.Sphere())
  return {
    box,
    center: sphere.center,
    radius: sphere.radius,
    diagonal: box.getSize(new THREE.Vector3()).length(),
    corners: [],
  }
}

describe('shadowCatcherPlacement', () => {
  it('centres under the design in X/Z and sits flush with the bottom of the box', () => {
    const p = shadowCatcherPlacement(boundsFor([-10, 4, 20], [30, 12, 60]))
    expect(p.x).toBeCloseTo(10, 6)     // (-10 + 30) / 2
    expect(p.z).toBeCloseTo(40, 6)     // ( 20 + 60) / 2
    expect(p.y).toBeCloseTo(4, 6)      // box.min.y — the lowest point, not the centre
  })

  it('offset pushes the plane OUTWARD, never into the structure', () => {
    const b = boundsFor([0, 5, 0], [10, 15, 10])
    expect(shadowCatcherPlacement(b, { offset: 0 }).y).toBeCloseTo(5, 6)
    expect(shadowCatcherPlacement(b, { offset: 3 }).y).toBeCloseTo(2, 6)
    // On the +Y face "outward" is UP, so the same positive offset must raise it.
    expect(shadowCatcherPlacement(b, { axis: '+y', offset: 0 }).y).toBeCloseTo(15, 6)
    expect(shadowCatcherPlacement(b, { axis: '+y', offset: 3 }).y).toBeCloseTo(18, 6)
  })

  it('sits against whichever bbox FACE the axis names, centred on the other two', () => {
    const b = boundsFor([-10, 4, 20], [30, 12, 60])
    const cases = {
      '-y': { y: 4,  x: 10, z: 40 },
      '+y': { y: 12, x: 10, z: 40 },
      '-x': { x: -10, y: 8, z: 40 },
      '+x': { x: 30,  y: 8, z: 40 },
      '-z': { z: 20, x: 10, y: 8 },
      '+z': { z: 60, x: 10, y: 8 },
    }
    for (const [axis, want] of Object.entries(cases)) {
      const p = shadowCatcherPlacement(b, { axis })
      for (const [k, v] of Object.entries(want)) {
        expect(p[k], `${axis}.${k}`).toBeCloseTo(v, 6)
      }
      expect(p.axis).toBe(axis)
    }
  })

  it('points its normal INWARD, at the structure', () => {
    // LightShadow.normalBias offsets along the normal, so an outward-facing
    // plane biases the sample the wrong way.
    for (const axis of FLOOR_AXES) {
      const { key, sign } = parseFloorAxis(axis)
      const n = shadowCatcherPlacement(boundsFor([0, 0, 0], [10, 10, 10]), { axis }).normal
      expect(n[key], axis).toBeCloseTo(-sign, 6)
      expect(n.length()).toBeCloseTo(1, 6)
    }
  })

  it('falls back to the floor for a missing or malformed axis', () => {
    const b = boundsFor([0, 5, 0], [10, 15, 10])
    expect(DEFAULT_FLOOR_AXIS).toBe('-y')
    for (const bad of [undefined, null, '', 'up', 'y', '±q']) {
      expect(shadowCatcherPlacement(b, { axis: bad }).axis, String(bad)).toBe('-y')
    }
  })

  it('parseFloorAxis splits sign from axis and never returns garbage', () => {
    expect(parseFloorAxis('+x')).toEqual({ key: 'x', sign: 1 })
    expect(parseFloorAxis('-z')).toEqual({ key: 'z', sign: -1 })
    expect(parseFloorAxis('nonsense')).toEqual({ key: 'y', sign: -1 })
  })

  it('spans the whole shadow footprint: half-extent exceeds the bounding radius', () => {
    // The key light's ortho shadow frustum is half-width R about the centre, so
    // no shadow can land further than R away. A catcher narrower than that would
    // clip the shadow at its edge.
    const b = boundsFor([-50, 0, -50], [50, 20, 50])
    const p = shadowCatcherPlacement(b)
    expect(p.halfExtent).toBeGreaterThan(b.radius)
    expect(p.halfExtent).toBeCloseTo(b.diagonal * DEFAULT_SIZE_FACTOR, 6)
    expect(p.size).toBeCloseTo(p.halfExtent * 2, 6)
  })

  it('uses the BOX, not the sphere — a flat wide platform stays flush under itself', () => {
    // The sphere of a 400×4×400 platform has radius ~283, so a sphere-based
    // placement would park the plane ~280 nm below a 4 nm-thick object.
    const b = boundsFor([-200, 0, -200], [200, 4, 200])
    expect(shadowCatcherPlacement(b).y).toBeCloseTo(0, 6)
    expect(b.radius).toBeGreaterThan(100)
  })

  it('returns null for absent, empty or degenerate bounds', () => {
    expect(shadowCatcherPlacement(null)).toBe(null)
    expect(shadowCatcherPlacement({})).toBe(null)
    expect(shadowCatcherPlacement({ box: new THREE.Box3() })).toBe(null)
    expect(shadowCatcherPlacement(boundsFor([1, 1, 1], [1, 1, 1]))).toBe(null)
  })

  it('scales with the design — a 10× bigger structure gets a 10× bigger plane', () => {
    const small = shadowCatcherPlacement(boundsFor([0, 0, 0], [10, 10, 10]))
    const big   = shadowCatcherPlacement(boundsFor([0, 0, 0], [100, 100, 100]))
    expect(big.halfExtent / small.halfExtent).toBeCloseTo(10, 6)
  })
})

/** The plane's normal in WORLD space, through its full transform. */
function worldNormal(mesh) {
  const na = mesh.geometry.getAttribute('normal')
  return new THREE.Vector3(na.getX(0), na.getY(0), na.getZ(0))
    .applyMatrix3(new THREE.Matrix3().getNormalMatrix(mesh.matrixWorld))
    .normalize()
}

describe('createShadowCatcher', () => {
  const BOUNDS = boundsFor([-10, 0, -10], [10, 20, 10])

  it('adds nothing while disabled', () => {
    const scene = new THREE.Scene()
    const c = createShadowCatcher(scene)
    c.update(BOUNDS, { enabled: false })
    expect(c.getMesh()).toBe(null)
    expect(scene.children).toHaveLength(0)
  })

  it('builds a horizontal plane that receives but never casts', () => {
    const scene = new THREE.Scene()
    const c = createShadowCatcher(scene)
    c.update(BOUNDS, { enabled: true, opacity: 0.4 })

    const mesh = c.getMesh()
    expect(scene.children).toContain(mesh)
    expect(mesh.receiveShadow).toBe(true)
    // A plane this size would shadow the entire scene if it cast.
    expect(mesh.castShadow).toBe(false)
    expect(mesh.material.isShadowMaterial).toBe(true)
    expect(mesh.material.opacity).toBeCloseTo(0.4, 6)
    // depthWrite:false — it must not occlude, and it must stay out of the depth
    // buffer the silhouette/depth-cue pass reads.
    expect(mesh.material.depthWrite).toBe(false)

    // Normal points straight up in world space (the lie-flat rotation is baked
    // into the geometry, so scaling X/Z cannot skew it).
    expect(worldNormal(mesh).y).toBeCloseTo(1, 5)
  })

  it('swings the mesh onto every face, including the antiparallel ceiling case', () => {
    // (0,1,0) → (0,-1,0) is the degenerate input for setFromUnitVectors; getting
    // it wrong leaves a NaN quaternion and the plane vanishes.
    const scene = new THREE.Scene()
    const c = createShadowCatcher(scene)
    for (const axis of FLOOR_AXES) {
      c.update(BOUNDS, { enabled: true, axis })
      const { key, sign } = parseFloorAxis(axis)
      const n = worldNormal(c.getMesh())
      expect(n[key], axis).toBeCloseTo(-sign, 4)
      expect(Number.isNaN(n.x + n.y + n.z), axis).toBe(false)
    }
  })

  it('a ceiling sits above the design and a wall beside it', () => {
    const scene = new THREE.Scene()
    const c = createShadowCatcher(scene)
    c.update(BOUNDS, { enabled: true, axis: '+y' })
    expect(c.getMesh().position.y).toBeCloseTo(20, 6)     // box.max.y
    c.update(BOUNDS, { enabled: true, axis: '-x' })
    expect(c.getMesh().position.x).toBeCloseTo(-10, 6)    // box.min.x
    expect(c.getMesh().position.y).toBeCloseTo(10, 6)     // centred in Y now
  })

  it('an unknown axis leaves the plane a floor rather than dropping it', () => {
    const scene = new THREE.Scene()
    const c = createShadowCatcher(scene)
    c.update(BOUNDS, { enabled: true, axis: 'sideways' })
    expect(c.getMesh()).not.toBe(null)
    expect(worldNormal(c.getMesh()).y).toBeCloseTo(1, 4)
  })

  it('carries userData.photoFloor, so every existing photo-mode skip-list catches it', () => {
    const scene = new THREE.Scene()
    const c = createShadowCatcher(scene)
    c.update(BOUNDS, { enabled: true })
    const mesh = c.getMesh()
    expect(mesh.userData.photoFloor).toBe(true)
    // The load-bearing consequence: it never sets the fitted shadow frustum and
    // never enters the geometry fingerprint.
    expect(isShadowExcluded(mesh)).toBe(true)
  })

  it('reuses one mesh across updates and re-fits it to new bounds', () => {
    const scene = new THREE.Scene()
    const c = createShadowCatcher(scene)
    c.update(BOUNDS, { enabled: true })
    const first = c.getMesh()

    c.update(boundsFor([0, 100, 0], [40, 140, 40]), { enabled: true })
    expect(c.getMesh()).toBe(first)              // no leak, no second plane
    expect(scene.children).toHaveLength(1)
    expect(first.position.y).toBeCloseTo(100, 6)
    expect(first.position.x).toBeCloseTo(20, 6)
  })

  it('drops the mesh when disabled again, and can be rebuilt', () => {
    const scene = new THREE.Scene()
    const c = createShadowCatcher(scene)
    c.update(BOUNDS, { enabled: true })
    c.update(BOUNDS, { enabled: false })
    expect(c.getMesh()).toBe(null)
    expect(scene.children).toHaveLength(0)

    c.update(BOUNDS, { enabled: true })
    expect(c.getMesh()).not.toBe(null)
  })

  it('clamps opacity into [0,1]', () => {
    const scene = new THREE.Scene()
    const c = createShadowCatcher(scene)
    c.update(BOUNDS, { enabled: true, opacity: 4 })
    expect(c.getMesh().material.opacity).toBe(1)
    c.update(BOUNDS, { enabled: true, opacity: -2 })
    expect(c.getMesh().material.opacity).toBe(0)
  })

  it('getReach() reports the far CORNER, so the camera far clip cannot crop it', () => {
    const scene = new THREE.Scene()
    const c = createShadowCatcher(scene)
    expect(c.getReach()).toBe(null)

    const p = c.update(BOUNDS, { enabled: true })
    const r = c.getReach()
    expect(r.center.y).toBeCloseTo(0, 6)
    // Half-width alone would leave the corners outside the frustum.
    expect(r.reach).toBeCloseTo(p.halfExtent * Math.SQRT2, 5)
    expect(r.reach).toBeGreaterThan(p.halfExtent)

    c.remove()
    expect(c.getReach()).toBe(null)
  })
})
