import { describe, it, expect, vi } from 'vitest'
import * as THREE from 'three'
import {
  fibonacciSphereDirections,
  tileLayout,
  configureShadowCamera,
  createMaterialOcclusion,
  MultishadowAOPass,
  MAX_DIRECTIONS,
} from './multishadow_ao.js'

describe('fibonacciSphereDirections', () => {
  it('returns exactly n unit vectors', () => {
    for (const n of [1, 16, 64, 128]) {
      const dirs = fibonacciSphereDirections(n)
      expect(dirs).toHaveLength(n)
      for (const [x, y, z] of dirs) {
        expect(Math.sqrt(x * x + y * y + z * z)).toBeCloseTo(1, 6)
      }
    }
  })

  it('covers the sphere without favouring a hemisphere', () => {
    // A biased set would tilt the occlusion like a directional light.
    const dirs = fibonacciSphereDirections(64)
    const mean = dirs.reduce((a, d) => [a[0] + d[0], a[1] + d[1], a[2] + d[2]], [0, 0, 0])
      .map(v => v / dirs.length)
    for (const c of mean) expect(Math.abs(c)).toBeLessThan(0.05)
  })

  it('never emits an exact pole (degenerate lookAt)', () => {
    for (const [, y] of fibonacciSphereDirections(64)) expect(Math.abs(y)).toBeLessThan(1)
  })
})

describe('tileLayout', () => {
  it('packs 64 maps into an 8x8 grid', () => {
    expect(tileLayout(64, 1024)).toEqual({ grid: 8, tile: 128, size: 1024 })
    expect(tileLayout(64, 4096)).toEqual({ grid: 8, tile: 512, size: 4096 })
  })

  it('never leaves a partial tile — size is always grid × tile', () => {
    for (const n of [1, 7, 16, 32, 50, 64, 128, 256]) {
      for (const m of [512, 1024, 4096]) {
        const { grid, tile, size } = tileLayout(n, m)
        expect(size).toBe(grid * tile)
        expect(grid * grid).toBeGreaterThanOrEqual(n)   // every direction has a cell
        expect(size).toBeLessThanOrEqual(m)
      }
    }
  })
})

describe('configureShadowCamera', () => {
  const center = new THREE.Vector3(3, -2, 5)
  const radius = 10

  it('maps every point inside the bounding sphere into [0,1]³', () => {
    const cam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 2)
    const probes = [
      center.clone(),
      ...[[radius, 0, 0], [-radius, 0, 0], [0, radius, 0], [0, -radius, 0], [0, 0, radius], [0, 0, -radius]]
        .map(v => center.clone().add(new THREE.Vector3(...v))),
    ]
    for (const d of fibonacciSphereDirections(24)) {
      const m = configureShadowCamera(cam, d, center, radius)
      for (const p of probes) {
        const s = p.clone().applyMatrix4(m)
        for (const c of [s.x, s.y, s.z]) {
          expect(c).toBeGreaterThanOrEqual(0)
          expect(c).toBeLessThanOrEqual(1)
        }
      }
    }
  })

  it('puts the sphere centre at the middle of the shadow map', () => {
    const cam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 2)
    const s = center.clone().applyMatrix4(configureShadowCamera(cam, [0, 0, 1], center, radius))
    expect(s.x).toBeCloseTo(0.5, 5)
    expect(s.y).toBeCloseTo(0.5, 5)
    expect(s.z).toBeCloseTo(0.5, 5)
  })

  it('does not degenerate when the direction is parallel to world up', () => {
    const cam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 2)
    for (const d of [[0, 1, 0], [0, -1, 0]]) {
      const m = configureShadowCamera(cam, d, center, radius)
      expect(m.elements.every(Number.isFinite)).toBe(true)
    }
  })
})

