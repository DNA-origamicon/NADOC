/**
 * Unit tests for initEndExtrudeArrows.
 *
 * Uses actual THREE.js math/geometry classes (pure JS, no WebGL) and mocks only:
 *   - the store module (no real state needed)
 *   - the scene object (a plain { add, remove } stub)
 *   - the selectionManager (gesture owner; measurement state is intentionally ignored)
 *   - the designRenderer (returns backbone entries on demand)
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import * as THREE from 'three'

// ── Store mock ────────────────────────────────────────────────────────────────

vi.mock('../state/store.js', () => ({
  store: {
    getState:  vi.fn(),
    subscribe: vi.fn(),
  },
}))

// ── API client mock ───────────────────────────────────────────────────────────

vi.mock('../api/client.js', () => ({
  resizeStrandEnds: vi.fn(() => Promise.resolve(null)),
}))

import { store } from '../state/store.js'
import { resizeStrandEnds } from '../api/client.js'
import { initEndExtrudeArrows, terminalRunLength, adjacentBpFree, oneNtResizableEnd } from './end_extrude_arrows.js'

// ── Helpers ───────────────────────────────────────────────────────────────────

function makeHelix(id = 'h_XY_0_0', { axisStart = [0, 0, 0], axisEnd = [0, 0, 14] } = {}) {
  return {
    id,
    axis_start: { x: axisStart[0], y: axisStart[1], z: axisStart[2] },
    axis_end:   { x: axisEnd[0],   y: axisEnd[1],   z: axisEnd[2]   },
    bp_start:   0,
    length_bp:  42,
  }
}

/**
 * Minimal bead entry matching the canonical End-ref renderer adapter.
 */
function makeBead({ helixId = 'h_XY_0_0', bp = 0, isFivePrime = true, pos = [0.1, 0.2, 0] } = {}) {
  const nuc = {
    helix_id:      helixId,
    bp_index:      bp,
    direction:     'FORWARD',
    strand_type:   'staple',
    is_five_prime:  isFivePrime,
    is_three_prime: !isFivePrime,
    backbone_position: pos,
  }
  return {
    entry: {
      pos:         new THREE.Vector3(...pos),
      instMesh:    { instanceColor: null, instanceMatrix: null },
      defaultColor: 0x29b6f6,
    },
    nuc,
  }
}

const selectionFor = (key, kind = 'base') => ({
  context: 'design', level: kind === 'end' ? 'end' : 'base',
  items: key ? [{ kind, key }] : [], primary: key ? { kind, key } : null,
})

// ── Fixtures ──────────────────────────────────────────────────────────────────

let scene, camera, canvas, selectionManager, designRenderer, selectionStoreSub

beforeEach(() => {
  vi.clearAllMocks()

  scene = { add: vi.fn(), remove: vi.fn() }

  camera = {}  // not used by the logic exercised in these tests

  canvas = {
    addEventListener:    vi.fn(),
    removeEventListener: vi.fn(),
    getBoundingClientRect: vi.fn(() => ({ left: 0, top: 0, width: 800, height: 600 })),
    style: {},
  }

  selectionManager = {}

  designRenderer = {
    getBackboneEntries: vi.fn(() => []),
  }

  store.getState.mockReturnValue({
    currentDesign:    { helices: [makeHelix()], strands: [] },
    currentHelixAxes: null,
    selection:        selectionFor(null),
    selectedObject:   null,
    selectableTypes:  { ends: false },
  })
  store.subscribe.mockImplementation(() => {})
})

// helper: grab root group and store subscriber from a fresh init
function setup() {
  initEndExtrudeArrows(scene, camera, canvas, selectionManager, designRenderer, null)
  const rootGroup    = scene.add.mock.calls[0][0]
  const storeSub     = store.subscribe.mock.calls[0][0]
  selectionStoreSub = storeSub
  return { rootGroup, storeSub }
}

