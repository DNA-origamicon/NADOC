import { describe, it, expect, beforeEach, vi } from 'vitest'
import { initTranslateRotateTool, decideSelectionAction, resolveSelectionClusterId } from './translate_rotate_tool.js'
import { createMockStore } from '../test-helpers/mock_store.js'
import { mountIds, clearDom } from '../test-helpers/factory_dom.js'
import { clearShortcuts } from '../input/shortcuts.js'

// Mock the imported (non-DI) side-effect helpers so the factory body is testable
// without real toast/progress DOM. showToast capture lets us assert guard paths.
const toastCalls = []
const shortcutSpecs = []
vi.mock('../ui/toast.js', () => ({ showToast: (...a) => toastCalls.push(a) }))
vi.mock('../ui/op_progress.js', () => ({ showOpProgress: vi.fn(), hideOpProgress: vi.fn() }))
vi.mock('../input/shortcuts.js', () => ({
  registerShortcut: (spec) => shortcutSpecs.push(spec),
  clearShortcuts: () => { shortcutSpecs.length = 0 },
}))

const JOINT = { id: 'J1', cluster_id: 'C1' }

function makeDeps(overrides = {}) {
  const state = {
    assemblyActive: false,
    activeInstanceId: null,
    activeClusterId: null,
    currentDesign: { cluster_transforms: [], cluster_joints: [] },
    currentGeometry: null,
    currentHelixAxes: null,
    currentAssembly: null,
    ...(overrides.state ?? {}),
  }
  const store = createMockStore(state)

  let active = false
  let dirty = false
  let editCtx = overrides.editContext ?? null

  const jointRenderer = {
    pickJointRing: vi.fn(() => null),
    rebuild: vi.fn(),
    rebuildHulls: vi.fn(),
  }
  const helixCtrl = { commitClusterPositions: vi.fn() }
  const clusterGizmo = {
    isJointConstraintActive: vi.fn(() => false),
    getActiveJoint: vi.fn(() => null),
    beginConstrainedRotation: vi.fn(),
    attach: vi.fn(),
    setTransform: vi.fn(),
    setConstraint: vi.fn(),
    getPendingTransform: vi.fn(() => ({ translation: [1, 0, 0], rotation: [0, 0, 0, 1] })),
    clearPendingTransform: vi.fn(),
    commitPendingTransforms: vi.fn(async () => ({ clusterIds: [] })),
    discardPendingTransforms: vi.fn(),
    detach: vi.fn(),
  }
  const deps = {
    store,
    scene: {}, camera: {}, canvas: { addEventListener: vi.fn(), removeEventListener: vi.fn() },
    designRenderer: { getHelixCtrl: vi.fn(() => helixCtrl) },
    getJointRenderer: () => jointRenderer,
    clusterGizmo,
    instanceGizmo: { detach: vi.fn() },
    assemblyRenderer: { rebuild: vi.fn(async () => {}), rebuildLinkers: vi.fn() },
    assemblyJointRenderer: { rebuild: vi.fn() },
    api: { skipNextResponseDelta: vi.fn(), editFeature: vi.fn(async () => {}), seekFeatures: vi.fn(async () => {}) },
    moveRotatePanel: { setAssemblyCtx: vi.fn(), setSessionMode: vi.fn() },
    mrPanel: document.getElementById('__mrPanel'),
    mrPivotSel: document.getElementById('__mrPivotSel'),
    setTransformValues: vi.fn(),
    setTransformValuesFromMatrix: vi.fn(),
    setPivotOptions: vi.fn(),
    setSelectedPivot: vi.fn(),
    refreshCurrentSelection: vi.fn(),
    createAssemblyTransformContext: vi.fn((id) => ({ primaryStart: {}, instanceId: id })),
    hasAssemblyPending: vi.fn(() => false),
    commitAssemblyPending: vi.fn(async () => {}),
    assemblyPendingTransforms: { clear: vi.fn() },
    assemblyPendingPartJoints: { clear: vi.fn() },
    attachGroupGizmo: vi.fn(),
    flexRelax: { refreshFlexGates: vi.fn(async () => {}) },
    refreshClusterPivotForAttach: vi.fn(async () => {}),
    pickActiveClusterEntry: vi.fn(() => ({})),
    syncAssemblyBluntEnds: vi.fn(),
    rebakeHelixAxesForClusterDelta: vi.fn(),
    reemitClusterBridges: vi.fn(async () => {}),
    refreshClusterOverlays: vi.fn(),
    getActive: () => active,
    setActive: (v) => { active = v; store.setState({ translateRotateActive: v }) },
    getClusterDirty: () => dirty,
    setClusterDirty: (v) => { dirty = v },
    getEditContext: () => editCtx,
    setEditContext: (v) => { editCtx = v },
  }
  return { deps, store, clusterGizmo, jointRenderer, helixCtrl, get active() { return active }, get dirty() { return dirty }, get editCtx() { return editCtx } }
}