describe('MultishadowAOPass', () => {
  const makePass = (opts) => new MultishadowAOPass(
    new THREE.Scene(), new THREE.PerspectiveCamera(55, 1, 0.1, 2000), opts,
  )

  // Enough of a renderer for bake() to run headlessly: render targets and the
  // matrix DataTexture are descriptors until something draws them.
  const fakeRenderer = () => ({
    autoClear: true,
    shadowMap: { enabled: true, autoUpdate: true, needsUpdate: false },
    getRenderTarget: () => null,
    setRenderTarget() {},
    clear() {},
    render() {},
  })

  it('defaults to 64 directions at an origami-appropriate map size', () => {
    // 4096, not ChimeraX's 1024: at 64 directions 1024 gives 128 px per
    // direction ≈ 2.3 nm/texel on a 150 nm design — coarser than a duplex.
    expect(makePass().getSettings()).toEqual({
      directions: 64, mapSize: 4096, intensity: 1.0, bias: 0.01,
    })
  })

  it('starts stale and not ready — nothing is drawn before a bake', () => {
    const pass = makePass()
    expect(pass.isStale()).toBe(true)
    expect(pass.isReady()).toBe(false)
  })

  it('drives the real uniforms, not just the settings object', () => {
    const pass = makePass()
    pass.setIntensity(0.4)
    pass.setBias(0.025)
    expect(pass.uniforms.uIntensity.value).toBeCloseTo(0.4, 6)
    expect(pass.uniforms.uBias.value).toBeCloseTo(0.025, 6)
  })

  it('invalidates the bake when the direction count or map size changes', () => {
    const pass = makePass()
    pass._stale = false
    pass.setDirections(128)
    expect(pass.isStale()).toBe(true)

    pass._stale = false
    pass.setMapSize(8192)
    expect(pass.isStale()).toBe(true)
  })

  it('does NOT invalidate for intensity or bias — they apply at sample time', () => {
    const pass = makePass()
    pass._stale = false
    pass.setIntensity(0.2)
    pass.setBias(0.03)
    expect(pass.isStale()).toBe(false)
  })

  it('clamps the direction count to the shader loop ceiling', () => {
    const pass = makePass()
    pass.setDirections(10_000)
    expect(pass.getSettings().directions).toBe(MAX_DIRECTIONS)
  })

  it('NEVER disables renderer.shadowMap.enabled during the bake', () => {
    // Regression: `shadowMapEnabled` is a PROGRAM parameter and three does not
    // re-check it in setProgram. The bake is where every material first
    // compiles, so flipping the flag off compiles them all without
    // USE_SHADOWMAP — and the key-light shadow then never appears again.
    const scene = new THREE.Scene()
    scene.add(new THREE.Mesh(new THREE.BoxGeometry(2, 2, 2), new THREE.MeshPhongMaterial()))
    const pass = new MultishadowAOPass(scene, new THREE.PerspectiveCamera(55, 1, 0.1, 2000), { directions: 16 })

    const seen = []
    const r = fakeRenderer()
    r.render = () => seen.push({ enabled: r.shadowMap.enabled, autoUpdate: r.shadowMap.autoUpdate })

    pass.bake(r)

    expect(seen.length).toBe(16)
    expect(seen.every(s => s.enabled === true)).toBe(true)      // compile WITH shadows
    expect(seen.every(s => s.autoUpdate === false)).toBe(true)  // but do not re-render the map
    expect(r.shadowMap.enabled).toBe(true)                      // handed back untouched
    expect(r.shadowMap.autoUpdate).toBe(true)
    expect(r.shadowMap.needsUpdate).toBe(false)
  })

  it('bakes headlessly and reports what it did', () => {
    const scene = new THREE.Scene()
    scene.add(new THREE.Mesh(new THREE.BoxGeometry(2, 2, 2), new THREE.MeshPhongMaterial()))
    const pass = new MultishadowAOPass(scene, new THREE.PerspectiveCamera(55, 1, 0.1, 2000), { directions: 16 })
    pass.bake(fakeRenderer())

    expect(pass.isReady()).toBe(true)
    expect(pass.isStale()).toBe(false)
    expect(pass.lastBake().count).toBe(16)
    expect(pass.lastBake().radius).toBeGreaterThan(0)
    // 5 texels per direction: 4 matrix columns + the light direction.
    expect(pass._matrixTex.image.data).toHaveLength(16 * 5 * 4)
    expect(pass.uniforms.uGrid.value).toBe(4)
  })

  it('packs each direction as 4 matrix columns plus the light vector', () => {
    const scene = new THREE.Scene()
    scene.add(new THREE.Mesh(new THREE.BoxGeometry(2, 2, 2), new THREE.MeshPhongMaterial()))
    const pass = new MultishadowAOPass(scene, new THREE.PerspectiveCamera(55, 1, 0.1, 2000), { directions: 16 })
    pass.bake(fakeRenderer())

    const data = pass._matrixTex.image.data
    const dirs = fibonacciSphereDirections(16)
    for (let i = 0; i < 16; i++) {
      const o = i * 20
      expect([data[o + 16], data[o + 17], data[o + 18]]).toEqual(dirs[i].map(v => Math.fround(v)))
      expect(data[o + 15]).toBeCloseTo(1, 5)   // w row of bias×proj×view
    }
  })

  it('bake() on an empty scene marks itself not-ready rather than throwing', () => {
    const pass = makePass()
    expect(() => pass.bake(null)).not.toThrow()
    expect(pass.isReady()).toBe(false)
  })

  it('re-stales itself when meshes are replaced without anyone announcing it', () => {
    // The representation-switch path: no store field moves, so the periodic
    // fingerprint check is the only thing that notices.
    const scene = new THREE.Scene()
    const first = new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), new THREE.MeshPhongMaterial())
    scene.add(first)
    const pass = new MultishadowAOPass(scene, new THREE.PerspectiveCamera(55, 1, 0.1, 2000), { directions: 16 })
    const renderer = fakeRenderer()
    pass.bake(renderer)
    const firstBake = pass.lastBake()

    for (let i = 0; i < 200; i++) pass.ensureBaked(renderer)
    expect(pass.lastBake()).toEqual(firstBake)

    scene.remove(first)
    scene.add(new THREE.Mesh(new THREE.SphereGeometry(3, 8, 6), new THREE.MeshPhongMaterial()))
    for (let i = 0; i < 40; i++) pass.ensureBaked(renderer)
    expect(pass.lastBake().radius).not.toBeCloseTo(firstBake.radius, 6)
  })

  it('declares a loop ceiling the shader can actually compile against', () => {
    // GLSL ES 1.00 needs a constant bound; the runtime count breaks out early.
    expect(makePass()._material.fragmentShader).toContain(`i < ${MAX_DIRECTIONS}`)
    expect(makePass()._material.fragmentShader).toContain('if (i >= uCount) break;')
  })
})

