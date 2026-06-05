/**
 * Tests for scene/flex_relax.js (extracted from main.js's Move/Rotate region).
 *
 * Two layers:
 *  - Pure cores (makeWorldPosResolver / buildTetherPayload / clusterBeadCount),
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
  clusterBeadCount,
  initFlexRelax,
} from './flex_relax.js'

// A position stub with a controllable distance, mimicking THREE.Vector3.distanceTo.
function pos(distanceTo) {
  return { distanceTo: () => distanceTo }
}

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

describe('clusterBeadCount (pure)', () => {
  const design = makeDesign()
  const entries = [
    { nuc: { helix_id: 'h1' } },
    { nuc: { helix_id: 'h1' } },
    { nuc: { helix_id: 'h2' } },
    { nuc: { helix_id: 'h3' } },
  ]

  it('counts backbone entries whose helix is in the cluster', () => {
    expect(clusterBeadCount('c1', design, entries)).toBe(2)
    expect(clusterBeadCount('c2', design, entries)).toBe(1)
  })

  it('returns 0 for an unknown cluster or empty entries', () => {
    expect(clusterBeadCount('nope', design, entries)).toBe(0)
    expect(clusterBeadCount('c1', design, [])).toBe(0)
  })
})

describe('initFlexRelax factory', () => {
  let store, api, designRenderer, clusterGizmo, deps, trActive

  function makeFlex({ entries = [], designOverrides = {} } = {}) {
    store = createMockStore({ currentDesign: makeDesign(designOverrides), assemblyActive: false })
    api = {
      getFlexibleConnections: vi.fn().mockResolvedValue({ gates: {}, connections: [] }),
      relaxFlexibleSegments: vi.fn().mockResolvedValue({}),
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
    expect(api.relaxFlexibleSegments).not.toHaveBeenCalled()
  })

  it('relaxFlexible refuses while a move is in progress', async () => {
    const flex = makeFlex()
    trActive = true
    await flex.relaxFlexible('all')
    expect(showToast).toHaveBeenCalledWith('Finish the current move first', { severity: 'error' })
    expect(api.relaxFlexibleSegments).not.toHaveBeenCalled()
  })

  it('relaxFlexible toasts when there are no flexible segments', async () => {
    const flex = makeFlex()
    await flex.relaxFlexible('all')
    expect(showToast).toHaveBeenCalledWith('No flexible segments to relax')
    expect(clusterGizmo.relaxClusterHeadless).not.toHaveBeenCalled()
  })

  it('relax-one: solves the overstretched pair headlessly and commits atomically', async () => {
    const entries = [
      { nuc: { helix_id: 'h1', bp_index: 5, direction: 'fwd' }, pos: pos(10) },
      { nuc: { helix_id: 'h2', bp_index: 8, direction: 'rev' }, pos: pos(10) },
    ]
    const flex = makeFlex({ entries, designOverrides: { flexible_connections: [CONN] } })
    clusterGizmo.getAllPendingTransforms.mockReturnValue([
      { clusterId: 'c1', pivot: [0, 0, 0], translation: [1, 0, 0], rotation: [0, 0, 0, 1] },
    ])

    await flex.relaxFlexible('one', 'conn1')

    // smaller/tied cluster c1 picked as mover; single tether → translateOnly.
    expect(clusterGizmo.relaxClusterHeadless).toHaveBeenCalled()
    const [movedId, opts] = clusterGizmo.relaxClusterHeadless.mock.calls[0]
    expect(movedId).toBe('c1')
    expect(opts.translateOnly).toBe(true)
    // one atomic commit with the mapped pending transform + the 'one' label.
    expect(api.relaxFlexibleSegments).toHaveBeenCalledTimes(1)
    const [transforms, label] = api.relaxFlexibleSegments.mock.calls[0]
    expect(transforms).toEqual([{ cluster_id: 'c1', pivot: [0, 0, 0], translation: [1, 0, 0], rotation: [0, 0, 0, 1] }])
    expect(label).toBe('Relax flexible segment')
    expect(showOpProgress).toHaveBeenCalled()
    expect(hideOpProgress).toHaveBeenCalled()
  })

  it('relax: skips non-overstretched pairs (no headless solve, no commit)', async () => {
    const entries = [
      { nuc: { helix_id: 'h1', bp_index: 5, direction: 'fwd' }, pos: pos(1) },  // 1 nm < 3 contour
      { nuc: { helix_id: 'h2', bp_index: 8, direction: 'rev' }, pos: pos(1) },
    ]
    const flex = makeFlex({ entries, designOverrides: { flexible_connections: [CONN] } })
    await flex.relaxFlexible('all')
    expect(clusterGizmo.relaxClusterHeadless).not.toHaveBeenCalled()
    expect(api.relaxFlexibleSegments).not.toHaveBeenCalled()
    expect(showToast).toHaveBeenCalledWith('Flexible segments already relaxed')
  })
})
