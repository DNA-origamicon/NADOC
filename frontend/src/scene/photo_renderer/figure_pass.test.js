import { describe, it, expect, beforeEach } from 'vitest'
import * as THREE from 'three'
import { FigurePass } from './figure_pass.js'

// The pass is constructible without a GL context (render targets and materials
// are descriptors until something renders them), so its parameter mapping and
// enable logic can be pinned without a browser.
function makePass() {
  const scene  = new THREE.Scene()
  const camera = new THREE.PerspectiveCamera(55, 1, 0.1, 2000)
  return new FigurePass(scene, camera)
}

describe('FigurePass.setParams', () => {
  let pass
  beforeEach(() => { pass = makePass() })

  it('maps the outline settings onto the shader uniforms', () => {
    pass.setParams({
      outline: true,
      outlineColor: '#ff0000',
      outlineStrength: 0.5,
      outlineThickness: 2.5,
      outlineDepthSensitivity: 0.2,
      outlineCreaseSensitivity: 1.3,
    })
    const u = pass.uniforms
    expect(u.uOutline.value).toBe(1)
    expect(u.uOutlineColor.value.getHexString()).toBe('ff0000')
    expect(u.uOutlineStrength.value).toBe(0.5)
    expect(u.uOutlineThickness.value).toBe(2.5)
    expect(u.uDepthSens.value).toBe(0.2)
    expect(u.uNormalSens.value).toBe(1.3)
  })

  it('maps the depth-cue settings onto the shader uniforms', () => {
    pass.setParams({ depthCue: true, depthCueColor: '#00ff00', depthCueStrength: 0.6 })
    const u = pass.uniforms
    expect(u.uCue.value).toBe(1)
    expect(u.uCueColor.value.getHexString()).toBe('00ff00')
    expect(u.uCueStrength.value).toBe(0.6)
  })

  it('leaves omitted settings untouched (partial updates are safe)', () => {
    pass.setParams({ outlineStrength: 0.25 })
    pass.setParams({ depthCue: true })
    expect(pass.uniforms.uOutlineStrength.value).toBe(0.25)
  })

  it('booleans drive 0/1 uniforms both ways', () => {
    pass.setParams({ outline: true, depthCue: true })
    expect(pass.uniforms.uOutline.value).toBe(1)
    pass.setParams({ outline: false })
    expect(pass.uniforms.uOutline.value).toBe(0)
    expect(pass.uniforms.uCue.value).toBe(1)
  })
})

describe('FigurePass.hasEffect', () => {
  it('is false when neither effect is on — the composer then skips the pass entirely', () => {
    const pass = makePass()
    pass.setParams({ outline: false, depthCue: false })
    expect(pass.hasEffect()).toBe(false)
  })

  it('is true when EITHER effect is on (they are independent)', () => {
    const pass = makePass()
    pass.setParams({ outline: true, depthCue: false })
    expect(pass.hasEffect()).toBe(true)
    pass.setParams({ outline: false, depthCue: true })
    expect(pass.hasEffect()).toBe(true)
  })
})

describe('FigurePass.setCueRange', () => {
  it('stores the window', () => {
    const pass = makePass()
    pass.setCueRange(5, 40)
    expect(pass.uniforms.uCueNear.value).toBe(5)
    expect(pass.uniforms.uCueFar.value).toBe(40)
  })

  it('keeps far strictly above near so the shader never divides by zero', () => {
    const pass = makePass()
    pass.setCueRange(10, 10)
    expect(pass.uniforms.uCueFar.value).toBeGreaterThan(pass.uniforms.uCueNear.value)
    pass.setCueRange(10, 2)      // degenerate: far behind near
    expect(pass.uniforms.uCueFar.value).toBeGreaterThan(10)
  })
})

describe('FigurePass pre-pass exclusions', () => {
  it('hides only the meshes MeshNormalMaterial cannot reproduce, and restores them', () => {
    const scene  = new THREE.Scene()
    const camera = new THREE.PerspectiveCamera()
    const pass   = new FigurePass(scene, camera)

    const normal = new THREE.Mesh(new THREE.BoxGeometry(), new THREE.MeshStandardMaterial())
    // Shared-renderer LOD impostor: custom instancing shader → would collapse to
    // the source origin under the override and stamp a bogus edge there.
    const impostor = new THREE.Mesh(new THREE.BoxGeometry(), new THREE.MeshStandardMaterial())
    impostor.userData.sharedLodImpostor = true
    // Additive glow sprite: an opaque quad under the override → phantom rectangle.
    const glow = new THREE.Mesh(
      new THREE.PlaneGeometry(),
      new THREE.MeshBasicMaterial({ blending: THREE.AdditiveBlending }),
    )
    scene.add(normal, impostor, glow)

    pass._hideNonSurfaces()
    expect(normal.visible).toBe(true)
    expect(impostor.visible).toBe(false)
    expect(glow.visible).toBe(false)

    pass._restoreHidden()
    expect(impostor.visible).toBe(true)
    expect(glow.visible).toBe(true)
  })
})
