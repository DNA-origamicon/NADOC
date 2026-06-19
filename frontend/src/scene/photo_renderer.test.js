/**
 * Oracle suite for scene/photo_renderer.js (the photo-mode controller).
 *
 * Closes the AF-PHOTO automation gap: photo mode's ~45 setters were the de-facto
 * automation API (window.__photoRenderer) but had ZERO coverage — no proof any
 * option actually takes effect. These tests follow the anti-shovel rule: each
 * oracle reads the REAL Three.js object the setter drives (a scene-graph light,
 * a material param, a camera.fov, renderer.toneMapping, a composer pass), NOT
 * getSettings() — which only echoes stored intent and would be a passthrough.
 *
 * jsdom has no WebGL, so the composer is mocked (it constructs GL-adjacent passes)
 * and activate() runs with environment:'off' (no PMREM bake). What needs real
 * pixels — PMREM-baked env texture, bloom/tone-map *look*, the yellow/purple
 * no-tint regression — lives in the P-C / MV-PHOTO e2e tier, not here.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import * as THREE from 'three'

// ── Mock the GL-adjacent collaborators ────────────────────────────────────────
vi.mock('../ui/toast.js', () => ({ showToast: vi.fn() }))

vi.mock('./photo_renderer/floor.js', () => ({
  createFloor: () => ({
    build: vi.fn(),
    dispose: vi.fn(),
    getLastBBox: () => null,
    getReach: () => null,
  }),
}))

// A controllable composer handle: passes are plain objects with the same fields
// the real ones expose, so getComposerState() reads them exactly as it would the
// real composer. A fresh handle per activate (the real one is disposed on exit).
let lastComposer = null
vi.mock('./photo_renderer/post_processing.js', () => ({
  createComposer: vi.fn(() => {
    lastComposer = {
      composer: { render: vi.fn() },
      bloomPass: { enabled: false, strength: 0.5, radius: 0.4, threshold: 0.85 },
      ssaoPass: { enabled: true, setSize: vi.fn() },
      inscatterPass: {
        enabled: false,
        setSize: vi.fn(), setLights: vi.fn(), setMistParams: vi.fn(), setNoiseParams: vi.fn(),
      },
      setSize: vi.fn(),
      dispose: vi.fn(),
    }
    return lastComposer
  }),
}))

import { createPhotoRenderer } from './photo_renderer.js'

// ── Harness ───────────────────────────────────────────────────────────────────
function makeFakeRenderer() {
  return {
    toneMapping: THREE.NoToneMapping,
    toneMappingExposure: 1.0,
    shadowMap: { enabled: false, type: null },
    capabilities: { maxTextureSize: 4096 },
    domElement: { width: 800, height: 600 },
    getClearColor: (t) => t,
    getClearAlpha: () => 0,
    setClearColor: vi.fn(),
    getPixelRatio: () => 1,
    getSize: (v) => v.set(800, 600),
    setRenderTarget: vi.fn(),
    resetState: vi.fn(),
    render: vi.fn(),
  }
}

function seedMeshes(scene) {
  const std = () => new THREE.MeshStandardMaterial()
  const mk = (name, mat) => {
    const m = new THREE.Mesh(new THREE.BoxGeometry(), mat)
    m.name = name
    scene.add(m)
    return m
  }
  const meshes = {
    full: mk('backboneSpheres', std()),
    cyl: mk('helixCylinders', std()),
    surf: mk('dna-surface', new THREE.MeshStandardMaterial({ side: THREE.DoubleSide })),
    atom: mk('atoms', std()),  // unmapped name + MeshStandardMaterial → inferred 'atomistic'
  }
  // Fluorophore InstancedMesh with per-instance colours.
  const fl = new THREE.InstancedMesh(new THREE.SphereGeometry(), std(), 3)
  fl.name = 'extensionFluorophores'
  const m = new THREE.Matrix4()
  for (let i = 0; i < 3; i++) {
    fl.setMatrixAt(i, m.makeTranslation(i, 0, 0))
    fl.setColorAt(i, new THREE.Color(1, 0, 0))
  }
  scene.add(fl)
  meshes.fluoro = fl
  return meshes
}

function setup(initial = {}) {
  const scene = new THREE.Scene()
  const camera = new THREE.PerspectiveCamera(55, 1, 0.1, 2000)
  const renderer = makeFakeRenderer()
  const meshes = seedMeshes(scene)
  const sceneCtx = {
    scene, camera, renderer,
    setRenderFn: vi.fn(), resetRenderFn: vi.fn(),
  }
  const pr = createPhotoRenderer(sceneCtx)
  // Set the env SOURCE to 'off' before activate so no PMREM bake runs (jsdom has
  // no WebGL). activate({environment:'off'}) alone only sets _settings, not the
  // source type — setEnvironment is what drives _envSourceType.
  pr.setEnvironment('off')
  pr.activate({ environment: 'off', ...initial })
  return { pr, scene, camera, renderer, meshes }
}

const group = (scene, name) => scene.getObjectByName(name)

beforeEach(() => { lastComposer = null })

// ── Tier P-A: per-setter effect oracles (read the real object) ────────────────
describe('P-A — tone mapping (R1)', () => {
  it('activate switches the shared renderer to ACES filmic + exposure', () => {
    const { renderer } = setup()
    expect(renderer.toneMapping).toBe(THREE.ACESFilmicToneMapping)
    expect(renderer.toneMappingExposure).toBe(1.0)
  })

  it('deactivate restores the live editor tone mapping', () => {
    const { pr, renderer } = setup()
    pr.deactivate()
    expect(renderer.toneMapping).toBe(THREE.NoToneMapping)
  })

  it('setExposure drives renderer.toneMappingExposure (not just settings)', () => {
    const { pr, renderer } = setup()
    pr.setExposure(1.8)
    expect(renderer.toneMappingExposure).toBeCloseTo(1.8)
    expect(pr.getComposerState().exposure).toBeCloseTo(1.8)
  })
})

describe('P-A — lighting rig', () => {
  it('setLighting installs the preset ambient + directionals in photoLights', () => {
    const { pr, scene } = setup()
    pr.setLighting('dramatic')  // ambient 0.05 + 2 directionals
    const rig = group(scene, 'photoLights')
    const amb = rig.children.filter(c => c.isAmbientLight)
    const dir = rig.children.filter(c => c.isDirectionalLight)
    expect(amb).toHaveLength(1)
    expect(amb[0].intensity).toBeCloseTo(0.05)
    expect(dir).toHaveLength(2)
  })

  it('setLightingDirection rotates the rig (YXZ Euler from yaw/pitch)', () => {
    const { pr, scene } = setup()
    pr.setLightingDirection(90, 30)
    const rig = group(scene, 'photoLights')
    expect(rig.rotation.order).toBe('YXZ')
    expect(rig.rotation.y).toBeCloseTo(Math.PI / 2)       // yaw
    expect(rig.rotation.x).toBeCloseTo(THREE.MathUtils.degToRad(30)) // pitch
  })
})

describe('P-A — materials', () => {
  it('setMaterialPreset(full, metallic) drives metalness on the full mesh', () => {
    const { pr, meshes } = setup()
    pr.setMaterialPreset('full', 'metallic')
    expect(meshes.full.material.metalness).toBe(1.0)
    expect(meshes.full.material.roughness).toBeCloseTo(0.30)
  })

  it('setMaterialPreset(cylinders, glossy) drives clearcoat on the cylinder mesh', () => {
    const { pr, meshes } = setup()
    pr.setMaterialPreset('cylinders', 'glossy')
    expect(meshes.cyl.material.clearcoat).toBeCloseTo(0.5)
  })

  it('setTranslucency drives transmission on full/cylinders only', () => {
    const { pr, meshes } = setup()
    pr.setTranslucency(0.5)
    expect(meshes.full.material.transmission).toBeCloseTo(0.5)
    expect(meshes.cyl.material.transmission).toBeCloseTo(0.5)
  })
})

describe('P-A — fluorophores', () => {
  it('setFluorophoreEmissive spawns one PointLight per instance + emissive material', () => {
    const { pr, scene, meshes } = setup()
    pr.setFluorophoreEmissive(true, 8)
    expect(meshes.fluoro.material.emissiveIntensity).toBe(8)
    const lights = group(scene, 'photoFluoroLights')
    expect(lights.children.filter(c => c.isPointLight)).toHaveLength(3)
  })

  it('setFluorophoreIntensity scales each PointLight by the gain', () => {
    const { pr, scene } = setup()
    pr.setFluorophoreEmissive(true, 5)
    pr.setFluorophoreIntensity(3)
    const lights = group(scene, 'photoFluoroLights').children.filter(c => c.isPointLight)
    expect(lights[0].intensity).toBeCloseTo(3 * 12.0)  // _FLUORO_LIGHT_GAIN
  })

  it('R5: emissive self-glow is clamped, but the PointLight keeps the full range', () => {
    const { pr, scene, meshes } = setup()
    pr.setFluorophoreEmissive(true, 100)  // maxed slider
    // self-emission (feeds bloom) is capped at FLUORO_EMISSIVE_MAX (25)
    expect(meshes.fluoro.material.emissiveIntensity).toBe(25)
    // illumination (reflections) is NOT capped — the user-requested 0..100 range
    const lights = group(scene, 'photoFluoroLights').children.filter(c => c.isPointLight)
    expect(lights[0].intensity).toBeCloseTo(100 * 12.0)
  })
})

describe('P-A — Sun = truly sole (R2)', () => {
  it('sun on hides the preset rig and drops fluorophore PointLights', () => {
    const { pr, scene } = setup()
    pr.setFluorophoreEmissive(true, 5)
    expect(group(scene, 'photoFluoroLights').children).toHaveLength(3)
    pr.setSun(true)
    expect(group(scene, 'photoLights').visible).toBe(false)
    expect(group(scene, 'photoSunLight')).toBeTruthy()
    // fluoro lights cleared while the sun owns the scene
    const fl = group(scene, 'photoFluoroLights')
    expect(fl ? fl.children.filter(c => c.isPointLight).length : 0).toBe(0)
  })

  it('sun off restores the rig and respawns fluorophore lights', () => {
    const { pr, scene } = setup()
    pr.setFluorophoreEmissive(true, 5)
    pr.setSun(true)
    pr.setSun(false)
    expect(group(scene, 'photoLights').visible).toBe(true)
    expect(group(scene, 'photoSunLight')).toBeFalsy()
    expect(group(scene, 'photoFluoroLights').children.filter(c => c.isPointLight)).toHaveLength(3)
  })
})

describe('P-A — camera / background / post-processing passes', () => {
  it('setFOV drives camera.fov', () => {
    const { pr, camera } = setup()
    pr.setFOV(40)
    expect(camera.fov).toBe(40)
  })

  it('setBackground(black) sets an opaque scene background colour', () => {
    const { pr, scene, renderer } = setup()
    pr.setBackground('black')
    expect(scene.background).toBeInstanceOf(THREE.Color)
    expect(scene.background.getHex()).toBe(0x000000)
    expect(renderer.setClearColor).toHaveBeenCalled()
  })

  it('setBloom / setSSAO / setEnvironmentalEffect flip the real composer passes', () => {
    const { pr } = setup()
    pr.setBloom(true, 0.8)
    pr.setSSAO(false)
    pr.setEnvironmentalEffect('mist')
    const cs = pr.getComposerState()
    expect(cs.bloom).toBe(true)
    expect(cs.bloomStrength).toBeCloseTo(0.8)
    expect(cs.ssao).toBe(false)
    expect(cs.mist).toBe(true)
  })
})

// ── Tier P-B: the automation contract (every option reachable + persisted) ────
describe('P-B — automation contract', () => {
  it('getSettings returns a copy (mutation does not leak into the controller)', () => {
    const { pr } = setup()
    const s = pr.getSettings()
    s.exposure = 99
    expect(pr.getSettings().exposure).not.toBe(99)
  })

  // Drive every option through its setter and prove getSettings reflects it —
  // this IS the "all photomode options are settable through the API" proof.
  const CASES = [
    ['setLighting', ['flat'], 'lighting', 'flat'],
    ['setMaterialPreset', ['full', 'glossy'], 'full', 'glossy'],
    ['setMaterialPreset', ['cylinders', 'metallic'], 'cylinders', 'metallic'],
    ['setMaterialPreset', ['surface', 'glass'], 'surface', 'glass'],
    ['setMaterialPreset', ['atomistic', 'cpk-glossy'], 'atomistic', 'cpk-glossy'],
    ['setTranslucency', [0.7], 'translucency', 0.7],
    ['setExposure', [1.5], 'exposure', 1.5],
    ['setFOV', [42], 'fov', 42],
    ['setBackground', ['white'], 'bgType', 'white'],
    ['setSSAO', [false], 'ssao', false],
    ['setSun', [true], 'sun', true],
    ['setSunAzimuth', [200], 'sunAzimuth', 200],
    ['setSunElevation', [60], 'sunElevation', 60],
    ['setSunStrength', [2.2], 'sunStrength', 2.2],
    ['setFloor', ['-y'], 'floor', '-y'],
    ['setFloorMaterial', ['glossy'], 'floorMaterial', 'glossy'],
    ['setFloorOpacity', [0.5], 'floorOpacity', 0.5],
    ['setMistDensity', [0.12], 'mistDensity', 0.12],
    ['setMistHaloIntensity', [2], 'mistHaloIntensity', 2],
    ['setEnvironmentalEffect', ['mist'], 'envEffect', 'mist'],
    ['setFluorophoreIntensity', [9], 'fluorophoreIntensity', 9],
  ]

  it.each(CASES)('%s(%o) → getSettings.%s reflects the value', (fn, args, key, expected) => {
    const { pr } = setup()
    pr[fn](...args)
    expect(pr.getSettings()[key]).toEqual(expected)
  })

  it('setBloom persists enabled + strength into getSettings', () => {
    const { pr } = setup()
    pr.setBloom(true, 1.2)
    const s = pr.getSettings()
    expect(s.bloom).toBe(true)
    expect(s.bloomStrength).toBeCloseTo(1.2)
  })

  it('every CASES setting key exists in the default getSettings snapshot', () => {
    const { pr } = setup()
    const keys = Object.keys(pr.getSettings())
    for (const [, , key] of CASES) expect(keys).toContain(key)
  })
})
