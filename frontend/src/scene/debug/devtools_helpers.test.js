import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { initDevtoolsDebug } from './devtools_helpers.js'
import { createMockStore } from '../../test-helpers/mock_store.js'

function makeDeps(overrides = {}) {
  const store = overrides.store ?? createMockStore({ currentDesign: null, currentGeometry: null, cadnanoActive: false })
  return {
    store,
    designRenderer: {
      getBackboneEntries: vi.fn(() => []),
      getHelixCtrl: vi.fn(() => null),
      applyUnfoldOffsets: vi.fn(),
      applyDeformLerp: vi.fn(),
      applyCadnanoPositions: vi.fn(),
      ...overrides.designRenderer,
    },
    api: { getDesign: vi.fn(async () => {}), getGeometry: vi.fn(async () => {}), ...overrides.api },
    overhangLinkArcs: overrides.overhangLinkArcs ?? { group: { children: [] } },
    selectionManager: overrides.selectionManager ?? { tag: 'selMgr' },
    scene: overrides.scene ?? { tag: 'scene' },
  }
}

// Silence the helpers' console chatter but keep spies for assertions.
beforeEach(() => {
  vi.spyOn(console, 'log').mockImplementation(() => {})
  vi.spyOn(console, 'warn').mockImplementation(() => {})
  vi.spyOn(console, 'group').mockImplementation(() => {})
  vi.spyOn(console, 'groupEnd').mockImplementation(() => {})
  vi.spyOn(console, 'trace').mockImplementation(() => {})
})
afterEach(() => vi.restoreAllMocks())

const snap = (entries) => {
  const map = new Map()
  for (const [k, v] of entries) map.set(k, v)
  return { label: 'l', map }
}

describe('diffPos (pure)', () => {
  const dbg = () => initDevtoolsDebug(makeDeps())

  it('flags only beads that moved more than the threshold', () => {
    const a = snap([['x', [0, 0, 0]], ['y', [1, 1, 1]]])
    const b = snap([['x', [0, 0, 0]], ['y', [1, 1, 2]]]) // y moved 1nm
    const moved = dbg().diffPos(a, b)
    expect(moved.map(r => r[0])).toEqual(['y'])
  })

  it('honors a custom threshold', () => {
    const a = snap([['x', [0, 0, 0]]])
    const b = snap([['x', [0, 0, 0.1]]]) // 0.1nm
    expect(dbg().diffPos(a, b, 0.05)).toHaveLength(1)
    expect(dbg().diffPos(a, b, 0.2)).toHaveLength(0)
  })

  it('reports keys present in A but missing in B', () => {
    const moved = dbg().diffPos(snap([['gone', [0, 0, 0]]]), snap([]))
    expect(moved).toEqual([['gone', 'missing in B']])
  })
})

describe('snapPos', () => {
  it('snapshots non-phantom beads keyed by helix:bp:dir, skipping __ helices', () => {
    const entries = [
      { nuc: { helix_id: 'h0', bp_index: 5, direction: 'FORWARD' }, pos: { x: 1, y: 2, z: 3 } },
      { nuc: { helix_id: '__ext_1', bp_index: 0, direction: 'FORWARD' }, pos: { x: 9, y: 9, z: 9 } },
    ]
    const dbg = initDevtoolsDebug(makeDeps({ designRenderer: { getBackboneEntries: () => entries } }))
    const { map } = dbg.snapPos('before')
    expect([...map.keys()]).toEqual(['h0:5:FORWARD'])
    expect(map.get('h0:5:FORWARD')).toEqual([1, 2, 3])
  })
})