beforeEach(() => {
  clearDom()
  clearShortcuts()
  toastCalls.length = 0
  // mode-indicator + the panel/sidebar elements the factory + bodies query by id.
    mountIds(['mode-indicator', 'mr-apply-btn', 'mr-cancel-btn', 'mr-reset-btn', 'menu-tools-translate-rotate',
            '__mrPanel', '__mrPivotSel'])
  global.requestAnimationFrame = (cb) => { cb(0); return 0 }
})

describe('initTranslateRotateTool — API + init side effects', () => {
  it('returns the tool API surface', () => {
    const { deps } = makeDeps()
    const t = initTranslateRotateTool(deps)
    expect(typeof t.activate).toBe('function')
    expect(typeof t.confirm).toBe('function')
    expect(typeof t.cancel).toBe('function')
    expect(typeof t.rotateJoint).toBe('function')
    expect(typeof t.removeToolPickListeners).toBe('function')
    expect(typeof t.hideConfirmBtn).toBe('function')
    expect(typeof t.beginVRPreview).toBe('function')
    expect(typeof t.applyVRPreviewMatrix).toBe('function')
    expect(typeof t.cancelVRPreview).toBe('function')
  })

  it('creates the floating ✓ confirm button (hidden) and appends it to the body', () => {
    const { deps } = makeDeps()
    initTranslateRotateTool(deps)
    const btn = [...document.body.children].find(el => el.textContent === '✓')
    expect(btn).toBeTruthy()
    expect(btn.title).toBe('Confirm transforms and exit tool')
    // NB: initial hidden state is set via a multi-prop cssText; jsdom does not
    // reflect `display` from cssText (logged #19/#75), so we don't assert it here
    // — the hideConfirmBtn test (explicit style.display set) covers the toggle.
  })

  it('registers the "m" keyboard shortcut whose handler routes activate↔confirm', async () => {
    const ctx = makeDeps({ state: {
      selection: { items: [{ kind: 'cluster', id: 'C1' }] },
      currentDesign: { cluster_transforms: [
      { id: 'C1', translation: [0, 0, 0], rotation: [0, 0, 0, 1], helix_ids: [2] },
    ], cluster_joints: [] } } })
    initTranslateRotateTool(ctx.deps)
    const spec = shortcutSpecs.find(s => s.key === 'm' && s.shift === false)
    expect(spec).toBeTruthy()
    expect(spec.blockedInInput).toBe(true)
    // inactive → handler activates
    await spec.handler()
    expect(ctx.active).toBe(true)
    // active → handler confirms (deactivates)
    await spec.handler()
    expect(ctx.active).toBe(false)
  })
})

