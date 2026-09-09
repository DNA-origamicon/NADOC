import { describe, it, expect, beforeEach, vi } from 'vitest'
import * as THREE from 'three'
import { createMockStore } from '../test-helpers/mock_store.js'
import { clearDom } from '../test-helpers/factory_dom.js'
import { LIGHTING_PRESETS } from './photo_renderer/lighting_presets.js'
import { applyInstanceAlphaMaterial, instanceAlphaOnBeforeCompile } from './instance_alpha.js'
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
    expect(mesh.material.envMapIntensity).toBe(0)
  })

  it('keeps a gold nanoparticle metallic regardless of the Full preset', () => {
    const scene = new THREE.Scene()
    const original = new THREE.MeshPhysicalMaterial({ color: 0xd4af37 })
    const particle = new THREE.Mesh(box(), original)
    particle.name = 'gold-nanosphere:np-1'
    particle.userData.photoMaterialKind = 'gold-nanoparticle'
    scene.add(particle)

    const swap = swapToFlatMaterials(scene, {
      full: 'flat', cylinders: 'flat', surface: 'flat', atomistic: 'cpk-flat',
    })

    expect(particle.material.name).toBe('photoGoldNanoparticle')
    expect(particle.material.color.getHex()).toBe(0xd4af37)
    expect(particle.material.metalness).toBe(1)
    expect(particle.material.roughness).toBeCloseTo(0.16)
    expect(particle.material.envMapIntensity).toBeGreaterThan(1)
    swap.restore()
    expect(particle.material).toBe(original)
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

  it('applies atomistic photo materials to stick-only bond meshes', () => {
    const scene = new THREE.Scene()
    const sticks = new THREE.InstancedMesh(
      new THREE.CylinderGeometry(1, 1, 1, 8), new THREE.MeshPhongMaterial(), 4)
    sticks.name = 'atomBonds'
    scene.add(sticks)
    swapToFlatMaterials(scene, {
      full: 'flat', cylinders: 'flat', surface: 'flat', atomistic: 'cpk-metallic',
    })
    expect(sticks.material.isMeshPhysicalMaterial).toBe(true)
    expect(sticks.material.metalness).toBe(1.0)
  })

  it('does not mistake hull-prism MeshStandardMaterial for atomistic', () => {
    const scene = new THREE.Scene()
    const hull = new THREE.Mesh(box(), new THREE.MeshStandardMaterial())
    scene.add(hull)
    swapToFlatMaterials(scene, { full: 'metallic', cylinders: 'flat', surface: 'flat', atomistic: 'cpk-flat' })
    expect(hull.material.metalness).toBe(1)
  })

  it('applies cylinder appearance to newer linker and curved-group meshes', () => {
    const scene = new THREE.Scene()
    const linker = new THREE.Mesh(box(), new THREE.MeshLambertMaterial())
    linker.name = 'linkerBindingCylinders'
    const curvedGroup = new THREE.Group()
    curvedGroup.name = 'curvedCylGroup'
    const curvedTube = new THREE.Mesh(box(), new THREE.MeshLambertMaterial())
    curvedGroup.add(curvedTube)
    scene.add(linker, curvedGroup)
    swapToFlatMaterials(scene, { full: 'flat', cylinders: 'metallic', surface: 'flat', atomistic: 'cpk-flat' })
    expect(linker.material.metalness).toBe(1)
    expect(curvedTube.material.metalness).toBe(1)
  })

  it('applies the surface selection to an assembly surface despite its shared-LOD tag', () => {
    const scene = new THREE.Scene()
    const surface = new THREE.InstancedMesh(box(), new THREE.MeshStandardMaterial({ side: THREE.DoubleSide }), 1)
    surface.name = 'assemblySurface'
    surface.userData.sharedLodImpostor = true
    scene.add(surface)
    swapToFlatMaterials(scene, { full: 'flat', cylinders: 'flat', surface: 'glass', atomistic: 'cpk-flat' })
    expect(surface.material.isMeshPhysicalMaterial).toBe(true)
    expect(surface.material.roughness).toBeCloseTo(0.05)
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

  it('preserves depthWrite:false — an overlay must not become an occluder', () => {
    const scene = new THREE.Scene()
    const overlay = new THREE.Mesh(box(), new THREE.MeshPhongMaterial({ depthWrite: false }))
    scene.add(overlay)
    swapToFlatMaterials(scene)
    expect(overlay.material.depthWrite).toBe(false)
  })

  it('photoForceDepthWrite re-opts structure back in — a faded base slab still casts', () => {
    // The slab-opacity slider drops depthWrite to blend correctly (LESSONS D8).
    // Without this opt-in, isShadowExcluded() reads that as "cannot occlude" and
    // silently removes the slabs from the figure's shadow pass.
    const scene = new THREE.Scene()
    const mat = new THREE.MeshPhongMaterial({ transparent: true, opacity: 0.45, depthWrite: false })
    mat.userData.photoForceDepthWrite = true
    const slabs = new THREE.Mesh(box(), mat)
    scene.add(slabs)
    swapToFlatMaterials(scene)
    expect(slabs.material.depthWrite).toBe(true)
  })

  it('re-installs the instanceAlpha patch a fresh material would silently drop', () => {
    // Per-cluster opacity / reference ghosting / mixed representation all fade via
    // an onBeforeCompile patch. makeMaterial builds a brand-new material with no
    // patch, so before this the faded geometry rendered fully OPAQUE in photo mode
    // and in the tiled export.
    const scene = new THREE.Scene()
    const mesh = new THREE.InstancedMesh(box(), new THREE.MeshPhongMaterial(), 4)
    applyInstanceAlphaMaterial(mesh.material)
    scene.add(mesh)
    swapToFlatMaterials(scene)
    expect(mesh.material.onBeforeCompile).toBe(instanceAlphaOnBeforeCompile)
    expect(mesh.material.userData.instanceAlphaPatch).toBe(true)
  })

  it('re-installs the shared assembly vertex patch on photo materials', () => {
    const scene = new THREE.Scene()
    const mesh = new THREE.InstancedMesh(box(), new THREE.MeshPhongMaterial(), 2)
    const install = vi.fn(material => { material.userData.sharedPatchInstalled = true })
    mesh.userData.applySharedInstancing = install
    scene.add(mesh)

    swapToFlatMaterials(scene)

    expect(install).toHaveBeenCalledWith(mesh.material)
    expect(mesh.material.userData.sharedPatchInstalled).toBe(true)
  })

  it('uses the photo material on a shared LOD when its shader can be reinstalled', () => {
    const scene = new THREE.Scene()
    const original = new THREE.MeshLambertMaterial()
    const lod = new THREE.InstancedMesh(box(), original, 2)
    lod.name = 'sharedLodMid'
    lod.userData.sharedLodImpostor = true
    lod.userData.applySharedInstancing = material => { material.userData.sharedPatchInstalled = true }
    scene.add(lod)

    const swapped = swapToFlatMaterials(scene)

    expect(lod.material).not.toBe(original)
    expect(lod.material.isMeshPhysicalMaterial).toBe(true)
    expect(lod.material.userData.sharedPatchInstalled).toBe(true)
    swapped.restore()
    expect(lod.material).toBe(original)
  })

  it('the re-installed patch is transparent AND still depth-writing', () => {
    // transparent: makeMaterial forces transparent:false for non-surface reps, and
    // the src.opacity < 1 carry-over never fires here (the fade is in the attribute,
    // so the material's own opacity is 1). depthWrite: one InstancedMesh holds both
    // faded and opaque instances, and shadow_bounds reads depthWrite:false as
    // "cannot occlude" — dropping it would remove the mesh from the key shadow.
    const scene = new THREE.Scene()
    const mesh = new THREE.InstancedMesh(box(), new THREE.MeshPhongMaterial(), 4)
    applyInstanceAlphaMaterial(mesh.material)
    scene.add(mesh)
    swapToFlatMaterials(scene)
    expect(mesh.material.transparent).toBe(true)
    expect(mesh.material.depthWrite).toBe(true)
  })

  it('does NOT blanket-apply the patch to unpatched meshes', () => {
    const scene = new THREE.Scene()
    const mesh = new THREE.Mesh(box(), new THREE.MeshPhongMaterial())
    scene.add(mesh)
    swapToFlatMaterials(scene)
    expect(mesh.material.onBeforeCompile).not.toBe(instanceAlphaOnBeforeCompile)
    expect(mesh.material.userData.instanceAlphaPatch).toBeUndefined()
  })

  it('restore() puts back the original patched material', () => {
    const scene = new THREE.Scene()
    const mesh = new THREE.InstancedMesh(box(), new THREE.MeshPhongMaterial(), 4)
    applyInstanceAlphaMaterial(mesh.material)
    const original = mesh.material
    scene.add(mesh)
    const swap = swapToFlatMaterials(scene)
    swap.restore()
    expect(mesh.material).toBe(original)
    expect(mesh.material.onBeforeCompile).toBe(instanceAlphaOnBeforeCompile)
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
    // Instance colors are a separate shader channel; enabling geometry vertex
    // colors when no `color` attribute exists would multiply them to black.
    expect(inst.material.vertexColors).toBe(false)
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

  it('leaves an invisible material alone — three\'s gizmo drag plane', () => {
    // The regression: TransformControls adds a 100000×100000 PlaneGeometry whose
    // material is `visible:false`, and it becomes visible in the scene the
    // moment a gizmo attaches (selecting a cluster). A fresh photo material
    // defaults to visible:true, so the swap turned it into a translucent
    // infinite ground plane — and because the new material also defaults to
    // depthWrite:true, isShadowExcluded stopped recognising it as an overlay and
    // it started receiving the key shadow. That is where the accidental "floor"
    // in photo mode came from.
    const scene = new THREE.Scene()
    const drag = new THREE.Mesh(
      new THREE.PlaneGeometry(100000, 100000),
      new THREE.MeshBasicMaterial({ visible: false, side: THREE.DoubleSide, transparent: true, opacity: 0.1 }),
    )
    scene.add(drag)
    const original = drag.material

    const { count } = swapToFlatMaterials(scene)

    expect(count).toBe(0)
    expect(drag.material).toBe(original)
    expect(drag.material.visible).toBe(false)
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

  it('uses renderer-owned bounds for GPU-instanced assembly geometry', () => {
    const authoritative = new THREE.Box3(
      new THREE.Vector3(-10, -20, -30),
      new THREE.Vector3(10, 20, 30),
    )
    const assemblyMode = createPhotoMode({
      ...ctx,
      getPhotoBounds: () => authoritative,
    })

    assemblyMode.activate()
    expect(assemblyMode.getStatus().radius).toBeCloseTo(Math.sqrt(1400), 6)
    assemblyMode.deactivate()
  })

  it('activate() hides the editor lights and deactivate() restores them', () => {
    const editorLight = ctx.scene.children.find(c => c.isPointLight)
    expect(editorLight.visible).toBe(true)

    mode.activate()
    expect(editorLight.visible).toBe(false)

    mode.deactivate()
    expect(editorLight.visible).toBe(true)
  })

  it('enforces one visible shadow source and reports studio ambient separately', () => {
    const editorLight = ctx.scene.children.find(c => c.isPointLight)
    editorLight.castShadow = true
    mode.activate()
    mode.setStudioEnvironment(false)

    // Simulate a subsystem adding a shadow-casting light after photo entry.
    const late = new THREE.SpotLight(0xffffff, 1)
    late.castShadow = true
    ctx.scene.add(late)
    mode.setKeyShadow(true)

    const diagnostics = mode.getDiagnostics()
    expect(diagnostics.shadowCastingLights).toHaveLength(1)
    expect(diagnostics.shadowCastingLights[0].isKey).toBe(true)
    expect(diagnostics.studioEnvironment).toMatchObject({ enabled: false, bound: false })
    expect(diagnostics.figureEffects).toMatchObject({ outline: false, depthCue: false, passEnabled: false })
    expect(late.castShadow).toBe(false)

    mode.deactivate()
    expect(editorLight.castShadow).toBe(true)
    expect(late.castShadow).toBe(true)
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

  it('uses a neutral studio environment for metallic reflections and restores scene state', () => {
    const priorEnv = { fake: 'editor-environment' }
    const studioEnv = { fake: 'studio-pmrem', dispose: vi.fn() }
    ctx.scene.environment = priorEnv
    ctx.scene.environmentIntensity = 0.4
    ctx.scene.environmentRotation.set(0.1, 0.2, 0.3)
    ctx.bakeStudioEnvironment = vi.fn(() => studioEnv)
    const withStudio = createPhotoMode(ctx)

    withStudio.activate()
    expect(ctx.bakeStudioEnvironment).toHaveBeenCalledWith(ctx.renderer)
    expect(ctx.scene.environment).toBe(studioEnv)
    expect(ctx.scene.environmentIntensity).toBe(1)

    withStudio.setStudioEnvironmentIntensity(1.75)
    withStudio.setStudioEnvironmentRotation(90)
    expect(ctx.scene.environmentIntensity).toBe(1.75)
    expect(ctx.scene.environmentRotation.y).toBeCloseTo(Math.PI / 2, 9)

    withStudio.setStudioEnvironment(false)
    expect(ctx.scene.environment).toBeNull()
    withStudio.setStudioEnvironment(true)
    expect(ctx.scene.environment).toBe(studioEnv)
    expect(ctx.bakeStudioEnvironment).toHaveBeenCalledTimes(1)

    withStudio.deactivate()
    expect(ctx.scene.environment).toBe(priorEnv)
    expect(ctx.scene.environmentIntensity).toBe(0.4)
    expect(ctx.scene.environmentRotation.toArray()).toEqual([0.1, 0.2, 0.3, 'XYZ'])
    expect(studioEnv.dispose).toHaveBeenCalledTimes(1)
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

  it('gives shader-instanced assembly meshes a matching shadow-depth material', () => {
    const material = new THREE.MeshLambertMaterial()
    material.onBeforeCompile = shader => {
      shader.vertexShader = shader.vertexShader.replace(
        '#include <begin_vertex>',
        'vec3 transformed = position + vec3(7.0, 0.0, 0.0);',
      )
    }
    const shared = new THREE.InstancedMesh(new THREE.BoxGeometry(1, 1, 1), material, 2)
    shared.name = 'sharedLodMid'
    shared.userData.sharedLodImpostor = true
    ctx.scene.add(shared)

    mode.activate()

    expect(shared.castShadow).toBe(true)
    expect(shared.receiveShadow).toBe(true)
    expect(shared.customDepthMaterial).toBeInstanceOf(THREE.MeshDepthMaterial)
    const shader = {
      uniforms: {},
      vertexShader: '#include <begin_vertex>',
      fragmentShader: '#include <dithering_fragment>',
    }
    shared.customDepthMaterial.onBeforeCompile(shader)
    expect(shader.vertexShader).toContain('position + vec3(7.0')

    mode.deactivate()
    expect(shared.castShadow).toBe(false)
    expect(shared.customDepthMaterial).toBeUndefined()
  })

  it('lets ordinary assembly surfaces use Three’s native instanced shadow pass', () => {
    const surface = new THREE.InstancedMesh(
      new THREE.BoxGeometry(1, 1, 1), new THREE.MeshStandardMaterial(), 2,
    )
    surface.name = 'assemblySurface'
    surface.userData.sharedLodImpostor = true
    ctx.scene.add(surface)
    mode.activate()
    expect(surface.castShadow).toBe(true)
    expect(surface.customDepthMaterial).toBeUndefined()
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
    // Even a whole-texel bias reaches several bead radii on a long origami;
    // use a tenth of that scale so thin DNA remains in the shadow pass.
    mode.activate()
    const key = mode._getKeyLight()
    const R = key.shadow.camera.right          // ortho half-width == bounds radius
    const texel = (2 * R) / key.shadow.mapSize.width
    expect(key.shadow.normalBias).toBeCloseTo(texel * 0.1, 9)
    // ...and stays a small fraction of a CG bead (0.10 nm) at origami scale.
    expect(key.shadow.normalBias).toBeLessThan(0.10)

    mode.setKeyShadowBias(3)
    expect(key.shadow.normalBias).toBeCloseTo(texel * 0.3, 9)
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

  // ── Shadow-catching floor ─────────────────────────────────────────────────

  it('raises a shadow catcher on activate and drops it on deactivate', () => {
    expect(mode.getSettings().floor).toBe(true)
    mode.activate()
    const mesh = mode._getFloor().getMesh()
    expect(mesh).not.toBe(null)
    expect(ctx.scene.children).toContain(mesh)
    // Auto-fitted to the seeded 2x2x2 box: flush with its lowest point.
    expect(mesh.position.y).toBeCloseTo(-1, 6)

    mode.deactivate()
    expect(mode._getFloor()).toBe(null)
    expect(ctx.scene.children.some(o => o.userData?.photoFloor)).toBe(false)
  })

  it('the catcher receives the key shadow — the exclusion list must not blank it', () => {
    // isShadowExcluded(photoFloor) is TRUE (it must never CAST, and must never
    // set the fitted frustum), so falling through _applyMeshShadowFlags would
    // set receiveShadow = !excluded = false on the one mesh whose job is to
    // receive. That is the whole reason for the explicit skip.
    mode.activate()
    const mesh = mode._getFloor().getMesh()
    expect(mesh.receiveShadow).toBe(true)
    expect(mesh.castShadow).toBe(false)
  })

  it('never inflates the fitted shadow frustum', () => {
    // The plane is ~1.25 diagonals across. If it reached computeShadowBounds the
    // radius would jump and the design would end up inside a single texel.
    mode.activate()
    const before = mode.getStatus().radius
    mode.resync()                        // refits the rig with the floor present
    expect(mode.getStatus().radius).toBeCloseTo(before, 6)
  })

  it('setFloor(false) removes it; the key shadow is untouched either way', () => {
    // The difference from photo mode v1, whose shadow rig was GATED on a floor.
    mode.activate()
    mode.setFloor(false)
    expect(mode._getFloor().getMesh()).toBe(null)
    expect(mode._getKeyLight().castShadow).toBe(true)
    mode.setFloor(true)
    expect(mode._getFloor().getMesh()).not.toBe(null)
  })

  it('turning the key shadow off takes the catcher with it — nothing to catch', () => {
    mode.activate()
    mode.setKeyShadow(false)
    expect(mode._getFloor().getMesh()).toBe(null)
    mode.setKeyShadow(true)
    expect(mode._getFloor().getMesh()).not.toBe(null)
  })

  it('floor opacity and gap are live', () => {
    mode.activate()
    mode.setFloorOpacity(0.8)
    expect(mode._getFloor().getMesh().material.opacity).toBeCloseTo(0.8, 6)
    mode.setFloorOffset(12)
    expect(mode._getFloor().getMesh().position.y).toBeCloseTo(-13, 6)   // -1 - 12
  })

  it('setFloorAxis moves the plane to that face of the seeded 2x2x2 box', () => {
    mode.activate()
    expect(mode.getSettings().floorAxis).toBe('-y')
    const mesh = mode._getFloor().getMesh()

    mode.setFloorAxis('+y')
    expect(mode.getSettings().floorAxis).toBe('+y')
    expect(mesh.position.y).toBeCloseTo(1, 6)      // ceiling: box.max.y

    mode.setFloorAxis('-z')
    expect(mesh.position.z).toBeCloseTo(-1, 6)     // wall: box.min.z
    expect(mesh.position.y).toBeCloseTo(0, 6)      // centred in Y now

    // The gap still means "outward", whichever face is selected.
    mode.setFloorOffset(5)
    expect(mesh.position.z).toBeCloseTo(-6, 6)
  })

  it('setFloorAxis rejects an unknown axis instead of breaking the plane', () => {
    mode.activate()
    mode.setFloorAxis('+x')
    mode.setFloorAxis('diagonal')
    expect(mode.getSettings().floorAxis).toBe('+x')
    expect(mode._getFloor().getMesh().position.x).toBeCloseTo(1, 6)
  })

  it('getFloorReach feeds the adaptive far clip only while a floor exists', () => {
    expect(mode.getFloorReach()).toBe(null)
    mode.activate()
    const r = mode.getFloorReach()
    expect(r.reach).toBeGreaterThan(0)
    mode.setFloor(false)
    expect(mode.getFloorReach()).toBe(null)
    mode.deactivate()
    expect(mode.getFloorReach()).toBe(null)
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

  it('resetFOV goes back to the 55 degree default, clearing parallel, and dollies in', () => {
    ctx.controls = { target: new THREE.Vector3(0, 0, 0), update: vi.fn() }
    const m2 = createPhotoMode(ctx)
    ctx.camera.position.set(0, 0, 40)
    m2.activate()
    m2.setParallel(true)
    const atLongLens = ctx.camera.position.length()
    m2.resetFOV()
    expect(ctx.camera.fov).toBe(55)
    expect(m2.getSettings().fov).toBe(55)
    expect(m2.getSettings().parallel).toBe(false)
    expect(ctx.camera.position.length()).toBeLessThan(atLongLens)   // dollied back IN
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
