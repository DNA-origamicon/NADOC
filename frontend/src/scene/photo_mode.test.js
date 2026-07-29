import { describe, it, expect, beforeEach, vi } from 'vitest'
import * as THREE from 'three'
import { createMockStore } from '../test-helpers/mock_store.js'
import { clearDom } from '../test-helpers/factory_dom.js'
import { LIGHTING_PRESETS } from './photo_renderer/lighting_presets.js'
import {
  keyLightDirection,
  swapToFlatMaterials,
  createPhotoMode,
  initPhotoMode,
  DEFAULT_PHOTO_SETTINGS,
} from './photo_mode.js'

// ── swapToFlatMaterials ──────────────────────────────────────────────────────

describe('swapToFlatMaterials', () => {
  const box = () => new THREE.BoxGeometry(1, 1, 1)

  it('flattens an ordinary mesh: no specular lobe, fully rough, no metal', () => {
    const scene = new THREE.Scene()
    const mesh = new THREE.Mesh(box(), new THREE.MeshPhongMaterial({ color: 0x3388ff }))
    scene.add(mesh)

    swapToFlatMaterials(scene)

    expect(mesh.material.isMeshPhysicalMaterial).toBe(true)
    expect(mesh.material.specularIntensity).toBe(0)
    expect(mesh.material.roughness).toBe(1)
    expect(mesh.material.metalness).toBe(0)
  })

  it('applies the preset for each mesh\'s OWN representation', () => {
    const scene = new THREE.Scene()
    const beads = new THREE.InstancedMesh(new THREE.SphereGeometry(1, 8, 6), new THREE.MeshPhongMaterial(), 4)
    beads.name = 'backboneSpheres'
    const cyls = new THREE.InstancedMesh(new THREE.CylinderGeometry(1, 1, 1, 6), new THREE.MeshPhongMaterial(), 4)
    cyls.name = 'helixCylinders'
    const surf = new THREE.Mesh(box(), new THREE.MeshPhongMaterial({ side: THREE.DoubleSide }))
    surf.name = 'dna-surface'
    scene.add(beads, cyls, surf)

    swapToFlatMaterials(scene, { full: 'metallic', cylinders: 'glossy', surface: 'matte', atomistic: 'cpk-flat' })

    expect(beads.material.metalness).toBe(1.0)          // full → metallic
    expect(cyls.material.clearcoat).toBeCloseTo(0.5)     // cylinders → glossy
    expect(surf.material.roughness).toBeCloseTo(0.85)    // surface → matte
  })

  it('defaults to the flat FIGURE materials when no presets are given', () => {
    const scene = new THREE.Scene()
    const m = new THREE.Mesh(box(), new THREE.MeshPhongMaterial())
    m.name = 'backboneSpheres'
    scene.add(m)
    swapToFlatMaterials(scene)
    expect(m.material.specularIntensity).toBe(0)
  })

  it('covers every representation, keyed off the material — not a name table', () => {
    // beads/atoms (instanced), cylinders (instanced), the marching-cubes
    // surface (DoubleSide), a hull prism (plain mesh).
    const scene = new THREE.Scene()
    const beads = new THREE.InstancedMesh(new THREE.SphereGeometry(1, 8, 6), new THREE.MeshPhongMaterial(), 4)
    const cyls  = new THREE.InstancedMesh(new THREE.CylinderGeometry(1, 1, 1, 6), new THREE.MeshPhongMaterial(), 4)
    const surf  = new THREE.Mesh(box(), new THREE.MeshPhongMaterial({ side: THREE.DoubleSide }))
    const hull  = new THREE.Mesh(box(), new THREE.MeshStandardMaterial())
    scene.add(beads, cyls, surf, hull)

    const { count } = swapToFlatMaterials(scene)

    expect(count).toBe(4)
    for (const m of [beads, cyls, surf, hull]) expect(m.material.isMeshPhysicalMaterial).toBe(true)
  })

  it('preserves DoubleSide — the surface mesh culls away without it', () => {
    const scene = new THREE.Scene()
    const surf = new THREE.Mesh(box(), new THREE.MeshPhongMaterial({ side: THREE.DoubleSide }))
    scene.add(surf)
    swapToFlatMaterials(scene)
    expect(surf.material.side).toBe(THREE.DoubleSide)
  })

  it('preserves vertexColors so strand colouring survives', () => {
    const scene = new THREE.Scene()
    const mesh = new THREE.Mesh(box(), new THREE.MeshPhongMaterial({ vertexColors: true }))
    scene.add(mesh)
    swapToFlatMaterials(scene)
    expect(mesh.material.vertexColors).toBe(true)
  })

  it('carries the source colour through for a uniformly-coloured mesh', () => {
    // Forcing white would blank a hull prism / cylinder proxy that has no
    // per-instance or per-vertex colour to supply the real one.
    const scene = new THREE.Scene()
    const mesh = new THREE.Mesh(box(), new THREE.MeshPhongMaterial({ color: 0x3388ff }))
    scene.add(mesh)
    swapToFlatMaterials(scene)
    expect(mesh.material.color.getHexString()).toBe('3388ff')
  })

  it('forces white where an instance colour will supply the real colour', () => {
    const scene = new THREE.Scene()
    const inst = new THREE.InstancedMesh(box(), new THREE.MeshPhongMaterial({ color: 0x3388ff }), 2)
    inst.instanceColor = new THREE.InstancedBufferAttribute(new Float32Array(6), 3)
    scene.add(inst)
    swapToFlatMaterials(scene)
    // material.color multiplies instanceColor, so anything but white tints it.
    expect(inst.material.color.getHexString()).toBe('ffffff')
  })

  it('leaves impostor materials alone — their sphere ray-paint is a shader patch', () => {
    const scene = new THREE.Scene()
    const mat = new THREE.MeshPhongMaterial()
    mat.userData.isImpostor = true
    mat.userData.impostorRadius = 0.1
    const mesh = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), mat)
    scene.add(mesh)
    swapToFlatMaterials(scene)
    expect(mesh.material).toBe(mat)
  })

  it('leaves helper lines, additive sprites, LOD impostors and the floor alone', () => {
    const scene = new THREE.Scene()
    const line   = new THREE.Mesh(box(), new THREE.LineBasicMaterial())
    const glow   = new THREE.Mesh(box(), new THREE.MeshBasicMaterial({ blending: THREE.AdditiveBlending }))
    const lod    = new THREE.Mesh(box(), new THREE.MeshPhongMaterial())
    lod.userData.sharedLodImpostor = true
    const floor  = new THREE.Mesh(box(), new THREE.MeshPhongMaterial())
    floor.userData.photoFloor = true
    scene.add(line, glow, lod, floor)

    const originals = [line, glow, lod, floor].map(m => m.material)
    const { count } = swapToFlatMaterials(scene)

    expect(count).toBe(0)
    ;[line, glow, lod, floor].forEach((m, i) => expect(m.material).toBe(originals[i]))
  })

  it('restore() puts every original material back', () => {
    const scene = new THREE.Scene()
    const a = new THREE.Mesh(box(), new THREE.MeshPhongMaterial())
    const b = new THREE.InstancedMesh(box(), new THREE.MeshStandardMaterial(), 2)
    scene.add(a, b)
    const before = [a.material, b.material]

    const handle = swapToFlatMaterials(scene)
    expect(a.material).not.toBe(before[0])

    handle.restore()
    expect(a.material).toBe(before[0])
    expect(b.material).toBe(before[1])
  })
})

