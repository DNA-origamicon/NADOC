import { describe, it, expect } from 'vitest'
import * as THREE from 'three'
import {
  isShadowExcluded,
  computeShadowBounds,
  findBoundsOutlier,
  rejectedObjects,
  sceneSignature,
} from './shadow_bounds.js'

describe('isShadowExcluded', () => {
  const meshWith = (material, userData = {}) => Object.assign(
    new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), material), { userData },
  )

  it('excludes the photo floor — a ground plane would shadow the whole underside', () => {
    expect(isShadowExcluded(meshWith(new THREE.MeshBasicMaterial(), { photoFloor: true }))).toBe(true)
  })

  it('excludes helper lines and additive glow sprites', () => {
    expect(isShadowExcluded(meshWith(new THREE.LineBasicMaterial()))).toBe(true)
    expect(isShadowExcluded(meshWith(new THREE.MeshBasicMaterial({ blending: THREE.AdditiveBlending })))).toBe(true)
    expect(isShadowExcluded(new THREE.Sprite())).toBe(true)
  })

  it('honours an explicit userData.noAO opt-out', () => {
    expect(isShadowExcluded(meshWith(new THREE.MeshBasicMaterial(), { noAO: true }))).toBe(true)
  })

  it('includes ordinary geometry from every representation', () => {
    // Beads/atoms (instanced spheres), cylinders, slabs, the surface mesh.
    const inst = new THREE.InstancedMesh(new THREE.SphereGeometry(1, 8, 6), new THREE.MeshPhongMaterial(), 4)
    expect(isShadowExcluded(inst)).toBe(false)
    expect(isShadowExcluded(meshWith(new THREE.MeshPhongMaterial({ side: THREE.DoubleSide })))).toBe(false)
    expect(isShadowExcluded(meshWith(new THREE.MeshStandardMaterial()))).toBe(false)
  })
})

describe('bounds outlier detection', () => {
  const mesh = (size, name) => {
    const m = new THREE.Mesh(new THREE.BoxGeometry(size, size, size), new THREE.MeshPhongMaterial())
    m.name = name
    return m
  }

  it('excludes depthWrite:false overlays — they cannot occlude anything', () => {
    // The real-world failure: a 100 um immobilisation/ghost plane next to a
    // 100 nm design pushes the shadow frustum out ~700x and the structure falls
    // below one texel, so shadows and occlusion silently render as nothing.
    const scene = new THREE.Scene()
    scene.add(mesh(100, 'design'))
    const tight = computeShadowBounds(scene).radius

    const overlay = new THREE.Mesh(
      new THREE.PlaneGeometry(100000, 100000),
      new THREE.MeshBasicMaterial({ transparent: true, depthWrite: false }),
    )
    overlay.name = 'overlay'
    scene.add(overlay)

    expect(isShadowExcluded(overlay)).toBe(true)
    expect(computeShadowBounds(scene).radius).toBeCloseTo(tight, 5)
  })

  it('lists contributors largest-first so an outlier is identifiable', () => {
    const scene = new THREE.Scene()
    scene.add(mesh(10, 'small'), mesh(4000, 'huge'), mesh(12, 'small2'))
    const b = computeShadowBounds(scene)
    expect(b.contributors[0].name).toBe('huge')
    expect(b.contributors).toHaveLength(3)
  })

  it('rejects a radius set by one outlier, and reports what it dropped', () => {
    const scene = new THREE.Scene()
    for (const n of ['a', 'b', 'c', 'd', 'e']) scene.add(mesh(10, n))
    const clean = computeShadowBounds(scene)
    expect(findBoundsOutlier(clean)).toBeNull()

    scene.add(mesh(100000, 'rogue'))
    const b = computeShadowBounds(scene)
    // The frustum must still describe the STRUCTURE, not the rogue mesh.
    expect(b.radius).toBeCloseTo(clean.radius, 5)
    const o = findBoundsOutlier(b)
    expect(o).not.toBeNull()
    expect(o.worst.name).toBe('rogue')
    expect(o.ratio).toBeGreaterThan(20)
    expect(rejectedObjects(b).size).toBe(1)
  })

  it('needs a real sample before it trusts the median enough to reject', () => {
    // Two meshes is not evidence that the bigger one is spurious.
    const scene = new THREE.Scene()
    scene.add(mesh(10, 'small'), mesh(100000, 'big'))
    const b = computeShadowBounds(scene)
    expect(b.rejected).toHaveLength(0)
    expect(b.radius).toBeGreaterThan(1000)
  })

  it('keeps a legitimately large mesh that sits near the median', () => {
    // The molecular surface spans the whole design while beads are tiny — but
    // each InstancedMesh box already covers all its instances, so the surface
    // sits AT the median rather than looking like an outlier.
    const scene = new THREE.Scene()
    for (const n of ['a', 'b', 'c', 'd', 'e']) scene.add(mesh(100, n))
    scene.add(mesh(140, 'dna-surface'))
    const b = computeShadowBounds(scene)
    expect(b.rejected).toHaveLength(0)
  })

  it('keeps a coherent large DNA mesh family when smaller protein meshes dominate the median', () => {
    // VoltronCoreArm has five ~425 nm DNA representations plus several ~17 nm
    // protein element meshes. The old unweighted-median rule rejected all DNA
    // as oversized and consequently set castShadow=false on it.
    const scene = new THREE.Scene()
    for (let i = 0; i < 6; i++) scene.add(mesh(17, `protein-${i}`))
    for (const [i, size] of [425, 426, 427, 428, 429].entries()) {
      scene.add(mesh(size, `dna-${i}`))
    }

    const b = computeShadowBounds(scene)

    expect(b.medianExtent).toBeLessThan(40)
    expect(b.rejected).toHaveLength(0)
    expect(b.radius).toBeGreaterThan(300)
  })

  it('still rejects an isolated overlay above a corroborated large structure family', () => {
    const scene = new THREE.Scene()
    for (let i = 0; i < 6; i++) scene.add(mesh(17, `protein-${i}`))
    for (let i = 0; i < 5; i++) scene.add(mesh(425 + i, `dna-${i}`))
    scene.add(mesh(100000, 'rogue-overlay'))

    const b = computeShadowBounds(scene)

    expect(b.rejected.map(row => row.name)).toEqual(['rogue-overlay'])
    expect(b.radius).toBeGreaterThan(300)
    expect(b.radius).toBeLessThan(1000)
  })

  it('does not cry outlier on a single-mesh scene', () => {
    const scene = new THREE.Scene()
    scene.add(mesh(100, 'only'))
    expect(findBoundsOutlier(computeShadowBounds(scene))).toBeNull()
  })
})