describe('createMaterialOcclusion', () => {
  const makePass = () => new MultishadowAOPass(
    new THREE.Scene(), new THREE.PerspectiveCamera(55, 1, 0.1, 2000),
  )

  /** Run a patched material's onBeforeCompile the way three does at compile time. */
  function compile(material) {
    const shader = {
      uniforms: {},
      vertexShader:   '#include <common>\nvoid main(){\n#include <worldpos_vertex>\n}',
      fragmentShader: '#include <common>\nvoid main(){\n#include <aomap_fragment>\n}',
    }
    material.onBeforeCompile(shader, null)
    return shader
  }

  it('shares the bake uniforms BY REFERENCE with the pass', () => {
    const pass = makePass()
    const occ = createMaterialOcclusion(pass)
    for (const k of ['tShadow', 'tMatrices', 'uCount', 'uRows', 'uGrid', 'uTileUV', 'uTileInset', 'uBias']) {
      expect(occ.uniforms[k]).toBe(pass.uniforms[k])
    }
  })

  it('keeps its own intensity, separate from the pass composite gate', () => {
    const pass = makePass()
    const occ = createMaterialOcclusion(pass)
    occ.setIntensity(0.7)
    expect(occ.uniforms.uMSIntensity.value).toBeCloseTo(0.7, 6)
    expect(pass.uniforms.uIntensity).not.toBe(occ.uniforms.uMSIntensity)
  })

  it('multiplies INDIRECT diffuse only — key and fill must stay untouched', () => {
    // The whole point of the material path under `lighting full`.
    const occ = createMaterialOcclusion(makePass())
    const mat = new THREE.MeshPhysicalMaterial()
    occ.apply(mat)
    const { fragmentShader } = compile(mat)

    expect(fragmentShader).toContain('reflectedLight.indirectDiffuse *= ambientOcclusion')
    expect(fragmentShader).not.toContain('reflectedLight.directDiffuse *=')
    expect(fragmentShader).not.toContain('reflectedLight.directSpecular *=')
  })

  it('injects the occlusion lookup and an instancing-aware world position', () => {
    const occ = createMaterialOcclusion(makePass())
    const mat = new THREE.MeshPhysicalMaterial()
    occ.apply(mat)
    const shader = compile(mat)

    expect(shader.fragmentShader).toContain('float msOcclusion(')
    expect(shader.vertexShader).toContain('vMSWorldPos =')
    // Beads/atoms/cylinders are all InstancedMesh, and three's own worldpos
    // chunk is only conditionally compiled.
    expect(shader.vertexShader).toContain('instanceMatrix * _msWorld')
    // Never leaves three's chunk in place — that would silently no-op the patch.
    expect(shader.fragmentShader).not.toContain('#include <aomap_fragment>')
  })

  it('gives patched materials a distinct program cache key', () => {
    const occ = createMaterialOcclusion(makePass())
    const mat = new THREE.MeshPhysicalMaterial()
    occ.apply(mat)
    expect(mat.customProgramCacheKey()).toBe('multishadowAO')
  })

  it('is idempotent — resync() re-patching must not double-inject', () => {
    const occ = createMaterialOcclusion(makePass())
    const mat = new THREE.MeshPhysicalMaterial()
    occ.apply(mat); occ.apply(mat); occ.apply(mat)
    const { fragmentShader } = compile(mat)
    const hits = fragmentShader.split('reflectedLight.indirectDiffuse *= ambientOcclusion').length - 1
    expect(hits).toBe(1)
  })

  it('preserves a pre-existing onBeforeCompile instead of clobbering it', () => {
    const occ = createMaterialOcclusion(makePass())
    const mat = new THREE.MeshPhysicalMaterial()
    const prior = vi.fn()
    mat.onBeforeCompile = prior
    occ.apply(mat)
    compile(mat)
    expect(prior).toHaveBeenCalledTimes(1)
  })

  it('syncCamera loads the view→world rotation the fragment needs', () => {
    const occ = createMaterialOcclusion(makePass())
    const cam = new THREE.PerspectiveCamera(55, 1, 0.1, 2000)
    cam.position.set(10, 0, 0)
    cam.lookAt(0, 0, 0)
    occ.syncCamera(cam)

    const back = new THREE.Vector3(0, 0, 1).applyMatrix3(occ.uniforms.uMSViewToWorld.value)
    expect(back.x).toBeCloseTo(1, 5)
    expect(back.y).toBeCloseTo(0, 5)
    expect(back.z).toBeCloseTo(0, 5)
  })
})
