import { afterEach, expect, it, vi } from 'vitest'
import * as THREE from 'three'
import { createMockStore } from '../test-helpers/mock_store.js'
import { initSweepPanel } from './sweep_panel.js'

let panel
const el = name => document.getElementById(`sweep-${name}`)
const field = label => document.querySelector(`[aria-label="${label}"]`)
const flush = async () => { await Promise.resolve(); await Promise.resolve() }
function change(node, value, event = 'change') {
  node.value = String(value)
  node.dispatchEvent(new Event(event, { bubbles: true }))
}
const inputs = () => ({ sweep_id: '9fb39673-88f1-40a1-8134-f5ed4214118f', _proof_version: 1,
  cells: [[0, 0]], points_nm: [[0, 0, 0], [0, 0, 10]], orientations_deg: [null, null],
  plane: 'XY', strand_filter: 'both', ligate_adjacent: true,
  source_helix_id: null, source_end: 'end', detach_source: false })
const metadata = params => ({ revision: 7, length_nm: 10, length_bp: 31, total_new_bp: 31,
  path_nm: params.points_nm, points_nm: params.points_nm,
  source_detached: !!params.detach_source, feasibility: { status: 'ok' } })

function setup({ enabled = true, initialReady = true, heldPrepare = false, params = {} } = {}) {
  document.body.innerHTML = '<button id="menu-tools-sweep"></button>'
  vi.useFakeTimers()
  const entry = { id: 'sweep-row', feature_type: 'snapshot', op_kind: 'sweep', label: 'Sweep',
    evicted: true, params: { ...inputs(), ...params } }
  const live = { id: 'part', lattice_type: 'SQUARE', feature_log: [entry], feature_log_cursor: -1,
    helices: [{ id: 'later-only', grid_pos: [8, 8], length_bp: 31,
      axis_start: { x: 0, y: 0, z: 0 }, axis_end: { x: 0, y: 0, z: 10 } }] }
  const store = createMockStore({ currentDesign: live, currentHelixAxes: {}, currentPlane: 'XY' })
  const sourceHelix = { id: 'prefix-h', label: 'Original source', grid_pos: [1, 2], length_bp: 21,
    bp_start: 0, lattice_frame_id: 'prefix-frame',
    axis_start: { x: 0, y: 0, z: 0 }, axis_end: { x: 10, y: 0, z: 0 } }
  const prefix = { id: 'part', lattice_type: 'SQUARE', helices: [sourceHelix],
    lattice_frames: [{ id: 'prefix-frame', plane: 'YZ' }] }
  const axes = { 'prefix-h': { samples: [[0, 0, 0], [5, 0, 0], [10, 0, 0]] } }
  let selected, view, finishOpening, opened = false, currentPicker = true
  const slicePlane = { show: vi.fn(), showDeformed: vi.fn(), hide: vi.fn(),
    setPreviewEnabled: vi.fn(), isPreviewEnabled: () => true, setExtrudeUiOpen: vi.fn(),
    setSelectedCells: vi.fn(), subscribeSelection: callback => { selected = callback; return vi.fn() } }
  const api = { previewSweep: vi.fn(async request => metadata(request)),
    createSweep: vi.fn(async () => ({})), editFeature: vi.fn(async () => ({})),
    currentRevisionWatermark: () => 7 }
  const status = extra => view.setStatus({ busy: false, expired: false, error: null,
    publicationUnknown: false, refreshNeeded: false, ...extra })
  const onChange = vi.fn(async patch => {
    view.updatePreview(metadata(patch)); status()
    return {}
  })
  const onApply = vi.fn(async () => { opened = false; view.close(); return true })
  const onCancel = vi.fn(async () => { opened = false; view.close(); return true })
  const owner = { open: vi.fn(async () => {
    opened = true
    if (heldPrepare) return new Promise(resolve => { finishOpening = resolve })
    view.open(structuredClone(entry.params), { design: prefix, helixAxes: axes, displayLayer: 31,
      onChange, onApply, onCancel, isPickerCurrent: () => currentPicker })
    if (initialReady) { view.updatePreview(metadata(entry.params)); status() }
    else status({ busy: true })
    return true
  }), cancel: vi.fn(() => onCancel()), active: () => opened, dispose: vi.fn() }
  const factory = vi.fn(options => { view = options.view; return owner })
  const scene = new THREE.Scene()
  panel = initSweepPanel({ store, api, slicePlane, scene,
    extrudePanel: { hide: vi.fn() }, getDocId: () => 'document',
    historyEnabled: enabled, createHistoryEditor: factory })
  return { store, live, entry, api, owner, factory, prefix, slicePlane, scene, onChange, onApply, onCancel,
    select: cells => selected(cells), status,
    takeoverPicker: () => { currentPicker = false },
    finishOpening: value => finishOpening(value),
    ready: () => { view.updatePreview(metadata(entry.params)); status() } }
}