describe('keyLightDirection', () => {
  it('reproduces ChimeraX\'s own key direction at the defaults', () => {
    // (135°, 35.264°) → (-0.577, 0.577, 0.577): 45° up-and-left, 54.7° off axis.
    const [x, y, z] = keyLightDirection(135, 35.264)
    expect(x).toBeCloseTo(-0.5774, 3)
    expect(y).toBeCloseTo( 0.5774, 3)
    expect(z).toBeCloseTo( 0.5774, 3)
    // …and it is the DEFAULT, so the rig comes up on ChimeraX's key direction.
    expect(DEFAULT_PHOTO_SETTINGS.keyAzimuth).toBe(135)
    expect(DEFAULT_PHOTO_SETTINGS.keyElevation).toBeCloseTo(35.264, 3)
  })

  it('always returns a unit vector', () => {
    for (const [a, e] of [[0, 0], [135, 35], [-90, 80], [180, -60], [37, -12]]) {
      const [x, y, z] = keyLightDirection(a, e)
      expect(Math.hypot(x, y, z)).toBeCloseTo(1, 9)
    }
  })

  it('azimuth sweeps the screen: 0 = right, 90 = above, 180 = left', () => {
    expect(keyLightDirection(0,   0)[0]).toBeCloseTo( 1, 6)   // +x = right
    expect(keyLightDirection(90,  0)[1]).toBeCloseTo( 1, 6)   // +y = up
    expect(keyLightDirection(180, 0)[0]).toBeCloseTo(-1, 6)   // -x = left
  })

  it('elevation tilts toward the viewer; 90° sits on the camera axis', () => {
    // At 90° the light is straight down the barrel — nothing can shadow, which
    // is why the panel warns about it rather than allowing it silently.
    expect(keyLightDirection(135, 90)[2]).toBeCloseTo(1, 6)
    // Negative elevation puts it BEHIND the subject: a rim light.
    expect(keyLightDirection(135, -40)[2]).toBeLessThan(0)
  })

  it('the angle off the camera axis is exactly 90 - elevation', () => {
    for (const el of [0, 20, 35.264, 60]) {
      const z = keyLightDirection(0, el)[2]              // dot with the view axis
      expect((Math.acos(z) * 180) / Math.PI).toBeCloseTo(90 - el, 4)
    }
  })
})

