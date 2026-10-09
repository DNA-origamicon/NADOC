import { afterEach, expect, it, vi } from 'vitest'
import * as THREE from 'three'
import { store } from '../state/store.js'
import * as api from '../api/client.js'
import { initDeformationEditor, startToolAtBp, previewDeformation, exitTool,
  waitForDeformationIdle, confirmDeformation, setDeformSessionTargets, startToolForSelection, getPlanes, getState } from './deformation_editor.js'
vi.mock('../api/client.js', () => ({ addDeformation: vi.fn(), updateDeformation: vi.fn(), deleteDeformation: vi.fn() }))
vi.mock('../ui/toast.js', () => ({ showPersistentToast: vi.fn(), dismissToast: vi.fn() }))
const params = { kind: 'twist', total_degrees: 30 }
function setup() {
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({ clearRect() {}, fillText() {}, fillRect() {} })
  store.setState({ currentDesign: { id: 'part', helices: [{ id: 'h', bp_start: 0, length_bp: 30,
    axis_start: { x: 0, y: 0, z: 0 }, axis_end: { x: 0, y: 0, z: 10 } }],
    cluster_transforms: [], strands: [{ id: 's', domains: [{ helix_id: 'h', start_bp: 0, end_bp: 29 }] }], deformations: [] },
    currentHelixAxes: null, activeClusterId: null })
  initDeformationEditor(new THREE.Scene(), new THREE.PerspectiveCamera(), document.createElement('canvas'), {}, {}, () => {})
  setDeformSessionTargets([{ kind: 'strand', id: 's' }])
  startToolAtBp('twist', 'h', 29, 1)
  api.deleteDeformation.mockImplementation(async id => {
    const design = store.getState().currentDesign
    store.setState({ currentDesign: { ...design, deformations: design.deformations.filter(d => d.id !== id) } })
  })
}
afterEach(async () => { exitTool(); await waitForDeformationIdle(); vi.restoreAllMocks(); vi.clearAllMocks() })
it('deletes a preview whose POST completes after cancellation', async () => {
  setup()
  let finish
  api.addDeformation.mockImplementation(() => new Promise(resolve => { finish = () => {
    const d = store.getState().currentDesign
    store.setState({ currentDesign: { ...d, deformations: [{ id: 'late' }] } }); resolve()
  } }))
  const pending = previewDeformation(params)
  await Promise.resolve()
  exitTool()
  finish()
  await pending; await waitForDeformationIdle()
  expect(api.deleteDeformation).toHaveBeenCalledWith('late', true)
  expect(store.getState().currentDesign.deformations).toEqual([])
})
it('Apply waits for an outstanding preview before deleting it and committing exact scope', async () => {
  setup()
  let finish
  api.addDeformation.mockImplementationOnce(() => new Promise(resolve => { finish = () => {
    const d = store.getState().currentDesign
    store.setState({ currentDesign: { ...d, deformations: [{ id: 'preview' }] } }); resolve()
  } })).mockResolvedValue(undefined)
  const preview = previewDeformation(params)
  await Promise.resolve()
  const commit = confirmDeformation(params)
  expect(api.addDeformation).toHaveBeenCalledTimes(1)
  finish(); await preview; await commit
  expect(api.deleteDeformation).toHaveBeenCalledWith('preview', true)
  expect(api.addDeformation.mock.calls[1][5]).toBe(false)
  expect(api.addDeformation.mock.calls[1][7].targets).toEqual([{ kind: 'strand', id: 's' }])
})

it.each([
  [[{ kind: 'cluster', id: 'partial' }], 10, 19],
  [[{ kind: 'domain', strandId: 's', domainIndex: 1 }], 10, 19],
  [[{ kind: 'strand', id: 's' }], 5, 19],
  [[{ kind: 'cluster', id: 'partial' }, { kind: 'strand', id: 't' }], 10, 25],
])('places planes at selected bounds for %j', (targets, a, b) => {
  setup(); exitTool()
  const design = store.getState().currentDesign
  store.setState({ currentDesign: { ...design,
    helices: [...design.helices, { ...design.helices[0], id: 'unselected', length_bp: 1000 }],
    strands: [
      { id: 's', domains: [{ helix_id: 'h', start_bp: 5, end_bp: 9 }, { helix_id: 'h', start_bp: 19, end_bp: 10 }] },
      { id: 't', domains: [{ helix_id: 'h', start_bp: 22, end_bp: 25 }] },
    ],
    cluster_transforms: [{ id: 'partial', helix_ids: ['h'], domain_ids: [{ strand_id: 's', domain_index: 1 }] }],
  } })
  setDeformSessionTargets(targets)
  startToolForSelection('bend')
  expect(getState()).toBe('BOTH')
  expect(getPlanes()).toEqual({ a: { bp: a }, b: { bp: b } })
})

it('rejects a one-base selection before activating the tool', () => {
  setup(); exitTool()
  const design = store.getState().currentDesign
  store.setState({ currentDesign: { ...design,
    strands: [{ id: 's', domains: [{ helix_id: 'h', start_bp: 5, end_bp: 5 }] }],
  } })
  setDeformSessionTargets([{ kind: 'strand', id: 's' }])
  expect(() => startToolForSelection('twist')).toThrow('at least two base positions')
  expect(store.getState().deformToolActive).toBe(false)
  expect(getState()).toBe('IDLE')
})
