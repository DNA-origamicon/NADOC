import { expect, it, vi } from 'vitest'
import * as THREE from 'three'
import { createMockStore } from '../test-helpers/mock_store.js'
import { initDesignRenderer } from './design_renderer.js'

const hiddenUpdates = vi.hoisted(() => vi.fn())

// Stub GPU buffers only; drive the real store subscriber and rebuild decisions.
vi.mock('./helix_renderer.js', async importOriginal => ({
  ...await importOriginal(),
  buildStapleColorMap: () => new Map(),
  buildHelixObjects: (geometry, design) => {
    const root = new THREE.Group()
    const connection = { toBp: design.strands[0].domains[1].start_bp }
    return new Proxy({ root,
      setHiddenNucs: hiddenUpdates,
      getCrossHelixConnections: () => [connection],
      getBackboneEntries: () => [],
      lookupEntry: () => null,
    }, { get: (target, key) => key in target ? target[key] : () => {} })
  },
}))
vi.mock('./crossover_connections.js', () => ({ buildCrossoverConnections: () => null }))

for (const partial of [false, true]) {
  it(`undo restores the connection endpoint immediately (partial=${partial})`, () => {
    const design = root => ({ helices: [], crossovers: [], forced_ligations: [],
      extensions: [], overhangs: [], deformations: [], cluster_transforms: [],
      strands: [{ id: 'QD_OH1', domains: [
        { helix_id: 'parent', start_bp: 1208, end_bp: 1223, direction: 'FORWARD' },
        { helix_id: 'overhang', start_bp: root, end_bp: 1209, direction: 'REVERSE' },
      ] }],
    })
    const geometry = [{ helix_id: 'overhang', bp_index: 1209, direction: 'REVERSE' }]
    const store = createMockStore({ currentDesign: null, currentGeometry: null,
      strandColors: {}, strandGroups: [], loopStrandIds: [], currentHelixAxes: {},
    })
    const renderer = initDesignRenderer(new THREE.Scene(), store)
    try {
      store.setState({ currentDesign: design(1218), currentGeometry: geometry })
      expect(renderer.getCrossHelixConnections()[0].toBp).toBe(1218)
      store.setState({ currentDesign: design(1223),
        ...(partial ? { currentGeometry: [...geometry], lastPartialChangedHelixIds: ['parent', 'overhang'] } : {}),
      })
      expect(renderer.getCrossHelixConnections()[0].toBp).toBe(1223)
    } finally { renderer.dispose() }
  })
}

it('skips unchanged visibility while detecting mutations to a caller-owned set', () => {
  const store = createMockStore({ currentDesign: null, currentGeometry: null,
    strandColors: {}, strandGroups: [], loopStrandIds: [], currentHelixAxes: {} })
  const renderer = initDesignRenderer(new THREE.Scene(), store)
  store.setState({ currentDesign: { helices: [], crossovers: [], forced_ligations: [],
    extensions: [], overhangs: [], deformations: [], cluster_transforms: [],
    strands: [{ id: 's', domains: [{ helix_id: 'parent' }, { helix_id: 'overhang', start_bp: 1223 }] }] },
    currentGeometry: [{ helix_id: 'overhang', bp_index: 1209, direction: 'REVERSE' }] })
  try {
    hiddenUpdates.mockClear()
    renderer.setHiddenNucs(new Set())
    expect(hiddenUpdates).not.toHaveBeenCalled()
    const keys = new Set(['h:overhang'])
    renderer.setHiddenNucs(keys)
    keys.add('h:parent')
    renderer.setHiddenNucs(keys)
    renderer.setHiddenNucs(new Set(keys))
    expect(hiddenUpdates).toHaveBeenCalledTimes(2)
    expect(hiddenUpdates.mock.calls.at(-1)[0]).toEqual(keys)
  } finally { renderer.dispose() }
})
