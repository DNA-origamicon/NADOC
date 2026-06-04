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
  const pendingPartJoints = new Map()
  const canvas = { addEventListener: vi.fn(), removeEventListener: vi.fn() }
  const controls = { enabled: true }
  const deps = {
    store,
    camera: {},
    canvas,
    controls,
    api: { propagateFk: vi.fn(async () => {}) },
    applyFKLive: vi.fn(),
    applyClusterMateFKLive: vi.fn(),
    assemblyPendingPartJoints: pendingPartJoints,
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
  const ptr = initAssemblyPointer(deps)
  const setStateSpy = vi.spyOn(store, 'setState')
  return {
    ...ptr, deps, store, clusterPanel, setStateSpy, pendingPartJoints, canvas, controls,
    getPtrDownAt: () => ptrDownAt,
    setTranslateActive: (v) => { translateActive = v },
    getSelectedCluster: () => selectedCluster,
    getSelectedPartJoint: () => selectedPartJoint,
  }
}

// A part-joint drag descriptor with the bits onAssemblyDragUp reads. The drag
// MOVE math (ringPlaneHit/angleInRing → currentDelta/currentWorldDelta) is
// covered by e2e/assembly_joint_drag.spec.js; here we pre-seed a finished drag.
function makePartJointDrag(currentDelta) {
  return {
    instId: 'inst-A',
    inst: { joint_states: { 'j1': 0.5 } },
    cluster: { id: 'cl-1', translation: [0, 0, 0], rotation: [0, 0, 0, 1], pivot: [0, 0, 0] },
    joint: { id: 'j1', axis_origin: [0, 0, 0], axis_direction: [0, 0, 1] },
    assembly: { instances: [] },
    currentDelta,
    currentWorldDelta: new THREE.Matrix4(),
    startTransforms: new Map(),
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

describe('initAssemblyPointer · part-joint drag (sub-part a)', () => {
  it('beginPartJointDrag arms the move/up listeners', () => {
    const t = setup()
    t.beginPartJointDrag(makePartJointDrag(0.3))
    expect(t.canvas.addEventListener).toHaveBeenCalledWith('pointermove', t.onAssemblyDragMove)
    expect(t.canvas.addEventListener).toHaveBeenCalledWith('pointerup', t.onAssemblyDragUp)
  })

  it('drag-up records a pending part-joint rotation and re-enables controls', () => {
    const t = setup()
    t.controls.enabled = false                      // a live drag disabled them
    t.beginPartJointDrag(makePartJointDrag(0.4))
    t.onAssemblyDragUp()
    const entry = t.pendingPartJoints.get('inst-A:cl-1')
    expect(entry).toBeTruthy()
    expect(entry.instanceId).toBe('inst-A')
    expect(entry.body.joint_id).toBe('j1')
    expect(entry.body.joint_value).toBeCloseTo(0.9)   // prior 0.5 + delta 0.4
    expect(t.controls.enabled).toBe(true)
    expect(t.canvas.removeEventListener).toHaveBeenCalledWith('pointermove', t.onAssemblyDragMove)
  })

  it('drag-up with a near-zero delta records nothing', () => {
    const t = setup()
    t.beginPartJointDrag(makePartJointDrag(1e-12))
    t.onAssemblyDragUp()
    expect(t.pendingPartJoints.size).toBe(0)
  })

  it('cancelDrag is a no-op when no drag is in flight', () => {
    const t = setup()
    t.cancelDrag()
    expect(t.canvas.removeEventListener).not.toHaveBeenCalled()
  })

  it('onAssemblyDragMove is a no-op when nothing is being dragged', () => {
    const t = setup()
    t.onAssemblyDragMove({ clientX: 5, clientY: 5 })
    expect(t.deps.applyFKLive).not.toHaveBeenCalled()
    expect(t.deps.applyClusterMateFKLive).not.toHaveBeenCalled()
  })
})