function selectEndBeads(beads) {
  const entries = beads.map(bead => {
    bead.entry.nuc = bead.nuc
    return bead.entry
  })
  designRenderer.getBackboneEntries.mockReturnValue(entries)
  const prev = store.getState()
  const items = beads.map(bead => ({
    kind: 'end', key: `${bead.nuc.helix_id}:${bead.nuc.bp_index}:${bead.nuc.direction}`,
  }))
  const next = { ...prev, selection: {
    context: 'design', level: 'end', items, primary: items.at(-1) ?? null,
  } }
  store.getState.mockReturnValue(next)
  selectionStoreSub(next, prev)
}

// ── Setup ─────────────────────────────────────────────────────────────────────

describe('setup', () => {
  it('adds a root group to the scene on init', () => {
    const { rootGroup } = setup()
    expect(rootGroup).toBeInstanceOf(THREE.Group)
  })

  it('does not subscribe to measurement-anchor callbacks', () => {
    setup()
    expect(selectionManager.onCtrlBeadsChange).toBeUndefined()
  })

  it('subscribes to the store', () => {
    setup()
    expect(store.subscribe).toHaveBeenCalledOnce()
  })
})

// ── Arrow creation via canonical End refs ────────────────────────────────────

describe('canonical End path', () => {
  it('adds one arrow for a 5-prime End ref', () => {
    const { rootGroup } = setup()
    selectEndBeads([makeBead({ isFivePrime: true })])
    expect(rootGroup.children).toHaveLength(1)
  })

  it('adds one arrow for a 3-prime End ref', () => {
    const { rootGroup } = setup()
    selectEndBeads([makeBead({ isFivePrime: false })])
    expect(rootGroup.children).toHaveLength(1)
  })

  it('skips non-end entries even if given an End-shaped ref', () => {
    const { rootGroup } = setup()
    const bead = makeBead()
    bead.nuc.is_five_prime  = false
    bead.nuc.is_three_prime = false
    selectEndBeads([bead])
    expect(rootGroup.children).toHaveLength(0)
  })

  it('places two arrows for two end beads', () => {
    store.getState.mockReturnValue({
      currentDesign:    { helices: [makeHelix('h_XY_0_0'), makeHelix('h_XY_1_0')], strands: [] },
      currentHelixAxes: null,
      selectedObject:   null,
      selectableTypes:  { ends: true },
    })
    const { rootGroup } = setup()
    selectEndBeads([
      makeBead({ helixId: 'h_XY_0_0', isFivePrime: true  }),
      makeBead({ helixId: 'h_XY_1_0', isFivePrime: false }),
    ])
    expect(rootGroup.children).toHaveLength(2)
  })

  it('each arrow group has shaft and head meshes', () => {
    const { rootGroup } = setup()
    selectEndBeads([makeBead()])
    const ag = rootGroup.children[0]
    expect(ag.children).toHaveLength(2)
    expect(ag.children[0]).toBeInstanceOf(THREE.Mesh)
    expect(ag.children[1]).toBeInstanceOf(THREE.Mesh)
  })

  it('positions arrow at bead world position', () => {
    const { rootGroup } = setup()
    selectEndBeads([makeBead({ pos: [1.5, 2.3, 0.7] })])
    const ag = rootGroup.children[0]
    expect(ag.position.x).toBeCloseTo(1.5)
    expect(ag.position.y).toBeCloseTo(2.3)
    expect(ag.position.z).toBeCloseTo(0.7)
  })
})

// ── Arrow creation via canonical base selection ───────────────────────────────

