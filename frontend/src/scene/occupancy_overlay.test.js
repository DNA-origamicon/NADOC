import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import * as THREE from 'three'
import { beforeEach, describe, expect, it, vi } from 'vitest'

// The real builder needs a full Design + geometry and is ~5k LOC; the unit under test is
// the OVERLAY's discipline (grouping, opacity, LOD, disposal), so the builder is mocked
// at the module boundary. The one invariant that mocking would hide — that materials are
// created per build — is pinned separately by a source-text test at the bottom.
const built = []
vi.mock('./helix_renderer.js', () => ({
  CG_LOD: { full: 0, beads: 1, cylinders: 2 },
  buildHelixObjects: vi.fn((geometry, design, group, customColors, _loop, _axes, lod) => {
    const shared = new THREE.SphereGeometry(1, 4, 3)
    shared.userData.shared = true                      // a module-level template
    const own = new THREE.BoxGeometry(1, 1, 1)         // this build's own geometry
    const mesh = new THREE.Mesh(shared, new THREE.MeshBasicMaterial())
    const mesh2 = new THREE.Mesh(own, new THREE.MeshBasicMaterial())
    group.add(mesh, mesh2)
    const ctrl = {
      root: group, lod, customColors,
      setDetailLevel: vi.fn(() => ({ needsRebuild: false })),
      applyFemPositions: vi.fn(),
      _shared: shared, _own: own,
    }
    built.push(ctrl)
    return ctrl
  }),
}))

const { CG_LOD, buildHelixObjects } = await import('./helix_renderer.js')
const {
  OCCUPANCY_COLORS,
  OCC_MAX_ALPHA,
  OCC_MIN_ALPHA,
  clusterColors,
  clusterOpacity,
  ghostBytesPerNucleotide,
  ghostMemoryPlan,
  initOccupancyOverlay,
  occupancyFrameToUpdates,
} = await import('./occupancy_overlay.js')

// ── Pure helpers ──────────────────────────────────────────────────────────────────
describe('clusterColors', () => {
  it('is deterministic and distinct within the palette', () => {
    expect(clusterColors(3)).toEqual(clusterColors(3))
    expect(new Set(clusterColors(OCCUPANCY_COLORS.length)).size).toBe(OCCUPANCY_COLORS.length)
  })

  it('wraps past the palette rather than returning undefined', () => {
    const c = clusterColors(OCCUPANCY_COLORS.length + 2)
    expect(c).toHaveLength(OCCUPANCY_COLORS.length + 2)
    expect(c.every((v) => Number.isInteger(v))).toBe(true)
  })

  it('returns nothing for zero or negative counts', () => {
    expect(clusterColors(0)).toEqual([])
    expect(clusterColors(-1)).toEqual([])
  })
})

describe('clusterOpacity', () => {
  it('rises with population and stays inside the clamp', () => {
    expect(clusterOpacity(0)).toBeCloseTo(OCC_MIN_ALPHA)
    expect(clusterOpacity(1)).toBeCloseTo(OCC_MAX_ALPHA)
    expect(clusterOpacity(0.7)).toBeGreaterThan(clusterOpacity(0.3))
  })

  it('clamps out-of-range and non-finite populations', () => {
    expect(clusterOpacity(5)).toBeCloseTo(OCC_MAX_ALPHA)
    expect(clusterOpacity(-2)).toBeCloseTo(OCC_MIN_ALPHA)
    expect(clusterOpacity(NaN)).toBeCloseTo(OCC_MIN_ALPHA)
  })

  it('never reaches full opacity — a ghost must not read as the real model', () => {
    expect(clusterOpacity(1)).toBeLessThan(1)
  })
})

