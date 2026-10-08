import { describe, expect, it } from 'vitest'
import { circularPatternTarget, normalizedAxis } from './circular_pattern_panel.js'

const state = () => ({
  currentDesign: { cluster_transforms: [{ id: 'c', helix_ids: [1] }] },
  selection: { items: [{ kind: 'cluster', id: 'c' }] },
  currentGeometry: [
    { helix_id: 1, backbone_position: [10, 2, 0] },
    { helix_id: 1, backbone_position: [14, 4, 0] },
    { helix_id: 2, backbone_position: [100, 100, 100] },
  ],
})
describe('circular pattern target', () => {
  it('centers only selected cluster members without mutating geometry', () => {
    const s = state(), before = JSON.stringify(s)
    expect(circularPatternTarget(s)).toMatchObject({ center: [12, 3, 0], points: [[-2, -1, 0], [2, 1, 0]] })
    expect(JSON.stringify(s)).toBe(before)
  })
  it('rejects assemblies, mixed selections, multiple clusters, and missing geometry', () => {
    expect(circularPatternTarget({ ...state(), assemblyActive: true })).toBeNull()
    expect(circularPatternTarget({ ...state(), currentGeometry: [] })).toBeNull()
    for (const ref of [{ kind: 'strand', id: 's' }, { kind: 'cluster', id: 'd' }]) {
      const s = state(); s.selection.items.push(ref)
      expect(circularPatternTarget(s)).toBeNull()
    }
  })
  it('allows the existing active-cluster selection path', () => {
    expect(circularPatternTarget({ ...state(), selection: { items: [] }, activeClusterId: 'c' })).not.toBeNull()
  })
})
it('normalizes arbitrary directions and rejects degenerate axes', () => {
  expect(normalizedAxis([2, 3, 4], [0, 3, 4])).toEqual({ point: [2, 3, 4], direction: [0, 0.6, 0.8] })
  expect(normalizedAxis([0, 0, 0], [0, 0, 0])).toBeNull()
  expect(normalizedAxis([NaN, 0, 0], [0, 0, 1])).toBeNull()
})

import { vi } from 'vitest'
import { beginCircularPatternSelection } from './circular_pattern_panel.js'
import { createMockStore } from '../test-helpers/mock_store.js'
import { createSelectionController } from '../scene/selection_controller.js'

function pickerFixture() {
  const store = createMockStore({ ...state(), selectableTypes: { scaffold: false, overhangs: true } })
  const controller = createSelectionController({ store })
  const selectionManager = { clearSelection: controller.clear, setSelectionLevel: controller.setLevel }
  const onSelected = vi.fn(), onCancelled = vi.fn()
  const session = beginCircularPatternSelection({ store, selectionManager, onSelected, onCancelled })
  return { store, controller, session, onSelected, onCancelled }
}
it('arms cluster picking, then returns to default once after a fresh valid selection', async () => {
  const { store, controller, onSelected } = pickerFixture()
  expect(store.getState().selection.level).toBe('cluster')
  expect(store.getState().selection.items).toEqual([])
  expect(store.getState().selectableTypes.overhangs).toBe(false)
  controller.replace([{ kind: 'cluster', id: 'c' }])
  await Promise.resolve()
  expect(store.getState().selection.level).toBe('default')
  expect(store.getState().selection.items).toEqual([])
  expect(onSelected.mock.calls[0][0].cluster.id).toBe('c')
  expect(onSelected).toHaveBeenCalledOnce()
  controller.clear()
  await Promise.resolve()
  expect(onSelected).toHaveBeenCalledOnce()
})
it('cancels a queued pick without opening and restores the default level', async () => {
  const { store, controller, session, onSelected } = pickerFixture()
  controller.replace([{ kind: 'cluster', id: 'c' }])
  session.cancel()
  await Promise.resolve()
  expect(store.getState().selection.level).toBe('default')
  expect(onSelected).not.toHaveBeenCalled()
  expect(store.getState().selectableTypes.overhangs).toBe(true)
})
it('abandons picking on a document/context change and ignores non-cluster selections', async () => {
  const { store, controller, onSelected, onCancelled } = pickerFixture()
  controller.replace([{ kind: 'strand', id: 's' }])
  await Promise.resolve()
  expect(onSelected).not.toHaveBeenCalled()
  store.setState({ assemblyActive: true })
  await Promise.resolve()
  expect(onCancelled).toHaveBeenCalledOnce()
  expect(store.getState().selection.level).toBe('default')
})