describe('canonical base path', () => {
  it('adds an arrow when a 5-prime base ref is selected', () => {
    const bead = makeBead({ isFivePrime: true, pos: [0, 0, 0.1] })
    designRenderer.getBackboneEntries.mockReturnValue([bead.entry])
    // Make entry accessible by nuc fields
    bead.entry.nuc = bead.nuc

    store.getState.mockReturnValue({
      currentDesign:    { helices: [makeHelix()], strands: [] },
      currentHelixAxes: null,
      selection:        selectionFor('h_XY_0_0:0:FORWARD'),
      selectableTypes:  { ends: false },
    })

    const { rootGroup, storeSub } = setup()
    storeSub(store.getState(), { currentDesign: null, currentHelixAxes: null, selection: selectionFor(null) })

    expect(rootGroup.children).toHaveLength(1)
  })

  it('adds an arrow when a 3-prime base ref is selected', () => {
    const bead = makeBead({ bp: 41, isFivePrime: false, pos: [0, 0, 13.9] })
    designRenderer.getBackboneEntries.mockReturnValue([bead.entry])
    bead.entry.nuc = bead.nuc

    store.getState.mockReturnValue({
      currentDesign:    { helices: [makeHelix()], strands: [] },
      currentHelixAxes: null,
      selection:        selectionFor('h_XY_0_0:41:FORWARD'),
      selectableTypes:  { ends: false },
    })

    const { rootGroup, storeSub } = setup()
    storeSub(store.getState(), { currentDesign: null, currentHelixAxes: null, selection: selectionFor(null) })

    expect(rootGroup.children).toHaveLength(1)
  })

  it('does not add an arrow for a selected non-end base', () => {
    const bead = makeBead({ isFivePrime: false, pos: [0, 0, 5] })
    bead.nuc.is_three_prime = false
    designRenderer.getBackboneEntries.mockReturnValue([bead.entry])
    bead.entry.nuc = bead.nuc

    store.getState.mockReturnValue({
      currentDesign:    { helices: [makeHelix()], strands: [] },
      currentHelixAxes: null,
      selection:        selectionFor('h_XY_0_0:20:FORWARD'),
      selectableTypes:  { ends: false },
    })

    const { rootGroup, storeSub } = setup()
    storeSub(store.getState(), { currentDesign: null, currentHelixAxes: null, selection: selectionFor(null) })

    expect(rootGroup.children).toHaveLength(0)
  })

  it('does not duplicate an arrow for a canonical End ref', () => {
    const bead = makeBead({ isFivePrime: true })
    designRenderer.getBackboneEntries.mockReturnValue([bead.entry])
    bead.entry.nuc = bead.nuc

    store.getState.mockReturnValue({
      currentDesign:    { helices: [makeHelix()], strands: [] },
      currentHelixAxes: null,
      selection:        selectionFor('h_XY_0_0:0:FORWARD', 'end'),
      selectableTypes:  { ends: true },
    })

    const { rootGroup } = setup()
    selectEndBeads([bead])

    expect(rootGroup.children).toHaveLength(1)  // not 2
  })
})

// ── Arrow direction ───────────────────────────────────────────────────────────

describe('arrow direction', () => {
  it('points outward at the near end (−axisDir)', () => {
    // Axis along +Z; bead at z=0.1 is near axis_start → outward = −Z
    const { rootGroup } = setup()
    selectEndBeads([makeBead({ pos: [0, 0, 0.1] })])
    const q = rootGroup.children[0].quaternion
    // Y=(0,1,0) → (0,0,-1): axis=(-1,0,0), angle=90° → q=(-√2/2, 0, 0, √2/2)
    expect(q.x).toBeCloseTo(-Math.SQRT2 / 2, 4)
    expect(q.y).toBeCloseTo(0, 4)
    expect(q.z).toBeCloseTo(0, 4)
    expect(q.w).toBeCloseTo( Math.SQRT2 / 2, 4)
  })

  it('points outward at the far end (+axisDir)', () => {
    const { rootGroup } = setup()
    selectEndBeads([makeBead({ isFivePrime: false, pos: [0, 0, 13.9] })])
    const q = rootGroup.children[0].quaternion
    // Y=(0,1,0) → (0,0,+1): axis=(+1,0,0), angle=90° → q=(+√2/2, 0, 0, √2/2)
    expect(q.x).toBeCloseTo( Math.SQRT2 / 2, 4)
    expect(q.y).toBeCloseTo(0, 4)
    expect(q.z).toBeCloseTo(0, 4)
    expect(q.w).toBeCloseTo( Math.SQRT2 / 2, 4)
  })
})

// ── Reactivity ────────────────────────────────────────────────────────────────