describe('ghostMemoryPlan', () => {
  it('costs less at coarser LOD', () => {
    expect(ghostBytesPerNucleotide('full')).toBeGreaterThan(ghostBytesPerNucleotide('beads'))
    expect(ghostBytesPerNucleotide('beads')).toBeGreaterThan(ghostBytesPerNucleotide('cylinders'))
    expect(ghostBytesPerNucleotide('nonsense')).toBe(ghostBytesPerNucleotide('full'))
  })

  it('reports limitedBy null when everything fits', () => {
    const p = ghostMemoryPlan({ nNucleotides: 5000, nGhosts: 2, lod: 'full' })
    expect(p.capped).toBe(false)
    expect(p.limitedBy).toBeNull()
    expect(p.ghosts).toBe(2)
  })

  it("reports limitedBy 'ram' when host memory is the binding constraint", () => {
    const p = ghostMemoryPlan({ nNucleotides: 200_000, nGhosts: 5, lod: 'full',
                               availableBytes: 60 * 1024 * 1024 })
    expect(p.capped).toBe(true)
    expect(p.limitedBy).toBe('ram')
    expect(p.ghosts).toBeLessThan(5)
  })

  it("reports limitedBy 'heap' when the fixed browser ceiling binds first", () => {
    const p = ghostMemoryPlan({ nNucleotides: 5_000_000, nGhosts: 4, lod: 'full' })
    expect(p.capped).toBe(true)
    expect(p.limitedBy).toBe('heap')
  })
})

describe('occupancyFrameToUpdates', () => {
  it('pairs each key with its xyz triple and defaults copy to 0', () => {
    const keys = [['h0', 0, 'FORWARD'], ['h0', 1, 'REVERSE', 2]]
    const frame = [1, 2, 3, 0, 0, 1, 4, 5, 6, 1, 0, 0]
    expect(occupancyFrameToUpdates(keys, frame)).toEqual([
      { helix_id: 'h0', bp_index: 0, direction: 'FORWARD', copy: 0,
        backbone_position: [1, 2, 3], nx: 0, ny: 0, nz: 1 },
      { helix_id: 'h0', bp_index: 1, direction: 'REVERSE', copy: 2,
        backbone_position: [4, 5, 6], nx: 1, ny: 0, nz: 0 },
    ])
  })

  it('carries the base normal — cones and slabs are oriented from it', () => {
    // Dropping nx/ny/nz leaves every ghost base pointing the wrong way.
    const u = occupancyFrameToUpdates([['h0', 0, 'FORWARD']], [0, 0, 0, 0.6, 0, 0.8])
    expect(u[0]).toMatchObject({ nx: 0.6, ny: 0, nz: 0.8 })
  })

  it('stops at a short frame instead of emitting undefined coordinates', () => {
    const keys = [['h0', 0, 'FORWARD'], ['h0', 1, 'FORWARD']]
    expect(occupancyFrameToUpdates(keys, [1, 2, 3, 0, 0, 1])).toHaveLength(1)
    expect(occupancyFrameToUpdates(keys, null)).toEqual([])
  })
})

// ── The overlay factory ───────────────────────────────────────────────────────────
function makeResp(populations, nKeys = 2) {
  const keys = Array.from({ length: nKeys }, (_, i) => ['h0', i, 'FORWARD'])
  const frame = Array.from({ length: nKeys * 6 }, () => 0)
  return {
    keys,
    clusters: populations.map((population, rank) => ({ rank, population, frame: [...frame] })),
  }
}

function makeOverlay(overrides = {}) {
  const scene = new THREE.Scene()
  const statuses = []
  const overlay = initOccupancyOverlay({
    scene,
    getGeometry: () => Array.from({ length: 100 }, () => ({})),
    getDesign: () => ({ strands: [{ id: 's1' }, { id: 's2' }] }),
    getHelixAxes: () => ({}),
    getRepr: () => 'full',
    onStatus: (s) => statuses.push(s),
    ...overrides,
  })
  return { scene, overlay, statuses }
}

