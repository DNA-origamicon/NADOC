/**
 * Tests for scene/flex_relax.js (extracted from main.js's Move/Rotate region).
 *
 * Two layers:
 *  - Pure cores (makeWorldPosResolver / buildTetherPayload),
 *    tested against hand-built design + backbone-entry snapshots. flexTetherConnections
 *    stays REAL (it's already its own tested module).
 *  - initFlexRelax factory wiring, with ui/toast.js + ui/op_progress.js mocked so
 *    toast text is assertable, and a stub clusterGizmo/api so the relax solve path
 *    (early-returns + headless-solve + atomic commit) is observable.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('../ui/toast.js', () => ({ showToast: vi.fn() }))
vi.mock('../ui/op_progress.js', () => ({ showOpProgress: vi.fn(), hideOpProgress: vi.fn() }))

import { showToast } from '../ui/toast.js'
import { showOpProgress, hideOpProgress } from '../ui/op_progress.js'
import { createMockStore } from '../test-helpers/mock_store.js'
import {
  makeWorldPosResolver,
  buildTetherPayload,
  initFlexRelax,
} from './flex_relax.js'

// Design with one strand whose two domains live on h1 / h2 so flexAnchorKey
// resolves the connection anchors to 'h1:5:fwd' / 'h2:8:rev'.
function makeDesign(overrides = {}) {
  return {
    strands: [{ id: 's1', domains: [{ helix_id: 'h1' }, { helix_id: 'h2' }] }],
    cluster_transforms: [
      { id: 'c1', helix_ids: ['h1'] },
      { id: 'c2', helix_ids: ['h2'] },
    ],
    flexible_connections: [],
    ...overrides,
  }
}

const CONN = {
  id: 'conn1',
  cluster_a_id: 'c1',
  cluster_b_id: 'c2',
  anchor_a: { strand_id: 's1', domain_index: 0, bp_index: 5, direction: 'fwd' },
  anchor_b: { strand_id: 's1', domain_index: 1, bp_index: 8, direction: 'rev' },
  contour_length_nm: 3.0,
}

describe('makeWorldPosResolver (pure)', () => {
  const entries = [
    { nuc: { helix_id: 'h1', bp_index: 5, direction: 'fwd' }, pos: 'P_h1_5_fwd' },
    { nuc: { helix_id: 'h2', bp_index: 8, direction: 'rev' }, pos: 'P_h2_8_rev' },
  ]

  it('returns the matching entry pos for a helix:bp:dir key', () => {
    const r = makeWorldPosResolver(entries)
    expect(r('h1:5:fwd')).toBe('P_h1_5_fwd')
    expect(r('h2:8:rev')).toBe('P_h2_8_rev')
  })

  it('returns null when no entry matches (wrong bp / dir / helix)', () => {
    const r = makeWorldPosResolver(entries)
    expect(r('h1:5:rev')).toBeNull()
    expect(r('h1:9:fwd')).toBeNull()
    expect(r('hX:5:fwd')).toBeNull()
  })

  it('tolerates a null/empty entries snapshot', () => {
    expect(makeWorldPosResolver(null)('h1:5:fwd')).toBeNull()
    expect(makeWorldPosResolver([])('h1:5:fwd')).toBeNull()
  })
})

describe('buildTetherPayload (pure)', () => {
  it('builds per-tether moving/fixed keys for the moving cluster + a live resolver', () => {
    const design = makeDesign()
    const entries = [
      { nuc: { helix_id: 'h1', bp_index: 5, direction: 'fwd' }, pos: 'PM' },
      { nuc: { helix_id: 'h2', bp_index: 8, direction: 'rev' }, pos: 'PF' },
    ]
    const { connections, resolveWorldPos } = buildTetherPayload([CONN], 'c1', design, entries)
    // moving end is the anchor on c1 (anchor_a → h1:5:fwd); fixed = the other end.
    expect(connections).toEqual([{ movingKey: 'h1:5:fwd', fixedKey: 'h2:8:rev', contour: 3.0 }])
    expect(resolveWorldPos('h1:5:fwd')).toBe('PM')
    expect(resolveWorldPos('h2:8:rev')).toBe('PF')
  })

  it('swaps moving/fixed when the OTHER cluster is the mover', () => {
    const { connections } = buildTetherPayload([CONN], 'c2', makeDesign(), [])
    expect(connections).toEqual([{ movingKey: 'h2:8:rev', fixedKey: 'h1:5:fwd', contour: 3.0 }])
  })

  it('drops connections not touching the moving cluster', () => {
    const { connections } = buildTetherPayload([CONN], 'cZ', makeDesign(), [])
    expect(connections).toEqual([])
  })
})

describe('initFlexRelax factory', () => {
  let store, api, designRenderer, clusterGizmo, deps, trActive

  function makeFlex({ entries = [], designOverrides = {} } = {}) {
    store = createMockStore({ currentDesign: makeDesign(designOverrides), assemblyActive: false })
    api = {
      getFlexibleConnections: vi.fn().mockResolvedValue({ gates: {}, connections: [] }),
      solveFlexibleSegments: vi.fn().mockResolvedValue({
        converged: true, transforms: [], connections: [], max_excess_nm: 0,
      }),
    }
    designRenderer = { getBackboneEntries: vi.fn(() => entries) }
    clusterGizmo = {
      discardPendingTransforms: vi.fn(),
      relaxClusterHeadless: vi.fn(() => ({ moved: true, residual: 0 })),
      getAllPendingTransforms: vi.fn(() => []),
      detach: vi.fn(),
    }
    trActive = false
    deps = { store, api, designRenderer, clusterGizmo, isTranslateRotateActive: () => trActive }
    return initFlexRelax(deps)
  }

  beforeEach(() => { vi.clearAllMocks() })

  it('hasGate reflects refreshed gates', async () => {
    const flex = makeFlex()
    expect(flex.hasGate('c1')).toBe(false)       // before refresh
    api.getFlexibleConnections.mockResolvedValue({ gates: { c1: { gate: true } }, connections: [] })
    await flex.refreshFlexGates()
    expect(flex.hasGate('c1')).toBe(true)
    expect(flex.hasGate('c2')).toBe(false)
    expect(flex.hasGate(null)).toBe(false)
  })

  it('refreshFlexGates swallows API errors → empty gates/connections', async () => {
    const flex = makeFlex()
    api.getFlexibleConnections.mockRejectedValue(new Error('boom'))
    await flex.refreshFlexGates()
    expect(flex.hasGate('c1')).toBe(false)
  })

  it('coalesces concurrent gate fetches and ignores a stale document response',async()=>{
    const flex=makeFlex(), resolvers=[]
    api.getFlexibleConnections.mockImplementation(()=>new Promise(resolve=>resolvers.push(resolve)))
    const a=flex.refreshFlexGates(), same=flex.refreshFlexGates()
    expect(same).toBe(a)
    store.setState({currentDesign:makeDesign({id:'new'})})
    const b=flex.refreshFlexGates()
    resolvers[1]({gates:{c1:{gate:true}},connections:[]});await b
    resolvers[0]({gates:{},connections:[]});await a
    expect(flex.hasGate('c1')).toBe(true)
  })

  it('buildSsdnaPayload uses the refreshed connections + current design + live entries', async () => {
    const entries = [
      { nuc: { helix_id: 'h1', bp_index: 5, direction: 'fwd' }, pos: 'PM' },
      { nuc: { helix_id: 'h2', bp_index: 8, direction: 'rev' }, pos: 'PF' },
    ]
    const flex = makeFlex({ entries })
    api.getFlexibleConnections.mockResolvedValue({ gates: {}, connections: [CONN] })
    await flex.refreshFlexGates()
    const { connections, resolveWorldPos } = flex.buildSsdnaPayload('c1')
    expect(connections).toEqual([{ movingKey: 'h1:5:fwd', fixedKey: 'h2:8:rev', contour: 3.0 }])
    expect(resolveWorldPos('h1:5:fwd')).toBe('PM')
  })

  it('relaxFlexible no-ops in assembly mode (no toast, no commit)', async () => {
    const flex = makeFlex()
    store.setState({ assemblyActive: true })
    await flex.relaxFlexible('all')
    expect(showToast).not.toHaveBeenCalled()
    expect(api.solveFlexibleSegments).not.toHaveBeenCalled()
  })

  it('relaxFlexible refuses while a move is in progress', async () => {
    const flex = makeFlex()
    trActive = true
    await flex.relaxFlexible('all')
    expect(showToast).toHaveBeenCalledWith('Finish the current move first', { severity: 'error' })
    expect(api.solveFlexibleSegments).not.toHaveBeenCalled()
  })

  it('relaxFlexible toasts when there are no flexible segments', async () => {
    const flex = makeFlex()
    await flex.relaxFlexible('all')
    expect(showToast).toHaveBeenCalledWith('No flexible segments to relax')
    expect(clusterGizmo.relaxClusterHeadless).not.toHaveBeenCalled()
  })

  it('relax-one requests a joint network solve and reports global convergence', async () => {
    const flex = makeFlex({ designOverrides: { flexible_connections: [CONN] } })
    api.solveFlexibleSegments.mockResolvedValue({
      converged: true, transforms: [{ cluster_id: 'c2' }],
      connections: [CONN], max_excess_nm: .0001,
    })
    await flex.relaxFlexible('one', 'conn1')
    expect(api.solveFlexibleSegments).toHaveBeenCalledExactlyOnceWith('one', 'conn1')
    expect(clusterGizmo.relaxClusterHeadless).not.toHaveBeenCalled()
    expect(showToast).toHaveBeenCalledWith('Relaxed 1 flexible segment; maximum overstretch 0.000 nm')
    expect(hideOpProgress).toHaveBeenCalled()
  })

  it('reports an already satisfied network without a geometry commit', async () => {
    const flex = makeFlex({ designOverrides: { flexible_connections: [CONN] } })
    await flex.relaxFlexible('all')
    expect(api.solveFlexibleSegments).toHaveBeenCalledExactlyOnceWith('all', null)
    expect(showToast).toHaveBeenCalledWith('Flexible segments already relaxed')
    expect(clusterGizmo.relaxClusterHeadless).not.toHaveBeenCalled()
  })

  it('shows solver failures and clears progress without painting speculative poses', async () => {
    const flex = makeFlex({ designOverrides: { flexible_connections: [CONN] } })
    api.solveFlexibleSegments.mockRejectedValue(new Error('No changes applied'))
    await flex.relaxFlexible('all')
    expect(showToast).toHaveBeenCalledWith('No changes applied', { severity: 'error' })
    expect(hideOpProgress).toHaveBeenCalled()
    expect(clusterGizmo.relaxClusterHeadless).not.toHaveBeenCalled()
  })

  it('never reports success from an unconverged response', async () => {
    const flex = makeFlex({ designOverrides: { flexible_connections: [CONN] } })
    api.solveFlexibleSegments.mockResolvedValue({ converged: false })
    await flex.relaxFlexible('all')
    expect(showToast).toHaveBeenCalledWith('Flexible relaxation did not converge', { severity: 'error' })
  })
})
