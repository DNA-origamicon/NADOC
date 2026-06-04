import { describe, it, expect, vi } from 'vitest'
import * as THREE from 'three'
import { initAssemblyPointer } from './assembly_pointer.js'
import { createMockStore } from '../test-helpers/mock_store.js'

// Branch-logic coverage for the lifted assembly click handler. The real WebGL
// gesture (raycast pick → selection) is covered by e2e/assembly_select.spec.js;
// here we drive the decision tree with mock deps + a mock store.

function setup(stateOverrides = {}, depOverrides = {}) {
  let ptrDownAt = { x: 10, y: 10 }   // default: a recorded click (not a drag)
  let translateActive = false
  let selectedCluster = 'unset'
  let selectedPartJoint = 'unset'

  const store = createMockStore({
    activeInstanceId: null,
    currentAssembly: { instances: [], groups: [] },
    ...stateOverrides,
  })

  const clusterPanel = { selectAssemblyCluster: vi.fn() }
  const deps = {
    store,
    camera: {},
    assemblyRenderer: {
      pickInstance: vi.fn(() => null),
      pickInstanceCluster: vi.fn(() => null),
      getInstanceBackboneEntries: vi.fn(() => ({ entries: [], matrixWorld: new THREE.Matrix4() })),
      getInstanceDesign: vi.fn(() => ({})),
    },
    assemblyJointRenderer: { isBeltMode: () => false, isAttachMode: () => false },
    instanceGizmo: { getActiveAxis: () => null, isDragging: () => false, detach: vi.fn() },
    clusterGlowLayer: { setEntries: vi.fn() },
    overhangHoverPicker: { nearestAt: vi.fn(() => null) },
    getClusterPanel: () => clusterPanel,
    canvasNdc: () => ({ x: 0, y: 0 }),
    clusterBackboneEntries: vi.fn(() => [{ pos: new THREE.Vector3(1, 2, 3) }]),
    confirmTranslateRotateTool: vi.fn(async () => {}),
    activateTranslateRotateTool: vi.fn(async () => {}),
    hasAssemblyPending: vi.fn(() => false),
    commitAssemblyPending: vi.fn(async () => {}),
    showProgress: vi.fn(),
    hideProgress: vi.fn(),
    getAssemblyPtrDownAt: () => ptrDownAt,
    setAssemblyPtrDownAt: (v) => { ptrDownAt = v },
    getTranslateRotateActive: () => translateActive,
    setSelectedAssemblyCluster: (v) => { selectedCluster = v },
    setAssemblySelectedPartJoint: (v) => { selectedPartJoint = v },
    ...depOverrides,
  }
  const { onAssemblyClick } = initAssemblyPointer(deps)
  const setStateSpy = vi.spyOn(store, 'setState')
  return {
    onAssemblyClick, deps, store, clusterPanel, setStateSpy,
    getPtrDownAt: () => ptrDownAt,
    setTranslateActive: (v) => { translateActive = v },
    getSelectedCluster: () => selectedCluster,
    getSelectedPartJoint: () => selectedPartJoint,
  }
}

const ev = (over = {}) => ({ button: 0, clientX: 10, clientY: 10, ...over })

