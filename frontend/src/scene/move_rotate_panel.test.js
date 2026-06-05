/**
 * Tests for scene/move_rotate_panel.js — the Move/Rotate right-sidebar panel shell
 * (numeric transform inputs + pivot/cluster dropdowns + commit controller).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import * as THREE from 'three'
import { createMockStore } from '../test-helpers/mock_store.js'
import { mountIds, clearDom } from '../test-helpers/factory_dom.js'
import { initMoveRotatePanel } from './move_rotate_panel.js'

const DOM = {
  'move-rotate-panel':      'div',
  'mr-cluster-sel':         'select',
  'mr-tx':                  'input',
  'mr-ty':                  'input',
  'mr-tz':                  'input',
  'mr-rx':                  'input',
  'mr-ry':                  'input',
  'mr-rz':                  'input',
  'mr-ja':                  'input',
  'mr-pivot-sel':           'select',
  'mr-rotation-section':    'div',
  'mr-joint-angle-section': 'div',
}

function mountPanelDom() {
  const els = mountIds(DOM)
  // The pivot select ships with a default "centroid" option (index.html); the
  // setPivotOptions loop preserves option[0] and clears the rest.
  els['mr-pivot-sel'].appendChild(new Option('Centroid', 'centroid'))
  return els
}

function makeDeps(initialState = {}) {
  const store = createMockStore(initialState)
  return {
    store,
    scene: {}, camera: {}, canvas: {},
    clusterGizmo: {
      isActive: vi.fn(() => true), getActiveJoint: vi.fn(() => ({ id: 'j1' })),
      setJointRotation: vi.fn(), setTransform: vi.fn(), setConstraint: vi.fn(), attach: vi.fn(),
    },
    instanceGizmo: { setMatrix: vi.fn() },
    flexRelax: { hasGate: vi.fn(() => false), buildSsdnaPayload: vi.fn(() => ({ payload: 1 })), refreshFlexGates: vi.fn(() => Promise.resolve()) },
    applyAssemblyPrimaryLive: vi.fn(),
    queueAssemblyPrimaryCommit: vi.fn(),
    refreshClusterPivotForAttach: vi.fn(() => Promise.resolve()),
    isTranslateRotateActive: vi.fn(() => true),
  }
}

beforeEach(() => { clearDom() })

describe('initMoveRotatePanel — view setters', () => {
  it('no-ops gracefully when DOM is absent', () => {
    const api = initMoveRotatePanel(makeDeps())
    expect(api).toBeTruthy()
    expect(() => api.setTransformValues(1, 2, 3, 4, 5, 6)).not.toThrow()
    expect(() => api.setPivotOptions([])).not.toThrow()
  })

  it('setTransformValues writes inputs to 3 decimals, skipping the focused field', () => {
    const els = mountPanelDom()
    const api = initMoveRotatePanel(makeDeps())
    els['mr-tx'].focus()                       // active element is skipped
    api.setTransformValues(1.23456, -2, 3, 10, 20, 30)
    expect(els['mr-tx'].value).toBe('')        // skipped (focused)
    expect(els['mr-ty'].value).toBe('-2.000')
    expect(els['mr-rz'].value).toBe('30.000')
  })

  it('setTransformValuesFromMatrix decomposes pos + euler', () => {
    const els = mountPanelDom()
    const api = initMoveRotatePanel(makeDeps())
    const mat = new THREE.Matrix4().setPosition(5, 6, 7)
    api.setTransformValuesFromMatrix(mat)
    expect(els['mr-tx'].value).toBe('5.000')
    expect(els['mr-ty'].value).toBe('6.000')
    expect(els['mr-tz'].value).toBe('7.000')
    // null matrix → no-op, no throw
    expect(() => api.setTransformValuesFromMatrix(null)).not.toThrow()
  })

  it('setJointAngle writes mr-ja to 1 decimal', () => {
    const els = mountPanelDom()
    const api = initMoveRotatePanel(makeDeps())
    api.setJointAngle(42.37)
    expect(els['mr-ja'].value).toBe('42.4')
  })

  it('setClusterOptions builds options; default-selects the last, or the given id', () => {
    const els = mountPanelDom()
    const api = initMoveRotatePanel(makeDeps())
    api.setClusterOptions([{ id: 'a', name: 'A' }, { id: 'b', name: 'B' }])
    expect([...els['mr-cluster-sel'].options].map(o => o.value)).toEqual(['a', 'b'])
    expect(els['mr-cluster-sel'].value).toBe('b')          // last by default
    api.setClusterOptions([{ id: 'a', name: 'A' }, { id: 'b', name: 'B' }], 'a')
    expect(els['mr-cluster-sel'].value).toBe('a')          // explicit selection
  })

  it('setPivotOptions lists joints; appends ssDNA only when flexRelax.hasGate', () => {
    const els = mountPanelDom()
    const deps = makeDeps()
    const api = initMoveRotatePanel(deps)
    api.setPivotOptions([{ id: 'j1', name: 'hinge' }], 'c1')
    expect([...els['mr-pivot-sel'].options].map(o => o.value)).toEqual(['centroid', 'j1'])

    deps.flexRelax.hasGate.mockReturnValue(true)
    api.setPivotOptions([{ id: 'j1', name: 'hinge' }], 'c1')
    expect([...els['mr-pivot-sel'].options].map(o => o.value)).toEqual(['centroid', 'j1', 'ssdna'])
  })

  it('setSelectedPivot toggles joint-mode section visibility', () => {
    const els = mountPanelDom()
    const api = initMoveRotatePanel(makeDeps())
    api.setSelectedPivot('centroid')
    expect(els['mr-rotation-section'].style.display).toBe('')        // visible
    expect(els['mr-joint-angle-section'].style.display).toBe('none')
    expect(api.getPivotIsJoint()).toBe(false)

    api.setSelectedPivot('j1')
    expect(els['mr-rotation-section'].style.display).toBe('none')
    expect(els['mr-joint-angle-section'].style.display).toBe('')     // visible
    expect(api.getPivotIsJoint()).toBe(true)
  })

  it('syncClusterDropdown sets the select value', () => {
    const els = mountPanelDom()
    els['mr-cluster-sel'].appendChild(new Option('C', 'c'))
    const api = initMoveRotatePanel(makeDeps())
    api.syncClusterDropdown('c')
    expect(els['mr-cluster-sel'].value).toBe('c')
  })

  it('getAssemblyCtx/setAssemblyCtx round-trips', () => {
    const api = initMoveRotatePanel(makeDeps())
    expect(api.getAssemblyCtx()).toBe(null)
    const ctx = { id: 'x' }
    api.setAssemblyCtx(ctx)
    expect(api.getAssemblyCtx()).toBe(ctx)
  })
})

describe('initMoveRotatePanel — commit controller', () => {
  it('assembly path: applies live + sets gizmo matrix + queues commit', () => {
    const els = mountPanelDom()
    const deps = makeDeps({ assemblyActive: true })
    const api = initMoveRotatePanel(deps)
    const ctx = { id: 'inst1' }
    api.setAssemblyCtx(ctx)
    els['mr-tx'].value = '2'; els['mr-ty'].value = '0'; els['mr-tz'].value = '0'
    els['mr-rx'].value = '0'; els['mr-ry'].value = '0'; els['mr-rz'].value = '0'
    api.commitInputs()
    expect(deps.applyAssemblyPrimaryLive).toHaveBeenCalledTimes(1)
    expect(deps.applyAssemblyPrimaryLive.mock.calls[0][0]).toBe(ctx)
    expect(deps.instanceGizmo.setMatrix).toHaveBeenCalledTimes(1)
    expect(deps.queueAssemblyPrimaryCommit).toHaveBeenCalledTimes(1)
  })

  it('assembly path bails when no ctx is set', () => {
    mountPanelDom()
    const deps = makeDeps({ assemblyActive: true })
    const api = initMoveRotatePanel(deps)
    api.commitInputs()
    expect(deps.applyAssemblyPrimaryLive).not.toHaveBeenCalled()
  })

  it('design translate path: setTransform with parsed tx/ty/tz + quat', () => {
    const els = mountPanelDom()
    const deps = makeDeps({ assemblyActive: false })
    const api = initMoveRotatePanel(deps)
    els['mr-tx'].value = '1'; els['mr-ty'].value = '2'; els['mr-tz'].value = '3'
    els['mr-rx'].value = '0'; els['mr-ry'].value = '0'; els['mr-rz'].value = '0'
    api.commitInputs()
    expect(deps.clusterGizmo.setTransform).toHaveBeenCalledTimes(1)
    expect(deps.clusterGizmo.setTransform.mock.calls[0][0]).toEqual([1, 2, 3])
    expect(deps.clusterGizmo.setJointRotation).not.toHaveBeenCalled()
  })

  it('joint path: setJointRotation when pivot is joint-mode', () => {
    const els = mountPanelDom()
    const deps = makeDeps({ assemblyActive: false })
    const api = initMoveRotatePanel(deps)
    api.setSelectedPivot('j1')          // pivotIsJoint = true
    els['mr-ja'].value = '45'
    api.commitInputs()
    expect(deps.clusterGizmo.setJointRotation).toHaveBeenCalledWith({ id: 'j1' }, 45)
    expect(deps.clusterGizmo.setTransform).not.toHaveBeenCalled()
  })
})

describe('initMoveRotatePanel — dropdown handlers', () => {
  it('pivot change → centroid / ssdna / joint constraints', () => {
    const els = mountPanelDom()
    const deps = makeDeps()
    deps.store.setState({ activeClusterId: 'c1', currentDesign: { cluster_joints: [{ id: 'j1', name: 'h' }] } })
    initMoveRotatePanel(deps)
    const sel = els['mr-pivot-sel']
    sel.appendChild(new Option('ssDNA', 'ssdna'))
    sel.appendChild(new Option('Joint', 'j1'))

    sel.value = 'centroid'; sel.dispatchEvent(new Event('change'))
    expect(deps.clusterGizmo.setConstraint).toHaveBeenLastCalledWith('centroid', null)

    sel.value = 'ssdna'; sel.dispatchEvent(new Event('change'))
    expect(deps.flexRelax.buildSsdnaPayload).toHaveBeenCalledWith('c1')
    expect(deps.clusterGizmo.setConstraint).toHaveBeenLastCalledWith('ssdna', { payload: 1 })

    sel.value = 'j1'; sel.dispatchEvent(new Event('change'))
    expect(deps.clusterGizmo.setConstraint).toHaveBeenLastCalledWith('joint', { id: 'j1', name: 'h' })
  })

  it('cluster change → refresh pivot + attach + repopulate, guarded by tool-active', async () => {
    const els = mountPanelDom()
    const deps = makeDeps()
    deps.store.setState({ activeClusterId: 'c0', currentDesign: { cluster_joints: [] } })
    initMoveRotatePanel(deps)
    const sel = els['mr-cluster-sel']
    sel.appendChild(new Option('C1', 'c1'))

    // Tool inactive → bails.
    deps.isTranslateRotateActive.mockReturnValue(false)
    sel.value = 'c1'; sel.dispatchEvent(new Event('change'))
    await Promise.resolve()
    expect(deps.clusterGizmo.attach).not.toHaveBeenCalled()

    // Tool active → switches gizmo to the chosen cluster.
    deps.isTranslateRotateActive.mockReturnValue(true)
    sel.value = 'c1'; sel.dispatchEvent(new Event('change'))
    await new Promise(r => setTimeout(r))
    expect(deps.refreshClusterPivotForAttach).toHaveBeenCalledWith('c1')
    expect(deps.clusterGizmo.attach).toHaveBeenCalledWith('c1', deps.scene, deps.camera, deps.canvas)
    expect(deps.clusterGizmo.setConstraint).toHaveBeenLastCalledWith('centroid', null)
  })
})
