import { describe, it, expect, vi, beforeEach } from 'vitest'
import * as THREE from 'three'

// Capture the items passed to createContextMenu so the linker/belt menu
// branches can be asserted (and their onClick callbacks invoked).
const ctxMenuCalls = []
vi.mock('../ui/primitives/context_menu.js', () => ({
  createContextMenu: (opts) => { ctxMenuCalls.push(opts) },
}))

import { initAssemblyPointer } from './assembly_pointer.js'
import { createMockStore } from '../test-helpers/mock_store.js'

// Branch-logic coverage for the lifted assembly click handler. The real WebGL
// gesture (raycast pick → selection) is covered by e2e/assembly_select.spec.js;
// here we drive the decision tree with mock deps + a mock store.

function setup(stateOverrides = {}, depOverrides = {}) {
  let ptrDownAt = { x: 10, y: 10 }   // default: a recorded click (not a drag)
  let rightDownAt = null
  let translateActive = false
  let selectedCluster = null
  let selectedPartJoint = null
  const assemblyContextMenu = { show: vi.fn(), hide: vi.fn() }
  const attachPartToBelt = vi.fn()

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
    api: {
      propagateFk: vi.fn(async () => {}),
      getAssemblyOverhangConnectionRelaxStatus: vi.fn(async () => ({ available: true })),
      relaxAssemblyOverhangConnection: vi.fn(async () => {}),
    },
    applyFKLive: vi.fn(),
    applyClusterMateFKLive: vi.fn(),
    effectiveInstanceMatrix: vi.fn(() => new THREE.Matrix4()),
    assemblyPendingPartJoints: pendingPartJoints,
    polymerizePanel: { isOpen: () => false, setSelectedJoint: vi.fn() },
    assemblyLasso: { start: vi.fn(() => false) },
    assemblyRenderer: {
      pickInstance: vi.fn(() => null),
      pickInstanceCluster: vi.fn(() => null),
      pickPartJoint: vi.fn(() => null),
      pickLinker: vi.fn(() => null),
      getInstanceBackboneEntries: vi.fn(() => ({ entries: [], matrixWorld: new THREE.Matrix4() })),
      getInstanceDesign: vi.fn(() => ({})),
    },
    assemblyJointRenderer: {
      isBeltMode: () => false, isAttachMode: () => false, isMateMode: () => false,
      pickJointRing: vi.fn(() => null), pickJointAny: vi.fn(() => null), beginRingDrag: vi.fn(),
      pickBeltAt: vi.fn(() => null),
    },
    assemblyContextMenu,
    overhangLocations: { isVisible: () => false, hitTest: vi.fn(() => false) },
    attachPartToBelt,
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
    getAssemblyRightDownAt: () => rightDownAt,
    setAssemblyRightDownAt: (v) => { rightDownAt = v },
    getTranslateRotateActive: () => translateActive,
    getSelectedAssemblyCluster: () => selectedCluster,
    setSelectedAssemblyCluster: (v) => { selectedCluster = v },
    getAssemblySelectedPartJoint: () => selectedPartJoint,
    setAssemblySelectedPartJoint: (v) => { selectedPartJoint = v },
    ...depOverrides,
  }
  const ptr = initAssemblyPointer(deps)
  const setStateSpy = vi.spyOn(store, 'setState')
  return {
    ...ptr, deps, store, clusterPanel, setStateSpy, pendingPartJoints, canvas, controls,
    assemblyContextMenu, attachPartToBelt,
    getPtrDownAt: () => ptrDownAt,
    getRightDownAt: () => rightDownAt,
    setRightDownAt: (v) => { rightDownAt = v },
    setTranslateActive: (v) => { translateActive = v },
    setSelectedCluster: (v) => { selectedCluster = v },
    setSelectedPartJoint: (v) => { selectedPartJoint = v },
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

describe('initAssemblyPointer · onAssemblyPointerDown', () => {
  const pd = (over = {}) => ({ button: 0, clientX: 40, clientY: 50, stopPropagation: vi.fn(), ...over })

  it('belt mode owns the canvas — bails before any picking', () => {
    const t = setup({}, { assemblyJointRenderer: {
      isBeltMode: () => true, isAttachMode: () => false, isMateMode: () => false,
      pickJointRing: vi.fn(), pickJointAny: vi.fn(), beginRingDrag: vi.fn(),
    } })
    t.onAssemblyPointerDown(pd())
    expect(t.deps.assemblyRenderer.pickInstance).not.toHaveBeenCalled()
  })

  it('Priority 1: a joint-ring hit begins a ring drag and returns', () => {
    const t = setup()
    t.deps.assemblyJointRenderer.pickJointRing.mockReturnValue('joint-7')
    t.onAssemblyPointerDown(pd())
    expect(t.deps.assemblyJointRenderer.beginRingDrag).toHaveBeenCalledWith('joint-7', expect.anything())
    expect(t.deps.assemblyRenderer.pickInstanceCluster).not.toHaveBeenCalled()
  })

  it('a plain left-down on empty space records the click position', () => {
    const t = setup()                  // no joint, no cluster, lasso.start=false
    t.onAssemblyPointerDown(pd({ clientX: 40, clientY: 50 }))
    expect(t.getPtrDownAt()).toEqual({ x: 40, y: 50 })
  })

  it('a lasso start consumes the left-down (no click recorded)', () => {
    const t = setup()
    t.deps.setAssemblyPtrDownAt(null)
    t.deps.assemblyLasso.start.mockReturnValue(true)
    t.onAssemblyPointerDown(pd())
    expect(t.getPtrDownAt()).toBeNull()
  })

  it('right-button down records the right-down position for the contextmenu', () => {
    const t = setup()
    t.onAssemblyPointerDown(pd({ button: 2, clientX: 7, clientY: 9 }))
    expect(t.getRightDownAt()).toEqual({ x: 7, y: 9 })
  })

  it('clicking the active part-joint records the selected joint and suppresses the click', () => {
    const t = setup({ activeInstanceId: 'inst-A' })
    const e = pd()
    t.deps.assemblyRenderer.pickPartJoint.mockReturnValue({
      inst: { id: 'inst-A' }, joint: { id: 'j1' }, cluster: { id: 'cl-1' },
    })
    t.onAssemblyPointerDown(e)
    expect(t.getSelectedPartJoint()).toEqual({ instanceId: 'inst-A', jointId: 'j1', clusterId: 'cl-1' })
    expect(t.getPtrDownAt()).toBeNull()
    expect(e.stopPropagation).toHaveBeenCalled()
  })
})

describe('initAssemblyPointer · onAssemblyContextMenu (sub-part c)', () => {
  // Branch coverage for the right-click router. The real raycast picks
  // (pickLinker / pickBeltAt / pickInstance) are mocked; we assert the routing
  // decision + that the right menu / action fires.
  const rc = (over = {}) => ({
    button: 2, clientX: 100, clientY: 120,
    preventDefault: vi.fn(), stopPropagation: vi.fn(), ...over,
  })

  beforeEach(() => { ctxMenuCalls.length = 0 })

  it('always prevents the default browser menu and clears the right-down marker', async () => {
    const t = setup()
    t.setRightDownAt({ x: 100, y: 120 })   // a still right-click (no movement)
    const e = rc()
    await t.onAssemblyContextMenu(e)
    expect(e.preventDefault).toHaveBeenCalled()
    expect(e.stopPropagation).toHaveBeenCalled()
    expect(t.getRightDownAt()).toBeNull()
  })

  it('a right-drag (pan) is suppressed — no menu, no pick', async () => {
    const t = setup()
    t.setRightDownAt({ x: 100, y: 120 })
    await t.onAssemblyContextMenu(rc({ clientX: 130, clientY: 120 }))   // moved 30px > 5px threshold
    expect(t.deps.assemblyRenderer.pickLinker).not.toHaveBeenCalled()
    expect(t.assemblyContextMenu.show).not.toHaveBeenCalled()
    expect(ctxMenuCalls).toHaveLength(0)
  })

  it('a right-click hitting an overhang arrow bails (overhang dialog owns it)', async () => {
    const t = setup({}, { overhangLocations: { isVisible: () => true, hitTest: () => true } })
    await t.onAssemblyContextMenu(rc())
    expect(t.deps.assemblyRenderer.pickLinker).not.toHaveBeenCalled()
    expect(t.assemblyContextMenu.show).not.toHaveBeenCalled()
  })

  it('a linker hit opens the Relax menu, and Relax calls the backend', async () => {
    const t = setup({ currentAssembly: { instances: [], groups: [], overhang_connections: [{ id: 'L1', name: 'L1' }] } })
    t.deps.assemblyRenderer.pickLinker.mockReturnValue('L1')
    await t.onAssemblyContextMenu(rc())
    expect(t.deps.api.getAssemblyOverhangConnectionRelaxStatus).toHaveBeenCalledWith('L1')
    expect(ctxMenuCalls).toHaveLength(1)
    const relaxItem = ctxMenuCalls[0].items.find(i => i.label === 'Relax linker')
    expect(relaxItem.disabled).toBe(false)
    await relaxItem.onClick()
    expect(t.deps.api.relaxAssemblyOverhangConnection).toHaveBeenCalledWith('L1')
    expect(t.assemblyContextMenu.show).not.toHaveBeenCalled()
  })

  it('linker Relax is disabled when the backend reports it unavailable', async () => {
    const t = setup({ currentAssembly: { instances: [], groups: [], overhang_connections: [{ id: 'L1', name: 'L1' }] } })
    t.deps.assemblyRenderer.pickLinker.mockReturnValue('L1')
    t.deps.api.getAssemblyOverhangConnectionRelaxStatus.mockResolvedValue({ available: false, reason: 'ss linker' })
    await t.onAssemblyContextMenu(rc())
    const relaxItem = ctxMenuCalls[0].items.find(i => i.label === 'Relax linker')
    expect(relaxItem.disabled).toBe(true)
    expect(ctxMenuCalls[0].items.some(i => i.label === 'ss linker')).toBe(true)
  })

  it('a belt-path hit opens an "Attach part to belt" menu', async () => {
    const t = setup()
    t.deps.assemblyJointRenderer.pickBeltAt.mockReturnValue({ beltId: 'B1' })
    await t.onAssemblyContextMenu(rc())
    expect(ctxMenuCalls).toHaveLength(1)
    const attachItem = ctxMenuCalls[0].items.find(i => i.label === 'Attach part to belt')
    attachItem.onClick()
    expect(t.attachPartToBelt).toHaveBeenCalledWith('B1')
    expect(t.assemblyContextMenu.show).not.toHaveBeenCalled()
  })

  it('a part hit selects the instance and shows the part context menu', async () => {
    const t = setup()
    t.deps.assemblyRenderer.pickInstance.mockReturnValue({ id: 'inst-A' })
    await t.onAssemblyContextMenu(rc())
    expect(t.setStateSpy).toHaveBeenCalledWith({ activeInstanceId: 'inst-A' })
    expect(t.assemblyContextMenu.show).toHaveBeenCalledWith({ id: 'inst-A' }, 100, 120)
  })

  it('switching to a new part with a pending transform commits it first', async () => {
    const t = setup({ activeInstanceId: 'inst-OLD' }, { hasAssemblyPending: vi.fn(() => true) })
    t.deps.assemblyRenderer.pickInstance.mockReturnValue({ id: 'inst-NEW' })
    await t.onAssemblyContextMenu(rc())
    expect(t.deps.commitAssemblyPending).toHaveBeenCalled()
    expect(t.assemblyContextMenu.show).toHaveBeenCalledWith({ id: 'inst-NEW' }, 100, 120)
  })

  it('right-clicking empty space does nothing', async () => {
    const t = setup()
    await t.onAssemblyContextMenu(rc())
    expect(ctxMenuCalls).toHaveLength(0)
    expect(t.assemblyContextMenu.show).not.toHaveBeenCalled()
  })
})
