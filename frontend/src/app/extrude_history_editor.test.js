import { afterEach, expect, it, vi } from 'vitest'
import * as THREE from 'three'
import { createExtrudeHistoryEditor, usesExtrudeTool } from './extrude_history_editor.js'

const editors = []
afterEach(() => { for (const editor of editors.splice(0)) editor.dispose() })
function fixture(cursor = -1) {
  const entry = { id: 'extrude', feature_type: 'snapshot', op_kind: 'bundle-create',
    params: { _proof_version: 1, history_seed: 'seed', plane: 'XZ', length_bp: -35,
      cells: [[0, 1], [1, 1]], lattice_type: 'HONEYCOMB', name: 'Original', strand_filter: 'scaffold', ligate_adjacent: false } }
  const log = [entry, { id: 'later' }]
  const state = { revision: 1, currentDesign: { id: 'part', feature_log: log, feature_log_cursor: cursor, helices: [{ id: 'h' }] } }
  const subscribers = new Set()
  const store = { getState: () => state, subscribe: fn => { subscribers.add(fn); return () => subscribers.delete(fn) } }
  const api = {
    captureFeatureEditContext: () => ({ source: state.currentDesign, designId: 'part', docId: 'doc', revision: state.revision }),
    isFeatureEditContextCurrent: context => context.source === state.currentDesign && context.revision === state.revision,
    seekFeatures: vi.fn(async (position, subPosition = null) => {
      state.currentDesign = { ...state.currentDesign, feature_log_cursor: position, feature_log_sub_cursor: subPosition, helices: position === -2 ? [] : [{ id: 'h' }] }
      for (const fn of subscribers) fn()
      return true
    }),
    editNativeExtrusionFeature: vi.fn(async () => {
      state.currentDesign = { ...state.currentDesign, changed: true }
      for (const fn of subscribers) fn()
      return { design: state.currentDesign }
    }),
  }
  let picker, inputs
  const release = Object.assign(vi.fn(), { isCurrent: () => true })
  const slicePlane = {
    usePrivateContext: vi.fn(value => { picker = value; return release }),
    show: vi.fn(), showDeformed: vi.fn(),
    setExtrudeInputs: vi.fn(value => { inputs = value }), getExtrudeInputs: () => ({ cells: inputs.cells, length_bp: inputs.length_bp, strand_filter: inputs.strand_filter, ligate_adjacent: inputs.ligate_adjacent }),
    getPlaneNormalWorld: () => new THREE.Vector3(0, 1, 0),
    getPlaneUpWorld: () => new THREE.Vector3(0, 0, 1), getPlaneCenterWorld: () => new THREE.Vector3(3, 0, 4),
  }
  const panel = { refreshCrossSection: vi.fn(), hide: vi.fn(), activateEdit: vi.fn(), finishEdit: vi.fn() }
  const camera = new THREE.PerspectiveCamera(); camera.position.set(10, 20, 30)
  const controls = { target: new THREE.Vector3(), enableRotate: true, update: vi.fn() }
  const originalPosition = camera.position.clone()
  const setPreviewHelices = vi.fn(), showToast = vi.fn()
  const editor = createExtrudeHistoryEditor({ store, api, slicePlane, panel, getCamera: () => camera,
    getControls: () => controls, setPreviewHelices, showToast })
  editors.push(editor)
  return { editor, entry, state, api, panel, slicePlane, camera, controls, originalPosition, release, setPreviewHelices,
    notify: () => { for (const fn of subscribers) fn() }, picker: () => picker, inputs: () => inputs, externalChange() { state.currentDesign = { id: 'other' }; for (const fn of subscribers) fn() } }
}
it('opens the normal tool at the feature with original cells, signed length and requests shared cross-section framing', async () => {
  const f = fixture()
  expect(await f.editor.open(f.entry, 0)).toBe(true)
  expect(f.api.seekFeatures.mock.calls).toEqual([[-2, null], [0, null]])
  expect(f.state.currentDesign.feature_log_cursor).toBe(0)
  expect(f.picker().design.helices).toEqual([])
  expect(f.inputs()).toEqual(f.entry.params)
  expect(f.setPreviewHelices).toHaveBeenLastCalledWith(['h'])
  expect(f.panel.refreshCrossSection).toHaveBeenCalled()
  expect(f.api.editNativeExtrusionFeature).not.toHaveBeenCalled()
})
it.each([-1, 0])('Cancel restores cursor %s, camera and tool visibility without editing', async cursor => {
  const f = fixture(cursor)
  await f.editor.open(f.entry, 0)
  await f.editor.cancel()
  expect(f.state.currentDesign.feature_log_cursor).toBe(cursor)
  expect(f.camera.position).toEqual(f.originalPosition)
  expect(f.api.editNativeExtrusionFeature).not.toHaveBeenCalled()
  expect(f.panel.finishEdit).toHaveBeenCalled()
  expect(f.release).toHaveBeenCalled()
  expect(f.setPreviewHelices).toHaveBeenLastCalledWith([])
})
it('Apply edits the original row and preserves non-popup inputs', async () => {
  const f = fixture()
  await f.editor.open(f.entry, 0)
  await f.picker().onExtrude({ cells: [[0, 1], [1, 1], [1, 2]], lengthBp: 42,
    plane: 'XZ', strandFilter: 'both', ligateAdjacent: true })
  expect(f.api.editNativeExtrusionFeature).toHaveBeenCalledWith(0, expect.objectContaining({
    history_seed: 'seed', name: 'Original', length_bp: 42, cells: [[0, 1], [1, 1], [1, 2]],
  }), expect.objectContaining({ source: expect.objectContaining({ feature_log_cursor: -1 }) }), 'extrude')
  expect(f.editor.active()).toBe(false)
})
it('keeps a rejected draft at its feature for correction', async () => {
  const f = fixture()
  await f.editor.open(f.entry, 0)
  f.api.editNativeExtrusionFeature.mockRejectedValue(new Error('Downstream route cannot rebuild'))
  await expect(f.picker().onExtrude({ cells: [[0, 1]], lengthBp: 7, plane: 'XZ' })).rejects.toThrow('Downstream')
  expect(f.editor.active()).toBe(true)
  expect(f.state.currentDesign.feature_log_cursor).toBe(0)
  expect(f.inputs().length_bp).toBe(7)
})
it('retires on document change without navigating the replacement document', async () => {
  const f = fixture()
  await f.editor.open(f.entry, 0)
  f.api.seekFeatures.mockClear()
  f.externalChange()
  expect(f.editor.active()).toBe(false)
  expect(f.api.seekFeatures).not.toHaveBeenCalled()
})
it('does not open a future feature or reinterpret a specialized extrusion', async () => {
  const f = fixture(-2)
  expect(await f.editor.open(f.entry, 0)).toBe(false)
  expect(usesExtrudeTool({ ...f.entry, op_kind: 'overhang-extrude' })).toBe(false)
  expect(f.api.seekFeatures).not.toHaveBeenCalled()
})
it('changing the edit plane preserves the current draft cells and signed parameters', async () => {
  const f = fixture()
  await f.editor.open(f.entry, 0)
  f.slicePlane.setExtrudeInputs({ ...f.inputs(), cells: [[2, 3]], length_bp: -49 })
  f.panel.activateEdit.mock.calls[0][0].onPlaneChange('YZ')
  expect(f.inputs()).toMatchObject({ plane: 'YZ', cells: [[2, 3]], length_bp: -49,
    strand_filter: 'scaffold', ligate_adjacent: false })
  expect(f.entry.params.plane).toBe('XZ')
})
it('resolves a derived continuation frame against the prefix before opening its picker', async () => {
  const f = fixture()
  f.entry.op_kind = 'extrude-deformed-continuation'
  Object.assign(f.entry.params, { source_bp: 35, ref_helix_id: 'source' })
  const frame = { origin: [1, 2, 3], normal: [0, 1, 0] }
  f.api.getDeformedFrame = vi.fn(async () => {
    expect(f.state.currentDesign.feature_log_cursor).toBe(-2)
    return frame
  })
  expect(await f.editor.open(f.entry, 0)).toBe(true)
  expect(f.api.getDeformedFrame).toHaveBeenCalledWith(35, 'source')
  expect(f.slicePlane.showDeformed).toHaveBeenCalledWith(frame, expect.objectContaining({ sourceBp: 35 }))
})