afterEach(() => {
  panel?.dispose(); panel = null
  vi.useRealTimers(); document.body.innerHTML = ''; vi.restoreAllMocks()
})

it('opens evicted native inputs privately and keeps Apply disabled until evaluated display is ready', async () => {
  const { entry, owner, api, store, live, ready } = setup({ initialReady: false })
  await panel.edit(entry, 0); await flush()
  expect(owner.open).toHaveBeenCalledWith(entry)
  expect(panel.isActive()).toBe(true)
  expect(el('apply').disabled).toBe(true)
  expect(api.previewSweep).not.toHaveBeenCalled()
  expect(api.editFeature).not.toHaveBeenCalled()
  expect(store.getState().currentDesign).toBe(live)
  ready()
  expect(el('apply').disabled).toBe(false)
})

it('uses prefix source inventory instead of later materialized helices', async () => {
  const { entry, onChange, api } = setup()
  await panel.edit(entry, 0); await flush()
  el('cancel').click() // Previous: retain this private draft while changing inputs.
  expect(el('plane').disabled).toBe(false)
  expect(el('source').disabled).toBe(false)
  const options = [...el('source').options]
  expect(options.some(option => option.textContent.includes('Original source'))).toBe(true)
  expect(options.some(option => option.textContent.includes('8, 8'))).toBe(false)
  change(el('source'), options.find(option => option.textContent.includes('Original source') && option.textContent.includes('start')).value)
  await vi.advanceTimersByTimeAsync(130)
  expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ source_helix_id: 'prefix-h',
    source_end: 'start', plane: 'YZ', cells: [[1, 2]] }), expect.any(Object))
  expect(api.previewSweep).not.toHaveBeenCalled()
  expect(api.editFeature).not.toHaveBeenCalled()
})

it('edits plane, footprint, strands, ligation, path and orientation through the same owned draft', async () => {
  const { entry, select, onChange, onApply, api, store, live } = setup()
  const original = structuredClone(entry)
  await panel.edit(entry, 0); await flush()
  el('cancel').click()
  change(el('plane'), 'XZ'); select([[2, 3], [2, 4]])
  change(el('strands'), 'staples'); el('ligate').click()
  await vi.advanceTimersByTimeAsync(130)
  el('apply').click() // Next, not publication.
  change(field('Point Z (nm)'), 17, 'input')
  field('Control point orientation').click()
  change(field('Tilt X (degrees)'), 12)
  change(field('Twist (degrees)'), -30)
  await vi.advanceTimersByTimeAsync(130)
  const [patch] = onChange.mock.calls.at(-1)
  expect(patch).toMatchObject({ cells: [[2, 3], [2, 4]], plane: 'XZ', strand_filter: 'staples',
    ligate_adjacent: false, source_helix_id: null, source_end: 'end' })
  expect(patch.points_nm[1][2]).toBe(17)
  expect(patch.orientations_deg).toEqual([null, [12, 0, -30]])
  for (const key of ['sweep_id', '_proof_version', 'expected_design_id', 'expected_revision']) expect(patch).not.toHaveProperty(key)
  expect(onApply).not.toHaveBeenCalled()
  expect(api.previewSweep).not.toHaveBeenCalled()
  expect(api.editFeature).not.toHaveBeenCalled()
  expect(store.getState().currentDesign).toBe(live)
  expect(entry).toEqual(original)
  el('apply').click(); await flush()
  expect(onApply).toHaveBeenCalledTimes(1)
  expect(panel.isActive()).toBe(false)
})

it('moving an attached origin submits native detach intent without reconnecting when moved back', async () => {
  const { entry, onChange, api } = setup({ params: { source_helix_id: 'prefix-h', source_end: 'end', plane: 'YZ' } })
  await panel.edit(entry, 0); await flush()
  document.querySelector('[role="option"]').click()
  change(field('Point X (nm)'), 2, 'input')
  await vi.advanceTimersByTimeAsync(130)
  expect(onChange.mock.calls.at(-1)[0]).toMatchObject({ detach_source: true, source_helix_id: 'prefix-h' })
  change(field('Point X (nm)'), 0, 'input')
  await vi.advanceTimersByTimeAsync(130)
  expect(onChange.mock.calls.at(-1)[0].detach_source).toBe(true)
  expect(api.previewSweep).not.toHaveBeenCalled()
})

