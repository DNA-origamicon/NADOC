import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import * as THREE from 'three'
import { groupDesign } from '../test-helpers/part_groups.js'
import { createSelectionController } from './selection_controller.js'
import { createSelectionState } from './selection_model.js'
import { isSelectionRefLive } from './selection_ref.js'

const held = vi.hoisted(() => ({ state: null, listeners: [] }))
vi.mock('../state/store.js', () => ({ pushGroupUndo: vi.fn(), store: {
  getState: () => held.state,
  setState: patch => { const before = held.state; held.state = { ...before, ...patch }; held.listeners.forEach(fn => fn(held.state, before)) },
  subscribe: fn => { held.listeners.push(fn); return () => { held.listeners = held.listeners.filter(x => x !== fn) } },
} }))
vi.mock('../api/client.js', () => ({ groupOrganizationCommand: vi.fn(),
  captureExtensionContext: vi.fn(() => ({ source: held.state.currentDesign })),
}))
vi.mock('./ssdna_fjc.js', () => ({ ensureLoaded: async () => {} }))
vi.mock('../ui/cpd_conversion.js', () => ({ showCpdConversion: vi.fn() }))
vi.mock('./deformation_editor.js', () => ({
  getVRDeformationPlaneFrames: vi.fn(), nearestVRDeformationPlane: vi.fn(), extremeVRDeformationPlane: vi.fn(),
}))
import { store } from '../state/store.js'
import { groupOrganizationCommand } from '../api/client.js'
import { initSelectionManager } from './selection_manager.js'