it('keeps a draft open when delayed recovery bodies hydrate the source', async () => {
  const f = fixture(0)
  await f.editor.open(f.entry, 0)
  f.slicePlane.setExtrudeInputs({ ...f.inputs(), length_bp: 49, cells: [[2, 3]] })
  f.state.currentDesign = { ...f.state.currentDesign, feature_log: f.state.currentDesign.feature_log.map(entry =>
    ({ ...entry, post_state_gz_b64: 'recovered-body' })) }
  f.notify()
  expect(f.editor.active()).toBe(true)
  expect(f.inputs()).toMatchObject({ length_bp: 49, cells: [[2, 3]] })
  await f.picker().onExtrude({ cells: [[2, 3]], lengthBp: 49, plane: 'XZ' })
  expect(f.api.editNativeExtrusionFeature).toHaveBeenCalledOnce()
  expect(f.state.currentDesign.feature_log_cursor).toBe(0)
})
it.each([-1, 0, 1])('Apply restores original cursor %s after native publication', async cursor => {
  const f = fixture(cursor)
  await f.editor.open(f.entry, 0)
  await f.picker().onExtrude({ cells: [[0, 1]], lengthBp: 42, plane: 'XZ' })
  expect(f.state.currentDesign.feature_log_cursor).toBe(cursor)
  expect(f.camera.position).toEqual(f.originalPosition)
  expect(f.editor.active()).toBe(false)
})
it('does not treat changed authored inputs as recovery hydration', async () => {
  const f = fixture()
  await f.editor.open(f.entry, 0)
  f.state.currentDesign = { ...f.state.currentDesign, feature_log: [{ ...f.entry, params: { ...f.entry.params, length_bp: 99 } }] }
  f.notify()
  expect(f.editor.active()).toBe(false)
  expect(f.api.editNativeExtrusionFeature).not.toHaveBeenCalled()
})

