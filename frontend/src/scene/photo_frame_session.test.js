/**
 * beginFrameSession — the offscreen render session behind the tiled PNG export
 * and the photo-mode video export.
 *
 * Lives in its own file because it needs `three`'s WebGLRenderer and the
 * postprocessing passes MODULE-MOCKED (vitest module mocks are file-scoped, and
 * photo_mode.test.js's 100-odd cases want the real ones).
 *
 * The load-bearing assertion is `renders N frames from ONE offscreen renderer`.
 * That is the entire reason this function exists rather than a loop over
 * renderToBlob: browsers block new WebGL contexts after ~30, so a per-frame
 * context dies partway through any real animation.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import * as THREE from 'three'

// ── Module mocks ─────────────────────────────────────────────────────────────
// Only WebGLRenderer is replaced; everything else in three stays real, because
// the mode leans on Vector3/Quaternion/Box3/Scene maths throughout.

const rendererCtor = vi.fn()

vi.mock('three', async (importOriginal) => {
  const actual = await importOriginal()
  class FakeWebGLRenderer {
    constructor(opts) {
      rendererCtor(opts)
      this.capabilities = { maxTextureSize: 4096, isWebGL2: true }
      this.shadowMap = { enabled: false, type: null, autoUpdate: true }
      this.toneMapping = actual.NoToneMapping
      this.toneMappingExposure = 1
      this.disposed = false
    }
    setPixelRatio() {}
    setSize() {}
    setClearColor() {}
    getContext() { return null }
    render() {}
    resetState() {}
    dispose() { this.disposed = true }
  }
  return { ...actual, WebGLRenderer: FakeWebGLRenderer }
})

const composerDispose = vi.fn()
vi.mock('three/addons/postprocessing/EffectComposer.js', () => ({
  EffectComposer: class {
    constructor() { this.passes = [] }
    addPass(p) { this.passes.push(p) }
    setSize() {}
    render() { this.rendered = (this.rendered ?? 0) + 1 }
    dispose() { composerDispose() }
  },
}))
vi.mock('three/addons/postprocessing/RenderPass.js', () => ({ RenderPass: class {} }))
vi.mock('three/addons/postprocessing/SMAAPass.js',   () => ({ SMAAPass: class {} }))
vi.mock('three/addons/postprocessing/OutputPass.js', () => ({ OutputPass: class {} }))

const { createPhotoMode } = await import('./photo_mode.js')

// ── Harness ──────────────────────────────────────────────────────────────────

function makeSceneCtx() {
  const scene  = new THREE.Scene()
  const camera = new THREE.PerspectiveCamera(55, 1, 0.1, 2000)
  camera.position.set(0, 0, 50)
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
    renderFn: null, resizeFn: null,
    setRenderFn(fn) { ctx.renderFn = fn },
    resetRenderFn() { ctx.renderFn = null },
    setResizeCallback(fn) { ctx.resizeFn = fn },
    clearResizeCallback() { ctx.resizeFn = null },
  }
  return ctx
}

/** jsdom canvases have no 2D context and no toBlob — stub just enough. */
function stubCanvas2D() {
  HTMLCanvasElement.prototype.getContext = function () {
    return { drawImage: vi.fn(), clearRect: vi.fn() }
  }
  HTMLCanvasElement.prototype.toBlob = function (cb) { cb(new Blob(['x'], { type: 'image/png' })) }
}

