// cpd_weld_overlay.test.js
//
// planWeldDraw is the pure decision layer — which pairs are drawable this frame, where
// their markers go, and what colour they carry. Testing it without a scene is what makes
// the overlay's behaviour (skip unresolved pairs, skip atoms missing from this frame,
// flag sub-vdW contact) assertable at all.

import { describe, it, expect, vi } from 'vitest'
import { planWeldDraw, initCpdWeldOverlay } from './cpd_weld_overlay.js'
import { weldColor, VDW_FLOOR_NM } from './cpd_geometry.js'

// two parallel C5=C6 bonds, separation set by `gap` nm along z
const positionsFor = (gap) => ({
  0: [0, 0, 0], 1: [0.139, 0, 0],
  2: [0, 0, gap], 3: [0.139, 0, gap],
})
const getPosFor = (gap) => (s) => positionsFor(gap)[s] ?? null

const PAIR = {
  id: 'a:0~b:0', label: 'a[k=0]~b[k=0]',
  c5_a: 0, c6_a: 1, c5_b: 2, c6_b: 3, serials_resolved: true,
}

describe('planWeldDraw', () => {
  it('places markers on the two bond midpoints', () => {
    const [p] = planWeldDraw([PAIR], getPosFor(0.34))
    expect(p.midA).toEqual([0.0695, 0, 0])
    expect(p.midB).toEqual([0.0695, 0, 0.34])
    expect(p.dNm).toBeCloseTo(0.34, 9)
  })

  it('colours by propensity — a close pair differs from a far one', () => {
    const [near] = planWeldDraw([PAIR], getPosFor(0.34))
    const [far] = planWeldDraw([PAIR], getPosFor(1.14))
    expect(near.k).toBeGreaterThan(far.k)
    expect(near.color).toBe(weldColor(near.k))
    expect(near.color).not.toBe(far.color)
  })

  it('marks the reactive corner', () => {
    const [near] = planWeldDraw([PAIR], getPosFor(0.40))
    const [far] = planWeldDraw([PAIR], getPosFor(1.14))
    expect(near.reactive).toBe(true)
    expect(far.reactive).toBe(false)
  })

  it('flags sub-vdW separation, which the force field cannot really represent', () => {
    const [tooClose] = planWeldDraw([PAIR], getPosFor(0.20))
    expect(tooClose.dNm).toBeLessThan(VDW_FLOOR_NM)
    expect(tooClose.belowVdw).toBe(true)
    const [ok] = planWeldDraw([PAIR], getPosFor(0.40))
    expect(ok.belowVdw).toBe(false)
  })

  it('skips a pair whose serials never resolved', () => {
    expect(planWeldDraw([{ ...PAIR, serials_resolved: false }], getPosFor(0.34))).toEqual([])
  })

  it('skips a pair whose atoms are absent from this frame', () => {
    expect(planWeldDraw([{ ...PAIR, c6_b: 99 }], getPosFor(0.34))).toEqual([])
  })

  it('drops only the undrawable pair, keeping the rest', () => {
    const other = { ...PAIR, id: 'c:0~d:0', c6_b: 99 }
    const plans = planWeldDraw([PAIR, other], getPosFor(0.34))
    expect(plans).toHaveLength(1)
    expect(plans[0].id).toBe('a:0~b:0')
  })

  it('is empty for no pairs and does not throw on null', () => {
    expect(planWeldDraw([], getPosFor(0.34))).toEqual([])
    expect(planWeldDraw(null, getPosFor(0.34))).toEqual([])
  })

  it('carries a human-readable readout', () => {
    const [p] = planWeldDraw([PAIR], getPosFor(0.34))
    expect(p.readout).toContain('3.40 Å')
  })
})

// ── factory behaviour that does not need a real Three.js scene ────────────────

const fakeScene = () => ({ add: vi.fn(), remove: vi.fn() })