it('restores an original downstream child cursor after Apply', async () => {
  const f = fixture(1)
  f.state.currentDesign.feature_log_sub_cursor = 2
  await f.editor.open(f.entry, 0)
  await f.picker().onExtrude({ cells: [[0, 1]], lengthBp: 42, plane: 'XZ' })
  expect(f.api.seekFeatures).toHaveBeenLastCalledWith(1, 2)
  expect(f.state.currentDesign.feature_log_sub_cursor).toBe(2)
})
it('does not reopen a committed edit if restoring its cursor fails', async () => {
  const f = fixture(0)
  await f.editor.open(f.entry, 0)
  const seek = f.api.seekFeatures.getMockImplementation()
  f.api.seekFeatures.mockImplementation(async (...args) => f.state.currentDesign.changed ? false : seek(...args))
  await expect(f.picker().onExtrude({ cells: [[0, 1]], lengthBp: 42, plane: 'XZ' })).resolves.toBeTruthy()
  expect(f.api.editNativeExtrusionFeature).toHaveBeenCalledOnce()
  expect(f.editor.active()).toBe(false)
})

it('does not rebind recovery hydration across an authoritative revision change', async () => {
  const f = fixture()
  await f.editor.open(f.entry, 0)
  f.state.revision++
  f.state.currentDesign = { ...f.state.currentDesign }
  f.notify()
  expect(f.editor.active()).toBe(false)
})
it('keeps the picker and draft through an equivalent full design refresh', async () => {
  const f = fixture()
  await f.editor.open(f.entry, 0)
  f.slicePlane.setExtrudeInputs({ ...f.inputs(), length_bp: 63 })
  f.state.currentDesign = structuredClone(f.state.currentDesign)
  f.notify()
  expect(f.editor.active()).toBe(true)
  expect(f.inputs().length_bp).toBe(63)
  expect(f.release).not.toHaveBeenCalled()
})
it('drains an in-flight save before seeking, then holds saves until Cancel restores the cursor', async () => {
  const f = fixture(1)
  let finish
  const hold = { ready: new Promise(resolve => { finish = resolve }), release: vi.fn(() => {
    expect(f.state.currentDesign.feature_log_cursor).toBe(1)
  }) }
  f.api.holdFeatureEditSaves = vi.fn(() => hold)
  const opened = f.editor.open(f.entry, 0)
  expect(f.api.seekFeatures).not.toHaveBeenCalled()
  f.state.revision++
  finish()
  expect(await opened).toBe(true)
  expect(hold.release).not.toHaveBeenCalled()
  await f.editor.cancel()
  expect(hold.release).toHaveBeenCalledOnce()
})
it('releases deferred saves only after Apply has restored the opening cursor', async () => {
  const f = fixture(1)
  const hold = { ready: Promise.resolve(), release: vi.fn(() => {
    expect(f.state.currentDesign.changed).toBe(true)
    expect(f.state.currentDesign.feature_log_cursor).toBe(1)
  }) }
  f.api.holdFeatureEditSaves = () => hold
  await f.editor.open(f.entry, 0)
  await f.picker().onExtrude({ cells: [[0, 1]], lengthBp: 42, plane: 'XZ' })
  expect(hold.release).toHaveBeenCalledOnce()
})
it('releases the save hold on document change while waiting for an in-flight save', async () => {
  const f = fixture()
  let finish
  const hold = { ready: new Promise(resolve => { finish = resolve }), release: vi.fn() }
  f.api.holdFeatureEditSaves = () => hold
  const opened = f.editor.open(f.entry, 0)
  window.dispatchEvent(new Event('nadoc:document-reset'))
  expect(hold.release).toHaveBeenCalledOnce()
  finish()
  expect(await opened).toBe(false)
  expect(f.api.seekFeatures).not.toHaveBeenCalled()
})
