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
  'mr-rx-dec':              'button',
  'mr-rx-inc':              'button',
  'mr-ry-dec':              'button',
  'mr-ry-inc':              'button',
  'mr-rz-dec':              'button',
  'mr-rz-inc':              'button',
  'mr-snap-45':             'input',
  'mr-reset-btn':           'button',
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
      clearPendingTransform: vi.fn(), setRotationSnap: vi.fn(),
    },
    instanceGizmo: { setMatrix: vi.fn() },
    flexRelax: {
      hasGate: vi.fn(() => false),
      hasTetherOption: vi.fn(() => false),
      buildSsdnaPayload: vi.fn(() => ({ payload: 1 })),
      buildTethersPayload: vi.fn(() => Promise.resolve({ connections: [{ movingKey: 'h:1:FORWARD', fixedKey: 'h:2:REVERSE', contour: 0.67 }], resolveWorldPos: () => null })),
      buildDuplexTautPayload: vi.fn(() => Promise.resolve({ connections: [{ movingKey: 'h:1:FORWARD', fixedKey: 'h:2:REVERSE', contour: 0.67 }], resolveWorldPos: () => null })),
      refreshFlexGates: vi.fn(() => Promise.resolve()),
    },
    applyAssemblyPrimaryLive: vi.fn(),
    queueAssemblyPrimaryCommit: vi.fn(),
    refreshClusterPivotForAttach: vi.fn(() => Promise.resolve()),
    setClusterRotationPoint: vi.fn(() => Promise.resolve()),
    isTranslateRotateActive: vi.fn(() => true),
  }
}

// A minimal design whose cluster `dc1` is an overhang-duplex cluster: driver overhang
// `ohD` + driven overhang `ohV` (its domain lives in the cluster's domain_ids).
function duplexDesign() {
  return {
    cluster_joints: [],
    overhangs: [{ id: 'ohD', label: 'Drv' }, { id: 'ohV', label: 'Dvn' }],
    strands: [{ id: 's1', domains: [{ overhang_id: 'ohV' }] }],
    cluster_transforms: [{
      id: 'dc1', overhang_duplex_driver_id: 'ohD',
      domain_ids: [{ strand_id: 's1', domain_index: 0 }],
    }],
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

    deps.flexRelax.hasTetherOption.mockReturnValue(true)
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

describe('initMoveRotatePanel — 45° step buttons / reset / snap', () => {
  it('+45 about X from identity commits an absolute 45° X rotation', () => {
    const els = mountPanelDom()
    const deps = makeDeps({ assemblyActive: false })
    const api = initMoveRotatePanel(deps)
    els['mr-tx'].value = '0'; els['mr-ty'].value = '0'; els['mr-tz'].value = '0'
    els['mr-rx'].value = '0'; els['mr-ry'].value = '0'; els['mr-rz'].value = '0'
    els['mr-rx-inc'].click()
    // fields updated to the composed absolute angle
    expect(parseFloat(els['mr-rx'].value)).toBeCloseTo(45)
    // commit pushed the absolute transform to the gizmo (quat for 45° about X)
    expect(deps.clusterGizmo.setTransform).toHaveBeenCalledTimes(1)
    const [, quat] = deps.clusterGizmo.setTransform.mock.calls[0]
    const expected = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), Math.PI / 4)
    expect(quat[0]).toBeCloseTo(expected.x)
    expect(quat[3]).toBeCloseTo(expected.w)
  })

  it('two +45 X clicks accumulate to 90°', () => {
    const els = mountPanelDom()
    const deps = makeDeps({ assemblyActive: false })
    initMoveRotatePanel(deps)
    for (const inp of ['mr-tx', 'mr-ty', 'mr-tz', 'mr-rx', 'mr-ry', 'mr-rz']) els[inp].value = '0'
    els['mr-rx-inc'].click()
    els['mr-rx-inc'].click()
    expect(parseFloat(els['mr-rx'].value)).toBeCloseTo(90)
  })

  // Reset ("restore saved positions") is handled in translate_rotate_tool.js (a lifecycle action:
  // discard the in-progress move + revert geometry + re-attach at the committed pose), not the panel.
  // Its behavior is pinned in translate_rotate_tool.test.js.

  it('snap checkbox toggles clusterGizmo.setRotationSnap(45 | null)', () => {
    const els = mountPanelDom()
    els['mr-snap-45'].type = 'checkbox'
    const deps = makeDeps({ assemblyActive: false })
    initMoveRotatePanel(deps)
    els['mr-snap-45'].checked = true
    els['mr-snap-45'].dispatchEvent(new Event('change'))
    expect(deps.clusterGizmo.setRotationSnap).toHaveBeenLastCalledWith(45)
    els['mr-snap-45'].checked = false
    els['mr-snap-45'].dispatchEvent(new Event('change'))
    expect(deps.clusterGizmo.setRotationSnap).toHaveBeenLastCalledWith(null)
  })
})