describe('sceneSignature', () => {
  const mesh = () => new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), new THREE.MeshPhongMaterial())

  it('is stable across calls when nothing changed', () => {
    const scene = new THREE.Scene()
    scene.add(mesh(), mesh())
    expect(sceneSignature(scene)).toBe(sceneSignature(scene))
  })

  it('changes when meshes are REPLACED — the representation-switch case', () => {
    // Switching hull-prism → cylinders → full writes no store field; only the
    // fresh Object3D ids reveal it. This is the bug this function exists for.
    const scene = new THREE.Scene()
    const old = mesh()
    scene.add(old)
    const before = sceneSignature(scene)

    scene.remove(old)
    scene.add(mesh())                 // same shape + count, brand new object
    expect(sceneSignature(scene)).not.toBe(before)
  })

  it('changes when an instance count changes', () => {
    const scene = new THREE.Scene()
    const inst = new THREE.InstancedMesh(new THREE.SphereGeometry(1, 8, 6), new THREE.MeshPhongMaterial(), 10)
    scene.add(inst)
    const before = sceneSignature(scene)
    inst.count = 4
    expect(sceneSignature(scene)).not.toBe(before)
  })

  it('changes when geometry is swapped in place (the export detail upgrade)', () => {
    const scene = new THREE.Scene()
    const m = mesh()
    scene.add(m)
    const before = sceneSignature(scene)
    m.geometry = new THREE.SphereGeometry(1, 32, 24)
    expect(sceneSignature(scene)).not.toBe(before)
  })

  it('changes when geometry is hidden or shown', () => {
    const scene = new THREE.Scene()
    const m = mesh()
    scene.add(m, mesh())
    const before = sceneSignature(scene)
    m.visible = false
    expect(sceneSignature(scene)).not.toBe(before)
  })

  it('ignores excluded objects, so toggling the floor does not force a re-bake', () => {
    const scene = new THREE.Scene()
    scene.add(mesh())
    const before = sceneSignature(scene)
    const floor = mesh()
    floor.userData.photoFloor = true
    scene.add(floor)
    expect(sceneSignature(scene)).toBe(before)
  })

  it('does NOT change when only instance matrices move', () => {
    // Documents the deliberate limit: position-only changes (a simulation
    // frame, a cluster move) are covered by the mode's store subscription and
    // the manual re-bake, not by this fingerprint.
    const scene = new THREE.Scene()
    const inst = new THREE.InstancedMesh(new THREE.SphereGeometry(1, 8, 6), new THREE.MeshPhongMaterial(), 4)
    scene.add(inst)
    const before = sceneSignature(scene)
    inst.setMatrixAt(0, new THREE.Matrix4().makeTranslation(99, 99, 99))
    inst.instanceMatrix.needsUpdate = true
    expect(sceneSignature(scene)).toBe(before)
  })
})