// ── createPhotoMode ───────────────────────────────────────────────────────

function makeSceneCtx() {
  const scene  = new THREE.Scene()
  const camera = new THREE.PerspectiveCamera(55, 1, 0.1, 2000)
  const renderer = {
    toneMapping: THREE.NoToneMapping,
    toneMappingExposure: 1,
    shadowMap: { enabled: false, type: null },
    getClearColor: (t) => t.set(0x123456),
    getClearAlpha: () => 1,
    setClearColor: vi.fn(),
    getDrawingBufferSize: (t) => t.set(800, 600),
    getRenderTarget: () => null,
    setRenderTarget: vi.fn(),
    getContext: () => null,
    render: vi.fn(),
    clear: vi.fn(),
    getSize: (t) => t.set(800, 600),
    getPixelRatio: () => 1,
    capabilities: { isWebGL2: true },
  }
  const ctx = {
    scene, camera, renderer,
    renderFn: null,
    resizeFn: null,
    setRenderFn(fn) { ctx.renderFn = fn },
    resetRenderFn() { ctx.renderFn = null },
    setResizeCallback(fn) { ctx.resizeFn = fn },
    clearResizeCallback() { ctx.resizeFn = null },
  }
  return ctx
}

describe('createPhotoMode', () => {
  let ctx, mode

  beforeEach(() => {
    ctx = makeSceneCtx()
    // Some geometry so the mode has something to swap and bound.
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(2, 2, 2), new THREE.MeshPhongMaterial())
    ctx.scene.add(mesh, new THREE.PointLight(0xffffff, 1))
    mode = createPhotoMode(ctx)
  })

  it('starts inactive with the ChimeraX `lighting full` defaults', () => {
    expect(mode.isActive()).toBe(false)
    expect(mode.getSettings()).toEqual({ ...DEFAULT_PHOTO_SETTINGS })
    const s = mode.getSettings()
    expect(s.keyShadow).toBe(true)
    // Max-contrast IS the default: a cast shadow only subtracts the key light,
    // so at 2.0/0/0.15 it removes ~93% of the light instead of ChimeraX's 39%.
    expect(s.keyIntensity).toBeCloseTo(2.0, 6)
    expect(s.ambientIntensity).toBeCloseTo(0.15, 6)
    expect(s.pinLights).toBe(true)
    // Max-contrast is the default: the cast shadow removes ~93% of the light
    // instead of the 39% ChimeraX's own key/fill/ambient balance allows.
    expect(LIGHTING_PRESETS.full.ambient.intensity).toBeCloseTo(0.15, 6)
    expect(LIGHTING_PRESETS.full.lights).toHaveLength(2)     // key + fill(0)
    expect(LIGHTING_PRESETS.full.lights[1].intensity).toBe(0)
    // The settings MUST match the preset — _rebuildRig applies them over it.
    expect(DEFAULT_PHOTO_SETTINGS.keyIntensity).toBeCloseTo(LIGHTING_PRESETS.full.lights[0].intensity, 9)
    expect(DEFAULT_PHOTO_SETTINGS.ambientIntensity).toBeCloseTo(LIGHTING_PRESETS.full.ambient.intensity, 9)
    expect(LIGHTING_PRESETS.full.lights[0].intensity).toBeCloseTo(2.0, 6)
  })

  it('activate() installs a render override and a light rig', () => {
    mode.activate()
    expect(mode.isActive()).toBe(true)
    expect(typeof ctx.renderFn).toBe('function')
    const rig = ctx.scene.getObjectByName('expPhotoLights')
    expect(rig).toBeTruthy()
    expect(rig.children.some(c => c.isAmbientLight)).toBe(true)
  })

  it('activate() hides the editor lights and deactivate() restores them', () => {
    const editorLight = ctx.scene.children.find(c => c.isPointLight)
    expect(editorLight.visible).toBe(true)

    mode.activate()
    expect(editorLight.visible).toBe(false)

    mode.deactivate()
    expect(editorLight.visible).toBe(true)
  })

  it('deactivate() restores the render fn, tone mapping and scene environment', () => {
    ctx.scene.environment = { fake: 'pmrem' }
    const env = ctx.scene.environment
    ctx.renderer.toneMapping = THREE.NoToneMapping

    mode.activate()
    expect(ctx.scene.environment).toBeNull()
    expect(ctx.renderer.toneMapping).toBe(THREE.ACESFilmicToneMapping)

    mode.deactivate()
    expect(ctx.renderFn).toBeNull()
    expect(ctx.scene.environment).toBe(env)
    expect(ctx.renderer.toneMapping).toBe(THREE.NoToneMapping)
    expect(ctx.scene.getObjectByName('expPhotoLights')).toBeFalsy()
  })

  it('deactivate() restores every swapped material', () => {
    const mesh = ctx.scene.children.find(c => c.isMesh)
    const original = mesh.material
    mode.activate()
    expect(mesh.material).not.toBe(original)
    mode.deactivate()
    expect(mesh.material).toBe(original)
  })

  it('is idempotent — double activate/deactivate is safe', () => {
    mode.activate(); mode.activate()
    expect(mode.isActive()).toBe(true)
    mode.deactivate(); mode.deactivate()
    expect(mode.isActive()).toBe(false)
  })

  // ── `lighting full`: camera-pinned rig + key-light shadow ──────────────────

  it('builds the rig: a key light and a fill, both aimed at the centre', () => {
    mode.activate()
    const rig = mode._getLightGroup()
    const dirs = rig.children.filter(c => c.isDirectionalLight)
    expect(dirs).toHaveLength(2)      // key + fill (fill ships at intensity 0)
    expect(rig.children.some(c => c.isAmbientLight)).toBe(true)
    // Every directional aims at the rig's own origin, so rotating the rig sweeps
    // the lights without ever un-aiming them.
    for (const d of dirs) expect(d.target.parent).toBe(rig)
  })

  it('resetKeyDirection restores ChimeraX\'s own key direction', () => {
    mode.activate()
    mode.setKeyAzimuth(-90)
    mode.setKeyElevation(-30)
    mode.resetKeyDirection()
    const s = mode.getSettings()
    expect(s.keyAzimuth).toBe(DEFAULT_PHOTO_SETTINGS.keyAzimuth)
    expect(s.keyElevation).toBeCloseTo(DEFAULT_PHOTO_SETTINGS.keyElevation, 9)
    // …and the light actually moved back, not just the settings.
    const want = new THREE.Vector3(...keyLightDirection(s.keyAzimuth, s.keyElevation))
    expect(mode._getKeyLight().position.clone().normalize().angleTo(want)).toBeCloseTo(0, 6)
  })

  it('steers the key light by azimuth/elevation', () => {
    mode.activate()
    const key = mode._getKeyLight()
    const before = key.position.clone().normalize()
    // Default is up-left; sweep it to the opposite side of the screen.
    mode.setKeyAzimuth(-45)
    const after = mode._getKeyLight().position.clone().normalize()
    expect(after.x).toBeGreaterThan(0)          // now from the right
    expect(before.angleTo(after)).toBeGreaterThan(0.5)
  })

  it('the key direction matches keyLightDirection for the current settings', () => {
    mode.activate()
    mode.setKeyAzimuth(20)
    mode.setKeyElevation(50)
    const want = new THREE.Vector3(...keyLightDirection(20, 50))
    const got = mode._getKeyLight().position.clone().normalize()
    expect(got.angleTo(want)).toBeCloseTo(0, 6)
  })

  it('steering leaves the FILL light where the preset put it', () => {
    mode.activate()
    const rig = mode._getLightGroup()
    const fill = rig.children.filter(c => c.isDirectionalLight)[1]
    const before = fill.position.clone().normalize()
    mode.setKeyAzimuth(-90)
    const after = rig.children.filter(c => c.isDirectionalLight)[1].position.clone().normalize()
    expect(before.angleTo(after)).toBeCloseTo(0, 6)
  })

  it('pins the rig to the camera — the orientation-dependence ChimeraX has', () => {
    mode.activate()
    const rig = mode._getLightGroup()
    ctx.camera.position.set(30, 20, 40)
    ctx.camera.lookAt(0, 0, 0)
    ctx.camera.updateMatrixWorld()
    mode._syncFrame()                    // one frame of per-frame CPU work
    expect(rig.quaternion.angleTo(ctx.camera.quaternion)).toBeCloseTo(0, 6)

    // Move the camera again: the rig must follow, not stay put.
    const before = rig.quaternion.clone()
    ctx.camera.position.set(-40, 5, 10)
    ctx.camera.lookAt(0, 0, 0)
    ctx.camera.updateMatrixWorld()
    mode._syncFrame()
    expect(rig.quaternion.angleTo(before)).toBeGreaterThan(0.1)
  })

  it('setPinLights(false) welds the rig to the world', () => {
    mode.activate()
    const rig = mode._getLightGroup()
    mode.setPinLights(false)
    ctx.camera.position.set(30, 20, 40)
    ctx.camera.lookAt(0, 0, 0)
    ctx.camera.updateMatrixWorld()
    mode._syncFrame()
    expect(rig.quaternion.angleTo(new THREE.Quaternion())).toBeCloseTo(0, 6)
  })

  it('gives the key light a shadow with NO floor present', () => {
    // The shipping photo mode gates shadows behind `floor !== 'off'`, which makes
    // helix-on-helix shadow impossible. Here it must work with nothing but the
    // structure in the scene.
    mode.activate()
    const key = mode._getKeyLight()
    expect(key).toBeTruthy()
    expect(key.castShadow).toBe(true)
    expect(ctx.renderer.shadowMap.enabled).toBe(true)
    expect(key.shadow.mapSize.width).toBe(2048)
  })

  it('fits the shadow frustum to the scene bounding sphere', () => {
    mode.activate()
    const cam = mode._getKeyLight().shadow.camera
    // Bounding sphere of a 2×2×2 box → radius √3 ≈ 1.73.
    expect(cam.right).toBeCloseTo(Math.sqrt(3), 1)
    expect(cam.left).toBeCloseTo(-cam.right, 6)
    expect(cam.far).toBeGreaterThan(cam.right * 2)
  })

  it('flags meshes to cast and receive, and restores the flags on exit', () => {
    const mesh = ctx.scene.children.find(c => c.isMesh)
    expect(mesh.castShadow).toBe(false)
    mode.activate()
    expect(mesh.castShadow).toBe(true)
    expect(mesh.receiveShadow).toBe(true)
    mode.deactivate()
    expect(mesh.castShadow).toBe(false)
    expect(mesh.receiveShadow).toBe(false)
  })

  it('lets impostors receive but not cast — three drives its own depth pass', () => {
    const mat = new THREE.MeshPhongMaterial()
    mat.userData.impostorRadius = 0.1
    const imp = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), mat)
    ctx.scene.add(imp)
    mode.activate()
    expect(imp.castShadow).toBe(false)
    expect(imp.receiveShadow).toBe(true)
  })

  it('forces a material recompile when the shadow flag flips', () => {
    // `shadowMapEnabled` is compiled into each program and three does not
    // re-check it, so toggling the shadow back on is a no-op for materials that
    // already compiled without it unless we bump needsUpdate ourselves.
    mode.activate()
    const mesh = ctx.scene.children.find(c => c.isMesh)
    mode.setKeyShadow(false)
    const v = mesh.material.version
    mode.setKeyShadow(true)
    expect(mesh.material.version).toBeGreaterThan(v)
  })

  it('setKeyShadow(false) drops the shadow and restores the renderer flag', () => {
    mode.activate()
    expect(ctx.renderer.shadowMap.enabled).toBe(true)
    mode.setKeyShadow(false)
    expect(mode._getKeyLight().castShadow).toBe(false)
    expect(ctx.renderer.shadowMap.enabled).toBe(false)
  })

  it('deactivate() restores the renderer shadow state it found', () => {
    ctx.renderer.shadowMap.enabled = false
    mode.activate()
    expect(ctx.renderer.shadowMap.enabled).toBe(true)
    mode.deactivate()
    expect(ctx.renderer.shadowMap.enabled).toBe(false)
  })

  it('scales the shadow bias to the shadow-map TEXEL, not the scene radius', () => {
    // A radius-proportional bias reaches several bead diameters on a real
    // origami (0.24 nm at R=60 nm vs a 0.10 nm bead) and erases the shadow
    // rather than de-acneing it.
    mode.activate()
    const key = mode._getKeyLight()
    const R = key.shadow.camera.right          // ortho half-width == bounds radius
    const texel = (2 * R) / key.shadow.mapSize.width
    expect(key.shadow.normalBias).toBeCloseTo(texel, 9)
    // ...and stays a small fraction of a CG bead (0.10 nm) at origami scale.
    expect(key.shadow.normalBias).toBeLessThan(0.10)

    mode.setKeyShadowBias(3)
    expect(key.shadow.normalBias).toBeCloseTo(texel * 3, 9)
  })

  // ── Figure effects ────────────────────────────────────────────────────────

  it('the figure pass is OFF until an effect is switched on', () => {
    // EffectComposer skips a disabled pass entirely, so both effects off means
    // no depth/normal pre-pass at all.
    mode.activate()
    expect(mode._getFigurePass().enabled).toBe(false)
    mode.setOutline(true)
    expect(mode._getFigurePass().enabled).toBe(true)
    mode.setOutline(false)
    expect(mode._getFigurePass().enabled).toBe(false)
  })

  it('drives the real outline uniforms, not just the settings', () => {
    mode.activate()
    mode.setOutline(true)
    mode.setOutlineColor('#ff0000')
    mode.setOutlineStrength(0.4)
    mode.setOutlineThickness(2.5)
    mode.setOutlineSensitivity({ depth: 0.2, crease: 1.3 })
    const u = mode._getFigurePass().uniforms
    expect(u.uOutline.value).toBe(1)
    expect(u.uOutlineColor.value.getHexString()).toBe('ff0000')
    expect(u.uOutlineStrength.value).toBeCloseTo(0.4, 6)
    expect(u.uOutlineThickness.value).toBeCloseTo(2.5, 6)
    expect(u.uDepthSens.value).toBeCloseTo(0.2, 6)
    expect(u.uNormalSens.value).toBeCloseTo(1.3, 6)
  })

  it('drives the real depth-cue uniforms', () => {
    mode.activate()
    mode.setDepthCue(true)
    mode.setDepthCueColor('#00ff00')
    mode.setDepthCueStrength(0.6)
    const u = mode._getFigurePass().uniforms
    expect(u.uCue.value).toBe(1)
    expect(u.uCueColor.value.getHexString()).toBe('00ff00')
    expect(u.uCueStrength.value).toBeCloseTo(0.6, 6)
  })

  it('anchors the depth-cue window to the bbox DIAGONAL, not the view extent', () => {
    // Scaling the window to the current view's depth extent normalises every
    // view to a full 0..1 fade, washing out a thin helix seen side-on.
    mode.activate()
    mode.setDepthCue(true)
    const u = mode._getFigurePass().uniforms
    const span = u.uCueFar.value - u.uCueNear.value
    expect(span).toBeCloseTo(2 * Math.sqrt(3), 3)   // seeded 2x2x2 box

    ctx.camera.position.set(0, 0, 60)
    ctx.camera.lookAt(0, 0, 0)
    ctx.camera.updateMatrixWorld()
    mode._syncFrame()
    expect(u.uCueFar.value - u.uCueNear.value).toBeCloseTo(span, 6)
  })

  // ── Camera + export ───────────────────────────────────────────────────────

  it('setFOV dollies to preserve framing, not just changes the lens', () => {
    // Narrowing the FOV without dollying would zoom in; the point of the long
    // lens is to flatten perspective while keeping the subject the same size.
    ctx.controls = { target: new THREE.Vector3(0, 0, 0), update: vi.fn() }
    const m2 = createPhotoMode(ctx)
    ctx.camera.position.set(0, 0, 40)
    m2.activate()
    const before = ctx.camera.position.length()
    m2.setFOV(20)
    expect(ctx.camera.fov).toBe(20)
    expect(ctx.camera.position.length()).toBeGreaterThan(before)   // dollied OUT
    m2.deactivate()
  })

  it('setParallel snaps to the 8 degree long lens and keeps the flag honest', () => {
    ctx.controls = { target: new THREE.Vector3(0, 0, 0), update: vi.fn() }
    const m2 = createPhotoMode(ctx)
    m2.activate()
    m2.setParallel(true)
    expect(m2.getSettings().fov).toBe(8)
    expect(ctx.camera.fov).toBe(8)
    // Driving the FOV back up must clear the flag, or the checkbox lies.
    m2.setFOV(55)
    expect(m2.getSettings().parallel).toBe(false)
    m2.deactivate()
  })

  it('deactivate restores the editor lens', () => {
    ctx.controls = { target: new THREE.Vector3(0, 0, 0), update: vi.fn() }
    ctx.camera.fov = 55
    const m2 = createPhotoMode(ctx)
    m2.activate()
    m2.setParallel(true)
    expect(ctx.camera.fov).toBe(8)
    m2.deactivate()
    expect(ctx.camera.fov).toBe(55)
  })

  it('setExportSize stores a sane size and ignores garbage', () => {
    mode.setExportSize(8400, 5940)
    expect(mode.getSettings().exportWidth).toBe(8400)
    expect(mode.getSettings().exportHeight).toBe(5940)
    mode.setExportSize(0, -5)
    expect(mode.getSettings().exportWidth).toBe(8400)   // unchanged
  })

  it('renderToBlob refuses when the mode is not active', async () => {
    await expect(mode.renderToBlob(100, 100)).rejects.toThrow(/active/)
  })

  it('a transparent background clears scene.background so exports stay transparent', () => {
    mode.activate()
    mode.setBackground('transparent')
    expect(ctx.scene.background).toBeNull()
    mode.setBackground('color', '#ff0000')
    expect(ctx.scene.background.getHexString()).toBe('ff0000')
  })

  it('resync() re-swaps materials for rebuilt meshes and refits the rig', () => {
    mode.activate()
    // A rebuild replaces meshes: new mesh, editor material, no shadow flags.
    const fresh = new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), new THREE.MeshPhongMaterial())
    ctx.scene.add(fresh)
    mode.resync()

    expect(fresh.material.isMeshPhysicalMaterial).toBe(true)
    expect(fresh.castShadow).toBe(true)
  })

  it('getDiagnostics() reports the whole shadow chain', () => {
    mode.activate()
    const d = mode.getDiagnostics()
    expect(d.active).toBe(true)
    expect(d.rendererShadowMapEnabled).toBe(true)
    expect(d.keyLight.castShadow).toBe(true)
    expect(d.keyLight.frustumHalfWidth).toBeGreaterThan(0)
    expect(d.bounds.radius).toBeGreaterThan(0)
    expect(d.meshes.casters).toBeGreaterThan(0)
    expect(d.meshes.receivers).toBeGreaterThan(0)
    // The light must be off the view axis, not sitting on the camera.
    expect(d.keyLight.worldPos).not.toEqual(d.keyLight.targetPos)
  })

  it('getDiagnostics() is safe before activation', () => {
    const d = mode.getDiagnostics()
    expect(d.active).toBe(false)
    expect(d.keyLight).toBeNull()
  })
})

