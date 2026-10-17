/**
 * Tests for scene/move_rotate_panel.js — the Move/Rotate right-sidebar panel shell
 * (numeric transform inputs + pivot + current-selection box + commit controller).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import * as THREE from 'three'
import { createMockStore } from '../test-helpers/mock_store.js'
import { mountIds, clearDom } from '../test-helpers/factory_dom.js'
import { initMoveRotatePanel, moveRotateSelectionLabels } from './move_rotate_panel.js'
import { showToast } from '../ui/toast.js'

vi.mock('../ui/toast.js', () => ({ showToast: vi.fn() }))

const DOM = {
  'move-rotate-panel':      'div',
  'mr-current-selection':   'div',
  'mr-session-hint':        'div',
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
  'mr-frame-sel':           'select',
  'mr-reset-btn':           'button',
  'mr-apply-btn':           'button',
}

describe('session-mode UX', () => {
  it('disables exact fields while armed empty and explains the next action', () => {
    const els = mountPanelDom()
    const panel = initMoveRotatePanel(makeDeps())
    panel.setSessionMode('waiting')
    expect(els['mr-tx'].disabled).toBe(true)
    expect(els['mr-pivot-sel'].disabled).toBe(true)
    expect(els['mr-reset-btn'].disabled).toBe(true)
    expect(els['mr-apply-btn'].textContent).toBe('Done')
    expect(els['mr-session-hint'].textContent).toContain('Select a cluster or nucleotide')
  })

  it('shows gizmo guidance for nucleotide sessions and restores cluster inputs', () => {
    const els = mountPanelDom()
    const panel = initMoveRotatePanel(makeDeps())
    panel.setSessionMode('nucleotide')
    expect(els['mr-tx'].disabled).toBe(true)
    expect(els['mr-reset-btn'].disabled).toBe(false)
    expect(els['mr-session-hint'].textContent).toContain('Press Tab')
    panel.setSessionMode('cluster')
    expect(els['mr-tx'].disabled).toBe(false)
    expect(els['mr-pivot-sel'].disabled).toBe(false)
    expect(els['mr-apply-btn'].textContent).toBe('Apply')
  })

  it('uses global axes for a cluster group and restores the chosen local frame for one cluster', () => {
    const els = mountPanelDom()
    const deps = makeDeps()
    const panel = initMoveRotatePanel(deps)
    els['mr-frame-sel'].value = 'local'
    panel.setSessionMode('cluster-group')
    expect(els['mr-frame-sel'].disabled).toBe(true)
    expect(deps.clusterGizmo.setSpace).toHaveBeenLastCalledWith('world')
    expect(els['mr-session-hint'].textContent).toContain('global axes')

    panel.setSessionMode('cluster')
    expect(els['mr-frame-sel'].disabled).toBe(false)
    expect(deps.clusterGizmo.setSpace).toHaveBeenLastCalledWith('local')
  })
})

function mountPanelDom() {
  const els = mountIds(DOM)
  // The pivot select ships with a default "centroid" option (index.html); the
  // setPivotOptions loop preserves option[0] and clears the rest.
  els['mr-pivot-sel'].appendChild(new Option('Centroid', 'centroid'))
  els['mr-frame-sel'].appendChild(new Option('Global', 'world'))
  els['mr-frame-sel'].appendChild(new Option('Local', 'local'))
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
      clearPendingTransform: vi.fn(), setRotationSnap: vi.fn(), setSpace: vi.fn(),
    },
    instanceGizmo: { setMatrix: vi.fn(), setSpace: vi.fn() },
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
    setClusterRotationPoint: vi.fn(async (_clusterId, spec) => {
      const response = rotationPointResponse(store.getState().currentDesign, spec)
      store.setState({ currentDesign: response.design })
      return response
    }),
    clearSelection: vi.fn(),
  }
}

// A minimal design whose cluster `dc1` is an overhang-duplex cluster: driver overhang
// `ohD` + driven overhang `ohV` (its domain lives in the cluster's domain_ids).
function duplexDesign() {
  return {
    id: 'duplex-design',
    cluster_joints: [],
    overhangs: [{ id: 'ohD', label: 'Drv' }, { id: 'ohV', label: 'Dvn' }],
    strands: [{ id: 's1', domains: [{ overhang_id: 'ohV' }] }],
    cluster_transforms: [{
      id: 'dc1', overhang_duplex_driver_id: 'ohD',
      domain_ids: [{ strand_id: 's1', domain_index: 0 }],
      translation: [0, 0, 0], rotation: [0, 0, 0, 1], pivot: [0, 0, 0],
    }],
  }
}

// Explicit response data, not a second implementation of the native rebasing math.
function rotationPointResponse(source, spec = { kind: 'overhang_root', overhangId: 'ohD' }) {
  const design = structuredClone(source)
  const cluster = design.cluster_transforms.find(c => c.id === 'dc1')
  cluster.pivot = spec.kind === 'centroid' ? [2, 2, 2] : spec.overhangId === 'ohD' ? [1, 2, 3] : [4, 5, 6]
  cluster.translation = [7, 8, 9]
  return { design, revision: 2, validation: { passed: true } }
}

beforeEach(() => { clearDom(); vi.clearAllMocks() })

describe('exclusive history panel ownership', () => {
  function opened() {
    const els = mountPanelDom(), deps = makeDeps({ currentDesign: duplexDesign(), activeClusterId: 'dc1' })
    for (const [id, node] of Object.entries(els)) if (id !== 'move-rotate-panel') els['move-rotate-panel'].append(node)
    const panel = initMoveRotatePanel(deps)
    const callbacks = Object.fromEntries(['onApply', 'onCancel', 'onReset', 'onTransform', 'onJointAngle',
      'onPivot', 'onFrame', 'onSnap', 'onStep', 'onUpgrade'].map(key => [key, vi.fn()]))
    const lease = panel.bindHistorySession(callbacks)
    lease.update({ role: 'placement', labels: ['Historical placement'], translation: [1, 2, 3],
      euler: [0, 0, 0], pivots: [{ id: 'centroid', label: 'Centroid' }, { id: 'dup:root:ohD', label: 'Driver root' }] })
    return { els, deps, panel, callbacks, lease }
  }

  it('routes existing numeric and pivot controls only to the private session', () => {
    const f = opened()
    f.els['mr-tx'].value = '8'
    f.els['mr-tx'].dispatchEvent(new Event('change', { bubbles: true }))
    expect(f.callbacks.onTransform).toHaveBeenCalledWith([8, 2, 3], [0, 0, 0])
    f.els['mr-pivot-sel'].value = 'dup:root:ohD'
    f.els['mr-pivot-sel'].dispatchEvent(new Event('change', { bubbles: true }))
    expect(f.callbacks.onPivot).toHaveBeenCalledWith('dup:root:ohD')
    expect(f.deps.setClusterRotationPoint).not.toHaveBeenCalled()
    expect(f.deps.clusterGizmo.setTransform).not.toHaveBeenCalled()
    f.lease.release()
  })

  it('blocks live selection refreshes and ordinary Apply listeners while bound', () => {
    const f = opened(), ordinary = vi.fn()
    f.els['mr-apply-btn'].addEventListener('click', ordinary)
    f.panel.setCurrentSelection(['Latest selection'])
    f.panel.setTransformValues(99, 99, 99, 0, 0, 0)
    f.panel.setPivotOptions([], 'dc1')
    expect(f.els['mr-current-selection'].textContent).toBe('Historical placement')
    expect(f.els['mr-tx'].value).toBe('1.000')
    expect(f.els['mr-pivot-sel'].options).toHaveLength(2)
    f.els['mr-apply-btn'].click()
    expect(f.callbacks.onApply).toHaveBeenCalledOnce()
    expect(ordinary).not.toHaveBeenCalled()
    f.lease.release()
    f.els['mr-apply-btn'].click()
    expect(ordinary).toHaveBeenCalledOnce()
  })

  it('refuses concurrent ownership and makes released callbacks inert', () => {
    const f = opened()
    expect(() => f.panel.bindHistorySession({})).toThrow(/already/i)
    f.lease.release()
    const next = f.panel.bindHistorySession({})
    next.update({ role: 'reset', labels: ['Reset a saved nucleotide pose'] })
    f.lease.update({ labels: ['Late response'] })
    f.lease.release()
    expect(next.isCurrent()).toBe(true)
    expect(f.els['mr-current-selection'].textContent).toBe('Reset a saved nucleotide pose')
    expect(f.els['mr-tx'].disabled).toBe(true)
    next.release()
  })

  it('preserves invalid numeric input and reports it without authoring zero', () => {
    const f = opened()
    f.els['mr-tx'].value = 'not a number'
    f.els['mr-tx'].dispatchEvent(new Event('change', { bubbles: true }))
    expect(f.callbacks.onTransform).not.toHaveBeenCalled()
    expect(f.els['mr-session-hint'].textContent).toContain('finite')
    expect(f.els['mr-tx'].value).toBe('not a number')
    f.lease.release()
  })

  it('offers an explicit linked-placement upgrade only when admitted by Prepare', () => {
    const f = opened(), button = document.getElementById('mr-history-upgrade-btn')
    expect(button).not.toBeNull()
    expect(button.hidden).toBe(true)
    f.lease.update({ placement_upgrade: { upgrade_to: 'placement-poses-v1' } })
    expect(button.hidden).toBe(false)
    button.click()
    expect(f.callbacks.onUpgrade).toHaveBeenCalledOnce()
    f.lease.release()
    expect(button.hidden).toBe(true)
  })

  it('restores the previous joint control mode after releasing history', () => {
    const els = mountPanelDom(), panel = initMoveRotatePanel(makeDeps())
    panel.showJointMode(true)
    const lease = panel.bindHistorySession({})
    lease.update({ jointMode: false })
    lease.release()
    expect(panel.getPivotIsJoint()).toBe(true)
    expect(els['mr-rotation-section'].style.display).toBe('none')
  })

  it('keeps draft input editable during evaluation but uses explicit recovery labels', () => {
    const f = opened()
    f.lease.setStatus({ busy: 'evaluate' })
    expect(f.els['mr-tx'].disabled).toBe(false)
    f.lease.setStatus({ inputsUnavailable: true })
    expect(f.els['mr-tx'].disabled).toBe(true)
    expect(f.els['mr-reset-btn'].disabled).toBe(true)
    expect(f.els['mr-apply-btn'].disabled).toBe(false)
    f.lease.setStatus({ publicationUnknown: true, error: new Error('Response lost') })
    expect(f.els['mr-tx'].disabled).toBe(true)
    expect(f.els['mr-apply-btn'].textContent).toBe('Check saved result')
    expect(f.els['mr-apply-btn'].disabled).toBe(false)
    f.lease.release()
  })
})

describe('initMoveRotatePanel — view setters', () => {
  it('accepts an entity-neutral protein transform controller', () => {
    const els = mountPanelDom()
    const api = initMoveRotatePanel(makeDeps())
    const controller = { isAttached: () => true, setTransform() {}, commit: vi.fn() }
    api.setProteinController(controller)
    expect(api.getProteinController()).toBe(controller)
    els['mr-apply-btn'].click()
    expect(controller.commit).toHaveBeenCalledOnce()
  })

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

  it('setCurrentSelection renders the target list with an explicit clear action', () => {
    const els = mountPanelDom()
    const deps = makeDeps({ selection: { items: [{ kind: 'base', key: 'h:1:FORWARD' }] } })
    const api = initMoveRotatePanel(deps)
    api.setCurrentSelection(['Base · h:1:FORWARD', 'Strand · s1'])
    expect([...els['mr-current-selection'].querySelectorAll('.mr-selection-item')].map(e => e.textContent))
      .toEqual(['Base · h:1:FORWARD', 'Strand · s1'])
    els['mr-current-selection'].querySelector('.mr-selection-clear').click()
    expect(deps.clearSelection).toHaveBeenCalledOnce()
    api.setCurrentSelection([])
    expect(els['mr-current-selection'].textContent).toBe('Nothing selected')
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

  it('step buttons rotate about the selected local frame', () => {
    const els = mountPanelDom()
    const deps = makeDeps({ assemblyActive: false })
    initMoveRotatePanel(deps)
    els['mr-tx'].value = '0'; els['mr-ty'].value = '0'; els['mr-tz'].value = '0'
    els['mr-rx'].value = '30'; els['mr-ry'].value = '20'; els['mr-rz'].value = '10'
    els['mr-frame-sel'].value = 'local'
    els['mr-rz-inc'].click()

    const [, actual] = deps.clusterGizmo.setTransform.mock.calls.at(-1)
    const qCur = new THREE.Quaternion().setFromEuler(new THREE.Euler(
      THREE.MathUtils.degToRad(30), THREE.MathUtils.degToRad(20), THREE.MathUtils.degToRad(10), 'XYZ'))
    const qStep = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), Math.PI / 4)
    const expected = qCur.multiply(qStep)
    expect(new THREE.Quaternion(...actual).angleTo(expected)).toBeCloseTo(0)
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

  it('frame selector switches both design and assembly gizmos between global and local axes', () => {
    const els = mountPanelDom()
    const deps = makeDeps()
    const api = initMoveRotatePanel(deps)
    els['mr-frame-sel'].value = 'local'
    els['mr-frame-sel'].dispatchEvent(new Event('change'))
    expect(deps.clusterGizmo.setSpace).toHaveBeenLastCalledWith('local')
    expect(deps.instanceGizmo.setSpace).toHaveBeenLastCalledWith('local')
    expect(api.getFrameSpace()).toBe('local')

    els['mr-frame-sel'].value = 'world'
    els['mr-frame-sel'].dispatchEvent(new Event('change'))
    expect(deps.clusterGizmo.setSpace).toHaveBeenLastCalledWith('world')
    expect(deps.instanceGizmo.setSpace).toHaveBeenLastCalledWith('world')
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

})

describe('duplex pivot response ownership', () => {
  function setup() {
    const els = mountPanelDom()
    const deps = makeDeps({ activeClusterId: 'dc1', currentDesign: duplexDesign(), assemblyActive: false, translateRotateActive: true })
    const select = els['mr-pivot-sel']
    const events = vi.spyOn(select, 'addEventListener')
    const panel = initMoveRotatePanel(deps)
    panel.setPivotOptions([], 'dc1')
    const change = events.mock.calls.find(([type]) => type === 'change')[1]
    let pending = { pivot: [8, 0, 0], translation: [9, 0, 0], rotation: [0, 0, 0, 1] }
    const subscribe = deps.store.subscribe, releases = []
    vi.spyOn(deps.store, 'subscribe').mockImplementation(listener => {
      const release = vi.fn(subscribe(listener)); releases.push(release); return release
    })
    deps.clusterGizmo.getPendingTransform = vi.fn(() => pending && structuredClone(pending))
    deps.clusterGizmo.clearPendingTransform.mockImplementation(() => { pending = null })
    return { deps, select, panel, releases, getPending: () => pending, setPending: value => { pending = value },
      choose(value) { select.value = value; return change(new Event('change')) } }
  }
  function deferred() {
    let resolve
    const promise = new Promise(r => { resolve = r })
    return { promise, resolve }
  }
  function untouched(ctx, pending) {
    expect(ctx.getPending()).toEqual(pending)
    expect(ctx.deps.clusterGizmo.attach).not.toHaveBeenCalled()
    expect(ctx.deps.clusterGizmo.clearPendingTransform).not.toHaveBeenCalled()
    expect(ctx.releases.every(release => release.mock.calls.length === 1)).toBe(true)
  }

  it('invalidates an earlier live pivot request when history takes ownership', async () => {
    const ctx = setup(), before = ctx.getPending(), waiting = deferred()
    const response = rotationPointResponse(ctx.deps.store.getState().currentDesign)
    ctx.deps.setClusterRotationPoint.mockReturnValue(waiting.promise)
    const operation = ctx.choose('dup:root:ohD')
    const lease = ctx.panel.bindHistorySession({})
    lease.update({ pivots: [{ id: 'centroid', label: 'History centroid' }], pivot: 'centroid' })
    ctx.deps.store.setState({ currentDesign: response.design })
    waiting.resolve(response); await operation
    untouched(ctx, before)
    expect(ctx.select.value).toBe('centroid')
    lease.release()
  })

  it.each(['null', 'throw', 'missing design', 'missing cluster', 'malformed pose'])(
    'preserves pending/live gizmo and restores prior choice after %s', async failure => {
      const ctx = setup(), before = ctx.getPending(), design = ctx.deps.store.getState().currentDesign
      ctx.panel.setSelectedPivot('dup:root:ohV')
      ctx.deps.setClusterRotationPoint.mockImplementation(async () => {
        if (failure === 'throw') throw new Error('Refused by server')
        if (failure === 'null') return null
        if (failure === 'missing design') return { revision: 2 }
        if (failure === 'missing cluster') return { design: { ...design, cluster_transforms: [] } }
        const response = rotationPointResponse(design)
        response.design.cluster_transforms[0].pivot = [NaN, 0, 0]
        return response
      })
      await expect(ctx.choose('dup:root:ohD')).resolves.toBeUndefined()
      untouched(ctx, before)
      expect(ctx.select.value).toBe('dup:root:ohV')
      expect(ctx.deps.store.getState().currentDesign).toBe(design)
      expect(showToast).toHaveBeenCalledWith(expect.any(String), expect.objectContaining({ severity: 'warning' }))
    },
  )

  it.each(['document', 'selection', 'tool'])(
    'does not revive an old request after leaving and returning to the same %s', async changed => {
      const ctx = setup(), before = ctx.getPending(), old = ctx.deps.store.getState().currentDesign
      const waiting = deferred(), response = rotationPointResponse(old)
      ctx.deps.setClusterRotationPoint.mockReturnValue(waiting.promise)
      const operation = ctx.choose('dup:root:ohD')
      if (changed === 'document') ctx.deps.store.setState({ currentDesign: { ...old, id: 'other' } })
      if (changed === 'selection') ctx.deps.store.setState({ activeClusterId: 'other' })
      if (changed === 'tool') ctx.deps.store.setState({ translateRotateActive: false })
      ctx.deps.store.setState({ activeClusterId: 'dc1', currentDesign: response.design, translateRotateActive: true })
      ctx.panel.setSelectedPivot('centroid')
      waiting.resolve(response); await operation
      untouched(ctx, before)
      expect(ctx.select.value).toBe('centroid')
    },
  )

  it.each(['document', 'selection', 'assembly', 'inactive gizmo'])(
    'ignores a late successful pivot after changing %s', async changed => {
      const ctx = setup(), before = ctx.getPending(), old = ctx.deps.store.getState().currentDesign
      const waiting = deferred()
      ctx.deps.setClusterRotationPoint.mockReturnValue(waiting.promise)
      const operation = ctx.choose('dup:root:ohD')
      if (changed === 'document') ctx.deps.store.setState({ currentDesign: { ...duplexDesign(), id: 'other-design' } })
      if (changed === 'selection') ctx.deps.store.setState({ activeClusterId: 'other-cluster' })
      if (changed === 'assembly') ctx.deps.store.setState({ assemblyActive: true })
      if (changed === 'inactive gizmo') ctx.deps.clusterGizmo.isActive.mockReturnValue(false)
      ctx.panel.setSelectedPivot('centroid')
      waiting.resolve(rotationPointResponse(old))
      await operation
      untouched(ctx, before)
      expect(ctx.select.value).toBe('centroid')
    },
  )

  it.each(['translation', 'rotation', 'pivot'])(
    'does not adopt an older same-document response whose %s no longer matches', async field => {
      const ctx = setup(), before = ctx.getPending(), old = ctx.deps.store.getState().currentDesign
      const response = rotationPointResponse(old)
      const current = structuredClone(response.design)
      current.cluster_transforms[0][field][0] += 1
      ctx.deps.setClusterRotationPoint.mockImplementation(async () => {
        ctx.deps.store.setState({ currentDesign: current })
        ctx.panel.setSelectedPivot('centroid')
        return response // Shared client returns stale responses without adopting them.
      })
      await ctx.choose('dup:root:ohD')
      untouched(ctx, before)
      expect(ctx.select.value).toBe('centroid')
      expect(ctx.deps.store.getState().currentDesign).toBe(current)
    },
  )

  it('does not discard a newer local drag queued while the pivot request was pending', async () => {
    const ctx = setup(), response = rotationPointResponse(ctx.deps.store.getState().currentDesign)
    const waiting = deferred()
    ctx.deps.setClusterRotationPoint.mockReturnValue(waiting.promise)
    const operation = ctx.choose('dup:root:ohD')
    const newPending = { pivot: [2, 3, 4], translation: [20, 0, 0], rotation: [0, 0, 0, 1] }
    ctx.setPending(newPending)
    ctx.deps.store.setState({ currentDesign: response.design })
    ctx.panel.setSelectedPivot('centroid')
    waiting.resolve(response); await operation
    untouched(ctx, newPending)
    expect(ctx.select.value).toBe('centroid')
  })

  it('only the latest pivot request can reattach even if both replies have the same absolute pose', async () => {
    const ctx = setup(), first = deferred(), second = deferred()
    const response = rotationPointResponse(ctx.deps.store.getState().currentDesign)
    ctx.deps.setClusterRotationPoint.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)
    const one = ctx.choose('dup:root:ohD'), two = ctx.choose('dup:root:ohV')
    ctx.deps.store.setState({ currentDesign: response.design })
    second.resolve(response); await two
    first.resolve(structuredClone(response)); await one
    expect(ctx.getPending()).toBeNull()
    expect(ctx.deps.clusterGizmo.attach).toHaveBeenCalledExactlyOnceWith('dc1', ctx.deps.scene, ctx.deps.camera, ctx.deps.canvas)
    expect(ctx.select.value).toBe('dup:root:ohV')
  })

  it('accepts matching absolute pose after harmless metadata adoption and holds the requested option after reattach', async () => {
    const ctx = setup(), response = rotationPointResponse(ctx.deps.store.getState().currentDesign)
    ctx.deps.setClusterRotationPoint.mockImplementation(async () => {
      ctx.deps.store.setState({ currentDesign: { ...response.design, name: 'New metadata' } })
      return response
    })
    ctx.deps.clusterGizmo.attach.mockImplementation(() => ctx.panel.setSelectedPivot('centroid'))
    await ctx.choose('dup:root:ohD')
    expect(ctx.getPending()).toBeNull()
    expect(ctx.deps.clusterGizmo.attach).toHaveBeenCalledExactlyOnceWith('dc1', ctx.deps.scene, ctx.deps.camera, ctx.deps.canvas)
    expect(ctx.select.value).toBe('dup:root:ohD')
    expect(showToast).not.toHaveBeenCalled()
    expect(ctx.releases[0]).toHaveBeenCalledOnce()
  })
})

describe('moveRotateSelectionLabels', () => {
  it('describes base selections without substituting their containing cluster', () => {
    expect(moveRotateSelectionLabels({ selection: { items: [{ kind: 'base', key: '__xb__:xo1:0' }] } }))
      .toEqual(['Base · __xb__:xo1:0'])
  })

  it('uses the selected cluster name only when the cluster itself is selected', () => {
    expect(moveRotateSelectionLabels({
      currentDesign: { cluster_transforms: [{ id: 'c1', name: 'Arm' }] },
      selection: { items: [{ kind: 'cluster', id: 'c1' }] },
    })).toEqual(['Cluster · Arm'])
  })
})