describe('initTranslateRotateTool — native VR preview adapter', () => {
  function vrContext() {
    const ctx = makeDeps({ state: { currentDesign: { cluster_transforms: [
      {
        id: 'C1', pivot: [10, 0, 0], translation: [1, 0, 0],
        rotation: [0, 0, 0, 1], helix_ids: [2],
      },
    ], cluster_joints: [] } } })
    ctx.clusterGizmo.getPendingTransform.mockReturnValue({
      pivot: [10, 0, 0], translation: [1, 0, 0], rotation: [0, 0, 0, 1],
    })
    return ctx
  }

  it('maps an immutable NADOC delta to the desktop gizmo and restores on cancel', async () => {
    const ctx = vrContext()
    const tool = initTranslateRotateTool(ctx.deps)
    const matrix = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 2, 3, 4, 1]

    const starting = tool.beginVRPreview('C1')
    expect(tool.applyVRPreviewMatrix(matrix)).toBe(false) // queued during async attach
    await expect(starting).resolves.toEqual({ accepted: true })
    expect(ctx.clusterGizmo.setTransform).toHaveBeenCalledWith(
      [3, 3, 4], [0, 0, 0, 1],
    )
    ctx.deps.setClusterDirty(true)
    await expect(tool.cancelVRPreview()).resolves.toBe(true)
    expect(ctx.clusterGizmo.discardPendingTransforms).toHaveBeenCalled()
    expect(ctx.clusterGizmo.detach).toHaveBeenCalled()
    expect(ctx.active).toBe(false)

    ctx.clusterGizmo.setTransform.mockClear()
    expect(tool.applyVRPreviewMatrix(matrix)).toBe(false)
    await tool.beginVRPreview('C1')
    expect(ctx.clusterGizmo.setTransform).not.toHaveBeenCalled()
    await tool.cancelVRPreview()
  })

  it('refuses to attach over an existing desktop tool and blocks preview commit', async () => {
    const ctx = vrContext()
    const tool = initTranslateRotateTool(ctx.deps)
    await tool.activate('C1')
    await expect(tool.beginVRPreview('C1')).resolves.toEqual({
      accepted: false, reason: 'desktop_tool_active',
    })

    await tool.cancel()
    await tool.beginVRPreview('C1')
    await tool.confirm()
    expect(ctx.active).toBe(true)
    expect(ctx.clusterGizmo.commitPendingTransforms).not.toHaveBeenCalled()
    expect(toastCalls.at(-1)?.[0]).toContain('preview-only')
  })

  it('cancels and restores instead of retargeting when selection changes mid-preview', async () => {
    const ctx = vrContext()
    ctx.store.setState({
      selection: {
        context: 'design', level: 'cluster',
        items: [{ kind: 'cluster', id: 'C1' }],
        primary: { kind: 'cluster', id: 'C1' },
      },
    })
    const tool = initTranslateRotateTool(ctx.deps)
    await tool.beginVRPreview('C1')
    const previous = ctx.store.getState()
    ctx.store.setState({
      selection: {
        context: 'design', level: 'cluster',
        items: [{ kind: 'cluster', id: 'C2' }],
        primary: { kind: 'cluster', id: 'C2' },
      },
      activeClusterId: 'C2',
    })
    const next = ctx.store.getState()

    await Promise.all([
      tool.handleSelectionChange(next, previous),
      tool.handleMultiClusterSelectionChange(next, previous),
    ])

    expect(ctx.clusterGizmo.discardPendingTransforms).toHaveBeenCalledOnce()
    expect(ctx.clusterGizmo.detach).toHaveBeenCalledOnce()
    expect(ctx.clusterGizmo.attach).not.toHaveBeenCalledWith(
      'C2', expect.anything(), expect.anything(), expect.anything(),
    )
    expect(ctx.active).toBe(false)
  })
})

