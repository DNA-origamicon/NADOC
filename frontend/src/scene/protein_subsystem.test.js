/**
 * Wiring tests for the protein subsystem factory (extraction #85).
 *
 * No pure cores here — the block is a stateful cluster (dedicated atomistic
 * renderer + transform gizmo + coalesced server fetch + 2 store subscribers).
 * We mock the two scene-module imports and global fetch, then drive store
 * changes and assert the subscribers route to refresh / gizmo correctly.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { Vector3 } from 'three'
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
  raycastPick: vi.fn(),
  applyOxdnaTransforms: vi.fn(),
  clearOxdnaTransforms: vi.fn(),
  dispose: vi.fn(),
})
let _lastRenderer = null
let _lastTraceRenderer = null
let _lastGizmo = null

vi.mock('./atomistic_renderer.js', () => ({
  initAtomisticRenderer: vi.fn(() => { _lastRenderer = rendererStub(); return _lastRenderer }),
}))
vi.mock('./protein_trace_renderer.js', () => ({
  initProteinTraceRenderer: vi.fn(() => {
    _lastTraceRenderer = { ...rendererStub(), dispose: vi.fn(), applyOxdnaTransforms: vi.fn(), clearOxdnaTransforms: vi.fn(), raycastPick: vi.fn() }
    return _lastTraceRenderer
  }),
}))
vi.mock('./protein_gizmo.js', () => ({
  initProteinGizmo: vi.fn((store, controls, cbs) => {
    let attached = false
    _lastGizmo = {
      _cbs: cbs,
      attach: vi.fn(() => { attached = true }),
      detach: vi.fn(() => { attached = false }),
      cancel: vi.fn(() => { attached = false; return Promise.resolve(true) }),
      isAttached: vi.fn(() => attached),
      getAttachmentId: vi.fn(() => attached ? 'p1' : null),
    }
    return _lastGizmo
  }),
}))
vi.mock('../shared/doc_id.js', () => ({ docHeaders: () => ({ 'X-NADOC-Doc': 'test' }) }))

import { initProteinSubsystem } from './protein_subsystem.js'

function makeDeps(initialState = {}) {
  return {
    scene: {},
    store: createMockStore({
      selection: { context: 'design', level: 'default', items: [], primary: null },
      selectedObject: null, currentDesign: null, ...initialState,
    }),
    controls: {},
    camera: {},
    canvas: {},
  }
}

const flush = () => new Promise(r => setTimeout(r, 0))

describe('initProteinSubsystem', () => {
  beforeEach(() => {
    _lastRenderer = null
    _lastTraceRenderer = null
    _lastGizmo = null
    global.fetch = vi.fn()
    global.window = global.window || {}
  })
  afterEach(() => { vi.clearAllMocks() })

  it('returns the renderer + gizmo + refresh + syncSelectionVisual api', () => {
    const deps = makeDeps()
    const sub = initProteinSubsystem(deps)
    expect(sub.renderer).not.toBe(_lastRenderer)
    expect(typeof sub.renderer.raycastPick).toBe('function')
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
    expect(_lastTraceRenderer.setMode).toHaveBeenCalledWith('trace')
    expect(_lastRenderer.setMode).toHaveBeenCalledWith('off')
    expect(_lastRenderer.update).toHaveBeenCalledWith({ atoms: [{ helix_id: '__protein__p1' }] })
    expect(_lastTraceRenderer.update).toHaveBeenCalledWith({ atoms: [{ helix_id: '__protein__p1' }] })
  })

  it('applies stick and yields protein geometry to the global surface renderer', async () => {
    global.fetch.mockResolvedValue({
      ok: true,
      json: async () => ({ atoms: [{ helix_id: '__protein__p1' }], bonds: [[0, 1]] }),
    })
    const deps = makeDeps()
    const sub = initProteinSubsystem(deps)
    await sub.refresh()

    window.dispatchEvent(new CustomEvent('nadoc:representation-change', {
      detail: { representation: 'stick' },
    }))
    expect(_lastRenderer.setMode).toHaveBeenLastCalledWith('stick')

    window.dispatchEvent(new CustomEvent('nadoc:representation-change', {
      detail: { representation: 'surface' },
    }))
    expect(_lastRenderer.setMode).toHaveBeenLastCalledWith('off')
    sub.dispose()
  })

  it('uses the protein ovoid renderer for cylinders', async () => {
    global.fetch.mockResolvedValue({
      ok: true,
      json: async () => ({ atoms: [{ helix_id: '__protein__p1' }] }),
    })
    const sub = initProteinSubsystem(makeDeps())
    await sub.refresh()
    window.dispatchEvent(new CustomEvent('nadoc:representation-change', {
      detail: { representation: 'cylinders' },
    }))
    expect(_lastRenderer.setMode).toHaveBeenLastCalledWith('off')
    expect(_lastTraceRenderer.setMode).toHaveBeenLastCalledWith('ovoid')
    sub.dispose()
  })

  it('clears proteins (mode off + empty update) when the fetch returns no atoms', async () => {
    global.fetch.mockResolvedValue({ ok: true, json: async () => ({ atoms: [] }) })
    const deps = makeDeps()
    const sub = initProteinSubsystem(deps)
    // renderer currently shows something → removal path fires even with no attachments
    _lastTraceRenderer.getMode.mockReturnValue('trace')
    deps.store._emit({ currentDesign: { protein_attachments: [] } })
    await flush()
    expect(_lastRenderer.setMode).toHaveBeenCalledWith('off')
    expect(_lastTraceRenderer.setMode).toHaveBeenCalledWith('off')
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
    deps.store._emit({ selection: {
      context: 'design', level: 'default',
      items: [{ kind: 'protein', id: 'p1' }], primary: { kind: 'protein', id: 'p1' },
    } })
    expect(_lastTraceRenderer.centroidOf).toHaveBeenCalled()
    expect(_lastGizmo.attach).toHaveBeenCalledWith('p1', deps.scene, deps.camera, deps.canvas, [1, 2, 3], null)
    expect(_lastRenderer.highlight).toHaveBeenCalledWith({ type: 'protein', id: 'p1', data: { attachment_id: 'p1' } })
  })

  it('anchors a conjugated protein gizmo at the protein centroid', async () => {
    const constraint = {
      attachment_id: 'p1', mode: 'two_ball_joint',
      root: [0, 0, 0], joint: [4, 5, 6], radius_nm: 8.77,
    }
    global.fetch.mockResolvedValue({
      ok: true,
      json: async () => ({ atoms: [{ helix_id: '__protein__p1' }], protein_constraints: [constraint] }),
    })
    document.body.innerHTML = '<div id="move-rotate-panel" style="display:none"></div><div id="mr-current-selection"></div><div id="mr-session-hint"></div>'
    const deps = makeDeps()
    deps.rightSidebar = { open: vi.fn() }
    const sub = initProteinSubsystem(deps)
    await sub.refresh()
    deps.store._emit({ selection: {
      context: 'design', level: 'default',
      items: [{ kind: 'protein', id: 'p1' }], primary: { kind: 'protein', id: 'p1' },
    } })
    expect(_lastGizmo.attach).toHaveBeenCalledWith(
      'p1', deps.scene, deps.camera, deps.canvas,
      [1, 2, 3], constraint,
    )
    expect(deps.rightSidebar.open).toHaveBeenCalledWith('properties')
    expect(document.getElementById('move-rotate-panel').style.display).toBe('')
    expect(document.getElementById('mr-session-hint').textContent).toContain('constrained live')
  })

  it('previews the constrained overhang and binder on every live protein frame', async () => {
    const helixCtrl = { captureClusterBase: vi.fn(), applyClusterTransform: vi.fn() }
    const bluntEnds = { captureClusterBase: vi.fn(), applyClusterTransform: vi.fn() }
    const locations = { captureClusterBase: vi.fn(), applyClusterTransform: vi.fn() }
    const constraint = {
      attachment_id: 'p1', mode: 'two_ball_joint', helix_id: 'oh-h', overhang_id: 'oh-1',
      domain_ids: [
        { strand_id: 'selected-oh', domain_index: 0 },
        { strand_id: 'selected-binder', domain_index: 0 },
      ],
      is_extrude: false,
      root: [0, 0, 0], joint: [5, 0, 0], radius_nm: 5,
    }
    global.fetch.mockResolvedValue({
      ok: true,
      json: async () => ({ atoms: [{ helix_id: '__protein__p1' }], protein_constraints: [constraint] }),
    })
    const deps = makeDeps()
    Object.assign(deps, {
      designRenderer: { getHelixCtrl: () => helixCtrl },
      getBluntEnds: () => bluntEnds,
      overhangLocations: locations,
    })
    const sub = initProteinSubsystem(deps)
    await sub.refresh()
    _lastGizmo._cbs.onLiveStart('p1')
    _lastGizmo._cbs.onLive('protein-matrix', {
      constraint,
      position: new Vector3(0, 5, 0),
    })
    expect(helixCtrl.captureClusterBase).toHaveBeenCalled()
    expect(helixCtrl.applyClusterTransform).toHaveBeenCalled()
    expect(bluntEnds.applyClusterTransform).toHaveBeenCalled()
    const domainIds = constraint.domain_ids
    expect(helixCtrl.captureClusterBase).toHaveBeenCalledWith(['oh-h'], domainIds)
    expect(helixCtrl.applyClusterTransform.mock.calls[0][4]).toEqual(domainIds)
    expect(bluntEnds.captureClusterBase.mock.calls[0][0]).toEqual(new Set(['oh-1']))
    expect(bluntEnds.applyClusterTransform.mock.calls[0][0]).toEqual(['oh-1'])
    // Shared/inline helix: never invoke the whole-helix location/axis path,
    // which would move sibling overhang domains on the same helix.
    expect(locations.captureClusterBase).not.toHaveBeenCalled()
    expect(locations.applyClusterTransform).not.toHaveBeenCalled()
    expect(_lastTraceRenderer.applyLiveTransform).toHaveBeenCalledWith('protein-matrix')
    expect(global.fetch).toHaveBeenCalledTimes(1) // selection fetch only; drag frames stay local
  })

  it('keeps extrude/stub sibling axes domain-scoped instead of appending forceAxes', async () => {
    const helixCtrl = { captureClusterBase: vi.fn(), applyClusterTransform: vi.fn() }
    const locations = { captureClusterBase: vi.fn(), applyClusterTransform: vi.fn() }
    const constraint = {
      attachment_id: 'p1', mode: 'two_ball_joint', helix_id: 'shared-stub',
      overhang_id: 'selected-oh', is_extrude: true,
      domain_ids: [{ strand_id: 'selected-strand', domain_index: 1 }],
      root: [0, 0, 0], joint: [4, 0, 0], radius_nm: 4,
    }
    global.fetch.mockResolvedValue({
      ok: true,
      json: async () => ({ atoms: [{ helix_id: '__protein__p1' }], protein_constraints: [constraint] }),
    })
    const deps = makeDeps()
    Object.assign(deps, {
      designRenderer: { getHelixCtrl: () => helixCtrl },
      overhangLocations: locations,
    })
    const sub = initProteinSubsystem(deps)
    await sub.refresh()

    _lastGizmo._cbs.onLiveStart('p1')
    _lastGizmo._cbs.onLive('protein-matrix', {
      constraint, position: new Vector3(0, 4, 0),
    })

    expect(helixCtrl.captureClusterBase).toHaveBeenCalledTimes(1)
    expect(helixCtrl.captureClusterBase).toHaveBeenCalledWith(
      ['shared-stub'], constraint.domain_ids,
    )
    expect(helixCtrl.applyClusterTransform).toHaveBeenCalledTimes(1)
    expect(helixCtrl.applyClusterTransform.mock.calls[0]).toHaveLength(5)
    expect(locations.captureClusterBase).not.toHaveBeenCalled()
    expect(locations.applyClusterTransform).not.toHaveBeenCalled()
  })

  it('implicitly cancels and restores the preview when selection leaves a protein', () => {
    document.body.innerHTML = '<div id="move-rotate-panel" data-protein-active="true"></div>'
    const deps = makeDeps()
    initProteinSubsystem(deps)
    deps.store._emit({ selection: {
      context: 'design', level: 'default',
      items: [{ kind: 'protein', id: 'p1' }], primary: { kind: 'protein', id: 'p1' },
    } })
    deps.store._emit({ selection: { context: 'design', level: 'default', items: [], primary: null } })
    expect(_lastGizmo.cancel).toHaveBeenCalledTimes(1)
    expect(_lastGizmo.detach).not.toHaveBeenCalled()
    expect(_lastRenderer.highlight).toHaveBeenLastCalledWith(null)
    expect(document.getElementById('move-rotate-panel').style.display).toBe('none')
  })

  it('wires the gizmo live-transform callbacks to the protein renderer', () => {
    const deps = makeDeps()
    initProteinSubsystem(deps)
    _lastGizmo._cbs.onLiveStart('p1')
    expect(_lastTraceRenderer.beginLiveTransform).toHaveBeenCalled()
    _lastGizmo._cbs.onLive('MATRIX')
    expect(_lastTraceRenderer.applyLiveTransform).toHaveBeenCalledWith('MATRIX')
    _lastGizmo._cbs.onLiveEnd()
    expect(_lastTraceRenderer.endLiveTransform).toHaveBeenCalled()
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
