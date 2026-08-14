// @vitest-environment jsdom

import { describe, expect, it, vi } from 'vitest'
import { createAssemblyLoadDefaults, initAssemblyModeSync } from './assembly_mode_sync.js'

const stub = () => vi.fn()

function harness() {
  let subscriber
  const elementTarget = { addEventListener: stub(), removeEventListener: stub() }
  const deps = {
    store: {
      subscribeSlice: vi.fn((_slice, callback) => { subscriber = callback; return stub() }),
      setState: stub(),
    },
    animPanel: { setAssemblyMode: stub() },
    setDesignGeometryVisible: stub(),
    assemblyPanel: { show: stub(), hide: stub(), rebuild: stub() },
    applyAssemblyLoadDefaults: stub(),
    runAssemblyRebuild: stub(),
    controls: elementTarget,
    updateFixedLockPositions: stub(),
    canvas: { ...elementTarget },
    onAssemblyPointerDown: stub(),
    onAssemblyClick: stub(),
    overhangHoverPicker: { onHoverMove: stub(), reset: stub() },
    onAssemblyContextMenu: stub(),
    hasAssemblyPending: vi.fn(() => false),
    commitAssemblyPending: stub(),
    rebuildFixedLocks: stub(),
    assemblyContextMenu: { hide: stub() },
    instanceGizmo: { detach: stub(), isDragging: vi.fn(() => false) },
    assemblyPendingTransforms: { clear: stub() },
    assemblyPendingPartJoints: { clear: stub() },
    assemblyRenderer: { dispose: stub(), setActiveInstance: stub() },
    assemblyJointRenderer: {
      exitAttachMode: stub(), rebuild: stub(), setActiveInstance: stub(),
    },
    beltPathRenderer: { rebuild: stub() },
    assemblyPointer: { cancelDrag: stub() },
    assemblyLasso: { cancel: stub() },
    assemblyMultiBox: { dispose: stub(), update: stub() },
    setMotionChip: stub(),
    isTranslateRotateActive: vi.fn(() => false),
    setTranslateRotateActive: stub(),
    translateRotateTool: { hideConfirmBtn: stub() },
    hideWelcome: stub(),
    getAssemblyLoadSettle: () => null,
    rebuildBeltPaths: stub(),
    attachGroupGizmoForGroup: stub(),
    attachGroupGizmo: stub(),
    clearSelectedAssemblyCluster: stub(),
    clusterGlowLayer: { clear: stub() },
    getClusterPanel: () => null,
  }
  initAssemblyModeSync(deps)
  return { deps, subscriber }
}

describe('initAssemblyModeSync', () => {
  it('normalizes assembly load representation in one batched persistence call', async () => {
    const api = { batchPatchInstances: vi.fn(() => Promise.resolve()) }
    const setColoringMode = stub()
    const updateReprRadio = stub()
    const applyDefaults = createAssemblyLoadDefaults({ api, setColoringMode, updateReprRadio })
    const assembly = { instances: [
      { id: 'a', representation: 'full' },
      { id: 'b', representation: 'cylinders' },
    ] }
    applyDefaults(assembly)
    expect(setColoringMode).toHaveBeenCalledWith('overhang-only')
    expect(updateReprRadio).toHaveBeenCalledWith('cylinders')
    expect(assembly.instances.map(item => item.representation)).toEqual([
      'cylinders', 'cylinders',
    ])
    expect(api.batchPatchInstances).toHaveBeenCalledWith([
      { id: 'a', representation: 'cylinders' },
      { id: 'b', representation: 'cylinders' },
    ], { skipSync: true })
  })

  it('enters assembly mode through one canonical build path', () => {
    const { deps, subscriber } = harness()
    const assembly = { instances: [], joints: [] }
    subscriber(
      { assemblyActive: true, currentAssembly: assembly, activeInstanceId: null },
      { assemblyActive: false, currentAssembly: null, activeInstanceId: null },
    )
    expect(deps.setDesignGeometryVisible).toHaveBeenCalledWith(false)
    expect(deps.applyAssemblyLoadDefaults).toHaveBeenCalledWith(assembly)
    expect(deps.runAssemblyRebuild).toHaveBeenCalledWith(assembly, {
      fitOnDone: true, activeInstanceId: null,
    })
    expect(deps.canvas.addEventListener).toHaveBeenCalledWith(
      'contextmenu', deps.onAssemblyContextMenu,
    )
  })

  it('fully releases assembly-only scene state and listeners on exit', () => {
    const { deps, subscriber } = harness()
    subscriber(
      { assemblyActive: false, currentAssembly: null, activeInstanceId: null },
      { assemblyActive: true, currentAssembly: { instances: [] }, activeInstanceId: null },
    )
    expect(deps.setDesignGeometryVisible).toHaveBeenCalledWith(true)
    expect(deps.assemblyRenderer.dispose).toHaveBeenCalledOnce()
    expect(deps.assemblyPointer.cancelDrag).toHaveBeenCalledOnce()
    expect(deps.assemblyLasso.cancel).toHaveBeenCalledOnce()
    expect(deps.assemblyMultiBox.dispose).toHaveBeenCalledOnce()
    expect(deps.canvas.removeEventListener).toHaveBeenCalledWith(
      'contextmenu', deps.onAssemblyContextMenu,
    )
  })
})
