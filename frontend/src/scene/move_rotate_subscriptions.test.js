import { describe, expect, it, vi } from 'vitest'
import { initMoveRotateSubscriptions } from './move_rotate_subscriptions.js'

function harness() {
  const subscribers = []
  const deps = {
    cancelTranslateRotateTool: vi.fn(),
    clusterBackboneEntries: vi.fn(() => ['entry']),
    clusterGizmo: {
      isGroupActive: vi.fn(() => false),
      getPendingTransform: vi.fn(() => null),
      setConstraint: vi.fn(),
    },
    clusterGlowLayer: { clear: vi.fn(), setEntries: vi.fn() },
    isTranslateRotateActive: () => true,
    nucleotideTransformTool: {
      canActivate: vi.fn(() => true), activate: vi.fn(),
      handleSelectionChange: vi.fn(),
    },
    quatToEulerDeg: vi.fn(() => [10, 20, 30]),
    refreshCurrentSelection: vi.fn(),
    setPivotOptions: vi.fn(),
    setSelectedPivot: vi.fn(),
    setTransformValues: vi.fn(),
    store: { subscribe: handler => subscribers.push(handler) },
    translateRotateTool: {
      cancel: vi.fn(),
      handleSelectionChange: vi.fn(),
      handleMultiClusterSelectionChange: vi.fn(),
    },
  }
  initMoveRotateSubscriptions(deps)
  return { deps, subscribers }
}

describe('initMoveRotateSubscriptions', () => {
  it('synchronizes pivot controls when the active cluster changes', () => {
    const { deps, subscribers } = harness()
    const cluster = { id: 'c1', translation: [1, 2, 3], rotation: [0, 0, 0, 1] }
    subscribers[0]({
      activeClusterId: 'c1',
      translateRotateActive: true,
      currentDesign: {
        cluster_transforms: [cluster],
        cluster_joints: [{ id: 'j1', cluster_id: 'c1' }],
      },
    }, { activeClusterId: null })
    expect(deps.setTransformValues).toHaveBeenCalledWith(1, 2, 3, 10, 20, 30)
    expect(deps.setPivotOptions).toHaveBeenCalledWith(
      [{ id: 'j1', cluster_id: 'c1' }], 'c1',
    )
    expect(deps.clusterGizmo.setConstraint).toHaveBeenCalledWith('centroid', null)
  })

  it('hands a single selected base to the nucleotide tool', async () => {
    const { deps, subscribers } = harness()
    await subscribers[2]({
      translateRotateActive: true,
      selection: { items: [{ kind: 'base', key: 'h:0:f' }] },
    }, { selection: null })
    expect(deps.translateRotateTool.cancel).toHaveBeenCalledOnce()
    expect(deps.nucleotideTransformTool.activate).toHaveBeenCalledOnce()
  })

  it('enforces deformation mutual exclusion and refreshes active glow', () => {
    const { deps, subscribers } = harness()
    subscribers[5]({ deformToolActive: true }, { deformToolActive: false })
    expect(deps.cancelTranslateRotateTool).toHaveBeenCalledOnce()
    const design = { cluster_transforms: [{ id: 'c1' }] }
    subscribers[6]({
      translateRotateActive: true,
      activeClusterId: 'c1',
      currentDesign: design,
      currentGeometry: {},
    }, { translateRotateActive: false, activeClusterId: null, currentGeometry: null })
    expect(deps.clusterBackboneEntries).toHaveBeenCalledWith(
      design.cluster_transforms[0], design,
    )
    expect(deps.clusterGlowLayer.setEntries).toHaveBeenCalledWith(['entry'])
  })

  it('lets a VR nucleotide preview restore itself on canonical selection change', () => {
    const { deps, subscribers } = harness()
    const previousState = { selection: { items: [{ kind: 'domain' }] } }
    const newState = { selection: { items: [{ kind: 'base' }] } }
    subscribers[7](newState, previousState)
    expect(deps.nucleotideTransformTool.handleSelectionChange)
      .toHaveBeenCalledWith(newState, previousState)
  })
})