describe('initOccupancyOverlay', () => {
  beforeEach(() => {
    built.length = 0
    buildHelixObjects.mockClear()
  })

  it('builds one copy per state — every state gets its own, including the first', async () => {
    const { scene, overlay } = makeOverlay()
    const r = await overlay.setClusters(makeResp([0.6, 0.3, 0.1]))

    expect(r.states).toBe(3)
    expect(buildHelixObjects).toHaveBeenCalledTimes(3)
    expect(overlay.stats().states).toBe(3)
    expect(scene.children.filter((c) => c.name?.startsWith('occupancyGhost'))).toHaveLength(3)
  })

  it('still builds a copy when there is only one state', async () => {
    const { overlay } = makeOverlay()
    expect((await overlay.setClusters(makeResp([1.0]))).states).toBe(1)
    expect(buildHelixObjects).toHaveBeenCalledTimes(1)
  })

  it('hands the design model aside while it owns the scene, and gives it back', async () => {
    // Every state is a copy drawn here, so the design's own per-strand-coloured model
    // must not show through underneath.
    const calls = []
    const { overlay } = makeOverlay({ setDesignVisible: (v) => calls.push(v) })
    await overlay.setClusters(makeResp([0.6, 0.4]))
    expect(calls).toEqual([false])
    expect(overlay.stats().owningScene).toBe(true)

    overlay.clear()
    expect(calls).toEqual([false, true])
    expect(overlay.stats().owningScene).toBe(false)
  })

  it('gives the model back when it ends up drawing nothing', async () => {
    const calls = []
    const { overlay } = makeOverlay({ getDesign: () => null, setDesignVisible: (v) => calls.push(v) })
    await overlay.setClusters(makeResp([0.6, 0.4]))
    expect(calls.at(-1)).toBe(true)
  })

  it('setStateVisible hides ONE state without rebuilding anything', async () => {
    const { scene, overlay } = makeOverlay()
    await overlay.setClusters(makeResp([0.6, 0.4]))
    buildHelixObjects.mockClear()

    expect(overlay.setStateVisible(1, false)).toBe(true)
    expect(scene.children.find((c) => c.name === 'occupancyGhost1').visible).toBe(false)
    expect(scene.children.find((c) => c.name === 'occupancyGhost0').visible).toBe(true)
    expect(overlay.stats().hidden).toBe(1)
    expect(buildHelixObjects).not.toHaveBeenCalled()

    overlay.setStateVisible(1, true)
    expect(scene.children.find((c) => c.name === 'occupancyGhost1').visible).toBe(true)
  })

  it('setStateColor rebuilds only the state it recolours', async () => {
    const { overlay } = makeOverlay()
    await overlay.setClusters(makeResp([0.6, 0.4]))
    buildHelixObjects.mockClear()

    expect(overlay.setStateColor(1, 0x123456)).toBe(true)
    expect(buildHelixObjects).toHaveBeenCalledTimes(1)
    expect(overlay.colors()[1]).toBe(0x123456)
    expect(overlay.colors()[0]).toBe(OCCUPANCY_COLORS[0])
  })

  it('setStateColor keeps that state hidden if it was hidden', async () => {
    const { scene, overlay } = makeOverlay()
    await overlay.setClusters(makeResp([0.6, 0.4]))
    overlay.setStateVisible(1, false)
    overlay.setStateColor(1, 0x00ff00)
    expect(scene.children.find((c) => c.name === 'occupancyGhost1').visible).toBe(false)
  })

  it('honours caller-supplied colours and visibility, so a rebuild restores the view', async () => {
    const { scene, overlay } = makeOverlay()
    await overlay.setClusters(makeResp([0.6, 0.4]),
      { colors: [0xaaaaaa, 0xbbbbbb], visible: [true, false] })
    expect(overlay.colors()).toEqual([0xaaaaaa, 0xbbbbbb])
    expect(scene.children.find((c) => c.name === 'occupancyGhost1').visible).toBe(false)
  })

  it('setStateVisible/Color report false for a rank that does not exist', async () => {
    const { overlay } = makeOverlay()
    await overlay.setClusters(makeResp([1.0]))
    expect(overlay.setStateVisible(7, false)).toBe(false)
    expect(overlay.setStateColor(7, 0x111111)).toBe(false)
  })

  it('tints every strand of a ghost one cluster colour', async () => {
    const { overlay } = makeOverlay()
    await overlay.setClusters(makeResp([0.6, 0.4]))
    const colors = built[0].customColors
    expect(Object.keys(colors)).toEqual(['s1', 's2'])
    expect(new Set(Object.values(colors)).size).toBe(1)
    expect(Object.values(colors)[0]).toBe(OCCUPANCY_COLORS[0])
  })

  it('makes ghosts transparent AND clears depthWrite', async () => {
    // A transparent mesh that still writes depth is an invisible occluder — it punches
    // voids into whatever is behind it.
    const { scene, overlay } = makeOverlay()
    await overlay.setClusters(makeResp([0.6, 0.4]))

    const ghost = scene.children.find((c) => c.name === 'occupancyGhost1')
    let checked = 0
    ghost.traverse((o) => {
      if (!o.material) return
      checked++
      expect(o.material.transparent).toBe(true)
      expect(o.material.depthWrite).toBe(false)
      expect(o.material.opacity).toBeLessThan(1)
    })
    expect(checked).toBeGreaterThan(0)
  })

  it('gives a more-populated state a more solid ghost', async () => {
    const { scene, overlay } = makeOverlay()
    await overlay.setClusters(makeResp([0.5, 0.4, 0.1]))
    const op = (n) => {
      let v = null
      scene.children.find((c) => c.name === `occupancyGhost${n}`)
        .traverse((o) => { if (o.material && v === null) v = o.material.opacity })
      return v
    }
    expect(op(1)).toBeGreaterThan(op(2))
  })

  it('calls setDetailLevel for a coarse LOD — without it the ghost draws nothing', async () => {
    const { overlay } = makeOverlay({ getRepr: () => 'cylinders' })
    await overlay.setClusters(makeResp([0.6, 0.4]))
    expect(built[0].setDetailLevel).toHaveBeenCalledWith(CG_LOD.cylinders)
  })

  it('does not call setDetailLevel at full LOD — that is already the built state', async () => {
    const { overlay } = makeOverlay({ getRepr: () => 'full' })
    await overlay.setClusters(makeResp([0.6, 0.4]))
    expect(built[0].setDetailLevel).not.toHaveBeenCalled()
  })

  it('applies each ghost its OWN cluster frame', async () => {
    const { overlay } = makeOverlay()
    const resp = makeResp([0.6, 0.3, 0.1])
    resp.clusters[1].frame[0] = 11
    resp.clusters[2].frame[0] = 22
    await overlay.setClusters(resp)

    expect(built[1].applyFemPositions.mock.calls[0][0][0].backbone_position[0]).toBe(11)
    expect(built[2].applyFemPositions.mock.calls[0][0][0].backbone_position[0]).toBe(22)
  })

  it('clear() removes every ghost from the scene', async () => {
    const { scene, overlay } = makeOverlay()
    await overlay.setClusters(makeResp([0.6, 0.4]))
    overlay.clear()

    expect(overlay.stats().ghosts).toBe(0)
    expect(scene.children.filter((c) => c.name?.startsWith('occupancyGhost'))).toHaveLength(0)
  })

  it('clear() disposes the ghost\'s own geometry but NOT shared templates', async () => {
    // The module-level template geometries are marked userData.shared precisely so
    // dispose walks skip them; disposing one would break the main model.
    const { overlay } = makeOverlay()
    await overlay.setClusters(makeResp([0.6, 0.4]))

    const sharedSpy = vi.spyOn(built[0]._shared, 'dispose')
    const ownSpy = vi.spyOn(built[0]._own, 'dispose')
    overlay.clear()

    expect(ownSpy).toHaveBeenCalled()
    expect(sharedSpy).not.toHaveBeenCalled()
  })

  it('replacing the clusters does not accumulate ghosts', async () => {
    const { scene, overlay } = makeOverlay()
    await overlay.setClusters(makeResp([0.6, 0.4]))
    await overlay.setClusters(makeResp([0.5, 0.3, 0.2]))

    expect(overlay.stats().states).toBe(3)
    expect(scene.children.filter((c) => c.name?.startsWith('occupancyGhost'))).toHaveLength(3)
  })

  it('refuses to build under a heavy representation, loudly', async () => {
    const { overlay, statuses } = makeOverlay({ getRepr: () => 'vdw' })
    const r = await overlay.setClusters(makeResp([0.6, 0.4]))

    expect(r.states).toBe(0)
    expect(r.blocked).toBe('heavy-representation')
    expect(buildHelixObjects).not.toHaveBeenCalled()
    expect(statuses.at(-1).level).toBe('warn')
    expect(statuses.at(-1).text).toMatch(/coarse-grained/i)
  })

  it('setVisible toggles the whole overlay without rebuilding it', async () => {
    const { scene, overlay } = makeOverlay()
    await overlay.setClusters(makeResp([0.6, 0.4]))
    buildHelixObjects.mockClear()
    overlay.setVisible(false)

    expect(scene.children.find((c) => c.name === 'occupancyGhost1').visible).toBe(false)
    overlay.setVisible(true)
    expect(scene.children.find((c) => c.name === 'occupancyGhost1').visible).toBe(true)
    expect(buildHelixObjects).not.toHaveBeenCalled()
  })

  it('setVisible(false) does not resurrect an individually hidden state', async () => {
    const { scene, overlay } = makeOverlay()
    await overlay.setClusters(makeResp([0.6, 0.4]))
    overlay.setStateVisible(1, false)
    overlay.setVisible(false)
    overlay.setVisible(true)
    expect(scene.children.find((c) => c.name === 'occupancyGhost1').visible).toBe(false)
  })

  it('maxStates caps how many copies are built', async () => {
    const { overlay } = makeOverlay()
    const r = await overlay.setClusters(makeResp([0.4, 0.3, 0.2, 0.1]), { maxStates: 2 })
    expect(r.states).toBe(2)
  })

  it('defaultColors gives every state a distinct colour, rank 0 included', () => {
    const { overlay } = makeOverlay()
    expect(overlay.defaultColors(3)).toEqual(
      [OCCUPANCY_COLORS[0], OCCUPANCY_COLORS[1], OCCUPANCY_COLORS[2]])
  })

  it('memoryPlan prices every state, since every state is now a copy', () => {
    const { overlay } = makeOverlay()
    const plan = overlay.memoryPlan(3)
    expect(plan.bytesPerGhost).toBe(100 * ghostBytesPerNucleotide('full'))
    expect(plan.wantBytes).toBe(3 * plan.bytesPerGhost)
  })
})