describe('initTranslateRotateTool — activate (design mode)', () => {
  it('no clusters or selection → arms without attaching a gizmo', async () => {
    const ctx = makeDeps()
    const t = initTranslateRotateTool(ctx.deps)
    await t.activate()
    expect(ctx.active).toBe(true)
    expect(ctx.clusterGizmo.attach).not.toHaveBeenCalled()
    expect(toastCalls.length).toBe(0)
    expect(ctx.deps.refreshCurrentSelection).toHaveBeenCalled()
    expect(ctx.deps.moveRotatePanel.setSessionMode).toHaveBeenCalledWith('waiting')
    expect(document.getElementById('mode-indicator').textContent).toContain('select an entity')
  })

  it('with clusters but no selected target → does not pick the last cluster', async () => {
    const ctx = makeDeps({ state: { currentDesign: { cluster_transforms: [
      { id: 'C0', translation: [0, 0, 0], rotation: [0, 0, 0, 1], helix_ids: [1] },
      { id: 'C1', translation: [1, 2, 3], rotation: [0, 0, 0, 1], helix_ids: [2] },
    ], cluster_joints: [] } } })
    const t = initTranslateRotateTool(ctx.deps)
    await t.activate()
    expect(ctx.active).toBe(true)
    expect(ctx.clusterGizmo.attach).not.toHaveBeenCalled()
    expect(toastCalls.length).toBe(0)
  })

  it('targetClusterId selects that cluster over the last', async () => {
    const ctx = makeDeps({ state: { currentDesign: { cluster_transforms: [
      { id: 'C0', translation: [0, 0, 0], rotation: [0, 0, 0, 1], helix_ids: [1] },
      { id: 'C1', translation: [0, 0, 0], rotation: [0, 0, 0, 1], helix_ids: [2] },
    ], cluster_joints: [] } } })
    const t = initTranslateRotateTool(ctx.deps)
    await t.activate('C0')
    expect(ctx.clusterGizmo.attach).toHaveBeenCalledWith('C0', expect.anything(), expect.anything(), expect.anything())
    expect(ctx.deps.refreshCurrentSelection).toHaveBeenCalled()
  })

  it('populates the number boxes from the gizmo PENDING transform, not the stored one (duplex pivot fix)', async () => {
    // Stored translation is [1,2,3]; the gizmo's pending (pivot-rebased) transform is
    // [1,0,0]. The fields must reflect the pending so a +45/reset commit rotates about
    // the gizmo's actual pivot instead of teleporting.
    const ctx = makeDeps({ state: { currentDesign: { cluster_transforms: [
      { id: 'C1', translation: [1, 2, 3], rotation: [0, 0, 0, 1], helix_ids: [2] },
    ], cluster_joints: [] } } })
    const t = initTranslateRotateTool(ctx.deps)
    await t.activate('C1')
    expect(ctx.deps.setTransformValues).toHaveBeenCalledWith(1, 0, 0, expect.any(Number), expect.any(Number), expect.any(Number))
  })

  it('falls back to the stored transform when the gizmo has no pending transform', async () => {
    const ctx = makeDeps({ state: { currentDesign: { cluster_transforms: [
      { id: 'C1', translation: [4, 5, 6], rotation: [0, 0, 0, 1], helix_ids: [2] },
    ], cluster_joints: [] } } })
    ctx.deps.clusterGizmo.getPendingTransform = () => null
    const t = initTranslateRotateTool(ctx.deps)
    await t.activate('C1')
    expect(ctx.deps.setTransformValues).toHaveBeenCalledWith(4, 5, 6, expect.any(Number), expect.any(Number), expect.any(Number))
  })
})

describe('initTranslateRotateTool — activate (assembly mode)', () => {
  it('no active instance → toast, stays inactive', async () => {
    const ctx = makeDeps({ state: { assemblyActive: true, activeInstanceId: null } })
    const t = initTranslateRotateTool(ctx.deps)
    await t.activate()
    expect(ctx.active).toBe(false)
    expect(ctx.deps.createAssemblyTransformContext).not.toHaveBeenCalled()
    expect(toastCalls.length).toBe(1)
  })

  it('fixed instance → toast, no gizmo', async () => {
    const ctx = makeDeps({ state: {
      assemblyActive: true, activeInstanceId: 'I1',
      currentAssembly: { instances: [{ id: 'I1', fixed: true, name: 'P' }] },
    } })
    const t = initTranslateRotateTool(ctx.deps)
    await t.activate()
    expect(ctx.active).toBe(false)
    expect(ctx.deps.attachGroupGizmo).not.toHaveBeenCalled()
    expect(toastCalls.length).toBe(1)
  })

  it('movable instance → ctx + group gizmo + active + confirm btn hidden', async () => {
    const ctx = makeDeps({ state: {
      assemblyActive: true, activeInstanceId: 'I1',
      currentAssembly: { instances: [{ id: 'I1', fixed: false, name: 'P' }] },
    } })
    const t = initTranslateRotateTool(ctx.deps)
    await t.activate()
    expect(ctx.active).toBe(true)
    expect(ctx.deps.createAssemblyTransformContext).toHaveBeenCalledWith('I1')
    expect(ctx.deps.moveRotatePanel.setAssemblyCtx).toHaveBeenCalled()
    expect(ctx.deps.attachGroupGizmo).toHaveBeenCalledWith('I1', expect.anything())
    expect(ctx.deps.moveRotatePanel.setSessionMode).toHaveBeenCalledWith('assembly')
    expect(ctx.deps.refreshCurrentSelection).toHaveBeenCalled()
    const btn = [...document.body.children].find(el => el.textContent === '✓')
    expect(btn.style.display).toBe('none')
  })
})