describe('computeShadowBounds', () => {
  it('ignores a huge helper below a hidden parent', () => {
    const scene = new THREE.Scene()
    const makeMesh = (size, name) => {
      const object = new THREE.Mesh(
        new THREE.BoxGeometry(size, size, size), new THREE.MeshBasicMaterial())
      object.name = name
      return object
    }
    const structure = makeMesh(10, 'structure')
    const hiddenGizmo = new THREE.Group()
    hiddenGizmo.visible = false
    const dragPlane = makeMesh(100000, 'transform-controls-plane')
    dragPlane.isTransformControlsPlane = true
    hiddenGizmo.add(dragPlane)
    scene.add(structure, hiddenGizmo)

    const bounds = computeShadowBounds(scene)

    expect(bounds.radius).toBeLessThan(20)
    expect(bounds.contributors.map(c => c.name)).toEqual(['structure'])
  })

  it('ignores a visible TransformControls picking plane', () => {
    const scene = new THREE.Scene()
    const structure = new THREE.Mesh(new THREE.BoxGeometry(10, 10, 10), new THREE.MeshBasicMaterial())
    const dragPlane = new THREE.Mesh(new THREE.PlaneGeometry(100000, 100000), new THREE.MeshBasicMaterial())
    dragPlane.isTransformControlsPlane = true
    scene.add(structure, dragPlane)

    expect(computeShadowBounds(scene).radius).toBeLessThan(20)
  })

  it('returns null for a scene with nothing to occlude', () => {
    expect(computeShadowBounds(new THREE.Scene())).toBeNull()
    const onlyLights = new THREE.Scene()
    onlyLights.add(new THREE.AmbientLight(0xffffff, 1))
    expect(computeShadowBounds(onlyLights)).toBeNull()
  })

  it('brackets the visible geometry', () => {
    const scene = new THREE.Scene()
    const a = new THREE.Mesh(new THREE.BoxGeometry(2, 2, 2), new THREE.MeshPhongMaterial())
    a.position.set(-10, 0, 0)
    const b = new THREE.Mesh(new THREE.BoxGeometry(2, 2, 2), new THREE.MeshPhongMaterial())
    b.position.set(10, 0, 0)
    scene.add(a, b)
    const bounds = computeShadowBounds(scene)
    expect(bounds.center.x).toBeCloseTo(0, 5)
    expect(bounds.radius).toBeGreaterThanOrEqual(11)
  })

  it('ignores the floor, so the frustum is not blown out by an infinite plane', () => {
    const scene = new THREE.Scene()
    const part = new THREE.Mesh(new THREE.BoxGeometry(2, 2, 2), new THREE.MeshPhongMaterial())
    scene.add(part)
    const tight = computeShadowBounds(scene).radius

    const floor = new THREE.Mesh(new THREE.PlaneGeometry(4000, 4000), new THREE.MeshPhongMaterial())
    floor.userData.photoFloor = true
    scene.add(floor)
    expect(computeShadowBounds(scene).radius).toBeCloseTo(tight, 5)
  })

  it('ignores hidden geometry', () => {
    const scene = new THREE.Scene()
    const shown = new THREE.Mesh(new THREE.BoxGeometry(2, 2, 2), new THREE.MeshPhongMaterial())
    const hidden = new THREE.Mesh(new THREE.BoxGeometry(2, 2, 2), new THREE.MeshPhongMaterial())
    hidden.position.set(500, 0, 0)
    hidden.visible = false
    scene.add(shown, hidden)
    expect(computeShadowBounds(scene).radius).toBeLessThan(10)
  })

  it('widens by the impostor radius (a billboard quad understates its sphere)', () => {
    const scene = new THREE.Scene()
    const mat = new THREE.MeshPhongMaterial()
    mat.userData.impostorRadius = 25
    const quad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), mat)
    scene.add(quad)
    expect(computeShadowBounds(scene).radius).toBeGreaterThan(25)
  })
})