describe('reactivity', () => {
  it('clears arrows when bead list becomes empty', () => {
    const { rootGroup } = setup()
    selectEndBeads([makeBead()])
    expect(rootGroup.children).toHaveLength(1)
    selectEndBeads([])
    expect(rootGroup.children).toHaveLength(0)
  })

  it('replaces arrows when bead list changes', () => {
    store.getState.mockReturnValue({
      currentDesign:    { helices: [makeHelix('h_XY_0_0'), makeHelix('h_XY_1_0')], strands: [] },
      currentHelixAxes: null,
      selectedObject:   null,
      selectableTypes:  { ends: true },
    })
    const { rootGroup } = setup()
    selectEndBeads([makeBead({ helixId: 'h_XY_0_0' })])
    expect(rootGroup.children).toHaveLength(1)
    selectEndBeads([
      makeBead({ helixId: 'h_XY_0_0' }),
      makeBead({ helixId: 'h_XY_1_0' }),
    ])
    expect(rootGroup.children).toHaveLength(2)
  })

  it('rebuilds when canonical selection changes', () => {
    const bead = makeBead({ isFivePrime: true })
    designRenderer.getBackboneEntries.mockReturnValue([bead.entry])
    bead.entry.nuc = bead.nuc

    const { rootGroup, storeSub } = setup()
    expect(rootGroup.children).toHaveLength(0)

    store.getState.mockReturnValue({
      currentDesign:    { helices: [makeHelix()], strands: [] },
      currentHelixAxes: null,
      selection:        selectionFor('h_XY_0_0:0:FORWARD'),
      selectableTypes:  { ends: false },
    })
    storeSub(
      { currentDesign: {}, currentHelixAxes: null, selection: selectionFor('h_XY_0_0:0:FORWARD') },
      { currentDesign: {}, currentHelixAxes: null, selection: selectionFor(null) },
    )

    expect(rootGroup.children).toHaveLength(1)
  })
})

// ── terminalRunLength (shorten-limit budget) ───────────────────────────────────

describe('terminalRunLength', () => {
  it('returns the terminal domain length for a plain (non-overhang) end', () => {
    const strand = { domains: [{ helix_id: 'h0', start_bp: 5, end_bp: 35, direction: 'FORWARD' }] }
    expect(terminalRunLength(strand, true)).toBe(31)   // 35-5+1
    expect(terminalRunLength(strand, false)).toBe(31)
  })

  it('spans the whole run for an inline overhang at the 3-prime end', () => {
    // [scaf_part 5..41] + [inline overhang 42..45] on the SAME helix.
    // The free 3′ end may be dragged through the boundary → run = 5..45 = 41 bp,
    // not just the 4-bp overhang domain.
    const strand = { domains: [
      { helix_id: 'h0', start_bp: 5,  end_bp: 41, direction: 'FORWARD' },
      { helix_id: 'h0', start_bp: 42, end_bp: 45, direction: 'FORWARD', overhang_id: 'ovhg_inline_stap_3p' },
    ] }
    expect(terminalRunLength(strand, false)).toBe(41)   // (41-5+1) + (45-42+1)
  })

  it('spans the whole run for an inline overhang at the 5-prime end', () => {
    const strand = { domains: [
      { helix_id: 'h0', start_bp: 0,  end_bp: 3,  direction: 'FORWARD', overhang_id: 'ovhg_inline_stap_5p' },
      { helix_id: 'h0', start_bp: 4,  end_bp: 40, direction: 'FORWARD' },
    ] }
    expect(terminalRunLength(strand, true)).toBe(41)    // (3-0+1) + (40-4+1)
  })

  it('does NOT extend when the overhang neighbour is on a different helix (crossover tail)', () => {
    // A whole-domain overhang whose adjacent domain crossed over to another helix
    // cannot merge across a scaffold boundary — keep the single-domain limit.
    const strand = { domains: [
      { helix_id: 'h1', start_bp: 10, end_bp: 30, direction: 'FORWARD' },
      { helix_id: 'h0', start_bp: 42, end_bp: 45, direction: 'FORWARD', overhang_id: 'ovhg_inline_stap_3p' },
    ] }
    expect(terminalRunLength(strand, false)).toBe(4)    // 45-42+1, neighbour ignored
  })

  it('does NOT extend for a non-inline overhang tag', () => {
    const strand = { domains: [
      { helix_id: 'h0', start_bp: 5,  end_bp: 41, direction: 'FORWARD' },
      { helix_id: 'h0', start_bp: 42, end_bp: 45, direction: 'FORWARD', overhang_id: 'user_overhang_7' },
    ] }
    expect(terminalRunLength(strand, false)).toBe(4)
  })

  it('returns 1 for empty / missing strands', () => {
    expect(terminalRunLength(null, true)).toBe(1)
    expect(terminalRunLength({ domains: [] }, false)).toBe(1)
  })
})

