import { describe, it, expect, afterEach } from 'vitest'
import * as THREE from 'three'
import { initMdSolventOverlay, capacityFor, ION_STYLE } from './md_solvent_overlay.js'
import { IMPOSTOR_QUAD } from './impostor_material.js'

const meshFor = (scene, key) =>
  scene.children.find((o) => o.isInstancedMesh && o.userData.solventKey === key)

/** Uniform scale baked into instance `i`'s matrix. */
function instanceScale(mesh, i = 0) {
  const m = new THREE.Matrix4()
  mesh.getMatrixAt(i, m)
  const s = new THREE.Vector3()
  m.decompose(new THREE.Vector3(), new THREE.Quaternion(), s)
  return s.x
}

/** A sphere-mode frame: nWater molecules, one xyz each. */
function sphereFrame(nWater, nIons = 0) {
  const water = new Float32Array(nWater * 3)
  for (let i = 0; i < nWater; i++) { water[i * 3] = i }
  const ions = new Float32Array(nIons * 3)
  for (let i = 0; i < nIons; i++) { ions[i * 3 + 1] = i }
  return { water, nWater, ions }
}

/** An atomistic frame: O,H,H per molecule (9 floats). */
function atomFrame(nWater, nIons = 0) {
  const water = new Float32Array(nWater * 9)
  for (let i = 0; i < nWater; i++) {
    const o = i * 9
    water[o] = i                       // O
    water[o + 3] = i + 0.1             // H1
    water[o + 6] = i - 0.1             // H2
  }
  return { water, nWater, ions: new Float32Array(nIons * 3) }
}

describe('capacityFor', () => {
  it('allocates headroom on the first fill', () => {
    expect(capacityFor(100, 0)).toBe(125)
  })

  it('keeps the existing capacity when it already fits', () => {
    expect(capacityFor(100, 125)).toBe(125)
    expect(capacityFor(125, 125)).toBe(125)
  })

  // Never shrink: a hydration shell oscillates in size every frame, and shrinking
  // on a dip just guarantees another reallocation on the next rise.
  it('never shrinks', () => {
    expect(capacityFor(10, 500)).toBe(500)
    expect(capacityFor(0, 500)).toBe(500)
  })

  it('grows past the current capacity with headroom', () => {
    expect(capacityFor(200, 125)).toBe(250)
  })
})