describe('beginFrameSession', () => {
  let ctx, mode

  beforeEach(() => {
    rendererCtor.mockClear()
    composerDispose.mockClear()
    stubCanvas2D()
    ctx = makeSceneCtx()
    ctx.scene.add(new THREE.Mesh(new THREE.BoxGeometry(2, 2, 2), new THREE.MeshPhongMaterial()))
    mode = createPhotoMode(ctx)
  })

  it('refuses when the mode is not active', () => {
    expect(() => mode.beginFrameSession(100, 100)).toThrow(/active/)
  })

  it('renders N frames from ONE offscreen renderer', async () => {
    mode.activate()
    rendererCtor.mockClear()                 // ignore anything activate() built

    const session = mode.beginFrameSession(640, 480)
    // One probe renderer + one offscreen renderer, and that is the whole budget.
    const afterOpen = rendererCtor.mock.calls.length
    expect(afterOpen).toBe(2)

    for (let i = 0; i < 40; i++) await session.renderFrame()

    // 40 frames — well past the ~30-context browser limit that killed the
    // renderToBlob-per-frame approach. Still 2.
    expect(rendererCtor.mock.calls.length).toBe(afterOpen)
    session.dispose()
  })

  it('the per-frame renderToBlob loop this replaced would blow the context budget', async () => {
    // The discriminator for the test above: same 40 frames, the OLD way. Each
    // renderToBlob is its own probe + offscreen context, so this is 80 — and a
    // browser stops handing them out around 30 ("Web page caused context loss
    // and was blocked"), which is why beginFrameSession exists at all.
    mode.activate()
    rendererCtor.mockClear()
    for (let i = 0; i < 40; i++) await mode.renderToBlob(320, 240)
    expect(rendererCtor.mock.calls.length).toBe(80)
    expect(rendererCtor.mock.calls.length).toBeGreaterThan(30)
  })

  it('renderFrame() returns a PNG blob and restores the camera each frame', async () => {
    mode.activate()
    const session = mode.beginFrameSession(640, 480)
    const aspect = ctx.camera.aspect
    const blob = await session.renderFrame()

    expect(blob).toBeInstanceOf(Blob)
    expect(blob.type).toBe('image/png')
    expect(ctx.camera.aspect).toBe(aspect)               // restored in the finally
    expect(ctx.camera.view?.enabled).toBeFalsy()          // clearViewOffset()
    session.dispose()
  })

  it('tiles anything above the GPU max texture size', () => {
    mode.activate()
    // maxTextureSize is 4096 in the fake; 300 DPI is 4200×2970.
    expect(mode.beginFrameSession(4200, 2970).tiles).toBe(2)
    expect(mode.beginFrameSession(1920, 1080).tiles).toBe(1)
  })

  it('renderFrame() after dispose() throws, and dispose() is idempotent', async () => {
    mode.activate()
    const session = mode.beginFrameSession(320, 240)
    session.dispose()
    session.dispose()                                // must not throw
    expect(composerDispose).toHaveBeenCalledTimes(1)
    await expect(session.renderFrame()).rejects.toThrow(/dispose/)
  })

  it('resyncs when the mesh set changes between frames', async () => {
    mode.activate()
    const session = mode.beginFrameSession(320, 240)
    const existing = ctx.scene.children.find(c => c.isMesh)

    // sceneSignature keys on object/geometry ids and instance counts, NOT
    // materials — so vandalising a material alone must NOT trigger a re-swap.
    existing.material = new THREE.MeshPhongMaterial()
    await session.renderFrame()
    expect(existing.material.isMeshPhysicalMaterial).toBeFalsy()

    // A trajectory keyframe swapping the heavy rep in looks exactly like this:
    // a brand-new mesh carrying the EDITOR's material. THAT the signature sees.
    const fresh = new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), new THREE.MeshPhongMaterial())
    ctx.scene.add(fresh)
    await session.renderFrame()

    expect(fresh.material.isMeshPhysicalMaterial).toBe(true)     // photo look applied
    expect(existing.material.isMeshPhysicalMaterial).toBe(true)  // and the old one repaired
    session.dispose()
  })

  it('followMotion refits the shadow frustum every frame; without it, never', async () => {
    mode.activate()
    const moving = ctx.scene.children.find(c => c.isMesh)
    const centerX = () => mode.getDiagnostics().bounds.center[0]

    // Same mesh set, MOVED geometry — the signature cannot see this, which is
    // exactly what a cluster rotation does mid-animation.
    const still = mode.beginFrameSession(320, 240)
    await still.renderFrame()
    const x0 = centerX()
    moving.position.set(500, 0, 0)
    await still.renderFrame()
    expect(centerX()).toBeCloseTo(x0, 6)                        // stale, by design
    still.dispose()

    moving.position.set(0, 0, 0)
    mode.resync()
    const follow = mode.beginFrameSession(320, 240, { followMotion: true })
    moving.position.set(500, 0, 0)
    await follow.renderFrame()
    expect(centerX()).toBeGreaterThan(400)                       // refitted
    follow.dispose()
  })

  it('followMotion refits WITHOUT rebuilding the light rig', async () => {
    // _rebuildRig calls applyLighting, which clears the group and constructs
    // fresh lights — discarding the key light's 2048² shadow MAP. Once on a
    // settings change is fine; at 30 fps it is a texture realloc per frame.
    // So the followMotion path must refit bounds and keep the same light objects.
    mode.activate()
    const before = mode._getKeyLight()
    const moving = ctx.scene.children.find(c => c.isMesh)

    const session = mode.beginFrameSession(320, 240, { followMotion: true })
    for (let i = 1; i <= 5; i++) {
      moving.position.set(i * 100, 0, 0)
      await session.renderFrame()
    }

    expect(mode._getKeyLight()).toBe(before)              // same object, same shadow map
    expect(mode.getDiagnostics().bounds.center[0]).toBeGreaterThan(400)  // but refitted
    session.dispose()
  })

  it('renderToBlob is a one-shot session and still refuses when inactive', async () => {
    await expect(mode.renderToBlob(100, 100)).rejects.toThrow(/active/)
    mode.activate()
    rendererCtor.mockClear()
    const blob = await mode.renderToBlob(320, 240)
    expect(blob).toBeInstanceOf(Blob)
    expect(rendererCtor.mock.calls.length).toBe(2)   // probe + offscreen, then disposed
    expect(composerDispose).toHaveBeenCalledTimes(1)
  })
})