describe('initAssemblyPointer · onAssemblyClick', () => {
  it('ignores non-left clicks', async () => {
    const t = setup()
    await t.onAssemblyClick(ev({ button: 2 }))
    expect(t.setStateSpy).not.toHaveBeenCalled()
    expect(t.deps.assemblyRenderer.pickInstance).not.toHaveBeenCalled()
  })

  it('belt mode clears the pending click and bails', async () => {
    const t = setup({}, { assemblyJointRenderer: { isBeltMode: () => true, isAttachMode: () => false } })
    await t.onAssemblyClick(ev())
    expect(t.getPtrDownAt()).toBeNull()
    expect(t.deps.assemblyRenderer.pickInstance).not.toHaveBeenCalled()
  })

  it('no-ops when there is no recorded pointer-down', async () => {
    const t = setup()
    t.deps.setAssemblyPtrDownAt(null)
    await t.onAssemblyClick(ev())
    expect(t.deps.assemblyRenderer.pickInstance).not.toHaveBeenCalled()
  })

  it('treats a moved pointer as a drag, not a click', async () => {
    const t = setup()                       // ptrDownAt = {10,10}
    await t.onAssemblyClick(ev({ clientX: 30, clientY: 30 }))  // far past 5px threshold
    expect(t.getPtrDownAt()).toBeNull()
    expect(t.deps.assemblyRenderer.pickInstance).not.toHaveBeenCalled()
  })

  it('selecting a new instance sets activeInstanceId and arms the gizmo', async () => {
    const t = setup({ activeInstanceId: null })
    t.deps.assemblyRenderer.pickInstance.mockReturnValue({ id: 'inst-A' })
    await t.onAssemblyClick(ev())
    expect(t.store.getState().activeInstanceId).toBe('inst-A')
    expect(t.getSelectedPartJoint()).toBeNull()           // newId !== prevId → cleared
    expect(t.deps.activateTranslateRotateTool).toHaveBeenCalledTimes(1)
  })

  it('clicking empty space clears the active instance and does not arm a gizmo', async () => {
    const t = setup({ activeInstanceId: 'inst-A' })
    t.deps.assemblyRenderer.pickInstance.mockReturnValue(null)
    await t.onAssemblyClick(ev())
    expect(t.store.getState().activeInstanceId).toBeNull()
    expect(t.deps.activateTranslateRotateTool).not.toHaveBeenCalled()
  })

  it('re-clicking the active instance picks a cluster and highlights it', async () => {
    const t = setup({ activeInstanceId: 'inst-A' })
    t.deps.assemblyRenderer.pickInstance.mockReturnValue({ id: 'inst-A' })
    t.deps.assemblyRenderer.pickInstanceCluster.mockReturnValue({ cluster: { id: 'cl-1' } })
    await t.onAssemblyClick(ev())
    expect(t.deps.clusterGlowLayer.setEntries).toHaveBeenCalledTimes(1)
    expect(t.clusterPanel.selectAssemblyCluster).toHaveBeenCalledWith('inst-A', 'cl-1')
    expect(t.getSelectedCluster()).toEqual({ instanceId: 'inst-A', clusterId: 'cl-1' })
    expect(t.deps.instanceGizmo.detach).toHaveBeenCalledTimes(1)
    expect(t.deps.activateTranslateRotateTool).not.toHaveBeenCalled()
  })

  it('overhang tool on: clicking near an overhang toggles selection and bails', async () => {
    const t = setup({ toolFilters: { overhangLocations: true } })
    t.deps.overhangHoverPicker.nearestAt.mockReturnValue({ instanceId: 'inst-A', overhangId: 'oh-1', label: 'P' })
    await t.onAssemblyClick(ev())
    const sel = t.store.getState().assemblyOverhangSelection
    expect(sel).toEqual([{ instanceId: 'inst-A', overhangId: 'oh-1', label: 'P' }])
    expect(t.deps.activateTranslateRotateTool).not.toHaveBeenCalled()
  })

  it('group click-through: first click on a grouped part selects the group', async () => {
    const t = setup({
      currentAssembly: { instances: [{ id: 'inst-A' }], groups: [{ id: 'g1', instance_ids: ['inst-A'] }] },
      activeGroupId: null,
    })
    t.deps.assemblyRenderer.pickInstance.mockReturnValue({ id: 'inst-A' })
    await t.onAssemblyClick(ev())
    expect(t.store.getState().activeGroupId).toBe('g1')
    expect(t.store.getState().activeInstanceId).toBeNull()
    expect(t.deps.activateTranslateRotateTool).not.toHaveBeenCalled()  // returned before select
  })

  it('gizmo active: a click on the active instance body leaves the gizmo alone', async () => {
    const t = setup({ activeInstanceId: 'inst-A' })
    t.setTranslateActive(true)
    t.deps.assemblyRenderer.pickInstance.mockReturnValue({ id: 'inst-A' })
    await t.onAssemblyClick(ev())
    expect(t.deps.confirmTranslateRotateTool).not.toHaveBeenCalled()
  })

  it('gizmo active: a click elsewhere commits the pending transform first', async () => {
    const t = setup({ activeInstanceId: 'inst-A' })
    t.setTranslateActive(true)
    // first pick (gizmo guard) returns a different instance → commit; then the
    // tail re-pick selects it.
    t.deps.assemblyRenderer.pickInstance.mockReturnValue({ id: 'inst-B' })
    await t.onAssemblyClick(ev())
    expect(t.deps.confirmTranslateRotateTool).toHaveBeenCalledTimes(1)
    expect(t.store.getState().activeInstanceId).toBe('inst-B')
  })
})