describe('linkers', () => {
  it('returns null and warns when no design is loaded', () => {
    const dbg = initDevtoolsDebug(makeDeps())
    expect(dbg.linkers()).toBeNull()
    expect(console.warn).toHaveBeenCalled()
  })

  it('flags orphan __lnk__ helices when there are 0 connections', () => {
    const store = createMockStore({
      currentDesign: { overhang_connections: [], helices: [{ id: '__lnk__c1' }], strands: [] },
      currentGeometry: [],
    })
    const dbg = initDevtoolsDebug(makeDeps({ store }))
    const inv = dbg.linkers()
    expect(inv.issues.some(i => i.includes('__lnk__ helices but 0 connections'))).toBe(true)
  })

  it('reports no mismatches when helices match their connections', () => {
    const store = createMockStore({
      currentDesign: {
        overhang_connections: [{ id: 'c1', name: 'L', linker_type: 'ds' }],
        helices: [{ id: '__lnk__c1' }],
        strands: [],
      },
      currentGeometry: [],
    })
    const dbg = initDevtoolsDebug(makeDeps({ store }))
    expect(dbg.linkers().issues).toEqual([])
  })
})

describe('refetch', () => {
  it('awaits getDesign then getGeometry', async () => {
    const deps = makeDeps()
    const dbg = initDevtoolsDebug(deps)
    await dbg.refetch()
    expect(deps.api.getDesign).toHaveBeenCalledOnce()
    expect(deps.api.getGeometry).toHaveBeenCalledOnce()
  })
})

describe('forceRebuild', () => {
  it('bumps currentGeometry to a fresh array reference', () => {
    const geo = [{ a: 1 }]
    const store = createMockStore({ currentGeometry: geo, currentHelixAxes: null })
    const dbg = initDevtoolsDebug(makeDeps({ store }))
    dbg.forceRebuild()
    const next = store.getState().currentGeometry
    expect(next).not.toBe(geo)       // new reference (triggers rebuild)
    expect(next).toEqual(geo)        // same contents
  })

  it('warns and no-ops with no geometry', () => {
    const store = createMockStore({ currentGeometry: null })
    initDevtoolsDebug(makeDeps({ store })).forceRebuild()
    expect(console.warn).toHaveBeenCalled()
  })
})

describe('storeTrace', () => {
  it('patches setState, then stop() un-patches and delegates to the real setState', () => {
    const store = createMockStore({})
    const orig = store.setState
    const dbg = initDevtoolsDebug(makeDeps({ store }))
    const stop = dbg.storeTrace(['cadnanoActive'])
    const patched = store.setState
    expect(patched).not.toBe(orig)        // setState is now wrapped
    stop()
    expect(store.setState).not.toBe(patched) // wrapper removed (restores a bound copy)
    store.setState({ cadnanoActive: true })  // un-patched path still mutates real state
    expect(store.getState().cadnanoActive).toBe(true)
  })
})

describe('posTrace', () => {
  it('wraps then restores designRenderer position setters (functionally)', () => {
    const deps = makeDeps()
    const origUnfold = deps.designRenderer.applyUnfoldOffsets
    const dbg = initDevtoolsDebug(deps)
    dbg.posTrace(true)
    const patched = deps.designRenderer.applyUnfoldOffsets
    expect(patched).not.toBe(origUnfold)  // wrapped
    dbg.posTrace(false)
    expect(deps.designRenderer.applyUnfoldOffsets).not.toBe(patched) // unwrapped
    deps.designRenderer.applyUnfoldOffsets('arg')  // delegates to the real setter
    expect(origUnfold).toHaveBeenCalledWith('arg')
  })
})

describe('factory shape', () => {
  it('exposes the debug API plus the test-only module handles', () => {
    const deps = makeDeps()
    const dbg = initDevtoolsDebug(deps)
    for (const m of ['posTrace', 'snapPos', 'diffPos', 'storeTrace', 'subTrace', 'linkers', 'forceRebuild', 'refetch', 'help'])
      expect(typeof dbg[m]).toBe('function')
    expect(dbg.selectionManager).toBe(deps.selectionManager)
    expect(dbg.overhangLinkArcs).toBe(deps.overhangLinkArcs)
    expect(dbg.scene).toBe(deps.scene)
  })
})