it.each(['refused', 'error'])('keeps the owned dialog and draft after %s Apply', async mode => {
  const { entry, onApply, status, api } = setup()
  await panel.edit(entry, 0); await flush()
  change(field('Point Z (nm)'), 19, 'input')
  await vi.advanceTimersByTimeAsync(130)
  onApply.mockImplementationOnce(async () => {
    if (mode === 'error') throw new Error('Downstream reference failed')
    status({ error: new Error('Downstream reference failed') }); return null
  })
  el('apply').click(); await flush()
  expect(panel.isActive()).toBe(true)
  expect(field('Point Z (nm)').value).toBe('19')
  expect(el('status').textContent).toMatch(/Downstream reference failed/)
  expect(api.editFeature).not.toHaveBeenCalled()
})

it('keeps an unknown publication under the owner instead of clearing it on Cancel', async () => {
  const { entry, owner, onCancel, status, api } = setup()
  await panel.edit(entry, 0); await flush()
  status({ publicationUnknown: true, error: new Error('Publication status unknown') })
  onCancel.mockResolvedValueOnce(false)
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
  await flush()
  expect(owner.cancel).toHaveBeenCalledTimes(1)
  expect(panel.isActive()).toBe(true)
  expect(api.editFeature).not.toHaveBeenCalled()
})

it('does not turn unknown publication recovery into a new footprint draft via Previous', async () => {
  const { entry, owner, onCancel, onChange, status } = setup()
  await panel.edit(entry, 0); await flush()
  status({ publicationUnknown: true, error: new Error('Publication status unknown') })
  onCancel.mockResolvedValueOnce(false)
  el('cancel').click(); await vi.advanceTimersByTimeAsync(130)
  expect(owner.cancel).toHaveBeenCalledTimes(1)
  expect(el('step').textContent).toContain('2/2')
  expect(el('apply').textContent).toBe('Check result')
  expect(el('apply').disabled).toBe(false)
  expect(onChange).not.toHaveBeenCalled()
  expect(panel.isActive()).toBe(true)
})

it.each(['Escape', 'other tool'])('cancels held Prepare from %s before the private view opens', async action => {
  const { entry, owner, api, store, live, finishOpening } = setup({ heldPrepare: true })
  const pending = panel.edit(entry, 0)
  expect(panel.isActive()).toBe(true)
  expect(el('path').hidden).toBe(true)
  if (action === 'Escape') window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
  else {
    const button = document.createElement('button')
    button.id = 'menu-tools-extrude'; document.body.append(button); button.click()
  }
  await flush()
  expect(owner.cancel).toHaveBeenCalledTimes(1)
  expect(panel.isActive()).toBe(false)
  expect(api.previewSweep).not.toHaveBeenCalled()
  expect(api.editFeature).not.toHaveBeenCalled()
  expect(store.getState().currentDesign).toBe(live)
  // The app-owner suite separately verifies late real Prepare packet rejection;
  // this integration test checks that the unopened panel reaches that owner.
  finishOpening(false); expect(await pending).toBe(false)
})

it('closes only its local view after a newer picker takes ownership', async () => {
  const { entry, owner, slicePlane, store, live, scene, takeoverPicker } = setup()
  await panel.edit(entry, 0); await flush()
  expect(scene.getObjectByName('sweep-control-points').children.length).toBeGreaterThan(0)
  takeoverPicker()
  slicePlane.hide.mockClear()
  slicePlane.setPreviewEnabled.mockClear()
  slicePlane.setExtrudeUiOpen.mockClear()
  expect(await owner.cancel()).toBe(true)
  expect(panel.isActive()).toBe(false)
  expect(document.getElementById('sweep-panel').style.display).toBe('none')
  expect(scene.getObjectByName('sweep-control-points').children).toHaveLength(0)
  expect(store.getState().sweepActive).toBe(false)
  expect(store.getState().currentDesign).toBe(live)
  expect(slicePlane.hide).not.toHaveBeenCalled()
  expect(slicePlane.setPreviewEnabled).not.toHaveBeenCalled()
  expect(slicePlane.setExtrudeUiOpen).not.toHaveBeenCalled()
})

it('leaves the existing legacy editor path intact when history rollout is disabled', async () => {
  const { entry, factory, api } = setup({ enabled: false })
  await panel.edit(entry, 0)
  await vi.advanceTimersByTimeAsync(130)
  expect(factory).not.toHaveBeenCalled()
  expect(api.previewSweep).toHaveBeenCalledWith(expect.objectContaining({ sweep_id: entry.params.sweep_id }), 0)
  el('apply').click(); await flush()
  expect(api.editFeature).toHaveBeenCalledWith(0, expect.objectContaining({ sweep_id: entry.params.sweep_id }))
})