let listeners, addListener
beforeEach(() => {
  held.listeners = []; held.state = { currentDesign: groupDesign(), selection: createSelectionState(),
    selectableTypes: { scaffold: true, staples: true, strands: true }, strandGroups: [] }
  listeners = []; const original = window.addEventListener.bind(window)
  addListener = vi.spyOn(window, 'addEventListener').mockImplementation((...args) => { listeners.push(args); original(...args) })
})
afterEach(() => {
  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
  for (const args of listeners) window.removeEventListener(...args)
  addListener.mockRestore(); held.listeners = []; document.body.innerHTML = ''; vi.useRealTimers()
})
function setup() {
  const canvas = document.createElement('canvas'); document.body.append(canvas)
  canvas.getBoundingClientRect = () => ({ left: 0, top: 0, width: 500, height: 500 })
  const camera = new THREE.PerspectiveCamera(60, 1, .1, 100); camera.position.z = 10; camera.updateMatrixWorld()
  const mesh = new THREE.InstancedMesh(new THREE.SphereGeometry(.1), new THREE.MeshBasicMaterial(), 2)
  mesh.setMatrixAt(0, new THREE.Matrix4().makeTranslation(-1, 0, 0))
  mesh.setMatrixAt(1, new THREE.Matrix4().makeTranslation(1, 0, 0)); mesh.updateMatrixWorld()
  const entries = [0, 1].map(i => ({ id: i, instMesh: mesh, pos: new THREE.Vector3(i ? 1 : -1, 0, 0), nuc: {
    helix_id: 'h', strand_id: 's', domain_index: i, bp_index: i ? 25 : 14, direction: 'FORWARD', strand_type: 'scaffold',
  } }))
  held.state.currentGeometry = entries.map(e => e.nuc)
  const renderer = new Proxy({ getBackboneEntries: () => entries, getHelixCtrl: () => ({ root: { visible: true } }),
    isColumnAtomistic: () => false,
    getCylinderMesh: () => null, setClusterSelectionGroups: vi.fn(), setPreviewGlow: vi.fn(),
  }, { get(target, key) { return target[key] ??= vi.fn(() => []) } })
  const controller = createSelectionController({ store })
  const manager = initSelectionManager(canvas, camera, renderer, { selectionController: controller,
    getAtomisticRenderer: () => ({ getMode: () => 'off' }),
    getRegionVdwRenderer: () => ({ getMode: () => 'off' }),
    getRegionBallstickRenderer: () => ({ getMode: () => 'off' }),
    getRegionStickRenderer: () => ({ getMode: () => 'off' }) })
  return { manager, controller, renderer, entries, canvas,
    dispose: () => { mesh.geometry.dispose(); mesh.material.dispose() } }
}
it('paints equal-ID group and placement selections separately and keeps them live after rebuild', () => {
  const d = setup()
  try {
    expect(d.manager.selectPartGroup('same')).toBe(true)
    expect(d.renderer.setClusterSelectionGroups).toHaveBeenLastCalledWith([[d.entries[1]]])
    d.manager.toggleCluster('same')
    expect(d.controller.getState().items).toEqual([{ kind: 'part_group', id: 'same' }, { kind: 'cluster', id: 'same' }])
    expect(d.renderer.setClusterSelectionGroups).toHaveBeenLastCalledWith([d.entries, [d.entries[1]]])
    const next = structuredClone(held.state.currentDesign); next.group_organization.groups = []
    store.setState({ currentDesign: next })
    d.controller.reconcile(ref => isSelectionRefLive(ref, next))
    expect(d.controller.getState().items).toEqual([{ kind: 'cluster', id: 'same' }])
    expect(d.manager.selectPartGroup('same')).toBe(false)
  } finally { d.dispose() }
})
it('permits explicit empty group selection without highlighting its equal-ID placement', () => {
  const d = setup()
  try {
    expect(d.manager.selectPartGroup('empty')).toBe(true)
    expect(d.renderer.setClusterSelectionGroups).toHaveBeenLastCalledWith([[]])
    d.manager.selectPartGroup('empty'); expect(d.controller.getState().items).toEqual([])
  } finally { d.dispose() }
})
it('restores group picking after a document/context change without changing explicit placement selectors', () => {
  const d = setup()
  try {
    expect(d.manager.getGroupPickMode()).toBe('groups')
    d.manager.setGroupPickMode('placements'); expect(d.manager.getGroupPickMode()).toBe('placements')
    d.manager.selectCluster('same'); expect(d.controller.getState().primary).toEqual({ kind: 'cluster', id: 'same' })
    store.setState({ currentDesign: { ...held.state.currentDesign, id: 'other' } })
    expect(d.manager.getGroupPickMode()).toBe('groups')
    expect(() => d.manager.setGroupPickMode('guess')).toThrow()
  } finally { d.dispose() }
})
it('resets explicit placement picking on a same-ID document reload', () => {
  const d = setup()
  try {
    d.manager.setGroupPickMode('placements')
    const source = held.state.currentDesign
    window.dispatchEvent(new CustomEvent('nadoc:document-reset'))
    expect(held.state.currentDesign).toBe(source)
    expect(d.manager.getGroupPickMode()).toBe('groups')
    expect(d.controller.getState().items).toEqual([])
  } finally { d.dispose() }
})
it('uses the same group member scope for actual hover and click, with explicit placement mode separate', async () => {
  vi.useFakeTimers()
  const d = setup()
  try {
    d.manager.setSelectionLevel('cluster')
    const pointer = (type, fields = {}) => d.canvas.dispatchEvent(new MouseEvent(type, { bubbles: true, button: 0, clientX: 293, clientY: 250, ...fields }))
    pointer('pointermove'); await vi.runOnlyPendingTimersAsync()
    expect(d.renderer.setPreviewGlow.mock.calls.at(-1)?.[0]).toHaveLength(1)
    pointer('pointerdown'); pointer('pointerup'); await vi.runOnlyPendingTimersAsync()
    expect(d.controller.getState().primary).toEqual({ kind: 'part_group', id: 'same' })
    d.manager.clearSelection(); d.manager.setGroupPickMode('placements')
    pointer('pointermove'); await vi.runOnlyPendingTimersAsync()
    expect(d.renderer.setPreviewGlow.mock.calls.at(-1)?.[0]).toHaveLength(2)
    pointer('pointerdown'); pointer('pointerup'); await vi.runOnlyPendingTimersAsync()
    expect(d.controller.getState().primary).toEqual({ kind: 'cluster', id: 'same' })
  } finally { d.dispose() }
})
it('retains the deferred VR placement contract and restores desktop group resolution after an exception', async () => {
  vi.useFakeTimers()
  const d = setup()
  try {
    d.manager.setSelectionLevel('cluster')
    const identity = 'nuc:s:1:h:25:FORWARD:0'
    expect(d.manager.selectVRIdentity(identity)?.selected).toBe(true)
    expect(d.controller.getState().primary).toEqual({ kind: 'cluster', id: 'same' })
    d.manager.clearSelection()
    d.renderer.setPreviewGlow.mockImplementationOnce(() => { throw new Error('renderer stopped') })
    expect(() => d.manager.previewVRIdentity(identity)).toThrow('renderer stopped')
    expect(d.manager.getGroupPickMode()).toBe('groups')
    d.canvas.dispatchEvent(new MouseEvent('pointermove', { clientX: 293, clientY: 250, buttons: 0 }))
    await vi.runOnlyPendingTimersAsync()
    expect(d.renderer.setPreviewGlow.mock.calls.at(-1)?.[0]).toHaveLength(1)
  } finally { d.dispose() }
})