describe('initCpdWeldOverlay', () => {
  it('starts hidden and draws nothing until made visible', () => {
    const overlay = initCpdWeldOverlay({ scene: fakeScene(), THREE: null })
    overlay.setPairs([PAIR])
    expect(overlay.isVisible()).toBe(false)
    expect(overlay.update(getPosFor(0.34))).toEqual([])
    expect(overlay.getReadouts()).toEqual([])
  })

  it('filters unresolved pairs out of the set it keeps', () => {
    const overlay = initCpdWeldOverlay({ scene: fakeScene(), THREE: null })
    overlay.setPairs([PAIR, { ...PAIR, id: 'x', serials_resolved: false }])
    overlay.setVisible(true)
    // THREE is null so nothing is built, but the plan still computes
    const plans = overlay.update(getPosFor(0.34))
    expect(plans.map((p) => p.id)).toEqual(['a:0~b:0'])
  })

  it('reports readouts once visible', () => {
    const overlay = initCpdWeldOverlay({ scene: fakeScene(), THREE: null })
    overlay.setPairs([PAIR])
    overlay.setVisible(true)
    overlay.update(getPosFor(0.34))
    const r = overlay.getReadouts()
    expect(r).toHaveLength(1)
    expect(r[0].label).toBe('a[k=0]~b[k=0]')
    expect(r[0].readout).toContain('Å')
  })

  it('clears its plans when hidden again', () => {
    const overlay = initCpdWeldOverlay({ scene: fakeScene(), THREE: null })
    overlay.setPairs([PAIR])
    overlay.setVisible(true)
    overlay.update(getPosFor(0.34))
    overlay.setVisible(false)
    expect(overlay.update(getPosFor(0.34))).toEqual([])
  })

  it('survives being constructed with no scene at all', () => {
    const overlay = initCpdWeldOverlay({})
    overlay.setPairs([PAIR])
    overlay.setVisible(true)
    expect(() => overlay.update(getPosFor(0.34))).not.toThrow()
    expect(() => overlay.dispose()).not.toThrow()
  })

  it('loadForJob fetches pairs, switches on, and reports the reason when there are none', async () => {
    const overlay = initCpdWeldOverlay({ scene: fakeScene(), THREE: null })
    const api = { getMdCpdPairs: vi.fn().mockResolvedValue({ ready: true, pairs: [PAIR] }) }
    const got = await overlay.loadForJob(api, 'job1')
    expect(api.getMdCpdPairs).toHaveBeenCalledWith('job1')
    expect(got.ready).toBe(true)
    expect(overlay.isVisible()).toBe(true)

    const empty = { getMdCpdPairs: vi.fn().mockResolvedValue({ ready: true, pairs: [], reason: 'no reciprocal pair' }) }
    const o2 = initCpdWeldOverlay({ scene: fakeScene(), THREE: null })
    const r2 = await o2.loadForJob(empty, 'job2')
    expect(r2.reason).toBe('no reciprocal pair')
    expect(o2.isVisible()).toBe(false) // nothing to show → stays off
  })

  it('does not throw when the request fails', async () => {
    const overlay = initCpdWeldOverlay({ scene: fakeScene(), THREE: null })
    const api = { getMdCpdPairs: vi.fn().mockResolvedValue(null) } // client returns null on error
    await expect(overlay.loadForJob(api, 'j')).resolves.toMatchObject({ ready: false })
  })
})

// ── the actual drawing, against real three.js ────────────────────────────────
// The tests above pass THREE: null, so they never exercise mesh creation. This does —
// it is where a bad quaternion/scale or a disposal leak would actually show up.

describe('initCpdWeldOverlay with real three.js', () => {
  it('creates meshes and places them on the bond midpoints', async () => {
    const THREE = await import('three')
    const scene = new THREE.Scene()
    const overlay = initCpdWeldOverlay({ scene, THREE })
    overlay.setPairs([PAIR])
    overlay.setVisible(true)
    overlay.update(getPosFor(0.34))

    const group = scene.getObjectByName('cpdWeldOverlay')
    expect(group).toBeTruthy()
    const meshes = group.children.filter((c) => c.isMesh)
    expect(meshes).toHaveLength(3) // marker A, marker B, connecting bar

    const positions = meshes.map((m) => [m.position.x, m.position.y, m.position.z])
    expect(positions).toContainEqual([0.0695, 0, 0]) // midpoint A
    expect(positions).toContainEqual([0.0695, 0, 0.34]) // midpoint B
    expect(positions).toContainEqual([0.0695, 0, 0.17]) // bar sits halfway
  })

  it('scales the bar to the pair separation and re-aims it as the pair moves', async () => {
    const THREE = await import('three')
    const scene = new THREE.Scene()
    const overlay = initCpdWeldOverlay({ scene, THREE })
    overlay.setPairs([PAIR])
    overlay.setVisible(true)

    overlay.update(getPosFor(0.34))
    const group = scene.getObjectByName('cpdWeldOverlay')
    const bar = group.children.find((c) => c.scale.y !== 1)
    expect(bar.scale.y).toBeCloseTo(0.34, 6)

    overlay.update(getPosFor(1.14))
    expect(bar.scale.y).toBeCloseTo(1.14, 6)
    // the cylinder's +Y axis must end up along the pair vector (+z here)
    const aim = new THREE.Vector3(0, 1, 0).applyQuaternion(bar.quaternion)
    expect(aim.z).toBeCloseTo(1, 6)
  })

  it('recolours as the pair approaches the reactive corner', async () => {
    const THREE = await import('three')
    const scene = new THREE.Scene()
    const overlay = initCpdWeldOverlay({ scene, THREE })
    overlay.setPairs([PAIR])
    overlay.setVisible(true)

    overlay.update(getPosFor(1.14))
    const group = scene.getObjectByName('cpdWeldOverlay')
    const far = group.children[0].material.color.getHex()
    overlay.update(getPosFor(0.40))
    const near = group.children[0].material.color.getHex()
    expect(near).not.toBe(far)
  })

  it('hides rather than mis-draws when the renderer supplies no resolver', async () => {
    const THREE = await import('three')
    const scene = new THREE.Scene()
    const overlay = initCpdWeldOverlay({ scene, THREE })
    overlay.setPairs([PAIR])
    overlay.setVisible(true)
    overlay.update(getPosFor(0.34))
    const group = scene.getObjectByName('cpdWeldOverlay')
    expect(group.children.some((c) => c.visible)).toBe(true)

    overlay.update(null) // the cluster-transform case the renderer guards
    expect(group.children.every((c) => !c.visible)).toBe(true)
  })

  it('dispose removes its group from the scene', async () => {
    const THREE = await import('three')
    const scene = new THREE.Scene()
    const overlay = initCpdWeldOverlay({ scene, THREE })
    overlay.setPairs([PAIR])
    overlay.setVisible(true)
    overlay.update(getPosFor(0.34))
    expect(scene.getObjectByName('cpdWeldOverlay')).toBeTruthy()
    overlay.dispose()
    expect(scene.getObjectByName('cpdWeldOverlay')).toBeFalsy()
  })
})