describe('initMoveRotatePanel — dropdown handlers', () => {
  it('pivot change → centroid / tethers / joint constraints', async () => {
    const els = mountPanelDom()
    const deps = makeDeps()
    deps.store.setState({ activeClusterId: 'c1', currentDesign: { cluster_joints: [{ id: 'j1', name: 'h' }] } })
    initMoveRotatePanel(deps)
    const sel = els['mr-pivot-sel']
    sel.appendChild(new Option('Constrained (tethers)', 'ssdna'))
    sel.appendChild(new Option('Joint', 'j1'))

    sel.value = 'centroid'; sel.dispatchEvent(new Event('change'))
    expect(deps.clusterGizmo.setConstraint).toHaveBeenLastCalledWith('centroid', null)

    // "Constrained (tethers)" builds the MERGED ssDNA + connection-tether payload (async).
    sel.value = 'ssdna'; sel.dispatchEvent(new Event('change'))
    await new Promise(r => setTimeout(r))
    expect(deps.flexRelax.buildTethersPayload).toHaveBeenCalledWith('c1')
    expect(deps.clusterGizmo.setConstraint).toHaveBeenLastCalledWith('ssdna', expect.objectContaining({ connections: expect.any(Array) }))

    sel.value = 'j1'; sel.dispatchEvent(new Event('change'))
    expect(deps.clusterGizmo.setConstraint).toHaveBeenLastCalledWith('joint', { id: 'j1', name: 'h' })
  })

  it('"Constrained (tethers)" option appears when hasTetherOption is true (connection-only cluster)', () => {
    const els = mountPanelDom()
    const deps = makeDeps()
    deps.flexRelax.hasGate = vi.fn(() => false)
    deps.flexRelax.hasTetherOption = vi.fn(() => true)   // connected by a duplex/linker, no ssDNA marks
    deps.store.setState({ activeClusterId: 'c1', currentDesign: { cluster_joints: [] } })
    const api = initMoveRotatePanel(deps)
    api.setPivotOptions([], 'c1')
    const opts = [...els['mr-pivot-sel'].options]
    const ssdna = opts.find(o => o.value === 'ssdna')
    expect(ssdna, 'tethers option present').toBeTruthy()
    expect(ssdna.textContent).toBe('Constrained (tethers)')
  })

  it('setPivotOptions lists each overhang root for a duplex cluster (driver + driven)', () => {
    const els = mountPanelDom()
    const deps = makeDeps()
    deps.store.setState({ currentDesign: duplexDesign() })
    const api = initMoveRotatePanel(deps)
    api.setPivotOptions([], 'dc1')
    const vals = [...els['mr-pivot-sel'].options].map(o => o.value)
    expect(vals).toEqual(['centroid', 'dup:root:ohD', 'dup:root:ohV', 'dup:taut'])
  })

  it('pivot change → dup:taut constrains the gizmo with the duplex bond tethers', async () => {
    const els = mountPanelDom()
    const deps = makeDeps()
    deps.store.setState({ activeClusterId: 'dc1', currentDesign: duplexDesign() })
    initMoveRotatePanel(deps)
    const sel = els['mr-pivot-sel']
    sel.appendChild(new Option('Constrained', 'dup:taut'))
    sel.value = 'dup:taut'; sel.dispatchEvent(new Event('change'))
    await new Promise(r => setTimeout(r))
    expect(deps.flexRelax.buildDuplexTautPayload).toHaveBeenCalledWith('dc1')
    const [type, payload] = deps.clusterGizmo.setConstraint.mock.calls.at(-1)
    expect(type).toBe('ssdna')
    expect(payload.connections).toHaveLength(1)   // fed the bond tethers, not centroid
  })

  it('pivot change → dup:taut with no resolvable bonds falls back to centroid', async () => {
    const els = mountPanelDom()
    const deps = makeDeps()
    deps.flexRelax.buildDuplexTautPayload.mockResolvedValue(null)
    deps.store.setState({ activeClusterId: 'dc1', currentDesign: duplexDesign() })
    initMoveRotatePanel(deps)
    const sel = els['mr-pivot-sel']
    sel.appendChild(new Option('Constrained', 'dup:taut'))
    sel.value = 'dup:taut'; sel.dispatchEvent(new Event('change'))
    await new Promise(r => setTimeout(r))
    expect(deps.clusterGizmo.setConstraint).toHaveBeenLastCalledWith('centroid', null)
  })

  it('setPivotOptions preserves the current selection across a rebuild (root pivot not reverted)', () => {
    const els = mountPanelDom()
    const deps = makeDeps()
    deps.store.setState({ currentDesign: duplexDesign() })
    const api = initMoveRotatePanel(deps)
    api.setPivotOptions([], 'dc1')
    els['mr-pivot-sel'].value = 'dup:root:ohD'          // user picks a root
    api.setPivotOptions([], 'dc1')                       // subscriber-driven rebuild
    expect(els['mr-pivot-sel'].value).toBe('dup:root:ohD')  // selection preserved, not centroid
  })

  it('pivot change → dup:root: sets the pivot, clears the centroid pending-transform, re-attaches, and HOLDS the selection', async () => {
    const els = mountPanelDom()
    const deps = makeDeps()
    deps.store.setState({ activeClusterId: 'dc1', currentDesign: duplexDesign() })
    initMoveRotatePanel(deps)
    const sel = els['mr-pivot-sel']
    sel.appendChild(new Option('Drv root', 'dup:root:ohD'))
    sel.value = 'dup:root:ohD'; sel.dispatchEvent(new Event('change'))
    await new Promise(r => setTimeout(r))
    expect(deps.setClusterRotationPoint).toHaveBeenCalledWith('dc1', { kind: 'overhang_root', overhangId: 'ohD' })
    // Must NOT recompute the pivot from the visual centroid (that would undo the root pivot).
    expect(deps.refreshClusterPivotForAttach).not.toHaveBeenCalled()
    expect(deps.clusterGizmo.clearPendingTransform).toHaveBeenCalledWith('dc1')
    expect(deps.clusterGizmo.attach).toHaveBeenCalledWith('dc1', deps.scene, deps.camera, deps.canvas)
    // The dropdown holds the root even though attach's activeClusterId churn resets it.
    expect(sel.value).toBe('dup:root:ohD')
  })

  it('pivot change → centroid on a duplex cluster routes to setClusterRotationPoint(centroid)', async () => {
    const els = mountPanelDom()
    const deps = makeDeps()
    deps.store.setState({ activeClusterId: 'dc1', currentDesign: duplexDesign() })
    initMoveRotatePanel(deps)
    const sel = els['mr-pivot-sel']
    sel.value = 'centroid'; sel.dispatchEvent(new Event('change'))
    await new Promise(r => setTimeout(r))
    expect(deps.setClusterRotationPoint).toHaveBeenCalledWith('dc1', { kind: 'centroid' })
    // No plain-cluster centroid constraint when it's a duplex cluster.
    expect(deps.clusterGizmo.setConstraint).not.toHaveBeenCalledWith('centroid', null)
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