// ── 1-nt resizable-end picker: re-export smoke ────────────────────────────────
// Canonical tests live in shared/strand_end_resize.test.js. This only guards the
// re-export binding (a bare `export … from` would forward to importers but leave
// the picker unusable inside this module — see LESSONS H9).

describe('adjacentBpFree / oneNtResizableEnd re-export', () => {
  it('re-exports the shared picker and it resolves the pinned-5′ stub to 3′', () => {
    expect(typeof adjacentBpFree).toBe('function')
    const stub = { helix_id: 'h0', direction: 'FORWARD', bp_index: 16, strand_id: 'stub' }
    const strands = [{ id: 'xo', domains: [{ helix_id: 'h0', start_bp: 0, end_bp: 15, direction: 'FORWARD' }] }]
    expect(oneNtResizableEnd(stub, strands)).toBe('3p')
  })
})

// ── Deformed axes ─────────────────────────────────────────────────────────────

describe('deformed axes', () => {
  it('uses curved-axis tangent when helixAxes samples are present', () => {
    // Axis curves along +X; bead near start → outward = −X
    const samples = [[0,0,0], [1,0,0], [2,0,0], [3,0,0]]
    store.getState.mockReturnValue({
      currentDesign:    { helices: [makeHelix()], strands: [] },
      currentHelixAxes: { 'h_XY_0_0': { start: [0,0,0], end: [3,0,0], samples } },
      selectedObject:   null,
      selectableTypes:  { ends: false },
    })

    const { rootGroup } = setup()
    selectEndBeads([makeBead({ pos: [0.1, 0, 0] })])

    // outward = samples[0]-samples[1] = (-1,0,0)
    // Y=(0,1,0) → (-1,0,0): axis=(0,0,+1), angle=90° → q=(0,0,+√2/2,+√2/2)
    const q = rootGroup.children[0].quaternion
    expect(q.x).toBeCloseTo(0, 4)
    expect(q.y).toBeCloseTo(0, 4)
    expect(q.z).toBeCloseTo( Math.SQRT2 / 2, 4)
    expect(q.w).toBeCloseTo( Math.SQRT2 / 2, 4)
  })
})