describe('initMdSolventOverlay', () => {
  afterEach(() => { delete window.NADOC_IMPOSTORS })

  it('draws nothing while mode is off', () => {
    const scene = new THREE.Scene()
    const ov = initMdSolventOverlay(scene)
    ov.setFrame(sphereFrame(10))
    expect(scene.children.filter((o) => o.isInstancedMesh)).toHaveLength(0)
  })

  it('draws one sphere per molecule in sphere mode', () => {
    const scene = new THREE.Scene()
    const ov = initMdSolventOverlay(scene)
    ov.setMode('sphere')
    ov.setFrame(sphereFrame(10))
    const m = meshFor(scene, 'waterO')
    expect(m.count).toBe(10)
    expect(meshFor(scene, 'waterH')).toBeUndefined()   // no H meshes in sphere mode
  })

  it('places each sphere at its oxygen', () => {
    const scene = new THREE.Scene()
    const ov = initMdSolventOverlay(scene)
    ov.setMode('sphere')
    ov.setFrame(sphereFrame(3))
    const m = meshFor(scene, 'waterO')
    const mat = new THREE.Matrix4()
    m.getMatrixAt(2, mat)
    expect(new THREE.Vector3().setFromMatrixPosition(mat).x).toBeCloseTo(2, 6)
  })

  it('draws O plus both H in atomistic mode', () => {
    const scene = new THREE.Scene()
    const ov = initMdSolventOverlay(scene)
    ov.setMode('atomistic')
    ov.setFrame(atomFrame(5))
    expect(meshFor(scene, 'waterO').count).toBe(5)
    expect(meshFor(scene, 'waterH').count).toBe(10)     // two per molecule
  })

  it('adds O-H sticks only in ball-and-stick, not VDW', () => {
    const scene = new THREE.Scene()
    const ov = initMdSolventOverlay(scene)
    ov.setMode('atomistic', true)
    ov.setFrame(atomFrame(4))
    expect(meshFor(scene, 'bonds').count).toBe(8)

    const vdwScene = new THREE.Scene()
    const vdw = initMdSolventOverlay(vdwScene)
    vdw.setMode('atomistic', false)
    vdw.setFrame(atomFrame(4))
    expect(meshFor(vdwScene, 'bonds')).toBeUndefined()
  })

  // THE capacity contract. A shell's molecule count changes every frame; the mesh
  // must be reallocated only when it actually overflows, never per frame.
  describe('capacity management', () => {
    it('tracks the count exactly while reusing one mesh', () => {
      const scene = new THREE.Scene()
      const ov = initMdSolventOverlay(scene)
      ov.setMode('sphere')

      ov.setFrame(sphereFrame(100))
      const first = meshFor(scene, 'waterO')
      expect(first.count).toBe(100)
      expect(ov.stats().capacity.waterO).toBe(125)

      // A dip: same mesh object, smaller count, capacity untouched.
      ov.setFrame(sphereFrame(50))
      expect(meshFor(scene, 'waterO')).toBe(first)
      expect(first.count).toBe(50)
      expect(ov.stats().capacity.waterO).toBe(125)

      // Still within headroom: still the same mesh.
      ov.setFrame(sphereFrame(120))
      expect(meshFor(scene, 'waterO')).toBe(first)
      expect(first.count).toBe(120)
    })

    it('reallocates only on genuine overflow', () => {
      const scene = new THREE.Scene()
      const ov = initMdSolventOverlay(scene)
      ov.setMode('sphere')
      ov.setFrame(sphereFrame(100))
      const first = meshFor(scene, 'waterO')

      ov.setFrame(sphereFrame(500))                   // > capacity 125 → new mesh
      const second = meshFor(scene, 'waterO')
      expect(second).not.toBe(first)
      expect(second.count).toBe(500)

      ov.setFrame(sphereFrame(50))                    // back down → same mesh
      expect(meshFor(scene, 'waterO')).toBe(second)
    })

    it('leaves exactly one mesh per key in the scene after growth', () => {
      const scene = new THREE.Scene()
      const ov = initMdSolventOverlay(scene)
      ov.setMode('sphere')
      for (const n of [10, 400, 20, 900]) ov.setFrame(sphereFrame(n))
      expect(scene.children.filter(
        (o) => o.userData.solventKey === 'waterO')).toHaveLength(1)
    })
  })

  // Ions get ONE MESH PER SPECIES. A single mesh cannot carry per-species radii
  // under impostors (the painted radius is a material uniform), which is exactly
  // how they shipped 7x oversized the first time — caught by screenshot, not by a
  // unit test, hence these.
  describe('ions', () => {
    it('buckets ions into one mesh per species', () => {
      const scene = new THREE.Scene()
      const ov = initMdSolventOverlay(scene)
      ov.setMode('sphere')
      ov.setIonSpecies(Uint8Array.from([0, 1, 2, 0]))   // Na, Cl, Mg, Na
      ov.setFrame(sphereFrame(0, 4))
      expect(meshFor(scene, 'ion0').count).toBe(2)      // two Na
      expect(meshFor(scene, 'ion1').count).toBe(1)      // one Cl
      expect(meshFor(scene, 'ion2').count).toBe(1)      // one Mg
    })

    it('colours each species mesh from its style entry', () => {
      const scene = new THREE.Scene()
      const ov = initMdSolventOverlay(scene)
      ov.setMode('sphere')
      ov.setIonSpecies(Uint8Array.from([0, 1, 2]))
      ov.setFrame(sphereFrame(0, 3))
      for (const s of [0, 1, 2]) {
        expect(meshFor(scene, `ion${s}`).material.color.getHex()).toBe(ION_STYLE[s].color)
      }
    })

    // THE bug the screenshot caught: every ion drew at scale 1 (a 1 nm sphere)
    // because the impostor test was `atomInstanceScale(1) === 1`, which is true in
    // BOTH paths. With real spheres the instance scale must be the species radius.
    it('scales each species to its own radius with real spheres', () => {
      const scene = new THREE.Scene()
      const ov = initMdSolventOverlay(scene)
      ov.setMode('sphere')
      ov.setIonSpecies(Uint8Array.from([0, 2]))
      ov.setFrame(sphereFrame(0, 2))
      expect(instanceScale(meshFor(scene, 'ion0'))).toBeCloseTo(ION_STYLE[0].radius, 6)
      expect(instanceScale(meshFor(scene, 'ion2'))).toBeCloseTo(ION_STYLE[2].radius, 6)
      // …and they really are different sizes, not accidentally equal.
      expect(ION_STYLE[0].radius).not.toBe(ION_STYLE[2].radius)
    })

    it('carries the radius in the material uniform under impostors', () => {
      window.NADOC_IMPOSTORS = true
      const scene = new THREE.Scene()
      const ov = initMdSolventOverlay(scene)
      ov.setMode('sphere')
      ov.setIonSpecies(Uint8Array.from([0, 2]))
      ov.setFrame(sphereFrame(0, 2))
      expect(instanceScale(meshFor(scene, 'ion0'))).toBeCloseTo(1, 6)
      expect(meshFor(scene, 'ion0').material.userData.impostorRadius)
        .toBeCloseTo(ION_STYLE[0].radius, 6)
      expect(meshFor(scene, 'ion2').material.userData.impostorRadius)
        .toBeCloseTo(ION_STYLE[2].radius, 6)
    })

    it('is drawn in atomistic mode too', () => {
      const scene = new THREE.Scene()
      const ov = initMdSolventOverlay(scene)
      ov.setMode('atomistic')
      ov.setIonSpecies(Uint8Array.from([0, 0]))
      ov.setFrame({ ...atomFrame(2), ions: new Float32Array(6) })
      expect(meshFor(scene, 'ion0').count).toBe(2)
    })

    it('falls back to the first species for an unknown code', () => {
      const scene = new THREE.Scene()
      const ov = initMdSolventOverlay(scene)
      ov.setMode('sphere')
      ov.setIonSpecies(Uint8Array.from([99]))
      ov.setFrame(sphereFrame(0, 1))
      expect(meshFor(scene, 'ion0').count).toBe(1)
    })
  })

  describe('visibility toggles', () => {
    it('water off hides water but keeps ions', () => {
      const scene = new THREE.Scene()
      const ov = initMdSolventOverlay(scene)
      ov.setMode('sphere')
      ov.setIonSpecies(Uint8Array.from([0, 0]))
      ov.setFrame(sphereFrame(10, 2))
      ov.setWaterVisible(false)
      ov.setFrame(sphereFrame(10, 2))
      expect(meshFor(scene, 'waterO').visible).toBe(false)
      expect(meshFor(scene, 'ion0').count).toBe(2)
      expect(ov.stats().nWater).toBe(0)
    })

    it('ions off hides ions but keeps water', () => {
      const scene = new THREE.Scene()
      const ov = initMdSolventOverlay(scene)
      ov.setMode('sphere')
      ov.setIonSpecies(Uint8Array.from([0, 0]))
      ov.setFrame(sphereFrame(10, 2))
      ov.setIonsVisible(false)
      ov.setFrame(sphereFrame(10, 2))
      expect(meshFor(scene, 'ion0').visible).toBe(false)
      expect(meshFor(scene, 'waterO').count).toBe(10)
    })
  })

  it('clear() hides everything but keeps the allocation', () => {
    const scene = new THREE.Scene()
    const ov = initMdSolventOverlay(scene)
    ov.setMode('sphere')
    ov.setFrame(sphereFrame(100))
    const m = meshFor(scene, 'waterO')
    ov.clear()
    expect(m.visible).toBe(false)
    expect(m.count).toBe(0)
    expect(ov.stats().capacity.waterO).toBe(125)   // still allocated
  })

  it('setMode("off") clears the scene contents', () => {
    const scene = new THREE.Scene()
    const ov = initMdSolventOverlay(scene)
    ov.setMode('sphere')
    ov.setFrame(sphereFrame(10))
    ov.setMode('off')
    expect(meshFor(scene, 'waterO').visible).toBe(false)
  })

  it('dispose() removes every mesh from the scene', () => {
    const scene = new THREE.Scene()
    const ov = initMdSolventOverlay(scene)
    ov.setMode('atomistic', true)
    ov.setIonSpecies(Uint8Array.from([0]))
    ov.setFrame({ ...atomFrame(5), ions: new Float32Array(3) })
    expect(scene.children.length).toBeGreaterThan(0)
    ov.dispose()
    expect(scene.children).toHaveLength(0)
  })

  it('a null frame clears rather than throwing', () => {
    const scene = new THREE.Scene()
    const ov = initMdSolventOverlay(scene)
    ov.setMode('sphere')
    ov.setFrame(sphereFrame(5))
    expect(() => ov.setFrame(null)).not.toThrow()
    expect(ov.stats().nWater).toBe(0)
  })

  describe('impostors', () => {
    it('uses the billboard quad and a scale-free instance matrix', () => {
      window.NADOC_IMPOSTORS = true
      const scene = new THREE.Scene()
      const ov = initMdSolventOverlay(scene)
      ov.setMode('sphere')
      ov.setFrame(sphereFrame(4))
      const m = meshFor(scene, 'waterO')
      expect(m.geometry).toBe(IMPOSTOR_QUAD)
      const mat = new THREE.Matrix4()
      m.getMatrixAt(0, mat)
      const s = new THREE.Vector3()
      mat.decompose(new THREE.Vector3(), new THREE.Quaternion(), s)
      expect(s.x).toBeCloseTo(1, 6)   // the uniform owns the radius, not the matrix
    })

    // Solvent is not selectable, and the impostor raycast is an O(count) JS loop —
    // installing it on 10^5 water spheres would make every click crawl.
    it('does not install the picking raycast on solvent', () => {
      window.NADOC_IMPOSTORS = true
      const scene = new THREE.Scene()
      const ov = initMdSolventOverlay(scene)
      ov.setMode('sphere')
      ov.setFrame(sphereFrame(4))
      const m = meshFor(scene, 'waterO')
      expect(Object.prototype.hasOwnProperty.call(m, 'raycast')).toBe(false)
    })

    it('reuses one material across frames (no per-frame shader compile)', () => {
      window.NADOC_IMPOSTORS = true
      const scene = new THREE.Scene()
      const ov = initMdSolventOverlay(scene)
      ov.setMode('sphere')
      ov.setFrame(sphereFrame(100))
      const first = meshFor(scene, 'waterO').material
      ov.setFrame(sphereFrame(900))          // forces a mesh reallocation
      expect(meshFor(scene, 'waterO').material).toBe(first)
    })
  })
})

it('draws actual graphene coordinates independently of water and ions and clears stale sites', () => {
  const scene = new THREE.Scene()
  const overlay = initMdSolventOverlay(scene)
  overlay.setMode('sphere')
  overlay.setWaterVisible(false)
  overlay.setIonsVisible(false)
  overlay.setFrame({ ...sphereFrame(0), graphene: new Float32Array([1, 2, 3, 35, 2, 34]) })
  const mesh = meshFor(scene, 'graphene')
  expect(mesh.count).toBe(2)
  const matrix = new THREE.Matrix4()
  mesh.getMatrixAt(1, matrix)
  expect(new THREE.Vector3().setFromMatrixPosition(matrix).toArray()).toEqual([35, 2, 34])
  overlay.setFrame(sphereFrame(0))
  expect(mesh.visible).toBe(false)
  overlay.dispose()
})