// ── initPhotoMode (tab orchestration) ─────────────────────────────────────

describe('initPhotoMode', () => {
  let ctx, store, deps, gizmos

  beforeEach(() => {
    clearDom()
    ctx = makeSceneCtx()
    ctx.scene.add(new THREE.Mesh(new THREE.BoxGeometry(2, 2, 2), new THREE.MeshPhongMaterial()))
    store = createMockStore({ toolFilters: { bluntEnds: true } })
    gizmos = {
      designRenderer:        { setAxisArrowsVisible: vi.fn() },
      assemblyRenderer:      { setPhotoMode: vi.fn(), onRebuildComplete: vi.fn() },
      assemblyJointRenderer: { setVisible: vi.fn() },
      bluntEnds:             { setVisible: vi.fn() },
      originAxes:            new THREE.AxesHelper(4),
    }
    deps = { store, sceneCtx: ctx, ...gizmos }
  })

  it('enter() activates the mode and suppresses the editor gizmos', () => {
    const tab = initPhotoMode(deps)
    tab.enter()

    expect(tab.mode.isActive()).toBe(true)
    expect(gizmos.designRenderer.setAxisArrowsVisible).toHaveBeenCalledWith(false)
    expect(gizmos.bluntEnds.setVisible).toHaveBeenCalledWith(false)
    expect(gizmos.assemblyRenderer.setPhotoMode).toHaveBeenCalledWith(true)
    expect(gizmos.assemblyJointRenderer.setVisible).toHaveBeenCalledWith(false)
    expect(gizmos.originAxes.visible).toBe(false)
  })

  it('exit() restores the gizmos, including the origin triad prior visibility', () => {
    gizmos.originAxes.visible = false            // user had it off already
    const tab = initPhotoMode(deps)
    tab.enter()
    tab.exit()

    expect(tab.mode.isActive()).toBe(false)
    expect(gizmos.designRenderer.setAxisArrowsVisible).toHaveBeenLastCalledWith(true)
    expect(gizmos.assemblyRenderer.setPhotoMode).toHaveBeenLastCalledWith(false)
    expect(gizmos.originAxes.visible).toBe(false)
  })

  it('restores the origin triad to visible when it was visible before', () => {
    const tab = initPhotoMode(deps)
    tab.enter()
    tab.exit()
    expect(gizmos.originAxes.visible).toBe(true)
  })

  it('exit() is a safe no-op when never entered', () => {
    const tab = initPhotoMode(deps)
    expect(() => tab.exit()).not.toThrow()
    expect(gizmos.designRenderer.setAxisArrowsVisible).not.toHaveBeenCalled()
  })

  it('refits the rig when the design changes, but not on unrelated state', () => {
    const tab = initPhotoMode(deps)
    tab.enter()
    const spy = vi.spyOn(tab.mode, 'resync')

    store.setState({ someUnrelatedFlag: true })
    expect(spy).not.toHaveBeenCalled()

    store.setState({ currentDesign: { id: 'd2' } })
    expect(spy).toHaveBeenCalled()
  })

  it('refits when staple visibility changes — it changes what is drawn', () => {
    const tab = initPhotoMode(deps)
    tab.enter()
    const spy = vi.spyOn(tab.mode, 'resync')
    store.setState({ staplesHidden: true })
    expect(spy).toHaveBeenCalled()
  })

  it('ignores store changes while inactive', () => {
    const tab = initPhotoMode(deps)
    expect(() => store.setState({ currentDesign: { id: 'd2' } })).not.toThrow()
    expect(tab.mode.isActive()).toBe(false)
  })
})
