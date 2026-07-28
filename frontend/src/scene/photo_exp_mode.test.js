import { describe, it, expect, beforeEach, vi } from 'vitest'
import * as THREE from 'three'
import { createMockStore } from '../test-helpers/mock_store.js'
import { clearDom } from '../test-helpers/factory_dom.js'
import { LIGHTING_PRESETS } from './photo_renderer/lighting_presets.js'
import {
  swapToFlatMaterials,
  createExpPhotoMode,
  initPhotoExpMode,
  DEFAULT_EXP_SETTINGS,
} from './photo_exp_mode.js'

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

// ── createExpPhotoMode ───────────────────────────────────────────────────────

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

describe('createExpPhotoMode', () => {
  let ctx, mode

  beforeEach(() => {
    ctx = makeSceneCtx()
    // Some geometry so the mode has something to swap and bound.
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(2, 2, 2), new THREE.MeshPhongMaterial())
    ctx.scene.add(mesh, new THREE.PointLight(0xffffff, 1))
    mode = createExpPhotoMode(ctx)
  })

  it('starts inactive with the ChimeraX `lighting full` defaults', () => {
    expect(mode.isActive()).toBe(false)
    expect(mode.getSettings()).toEqual({ ...DEFAULT_EXP_SETTINGS })
    const s = mode.getSettings()
    expect(s.lighting).toBe('full')
    expect(s.keyShadow).toBe(true)
    expect(s.pinLights).toBe(true)
    // Max-contrast is the default: the cast shadow removes ~93% of the light
    // instead of the 39% ChimeraX's own key/fill/ambient balance allows.
    expect(LIGHTING_PRESETS.full.ambient.intensity).toBeCloseTo(0.15, 6)
    expect(LIGHTING_PRESETS.full.lights).toHaveLength(1)
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

  it('builds the `full` rig: one key light, aimed at the centre', () => {
    mode.activate()
    const rig = mode._getLightGroup()
    const dirs = rig.children.filter(c => c.isDirectionalLight)
    expect(dirs).toHaveLength(1)      // key only — the fill was removed
    expect(rig.children.some(c => c.isAmbientLight)).toBe(true)
    // Every directional aims at the rig's own origin, so rotating the rig sweeps
    // the lights without ever un-aiming them.
    for (const d of dirs) expect(d.target.parent).toBe(rig)
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

  it('switching to an ambient-only preset leaves no key light casting', () => {
    mode.activate()
    expect(mode._getKeyLight().castShadow).toBe(true)
    mode.setLighting('flat')             // ambient only — no directionals at all
    expect(mode._getKeyLight()).toBeNull()
    expect(ctx.renderer.shadowMap.enabled).toBe(false)
  })

  it('changing the light preset swaps the rig in place', () => {
    mode.activate()
    mode.setLighting('scientific')
    const rig = ctx.scene.getObjectByName('expPhotoLights')
    // `scientific` is one key light; `ambient` is three weak fills.
    expect(rig.children.filter(c => c.isDirectionalLight)).toHaveLength(1)
    mode.setLighting('ambient')
    expect(rig.children.filter(c => c.isDirectionalLight)).toHaveLength(3)
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

// ── initPhotoExpMode (tab orchestration) ─────────────────────────────────────

describe('initPhotoExpMode', () => {
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
    const tab = initPhotoExpMode(deps)
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
    const tab = initPhotoExpMode(deps)
    tab.enter()
    tab.exit()

    expect(tab.mode.isActive()).toBe(false)
    expect(gizmos.designRenderer.setAxisArrowsVisible).toHaveBeenLastCalledWith(true)
    expect(gizmos.assemblyRenderer.setPhotoMode).toHaveBeenLastCalledWith(false)
    expect(gizmos.originAxes.visible).toBe(false)
  })

  it('restores the origin triad to visible when it was visible before', () => {
    const tab = initPhotoExpMode(deps)
    tab.enter()
    tab.exit()
    expect(gizmos.originAxes.visible).toBe(true)
  })

  it('exit() is a safe no-op when never entered', () => {
    const tab = initPhotoExpMode(deps)
    expect(() => tab.exit()).not.toThrow()
    expect(gizmos.designRenderer.setAxisArrowsVisible).not.toHaveBeenCalled()
  })

  it('refits the rig when the design changes, but not on unrelated state', () => {
    const tab = initPhotoExpMode(deps)
    tab.enter()
    const spy = vi.spyOn(tab.mode, 'resync')

    store.setState({ someUnrelatedFlag: true })
    expect(spy).not.toHaveBeenCalled()

    store.setState({ currentDesign: { id: 'd2' } })
    expect(spy).toHaveBeenCalled()
  })

  it('refits when staple visibility changes — it changes what is drawn', () => {
    const tab = initPhotoExpMode(deps)
    tab.enter()
    const spy = vi.spyOn(tab.mode, 'resync')
    store.setState({ staplesHidden: true })
    expect(spy).toHaveBeenCalled()
  })

  it('ignores store changes while inactive', () => {
    const tab = initPhotoExpMode(deps)
    expect(() => store.setState({ currentDesign: { id: 'd2' } })).not.toThrow()
    expect(tab.mode.isActive()).toBe(false)
  })
})