describe('VR arrow resizing', () => {
  function fixture() {
    const arrows = initEndExtrudeArrows(scene, camera, canvas, selectionManager, designRenderer, null)
    selectionStoreSub = store.subscribe.mock.calls[0][0]
    const state = store.getState()
    state.currentDesign.strands = [{ id: 's1', domains: [{ helix_id: 'h_XY_0_0', direction: 'FORWARD', start_bp: 0, end_bp: 41 }] }]
    const bead = makeBead()
    bead.nuc.strand_id = 's1'
    selectEndBeads([bead])
    resizeStrandEnds.mockResolvedValue({ design: {} })
    return arrows
  }

  it('exports the selected arrow and commits outward pulls with the correct signed bp delta', async () => {
    const arrows = fixture()
    const snapshot = arrows.vrHandles()
    expect(snapshot.minimum).toBe(-41)
    expect(snapshot.handles[0].direction[2]).toBeCloseTo(-1)
    await arrows.resizeFromVR(snapshot.version, 7)
    expect(resizeStrandEnds).toHaveBeenCalledWith([
      { strand_id: 's1', helix_id: 'h_XY_0_0', end: '5p', delta_bp: -7 },
    ])
    arrows.dispose()
  })

  it('forwards early export only for a validated native resize', async () => {
    const arrows = fixture()
    const snapshot = arrows.vrHandles()
    const onCommitted = vi.fn()
    await expect(arrows.resizeFromVR(snapshot.version + 1, 7, onCommitted)).rejects.toThrow()
    expect(resizeStrandEnds).not.toHaveBeenCalled()
    await arrows.resizeFromVR(snapshot.version, 7, onCommitted)
    expect(resizeStrandEnds).toHaveBeenCalledWith([
      { strand_id: 's1', helix_id: 'h_XY_0_0', end: '5p', delta_bp: -7 },
    ], { onCommitted })
    arrows.dispose()
  })

  it('resizes both termini by the same outward amount and retains both relocated end refs', async () => {
    const selectionController = { replace: vi.fn() }
    const arrows = initEndExtrudeArrows(scene, camera, canvas, selectionManager, designRenderer, null, { selectionController })
    selectionStoreSub = store.subscribe.mock.calls[0][0]
    store.getState().currentDesign.strands = [{ id: 's1', domains: [{ helix_id: 'h_XY_0_0', direction: 'FORWARD', start_bp: 0, end_bp: 41 }] }]
    const first = makeBead(), last = makeBead({ bp: 41, isFivePrime: false, pos: [0, 0, 14] })
    first.nuc.strand_id = last.nuc.strand_id = 's1'
    selectEndBeads([first, last])
    const snapshot = arrows.vrHandles()
    expect(snapshot.handles).toHaveLength(2)
    resizeStrandEnds.mockImplementation(async () => {
      // A topology refresh prunes old terminal keys before the response resolves.
      store.getState().selection = selectionFor(null)
      store.getState().currentGeometry = [
        { ...first.nuc, bp_index: -7 }, { ...last.nuc, bp_index: 48 },
      ]
      return { design: {} }
    })
    await arrows.resizeFromVR(snapshot.version, 7)
    expect(resizeStrandEnds).toHaveBeenCalledWith([
      { strand_id: 's1', helix_id: 'h_XY_0_0', end: '5p', delta_bp: -7 },
      { strand_id: 's1', helix_id: 'h_XY_0_0', end: '3p', delta_bp: 7 },
    ])
    expect(selectionController.replace).toHaveBeenCalledWith([
      { kind: 'end', key: 'h_XY_0_0:-7:FORWARD' },
      { kind: 'end', key: 'h_XY_0_0:48:FORWARD' },
    ])
    arrows.dispose()
  })

  it('rejects a stale design, duplicate release, and shortening through the last base', async () => {
    const arrows = fixture()
    const snapshot = arrows.vrHandles()
    await expect(arrows.resizeFromVR(snapshot.version, -42)).rejects.toThrow()
    await arrows.resizeFromVR(snapshot.version, -3)
    await expect(arrows.resizeFromVR(snapshot.version, -3)).rejects.toThrow()
    const fresh = arrows.vrHandles()
    store.getState.mockReturnValue({ ...store.getState(), currentDesign: { ...store.getState().currentDesign } })
    await expect(arrows.resizeFromVR(fresh.version, 1)).rejects.toThrow()
    expect(resizeStrandEnds).toHaveBeenCalledTimes(1)
    arrows.dispose()
  })

  it('caps extension at a neighboring strand and clears handles on deselection', () => {
    const arrows = fixture()
    store.getState().currentDesign.strands.push({ id: 'obstacle', domains: [{ helix_id: 'h_XY_0_0', direction: 'FORWARD', start_bp: -10, end_bp: -4 }] })
    expect(arrows.vrHandles().maximum).toBe(3)
    selectEndBeads([])
    expect(arrows.vrHandles().handles).toEqual([])
    arrows.dispose()
  })
})