it.each([true, false])('actual multi-strand menu uses the proper group authoring path (organization=%s)', async organized => {
  vi.useFakeTimers()
  if (!organized) held.state.currentDesign.group_organization = null
  held.state.currentDesign.strands.push({ ...structuredClone(held.state.currentDesign.strands[0]), id: 't' })
  const d = setup()
  try {
    d.controller.replace([{ kind: 'strand', id: 's' }, { kind: 'strand', id: 't' }])
    const before = held.state.currentDesign, selection = d.controller.getState()
    d.canvas.dispatchEvent(new MouseEvent('pointerdown', { button: 2, clientX: 293, clientY: 250 }))
    d.canvas.dispatchEvent(new MouseEvent('contextmenu', { button: 2, buttons: 0, clientX: 293, clientY: 250, cancelable: true }))
    await vi.runOnlyPendingTimersAsync()
    const localNewGroup = [...document.querySelectorAll('option')].some(option => option.textContent === '＋ New group…')
    expect(localNewGroup).toBe(!organized)
    const create = document.querySelector('[data-group-create]')
    expect(!!create).toBe(organized)
    if (organized) {
      groupOrganizationCommand.mockResolvedValueOnce(null)
      create.click(); await Promise.resolve(); await Promise.resolve()
      expect(groupOrganizationCommand).toHaveBeenLastCalledWith('group-create', {
        name: 'Group 4', helix_ids: ['h'], domain_ids: [
          { strand_id: 's', domain_index: 0 }, { strand_id: 's', domain_index: 1 },
          { strand_id: 't', domain_index: 0 }, { strand_id: 't', domain_index: 1 },
        ], color: null, opacity: 1,
      })
      expect(document.querySelector('[data-group-create]')).toBe(create)
      expect(held.state.currentDesign).toBe(before)
      expect(d.controller.getState()).toEqual(selection)
    }
  } finally { d.dispose() }
})

it.each([true, false])('single-strand menu preserves Isolate while routing groups correctly (organization=%s)', async organized => {
  vi.useFakeTimers()
  if (!organized) held.state.currentDesign.group_organization = null
  held.state.currentDesign.strands[0].strand_type = 'staple'
  const d = setup()
  try {
    d.entries.forEach(entry => { entry.nuc.strand_type = 'staple' })
    d.controller.replace([{ kind: 'strand', id: 's' }])
    d.canvas.dispatchEvent(new MouseEvent('pointerdown', { button: 2, clientX: 293, clientY: 250 }))
    d.canvas.dispatchEvent(new MouseEvent('contextmenu', { button: 2, buttons: 0, clientX: 293, clientY: 250, cancelable: true }))
    await vi.runOnlyPendingTimersAsync()
    expect([...document.querySelectorAll('div')].some(node => node.textContent === 'Isolate')).toBe(true)
    expect([...document.querySelectorAll('option')].some(option => option.textContent === '＋ New group…')).toBe(!organized)
    expect(!!document.querySelector('[data-group-create]')).toBe(organized)
  } finally { d.dispose() }
})