// ── Source-text pin for an invariant the mock would hide ───────────────────────────
describe('helix_renderer materials are per-build (the ghost tint depends on it)', () => {
  it('creates no Mesh*Material at module scope', () => {
    const src = readFileSync(resolve(process.cwd(), 'src/scene/helix_renderer.js'), 'utf8')
    const fnStart = src.indexOf('export function buildHelixObjects')
    expect(fnStart).toBeGreaterThan(0)

    // Any material constructed BEFORE buildHelixObjects begins would be shared across
    // every build, so setting opacity on a ghost would dim the real model too.
    const head = src.slice(0, fnStart)
    expect(head).not.toMatch(/new THREE\.Mesh\w*Material\(/)
  })
})

// ── The occupancy DOM contract, pinned against index.html ─────────────────────────
// A missing id here is silent: the panel's getElementById returns null, every listener
// is skipped with `?.`, and the feature simply never appears. These caught nothing at
// runtime — they are here so a markup rename fails a test instead of a user.
describe('index.html carries every element the occupancy UI binds', () => {
  const HTML = readFileSync(resolve(process.cwd(), 'index.html'), 'utf8')

  for (const id of [
    'oxdna-jobs-occupancy-toggle',
    'oxdna-jobs-occupancy-params',
    'oxdna-jobs-occupancy-n',
    'oxdna-jobs-occupancy-basis',
    'oxdna-jobs-occupancy-rerun',
    'oxdna-jobs-occupancy-status',
    'oxdna-jobs-occupancy-legend',
  ]) {
    it(`has #${id}`, () => {
      expect(HTML).toContain(`id="${id}"`)
    })
  }

  it('puts the toggle in the mutually-exclusive oxdna-viz radio group', () => {
    // Not being in the group would let occupancy coexist with the flexibility map, and
    // both would fight over applyFemPositions.
    const i = HTML.indexOf('id="oxdna-jobs-occupancy-toggle"')
    const tag = HTML.slice(HTML.lastIndexOf('<input', i), HTML.indexOf('>', i) + 1)
    expect(tag).toContain('name="oxdna-viz"')
    expect(tag).toContain('type="radio"')
  })
})