describe('initTranslateRotateTool — confirm', () => {
  it('inactive → no-op (no detach)', async () => {
    const ctx = makeDeps()
    const t = initTranslateRotateTool(ctx.deps)
    await t.confirm()
    expect(ctx.clusterGizmo.detach).not.toHaveBeenCalled()
  })

  it('assembly + pending → commits, detaches, ASSEMBLY MODE', async () => {
    const ctx = makeDeps({ state: { assemblyActive: true } })
    ctx.deps.hasAssemblyPending = vi.fn(() => true)
    ctx.deps.setActive(true)
    const t = initTranslateRotateTool(ctx.deps)
    await t.confirm()
    expect(ctx.deps.instanceGizmo.detach).toHaveBeenCalled()
    expect(ctx.deps.commitAssemblyPending).toHaveBeenCalled()
    expect(ctx.active).toBe(false)
    expect(document.getElementById('mode-indicator').textContent).toBe('ASSEMBLY MODE')
  })

  it('design standard commit (dirty, no edit ctx) → commit + reconcile helpers', async () => {
    const ctx = makeDeps({ state: { currentDesign: { cluster_transforms: [
      { id: 'C1', pivot: [0, 0, 0], translation: [0, 0, 0], rotation: [0, 0, 0, 1], helix_ids: [7] },
    ], cluster_joints: [] } } })
    ctx.clusterGizmo.commitPendingTransforms = vi.fn(async () => ({ clusterIds: ['C1'] }))
    ctx.deps.setActive(true)
    ctx.deps.setClusterDirty(true)
    const t = initTranslateRotateTool(ctx.deps)
    await t.confirm()
    expect(ctx.clusterGizmo.commitPendingTransforms).toHaveBeenCalledWith({ log: true })
    expect(ctx.helixCtrl.commitClusterPositions).toHaveBeenCalledWith([7])
    expect(ctx.deps.rebakeHelixAxesForClusterDelta).toHaveBeenCalled()
    expect(ctx.deps.reemitClusterBridges).toHaveBeenCalledWith(['C1'])
    expect(ctx.deps.refreshClusterOverlays).toHaveBeenCalledWith({ withFlexibleArcs: false })
    expect(ctx.clusterGizmo.detach).toHaveBeenCalled()
    expect(ctx.dirty).toBe(false)
    expect(document.getElementById('mode-indicator').textContent).toBe('NADOC · WORKSPACE')
  })

  it('cluster_op edit-in-place → editFeature + skipNextResponseDelta, not append', async () => {
    const ctx = makeDeps({
      state: { currentDesign: { cluster_transforms: [
        { id: 'C1', pivot: [0, 0, 0], translation: [0, 0, 0], rotation: [0, 0, 0, 1], helix_ids: [7] },
      ], cluster_joints: [] } },
      editContext: { editingFeatureType: 'cluster_op', featureIndex: 3, clusterId: 'C1' },
    })
    ctx.deps.setActive(true)
    ctx.deps.setClusterDirty(true)
    const t = initTranslateRotateTool(ctx.deps)
    await t.confirm()
    expect(ctx.deps.api.skipNextResponseDelta).toHaveBeenCalled()
    expect(ctx.deps.api.editFeature).toHaveBeenCalledWith(3, expect.anything())
    expect(ctx.clusterGizmo.clearPendingTransform).toHaveBeenCalledWith('C1')
    expect(ctx.clusterGizmo.commitPendingTransforms).not.toHaveBeenCalled()
    expect(ctx.editCtx).toBe(null)
    // Latest-op edit: no seek-back (live pose already == this op).
    expect(ctx.deps.api.seekFeatures).not.toHaveBeenCalled()
  })

  it('cluster_op edit of an EARLIER op → editFeature + seek back to restore cursor, skips in-place reconcile', async () => {
    const ctx = makeDeps({
      state: { currentDesign: { cluster_transforms: [
        { id: 'C1', pivot: [0, 0, 0], translation: [0, 0, 0], rotation: [0, 0, 0, 1], helix_ids: [7] },
      ], cluster_joints: [] } },
      editContext: { editingFeatureType: 'cluster_op', featureIndex: 0, clusterId: 'C1', seekRestoreCursor: -1 },
    })
    ctx.deps.setActive(true)
    ctx.deps.setClusterDirty(true)
    const t = initTranslateRotateTool(ctx.deps)
    await t.confirm()
    // Rewrites just this step's pose...
    expect(ctx.deps.api.skipNextResponseDelta).toHaveBeenCalled()
    expect(ctx.deps.api.editFeature).toHaveBeenCalledWith(0, expect.anything())
    expect(ctx.clusterGizmo.clearPendingTransform).toHaveBeenCalledWith('C1')
    // ...then seeks back to the latest pose (the cursor we left).
    expect(ctx.deps.api.seekFeatures).toHaveBeenCalledWith(-1)
    // In-place reconcile (latest-op path) is skipped — the seek re-renders.
    expect(ctx.deps.rebakeHelixAxesForClusterDelta).not.toHaveBeenCalled()
    expect(ctx.helixCtrl.commitClusterPositions).not.toHaveBeenCalled()
    expect(ctx.clusterGizmo.detach).toHaveBeenCalled()
    expect(ctx.editCtx).toBe(null)
  })
})

