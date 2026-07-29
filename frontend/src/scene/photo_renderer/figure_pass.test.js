import { describe, it, expect, beforeEach } from 'vitest'
import * as THREE from 'three'
import { FigurePass, FigureShader } from './figure_pass.js'

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

describe('FigurePass silhouette mode', () => {
  it('defaults to the Roberts cross — the shipping Photo tab must not change', () => {
    const pass = makePass()
    expect(pass.uniforms.uSilhouette.value).toBe(0)
    // and stays there when the shipping tab pushes its usual params
    pass.setParams({ outline: true, outlineDepthSensitivity: 0.35, outlineCreaseSensitivity: 0.85 })
    expect(pass.uniforms.uSilhouette.value).toBe(0)
  })

  it("selects the ChimeraX depth-outline on 'chimerax' and back on anything else", () => {
    const pass = makePass()
    pass.setParams({ silhouette: 'chimerax' })
    expect(pass.uniforms.uSilhouette.value).toBe(1)
    pass.setParams({ silhouette: 'roberts' })
    expect(pass.uniforms.uSilhouette.value).toBe(0)
  })

  it("carries ChimeraX's depth_jump default and accepts an override", () => {
    const pass = makePass()
    expect(pass.uniforms.uDepthJump.value).toBeCloseTo(0.03)
    pass.setParams({ outlineDepthJump: 0.08 })
    expect(pass.uniforms.uDepthJump.value).toBeCloseTo(0.08)
  })
})

describe('FigurePass.setSceneDepth', () => {
  it('stores a positive span, and treats non-positive as "fall back to far-near"', () => {
    const pass = makePass()
    pass.setSceneDepth(137.5)
    expect(pass.uniforms.uSceneDepth.value).toBe(137.5)
    pass.setSceneDepth(0)
    expect(pass.uniforms.uSceneDepth.value).toBe(0)
    pass.setSceneDepth(-4)
    expect(pass.uniforms.uSceneDepth.value).toBe(0)
  })
})

describe('FigureShader ChimeraX depth-outline', () => {
  // ChimeraX's test `nf*(d0-ds) < jump*(1-nf1*ds)*(1-nf1*d0) → discard` is a
  // perspective linearization of the depth buffer. Pinning the algebra here
  // (rather than only in a comment) is what justifies applying the threshold
  // directly in linear eye depth in the shader.
  const chimeraxDiscards = (d0, ds, jump, near, far) => {
    const nf = near / far
    const nf1 = 1 - nf
    return nf * (d0 - ds) < jump * (1 - nf1 * ds) * (1 - nf1 * d0)
  }
  // Window depth for an eye distance under a standard GL perspective projection.
  const windowDepth = (z, near, far) => (far * (z - near)) / (z * (far - near))

  it('reduces to a constant world-space gap of depth_jump * (far - near)', () => {
    const near = 1, far = 101, jump = 0.03
    const gap = jump * (far - near)   // 3 nm
    for (const zFar of [5, 20, 60, 95]) {
      // A gap just under the threshold is discarded, just over it draws — at
      // every distance from the camera, which is the whole point.
      const dNear = windowDepth(zFar - gap * 0.9, near, far)
      const dFar  = windowDepth(zFar, near, far)
      expect(chimeraxDiscards(dFar, dNear, jump, near, far)).toBe(true)

      const dNear2 = windowDepth(zFar - gap * 1.1, near, far)
      expect(chimeraxDiscards(dFar, dNear2, jump, near, far)).toBe(false)
    }
  })

  it('the shader carries the ChimeraX branch and its disc min-filter', () => {
    // Guards against the branch being lost in a future edit of the shader string.
    expect(FigureShader.fragmentShader).toContain('uSilhouette > 0.5')
    expect(FigureShader.fragmentShader).toMatch(/rr < 0\.5 \|\| rr > r2/)
    expect(FigureShader.fragmentShader).toContain('dsEye = min(dsEye')
  })

  it('paints the contour onto background pixels only in ChimeraX mode', () => {
    // Roberts mode early-returns on background (keeps an alpha export clean);
    // the ChimeraX contour lands on the FARTHER surface, so it must not.
    expect(FigureShader.fragmentShader)
      .toContain('if (isBackground && !(uOutline > 0.5 && uSilhouette > 0.5))')
    expect(FigureShader.fragmentShader).toContain('alpha = max(alpha, edge)')
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

  it('hides the grid and other non-mesh helpers, which are not surfaces', () => {
    // Regression: `scene.overrideMaterial` applies to Lines too, so a visible
    // GridHelper wrote depth into the pre-pass and the outline drew a contour
    // along every grid line. A Line is not `isMesh`, so the old isMesh-only
    // guard returned before the line-material checks could ever fire.
    const scene  = new THREE.Scene()
    const pass   = new FigurePass(scene, new THREE.PerspectiveCamera())

    const grid   = new THREE.GridHelper(500, 50)
    const axes   = new THREE.AxesHelper(10)
    const points = new THREE.Points(new THREE.BufferGeometry(), new THREE.PointsMaterial())
    const sprite = new THREE.Sprite(new THREE.SpriteMaterial())
    const real   = new THREE.Mesh(new THREE.BoxGeometry(), new THREE.MeshStandardMaterial())
    scene.add(grid, axes, points, sprite, real)

    pass._hideNonSurfaces()
    expect(grid.visible,   'GridHelper').toBe(false)
    expect(axes.visible,   'AxesHelper').toBe(false)
    expect(points.visible, 'Points').toBe(false)
    expect(sprite.visible, 'Sprite').toBe(false)
    expect(real.visible,   'real geometry must survive').toBe(true)

    pass._restoreHidden()
    for (const o of [grid, axes, points, sprite]) expect(o.visible).toBe(true)
  })
})