describe('curved desktop resize gesture', () => {
  it.each([1, 2])('traces a trim around the bend for %i ends, turns arrows, and cancels without a commit', count => {
    const rise = .334
    const samples = [[0, 0, 0], [0, 0, 7 * rise], [7 * rise, 0, 7 * rise], [14 * rise, 0, 7 * rise]]
    const helix = { ...makeHelix(), length_bp: 22 }
    store.getState().currentDesign = { helices: [helix], strands: [{ id: 's', domains: [
      { helix_id: helix.id, direction: 'FORWARD', start_bp: 0, end_bp: 21 },
    ] }] }
    store.getState().currentHelixAxes = { [helix.id]: { start: samples[0], end: samples.at(-1), samples } }
    camera = new THREE.OrthographicCamera(-10, 10, 7.5, -7.5, .1, 100)
    camera.position.set(0, 20, 0); camera.up.set(0, 0, 1); camera.lookAt(0, 0, 0); camera.updateMatrixWorld()
    const arrows = initEndExtrudeArrows(scene, camera, canvas, selectionManager, designRenderer, { enabled: true })
    selectionStoreSub = store.subscribe.mock.calls[0][0]
    const bead = makeBead({ bp: 21, isFivePrime: false, pos: samples.at(-1) }); bead.nuc.strand_id = 's'
    const beads = [bead]
    if (count === 2) {
      const other = { ...helix, id: 'other' }
      store.getState().currentDesign.helices.push(other)
      store.getState().currentDesign.strands.push({ id: 'other-strand', domains: [{ helix_id: other.id, direction: 'FORWARD', start_bp: 0, end_bp: 21 }] })
      const shifted = samples.map(([x, y, z]) => [x, y + 2, z])
      store.getState().currentHelixAxes.other = { start: shifted[0], end: shifted.at(-1), samples: shifted }
      const second = makeBead({ helixId: other.id, bp: 21, isFivePrime: false, pos: shifted.at(-1) })
      second.nuc.strand_id = 'other-strand'
      beads.push(second)
    }
    selectEndBeads(beads)
    const group = scene.add.mock.calls[0][0], preview = scene.add.mock.calls[1][0]
    const hit = vi.spyOn(THREE.Raycaster.prototype, 'intersectObjects').mockReturnValue([{ object: group.children[0].children[0] }])
    const screen = xyz => {
      const p = new THREE.Vector3(...xyz).project(camera)
      return { clientX: (p.x + 1) * 400, clientY: (1 - p.y) * 300 }
    }
    try {
      const down = canvas.addEventListener.mock.calls.find(c => c[0] === 'pointerdown')[1]
      down({ button: 0, ...screen([14 * rise + .75, 0, 7 * rise]), stopImmediatePropagation() {} })
      document.dispatchEvent(new MouseEvent('pointermove', screen([0, 0, 3 * rise + .75])))
      expect(preview.children).toHaveLength(3 * count)
      for (const arrow of group.children) expect(arrow.position.z).toBeCloseTo(3 * rise)
      expect(group.children[0].position.x).toBeCloseTo(0)
      expect(group.children[0].position.z).toBeCloseTo(3 * rise)
      const direction = new THREE.Vector3(0, 1, 0).applyQuaternion(group.children[0].quaternion)
      expect(direction.z).toBeCloseTo(1)
      expect(preview.children.every(m => m.material.color.getHex() === 0xff4400)).toBe(true)
      document.dispatchEvent(new MouseEvent('pointermove', screen([264 * rise + .75, 0, 7 * rise])))
      expect(group.children[0].position.x).toBeCloseTo(214 * rise)
      expect(preview.children.every(m => m.material.color.getHex() === 0x00e5ff)).toBe(true)
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
      expect(preview.children).toHaveLength(0)
      expect(group.children[0].position.toArray()).toEqual(samples.at(-1))
      expect(resizeStrandEnds).not.toHaveBeenCalled()
    } finally { hit.mockRestore(); arrows.dispose() }
  })

  it('orients an interior terminus by its bp tangent rather than the nearest helix endpoint', () => {
    const samples = [[0, 0, 0], [0, 0, 2], [2, 0, 2], [2, 0, 0]]
    store.getState().currentDesign.helices = [{ ...makeHelix(), length_bp: 22 }]
    store.getState().currentHelixAxes = { h_XY_0_0: { start: samples[0], end: samples.at(-1), samples } }
    const { rootGroup } = setup()
    selectEndBeads([makeBead({ bp: 10, isFivePrime: false, pos: [.8, 0, 2] })])
    const direction = new THREE.Vector3(0, 1, 0).applyQuaternion(rootGroup.children[0].quaternion)
    expect(direction.x).toBeCloseTo(1)
    expect(direction.z).toBeCloseTo(0)
  })
})