describe('initTranslateRotateTool — cancel', () => {
  it('inactive → no-op', async () => {
    const ctx = makeDeps()
    const t = initTranslateRotateTool(ctx.deps)
    await t.cancel()
    expect(ctx.clusterGizmo.detach).not.toHaveBeenCalled()
  })

  it('design with local preview → restores geometry + deactivates', async () => {
    const ctx = makeDeps({ state: { currentGeometry: [{}], currentHelixAxes: { a: 1 } } })
    ctx.deps.setActive(true)
    ctx.deps.setClusterDirty(true)
    const t = initTranslateRotateTool(ctx.deps)
    await t.cancel()
    expect(ctx.active).toBe(false)
    expect(ctx.clusterGizmo.discardPendingTransforms).toHaveBeenCalled()
    expect(ctx.clusterGizmo.detach).toHaveBeenCalled()
    expect(ctx.jointRenderer.rebuild).toHaveBeenCalled()
  })

  it('earlier-op edit cancelled → seeks back to the restore cursor', async () => {
    const ctx = makeDeps({
      state: { currentGeometry: [{}], currentHelixAxes: { a: 1 } },
      editContext: { editingFeatureType: 'cluster_op', featureIndex: 0, clusterId: 'C1', seekRestoreCursor: -1 },
    })
    ctx.deps.setActive(true)
    ctx.deps.setClusterDirty(true)
    const t = initTranslateRotateTool(ctx.deps)
    await t.cancel()
    expect(ctx.deps.api.seekFeatures).toHaveBeenCalledWith(-1)
    expect(ctx.editCtx).toBe(null)
  })

  it('assembly → clears pending maps + rebuilds renderers', async () => {
    const ctx = makeDeps({ state: { assemblyActive: true, currentAssembly: { instances: [] } } })
    ctx.deps.setActive(true)
    const t = initTranslateRotateTool(ctx.deps)
    await t.cancel()
    expect(ctx.deps.assemblyPendingTransforms.clear).toHaveBeenCalled()
    expect(ctx.deps.assemblyPendingPartJoints.clear).toHaveBeenCalled()
    expect(ctx.deps.assemblyRenderer.rebuild).toHaveBeenCalled()
    expect(ctx.deps.syncAssemblyBluntEnds).toHaveBeenCalled()
    expect(document.getElementById('mode-indicator').textContent).toBe('ASSEMBLY MODE')
  })
})

