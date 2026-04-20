/**
 * Unit tests for initEndExtrudeArrows.
 *
 * Uses actual THREE.js math/geometry classes (pure JS, no WebGL) and mocks only:
 *   - the store module (no real state needed)
 *   - the scene object (a plain { add, remove } stub)
 *   - the selectionManager (captures the registered callback)
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
import { initEndExtrudeArrows } from './end_extrude_arrows.js'

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
 * Minimal bead entry matching the shape that selection_manager puts in _ctrlBeads.
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

// ── Fixtures ──────────────────────────────────────────────────────────────────

let scene, camera, canvas, selectionManager, designRenderer, ctrlBeadsCb, currentBeads

beforeEach(() => {
  vi.clearAllMocks()

  currentBeads = []

  scene = { add: vi.fn(), remove: vi.fn() }

  camera = {}  // not used by the logic exercised in these tests

  canvas = {
    addEventListener:    vi.fn(),
    removeEventListener: vi.fn(),
    getBoundingClientRect: vi.fn(() => ({ left: 0, top: 0, width: 800, height: 600 })),
    style: {},
  }

  selectionManager = {
    onCtrlBeadsChange: vi.fn(cb => { ctrlBeadsCb = cb }),
    getCtrlBeads:      vi.fn(() => [...currentBeads]),
  }

  designRenderer = {
    getBackboneEntries: vi.fn(() => []),
  }

  store.getState.mockReturnValue({
    currentDesign:    { helices: [makeHelix()], strands: [] },
    currentHelixAxes: null,
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
  return { rootGroup, storeSub }
}

// ── Setup ─────────────────────────────────────────────────────────────────────

describe('setup', () => {
  it('adds a root group to the scene on init', () => {
    const { rootGroup } = setup()
    expect(rootGroup).toBeInstanceOf(THREE.Group)
  })

  it('registers onCtrlBeadsChange callback', () => {
    setup()
    expect(selectionManager.onCtrlBeadsChange).toHaveBeenCalledOnce()
    expect(ctrlBeadsCb).toBeTypeOf('function')
  })

  it('subscribes to the store', () => {
    setup()
    expect(store.subscribe).toHaveBeenCalledOnce()
  })
})

// ── Arrow creation via ctrl-click / lasso (_ctrlBeads) ────────────────────────

describe('ctrl-bead path', () => {
  it('adds one arrow for a 5-prime ctrl bead', () => {
    const { rootGroup } = setup()
    ctrlBeadsCb([makeBead({ isFivePrime: true })])
    expect(rootGroup.children).toHaveLength(1)
  })

  it('adds one arrow for a 3-prime ctrl bead', () => {
    const { rootGroup } = setup()
    ctrlBeadsCb([makeBead({ isFivePrime: false })])
    expect(rootGroup.children).toHaveLength(1)
  })

  it('skips non-end ctrl beads', () => {
    const { rootGroup } = setup()
    const bead = makeBead()
    bead.nuc.is_five_prime  = false
    bead.nuc.is_three_prime = false
    ctrlBeadsCb([bead])
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
    ctrlBeadsCb([
      makeBead({ helixId: 'h_XY_0_0', isFivePrime: true  }),
      makeBead({ helixId: 'h_XY_1_0', isFivePrime: false }),
    ])
    expect(rootGroup.children).toHaveLength(2)
  })

  it('each arrow group has shaft and head meshes', () => {
    const { rootGroup } = setup()
    ctrlBeadsCb([makeBead()])
    const ag = rootGroup.children[0]
    expect(ag.children).toHaveLength(2)
    expect(ag.children[0]).toBeInstanceOf(THREE.Mesh)
    expect(ag.children[1]).toBeInstanceOf(THREE.Mesh)
  })

  it('positions arrow at bead world position', () => {
    const { rootGroup } = setup()
    ctrlBeadsCb([makeBead({ pos: [1.5, 2.3, 0.7] })])
    const ag = rootGroup.children[0]
    expect(ag.position.x).toBeCloseTo(1.5)
    expect(ag.position.y).toBeCloseTo(2.3)
    expect(ag.position.z).toBeCloseTo(0.7)
  })
})

// ── Arrow creation via regular 3-click bead selection (selectedObject) ─────────

describe('selectedObject path', () => {
  it('adds an arrow when selectedObject is a 5-prime nucleotide', () => {
    const bead = makeBead({ isFivePrime: true, pos: [0, 0, 0.1] })
    designRenderer.getBackboneEntries.mockReturnValue([bead.entry])
    // Make entry accessible by nuc fields
    bead.entry.nuc = bead.nuc

    store.getState.mockReturnValue({
      currentDesign:    { helices: [makeHelix()], strands: [] },
      currentHelixAxes: null,
      selectedObject:   { type: 'nucleotide', id: 'h_XY_0_0:0:FORWARD', data: bead.nuc },
      selectableTypes:  { ends: false },
    })

    const { rootGroup, storeSub } = setup()
    storeSub(store.getState(), { currentDesign: null, currentHelixAxes: null, selectedObject: null })

    expect(rootGroup.children).toHaveLength(1)
  })

  it('adds an arrow when selectedObject is a 3-prime nucleotide', () => {
    const bead = makeBead({ isFivePrime: false, pos: [0, 0, 13.9] })
    designRenderer.getBackboneEntries.mockReturnValue([bead.entry])
    bead.entry.nuc = bead.nuc

    store.getState.mockReturnValue({
      currentDesign:    { helices: [makeHelix()], strands: [] },
      currentHelixAxes: null,
      selectedObject:   { type: 'nucleotide', id: 'h_XY_0_0:41:FORWARD', data: bead.nuc },
      selectableTypes:  { ends: false },
    })

    const { rootGroup, storeSub } = setup()
    storeSub(store.getState(), { currentDesign: null, currentHelixAxes: null, selectedObject: null })

    expect(rootGroup.children).toHaveLength(1)
  })

  it('does not add an arrow for a non-end nucleotide selectedObject', () => {
    const bead = makeBead({ isFivePrime: false, pos: [0, 0, 5] })
    bead.nuc.is_three_prime = false
    designRenderer.getBackboneEntries.mockReturnValue([bead.entry])
    bead.entry.nuc = bead.nuc

    store.getState.mockReturnValue({
      currentDesign:    { helices: [makeHelix()], strands: [] },
      currentHelixAxes: null,
      selectedObject:   { type: 'nucleotide', id: 'h_XY_0_0:20:FORWARD', data: bead.nuc },
      selectableTypes:  { ends: false },
    })

    const { rootGroup, storeSub } = setup()
    storeSub(store.getState(), { currentDesign: null, currentHelixAxes: null, selectedObject: null })

    expect(rootGroup.children).toHaveLength(0)
  })

  it('does not duplicate an arrow when the same bead is in both _ctrlBeads and selectedObject', () => {
    const bead = makeBead({ isFivePrime: true })
    designRenderer.getBackboneEntries.mockReturnValue([bead.entry])
    bead.entry.nuc = bead.nuc

    store.getState.mockReturnValue({
      currentDesign:    { helices: [makeHelix()], strands: [] },
      currentHelixAxes: null,
      selectedObject:   { type: 'nucleotide', id: 'h_XY_0_0:0:FORWARD', data: bead.nuc },
      selectableTypes:  { ends: true },
    })

    const { rootGroup } = setup()
    ctrlBeadsCb([bead])   // adds bead via _ctrlBeads

    expect(rootGroup.children).toHaveLength(1)  // not 2
  })
})

// ── Arrow direction ───────────────────────────────────────────────────────────

describe('arrow direction', () => {
  it('points outward at the near end (−axisDir)', () => {
    // Axis along +Z; bead at z=0.1 is near axis_start → outward = −Z
    const { rootGroup } = setup()
    ctrlBeadsCb([makeBead({ pos: [0, 0, 0.1] })])
    const q = rootGroup.children[0].quaternion
    // Y=(0,1,0) → (0,0,-1): axis=(-1,0,0), angle=90° → q=(-√2/2, 0, 0, √2/2)
    expect(q.x).toBeCloseTo(-Math.SQRT2 / 2, 4)
    expect(q.y).toBeCloseTo(0, 4)
    expect(q.z).toBeCloseTo(0, 4)
    expect(q.w).toBeCloseTo( Math.SQRT2 / 2, 4)
  })

  it('points outward at the far end (+axisDir)', () => {
    const { rootGroup } = setup()
    ctrlBeadsCb([makeBead({ isFivePrime: false, pos: [0, 0, 13.9] })])
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
    ctrlBeadsCb([makeBead()])
    expect(rootGroup.children).toHaveLength(1)
    ctrlBeadsCb([])
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
    ctrlBeadsCb([makeBead({ helixId: 'h_XY_0_0' })])
    expect(rootGroup.children).toHaveLength(1)
    ctrlBeadsCb([
      makeBead({ helixId: 'h_XY_0_0' }),
      makeBead({ helixId: 'h_XY_1_0' }),
    ])
    expect(rootGroup.children).toHaveLength(2)
  })

  it('rebuilds when store selectedObject changes', () => {
    const bead = makeBead({ isFivePrime: true })
    designRenderer.getBackboneEntries.mockReturnValue([bead.entry])
    bead.entry.nuc = bead.nuc

    const { rootGroup, storeSub } = setup()
    expect(rootGroup.children).toHaveLength(0)

    store.getState.mockReturnValue({
      currentDesign:    { helices: [makeHelix()], strands: [] },
      currentHelixAxes: null,
      selectedObject:   { type: 'nucleotide', data: bead.nuc },
      selectableTypes:  { ends: false },
    })
    storeSub(
      { currentDesign: {}, currentHelixAxes: null, selectedObject: { type: 'nucleotide' } },
      { currentDesign: {}, currentHelixAxes: null, selectedObject: null },
    )

    expect(rootGroup.children).toHaveLength(1)
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
    ctrlBeadsCb([makeBead({ pos: [0.1, 0, 0] })])

    // outward = samples[0]-samples[1] = (-1,0,0)
    // Y=(0,1,0) → (-1,0,0): axis=(0,0,+1), angle=90° → q=(0,0,+√2/2,+√2/2)
    const q = rootGroup.children[0].quaternion
    expect(q.x).toBeCloseTo(0, 4)
    expect(q.y).toBeCloseTo(0, 4)
    expect(q.z).toBeCloseTo( Math.SQRT2 / 2, 4)
    expect(q.w).toBeCloseTo( Math.SQRT2 / 2, 4)
  })
})