import * as THREE from 'three'
import { initCircularPatternPanel, circularPatternCluster, circularPatternBPTotals } from './circular_pattern_panel.js'
it('resolves dropdown clusters independently of selection', () => {
  expect(circularPatternCluster(state(), 'c').center).toEqual([12, 3, 0])
  expect(circularPatternCluster(state(), 'missing')).toBeNull()
})
it('previews in the part scene, switches clusters and centers about a second cluster, then cleans up', async () => {
  document.body.innerHTML = '<canvas id="canvas"></canvas><div id="circular-pattern-panel"></div>'
  const initial = state()
  initial.currentDesign.cluster_transforms.push({ id: 'd', helix_ids: [2] })
  const store = createMockStore(initial), controller = createSelectionController({ store })
  const scene = new THREE.Scene(), frames = new Set()
  const tool = initCircularPatternPanel({ store, scene, canvas: document.getElementById('canvas'),
    selectionManager: { clearSelection: controller.clear, setSelectionLevel: controller.setLevel },
    getCamera: () => new THREE.PerspectiveCamera(), getControls: () => ({ enabled: true }),
    addFrameCallback: fn => frames.add(fn), removeFrameCallback: fn => frames.delete(fn), showToast: vi.fn() })
  tool.open(); controller.replace([{ kind: 'cluster', id: 'c' }]); await Promise.resolve()
  const preview = scene.getObjectByName('circularPatternPreview')
  expect(preview.position.toArray()).toEqual([12, 3, 0])
  expect(preview.userData.instances).toBe(6)
  expect(document.querySelector('#circular-pattern-panel canvas')).toBeNull()
  expect(document.querySelector('[aria-label="Cluster"]').value).toBe('c')
  expect([...document.querySelectorAll('.tool-section > legend')].map(node => node.textContent)).toEqual(['Cluster', 'Direction', 'Origin', 'Pattern', 'Info'])
  const centered = [...document.querySelectorAll('button')].find(b => b.textContent === 'Centered about')
  centered.click()
  centered.click() // active mode cannot be deselected
  expect(centered.getAttribute('aria-pressed')).toBe('true')
  expect(document.querySelector('[aria-label="Origin offset (nm) X"]').closest('fieldset').hidden).toBe(true)
  expect(document.querySelector('.cp-snap').hidden).toBe(true)
  expect(preview.userData.axisPoint).toEqual([88, 97, 100])
  expect(preview.userData.centerClusterId).toBe('d')
  const source = document.querySelector('[aria-label="Cluster"]')
  source.value = 'd'; source.dispatchEvent(new Event('change'))
  expect(preview.position.toArray()).toEqual([100, 100, 100])
  expect(preview.userData.axisPoint).toEqual([-88, -97, -100])
  const x = [...document.querySelectorAll('button')].find(b => b.textContent === 'X')
  x.click()
  expect(x.closest('.tool-section').querySelectorAll('[aria-pressed="true"]')).toHaveLength(1)
  expect(x.getAttribute('aria-pressed')).toBe('true')
  controller.clear()
  expect(tool.isActive()).toBe(true)
  tool.close()
  expect(scene.children).toHaveLength(0)
  expect(frames.size).toBe(0)
  expect(document.querySelector('.cp-bead')).toBeNull()
  document.body.innerHTML = ''
})

it('counts new BP separately from whole-part totals, including the original once', () => {
  const design = { helices: [{ id: 'a', length_bp: 42 }, { id: 'b', length_bp: 35 }] }
  expect(circularPatternBPTotals(design, { helix_ids: ['a'] }, 4)).toEqual({ created: 126, total: 203 })
  expect(circularPatternBPTotals(design, { helix_ids: ['a'] }, 1)).toEqual({ created: 0, total: 77 })
  expect(circularPatternBPTotals(design, { helix_ids: ['a'] }, 2.5)).toBeNull()
})

it('rounds offset entry, restores offset mode, and confirms only once', async () => {
  document.body.innerHTML = '<canvas id="canvas"></canvas><div id="circular-pattern-panel"></div>'
  const initial = state()
  initial.currentDesign.cluster_transforms.push({ id: 'd', helix_ids: [2] })
  const store = createMockStore(initial), controller = createSelectionController({ store })
  let resolve
  const commitPattern = vi.fn(() => new Promise(done => { resolve = done }))
  const tool = initCircularPatternPanel({ store, scene: new THREE.Scene(), canvas: document.getElementById('canvas'),
    selectionManager: { clearSelection: controller.clear, setSelectionLevel: controller.setLevel },
    getCamera: () => new THREE.PerspectiveCamera(), getControls: () => ({ enabled: true }),
    addFrameCallback() {}, removeFrameCallback() {}, showToast: vi.fn(), commitPattern })
  tool.open(); controller.replace([{ kind: 'cluster', id: 'c' }]); await Promise.resolve()
  const button = name => [...document.querySelectorAll('button')].find(b => b.textContent === name)
  const input = document.querySelector('[aria-label="Origin offset (nm) X"]')
  input.value = '1.234567'; input.dispatchEvent(new Event('input'))
  expect(input.value).toBe('1.235')
  button('Centered about').click()
  expect(input.closest('fieldset').hidden).toBe(true)
  button('Offset').click()
  expect(input.value).toBe('1.235')
  expect(input.closest('fieldset').hidden).toBe(false)
  expect(document.querySelector('[aria-label="Center cluster"]').parentElement.hidden).toBe(true)
  button('Confirm').click()
  expect(commitPattern).toHaveBeenCalledOnce()
  expect(commitPattern.mock.calls[0][0].axis_point[0]).toBeCloseTo(13.235)
  expect(button('Cancel').disabled).toBe(true)
  tool.close(); expect(tool.isActive()).toBe(true)
  resolve(); await Promise.resolve(); await Promise.resolve()
  expect(tool.isActive()).toBe(false)
  document.body.innerHTML = ''
})