describe('initTranslateRotateTool — resetToSaved (restore saved positions)', () => {
  it('inactive → no-op', async () => {
    const ctx = makeDeps()
    const t = initTranslateRotateTool(ctx.deps)
    await t.resetToSaved()
    expect(ctx.clusterGizmo.discardPendingTransforms).not.toHaveBeenCalled()
    expect(ctx.clusterGizmo.attach).not.toHaveBeenCalled()
  })

  it('design mode: discards pending, restores geometry, re-attaches at the saved pose, STAYS active', async () => {
    const ctx = makeDeps({ state: {
      activeClusterId: 'C1',
      currentDesign: { cluster_transforms: [{ id: 'C1', translation: [0, 0, 0], rotation: [0, 0, 0, 1], helix_ids: [1] }], cluster_joints: [] },
      currentGeometry: [{}], currentHelixAxes: { a: 1 },
    } })
    ctx.deps.setActive(true)
    ctx.deps.setClusterDirty(true)   // an in-progress preview exists
    const t = initTranslateRotateTool(ctx.deps)
    await t.resetToSaved()
    expect(ctx.clusterGizmo.discardPendingTransforms).toHaveBeenCalled()
    expect(ctx.deps.refreshClusterPivotForAttach).toHaveBeenCalledWith('C1')
    expect(ctx.clusterGizmo.attach).toHaveBeenCalledWith('C1', expect.anything(), expect.anything(), expect.anything())
    expect(ctx.active).toBe(true)   // did NOT exit the tool
    expect(ctx.dirty).toBe(false)   // preview discarded
  })

  it('assembly mode: clears pending + rebuilds + re-attaches the instance gizmo (stays active)', async () => {
    const ctx = makeDeps({ state: {
      assemblyActive: true, activeInstanceId: 'I1', currentAssembly: { instances: [{ id: 'I1' }] },
    } })
    ctx.deps.setActive(true)
    const t = initTranslateRotateTool(ctx.deps)
    await t.resetToSaved()
    expect(ctx.deps.assemblyPendingTransforms.clear).toHaveBeenCalled()
    expect(ctx.deps.assemblyRenderer.rebuild).toHaveBeenCalled()
    expect(ctx.deps.attachGroupGizmo).toHaveBeenCalled()   // re-attached, not exited
    expect(ctx.active).toBe(true)
  })
})

describe('initTranslateRotateTool — rotateJoint + misc', () => {
  it('inactive → activates the tool then points the gizmo at the joint', async () => {
    const ctx = makeDeps({ state: { currentDesign: { cluster_transforms: [
      { id: 'C1', translation: [0, 0, 0], rotation: [0, 0, 0, 1], helix_ids: [2] },
    ], cluster_joints: [JOINT] } } })
    const t = initTranslateRotateTool(ctx.deps)
    await t.rotateJoint(JOINT)
    expect(ctx.active).toBe(true)
    expect(ctx.deps.setSelectedPivot).toHaveBeenCalledWith('J1')
    expect(ctx.clusterGizmo.setConstraint).toHaveBeenCalledWith('joint', JOINT)
  })

  it('removeToolPickListeners removes the canvas pointerdown listener', () => {
    const ctx = makeDeps()
    const t = initTranslateRotateTool(ctx.deps)
    t.removeToolPickListeners()
    expect(ctx.deps.canvas.removeEventListener).toHaveBeenCalledWith('pointerdown', expect.any(Function))
  })

  it('hideConfirmBtn hides the floating button', async () => {
    const ctx = makeDeps({ state: {
      assemblyActive: true, activeInstanceId: 'I1',
      currentAssembly: { instances: [{ id: 'I1', fixed: false, name: 'P' }] },
    } })
    const t = initTranslateRotateTool(ctx.deps)
    const btn = [...document.body.children].find(el => el.textContent === '✓')
    btn.style.display = 'flex'
    t.hideConfirmBtn()
    expect(btn.style.display).toBe('none')
  })
})

