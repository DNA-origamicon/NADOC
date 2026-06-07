/**
 * Wiring tests for the protein subsystem factory (extraction #85).
 *
 * No pure cores here — the block is a stateful cluster (dedicated atomistic
 * renderer + transform gizmo + coalesced server fetch + 2 store subscribers).
 * We mock the two scene-module imports and global fetch, then drive store
 * changes and assert the subscribers route to refresh / gizmo correctly.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createMockStore } from '../test-helpers/mock_store.js'

// Capture the gizmo callbacks main.js wires (onLiveStart/onLive/onLiveEnd) and
// expose vi.fn() stubs for the renderer + gizmo so we can assert the wiring.
const rendererStub = () => ({
  centroidOf: vi.fn(() => [1, 2, 3]),
  beginLiveTransform: vi.fn(),
  applyLiveTransform: vi.fn(),
  endLiveTransform: vi.fn(),
  highlight: vi.fn(),
  setMode: vi.fn(),
  update: vi.fn(),
  getMode: vi.fn(() => 'off'),
})
let _lastRenderer = null
let _lastGizmo = null

vi.mock('./atomistic_renderer.js', () => ({
  initAtomisticRenderer: vi.fn(() => { _lastRenderer = rendererStub(); return _lastRenderer }),
}))
vi.mock('./protein_gizmo.js', () => ({
  initProteinGizmo: vi.fn((store, controls, cbs) => {
    let attached = false
    _lastGizmo = {
      _cbs: cbs,
      attach: vi.fn(() => { attached = true }),
      detach: vi.fn(() => { attached = false }),
      isAttached: vi.fn(() => attached),
    }
    return _lastGizmo
  }),
}))
vi.mock('../shared/doc_id.js', () => ({ docHeaders: () => ({ 'X-NADOC-Doc': 'test' }) }))

import { initProteinSubsystem } from './protein_subsystem.js'

function makeDeps(initialState = {}) {
  return {
    scene: {},
    store: createMockStore({ selectedObject: null, currentDesign: null, ...initialState }),
    controls: {},
    camera: {},
    canvas: {},
  }
}

const flush = () => new Promise(r => setTimeout(r, 0))

describe('initProteinSubsystem', () => {
  beforeEach(() => {
    _lastRenderer = null
    _lastGizmo = null
    global.fetch = vi.fn()
    global.window = global.window || {}
  })
  afterEach(() => { vi.clearAllMocks() })

  it('returns the renderer + gizmo + refresh + syncSelectionVisual api', () => {
    const deps = makeDeps()
    const sub = initProteinSubsystem(deps)
    expect(sub.renderer).toBe(_lastRenderer)
    expect(sub.gizmo).toBe(_lastGizmo)
    expect(typeof sub.refresh).toBe('function')
    expect(typeof sub.syncSelectionVisual).toBe('function')
  })

  it('refreshes proteins (fetch + vdw update) when a design with attachments loads', async () => {
    global.fetch.mockResolvedValue({
      ok: true,
      json: async () => ({ atoms: [{ helix_id: '__protein__p1' }] }),
    })
    const deps = makeDeps()
    initProteinSubsystem(deps)
    deps.store._emit({ currentDesign: { protein_attachments: [{ id: 'p1' }] } })
    await flush()
    expect(global.fetch).toHaveBeenCalledWith(
      '/api/design/protein/atomistic',
      { headers: { 'X-NADOC-Doc': 'test' } },
    )
    expect(_lastRenderer.setMode).toHaveBeenCalledWith('vdw')
    expect(_lastRenderer.update).toHaveBeenCalledWith({ atoms: [{ helix_id: '__protein__p1' }] })
  })

  it('clears proteins (mode off + empty update) when the fetch returns no atoms', async () => {
    global.fetch.mockResolvedValue({ ok: true, json: async () => ({ atoms: [] }) })
    const deps = makeDeps()
    const sub = initProteinSubsystem(deps)
    // renderer currently shows something → removal path fires even with no attachments
    _lastRenderer.getMode.mockReturnValue('vdw')
    deps.store._emit({ currentDesign: { protein_attachments: [] } })
    await flush()
    expect(_lastRenderer.setMode).toHaveBeenCalledWith('off')
    expect(_lastRenderer.update).toHaveBeenCalledWith({ atoms: [] })
    void sub
  })

  it('does NOT refresh when no attachments and renderer already off', async () => {
    const deps = makeDeps()
    initProteinSubsystem(deps)
    deps.store._emit({ currentDesign: { protein_attachments: [] } })
    await flush()
    expect(global.fetch).not.toHaveBeenCalled()
  })

  it('attaches the gizmo at the centroid when a protein is selected', () => {
    const deps = makeDeps()
    initProteinSubsystem(deps)
    deps.store._emit({ selectedObject: { type: 'protein', id: 'p1' } })
    expect(_lastRenderer.centroidOf).toHaveBeenCalled()
    expect(_lastGizmo.attach).toHaveBeenCalledWith('p1', deps.scene, deps.camera, deps.canvas, [1, 2, 3])
    expect(_lastRenderer.highlight).toHaveBeenCalledWith({ type: 'protein', id: 'p1' })
  })

  it('detaches the gizmo + clears highlight when selection leaves a protein', () => {
    const deps = makeDeps()
    initProteinSubsystem(deps)
    deps.store._emit({ selectedObject: { type: 'protein', id: 'p1' } })  // attach
    deps.store._emit({ selectedObject: null })                            // deselect
    expect(_lastGizmo.detach).toHaveBeenCalled()
    expect(_lastRenderer.highlight).toHaveBeenLastCalledWith(null)
  })

  it('wires the gizmo live-transform callbacks to the protein renderer', () => {
    const deps = makeDeps()
    initProteinSubsystem(deps)
    _lastGizmo._cbs.onLiveStart('p1')
    expect(_lastRenderer.beginLiveTransform).toHaveBeenCalled()
    _lastGizmo._cbs.onLive('MATRIX')
    expect(_lastRenderer.applyLiveTransform).toHaveBeenCalledWith('MATRIX')
    _lastGizmo._cbs.onLiveEnd()
    expect(_lastRenderer.endLiveTransform).toHaveBeenCalled()
  })

  it('coalesces overlapping refreshes (one in-flight fetch at a time)', async () => {
    let resolveFetch
    global.fetch.mockReturnValue(new Promise(r => { resolveFetch = r }))
    const deps = makeDeps()
    const sub = initProteinSubsystem(deps)
    sub.refresh()  // in-flight
    sub.refresh()  // should set pending, NOT a second fetch
    expect(global.fetch).toHaveBeenCalledTimes(1)
    resolveFetch({ ok: true, json: async () => ({ atoms: [] }) })
    await flush()
    // pending re-run fires exactly one more fetch
    expect(global.fetch).toHaveBeenCalledTimes(2)
  })
})
