/**
 * Pin for the R4 targeted-isolation hardening in floor.js: the mirror floor
 * (THREE.Reflector) runs a nested scene render from inside onBeforeRender, which
 * churns the shared renderer's WebGLState mid-frame. floor.js wraps the
 * Reflector's onBeforeRender to call renderer.resetState() right after, so that
 * state churn can't bleed into the rest of the photo composer frame.
 *
 * (The visible payoff — no bloom/PBR-env desync flash with a mirror floor — is a
 * GPU-pixel property covered by MV-PHOTO-2; this test pins the wiring.)
 */
import { describe, it, expect, vi } from 'vitest'
import * as THREE from 'three'
import { createFloor } from './floor.js'

// A renderer fake rich enough for THREE.Reflector.onBeforeRender's nested render.
function fakeRenderer() {
  return {
    getRenderTarget: () => null,
    setRenderTarget: vi.fn(),
    xr: { enabled: false },
    shadowMap: { autoUpdate: true },
    state: { buffers: { depth: { setMask: vi.fn() } }, viewport: vi.fn() },
    autoClear: true,
    clear: vi.fn(),
    render: vi.fn(),
    resetState: vi.fn(),
  }
}

function sceneWithContent() {
  const scene = new THREE.Scene()
  const m = new THREE.Mesh(new THREE.BoxGeometry(2, 2, 2), new THREE.MeshStandardMaterial())
  scene.add(m)
  scene.updateMatrixWorld(true)
  return scene
}

const MIRROR_SETTINGS = {
  floor: '-y', floorMaterial: 'mirror', floorColor: '#888888',
  floorOpacity: 1, floorShadows: false, floorGrid: false, floorGridDensity: 10,
}

describe('floor.js — mirror Reflector state isolation (R4 targeted)', () => {
  it('mirror floor flushes renderer.resetState after its nested reflection render', () => {
    const scene = sceneWithContent()
    const floor = createFloor({ scene })
    floor.build(MIRROR_SETTINGS)
    const mesh = floor.getMesh()
    expect(mesh).toBeTruthy()

    const renderer = fakeRenderer()
    const camera = new THREE.PerspectiveCamera(55, 1, 0.1, 2000)
    // Drive the wrapped onBeforeRender exactly as the renderer would mid-frame.
    mesh.onBeforeRender(renderer, scene, camera, mesh.geometry, mesh.material, null)

    // The nested reflection render still ran (wrap, not replace) …
    expect(renderer.render).toHaveBeenCalled()
    // … and the state cache was flushed right after.
    expect(renderer.resetState).toHaveBeenCalled()
    floor.dispose()
  })

  it('a non-mirror (matte) floor does NOT call resetState (no nested render to isolate)', () => {
    const scene = sceneWithContent()
    const floor = createFloor({ scene })
    floor.build({ ...MIRROR_SETTINGS, floorMaterial: 'matte' })
    const mesh = floor.getMesh()

    const renderer = fakeRenderer()
    const camera = new THREE.PerspectiveCamera(55, 1, 0.1, 2000)
    mesh.onBeforeRender(renderer, scene, camera, mesh.geometry, mesh.material, null)

    expect(renderer.resetState).not.toHaveBeenCalled()
    floor.dispose()
  })
})