describe('decideSelectionAction (selection→tool bridge)', () => {
  const PARTS = { assemblyActive: false, cadnanoActive: false, unfoldActive: false }
  const cluster = id => ({ kind: 'cluster', id })

  it('does not open the tool when a cluster is selected', () => {
    expect(decideSelectionAction({
      newSel: cluster('c1'), toolActive: false, autoOpened: false, activeClusterId: null, mode: PARTS,
    })).toEqual({ action: 'none', clusterId: null })
  })

  it('does NOT open in assembly / cadnano / unfold modes', () => {
    for (const mode of [
      { ...PARTS, assemblyActive: true },
      { ...PARTS, cadnanoActive: true },
      { ...PARTS, unfoldActive: true },
    ]) {
      expect(decideSelectionAction({
        newSel: cluster('c1'), toolActive: false, autoOpened: false, activeClusterId: null, mode,
      })).toEqual({ action: 'none', clusterId: null })
    }
  })

  it('does nothing when the selection is not a cluster', () => {
    expect(decideSelectionAction({
      newSel: { kind: 'strand', id: 's1' },
      toolActive: false, autoOpened: false, activeClusterId: null, mode: PARTS,
    })).toEqual({ action: 'none', clusterId: null })
    expect(decideSelectionAction({
      newSel: null, toolActive: false, autoOpened: false, activeClusterId: null, mode: PARTS,
    })).toEqual({ action: 'none', clusterId: null })
  })

  it('does not close the explicitly opened tool when selection clears', () => {
    expect(decideSelectionAction({
      newSel: null, toolActive: true, autoOpened: true, activeClusterId: 'c1', mode: PARTS,
    })).toEqual({ action: 'none', clusterId: null })
  })

  it('does NOT close on a bare deselection that is really a promote-to-group', () => {
    // Multi-selection is owned by the unified selection subscriber; a null primary
    // passed to this pure seam never closes the explicitly active tool.
    expect(decideSelectionAction({
      newSel: null, toolActive: true, autoOpened: true, activeClusterId: 'c1', mode: PARTS,
      multiSelectedCount: 1,
    })).toEqual({ action: 'none', clusterId: null })
    expect(decideSelectionAction({
      newSel: null, toolActive: true, autoOpened: true, activeClusterId: 'c1', mode: PARTS,
      multiSelectedCount: 2,
    })).toEqual({ action: 'none', clusterId: null })
  })

  it('re-targets an explicitly opened tool when a different cluster is selected', () => {
    expect(decideSelectionAction({
      newSel: cluster('c2'), toolActive: true, autoOpened: true, activeClusterId: 'c1', mode: PARTS,
    })).toEqual({ action: 'retarget', clusterId: 'c2' })
  })

  it('does nothing when the same cluster is re-selected while the tool is open', () => {
    expect(decideSelectionAction({
      newSel: cluster('c1'), toolActive: true, autoOpened: true, activeClusterId: 'c1', mode: PARTS,
    })).toEqual({ action: 'none', clusterId: null })
  })

  it('leaves an explicitly opened tool active but permits cluster retargeting', () => {
    expect(decideSelectionAction({
      newSel: null, toolActive: true, autoOpened: false, activeClusterId: 'c1', mode: PARTS,
    })).toEqual({ action: 'none', clusterId: null })
    expect(decideSelectionAction({
      newSel: cluster('c2'), toolActive: true, autoOpened: false, activeClusterId: 'c1', mode: PARTS,
    })).toEqual({ action: 'retarget', clusterId: 'c2' })
  })

  it('accepts a minimal canonical cluster ref', () => {
    expect(decideSelectionAction({
      newSel: { kind: 'cluster', id: 'c9' }, toolActive: false, autoOpened: false, activeClusterId: null, mode: PARTS,
    })).toEqual({ action: 'none', clusterId: null })
  })
})

describe('resolveSelectionClusterId', () => {
  const design = {
    strands: [{ id: 's1', domains: [{ helix_id: 'h1' }, { helix_id: 'h2' }] }],
    cluster_transforms: [
      { id: 'whole', helix_ids: ['h1', 'h2'], domain_ids: [] },
      { id: 'domain', helix_ids: ['h2'], domain_ids: [{ strand_id: 's1', domain_index: 1 }] },
    ],
  }

  it('resolves a cluster directly', () => {
    expect(resolveSelectionClusterId({ kind: 'cluster', id: 'whole' }, design)).toBe('whole')
  })

  it('prefers exact domain scope for a selected domain or base bead', () => {
    expect(resolveSelectionClusterId({ kind: 'domain', strandId: 's1', domainIndex: 1 }, design)).toBe('domain')
  })

  it('falls back from a base or strand to its helix-level transform scope', () => {
    expect(resolveSelectionClusterId({ kind: 'base', key: 'h1:4:FORWARD' }, design)).toBe('whole')
    expect(resolveSelectionClusterId({ kind: 'strand', id: 's1' }, design)).toBe('whole')
  })

  it('returns null for stale or unsupported selections', () => {
    expect(resolveSelectionClusterId({ kind: 'cluster', id: 'missing' }, design)).toBeNull()
    expect(resolveSelectionClusterId({ kind: 'protein', id: 'p1' }, design)).toBeNull()
  })
})
