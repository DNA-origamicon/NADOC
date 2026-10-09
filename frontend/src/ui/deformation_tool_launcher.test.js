import { afterEach, expect, it, vi } from 'vitest'
import { createMockStore } from '../test-helpers/mock_store.js'
import { createSelectionController } from '../scene/selection_controller.js'
import { initDeformationToolLauncher } from './deformation_tool_launcher.js'
import { initBendTwistPopup } from './bend_twist_popup.js'
let launcher
afterEach(() => { launcher?.cancel(); document.body.innerHTML = '' })
function setup() {
  document.body.innerHTML = '<canvas id="canvas"></canvas><div id="mode-indicator"></div><div id="deform-panel"></div>'
  const panel = document.getElementById('deform-panel')
  for (const name of ['panel-title', 'twist-controls', 'bend-controls', 'twist-value', 'twist-value-label', 'twist-unit',
    'twist-rh', 'twist-lh', 'twist-total-radio', 'twist-pernm-radio', 'bend-dir', 'bend-angle', 'bend-radius',
    'polymer-circle', 'polymer-circle-label', 'polymer-count', 'polymer-count-row', 'compass-arm', 'compass-handle',
    'preview-check', 'cancel-btn', 'apply-btn', 'plane-a-bp', 'plane-b-bp', 'plane-a-nm', 'plane-b-nm']) {
    const node = document.createElement(name.endsWith('-btn') ? 'button' : 'input')
    node.id = `def-${name}`; panel.append(node)
  }
  initBendTwistPopup({ onCancel: vi.fn(), onPreview: vi.fn() })
  const store = createMockStore({ currentDesign: { id: 'part', helices: [{ id: 'h', length_bp: 42 }],
    strands: [{ id: 's', domains: [{ helix_id: 'h', start_bp: 0, end_bp: 41 }] }],
    cluster_transforms: [{ id: 'c', helix_ids: ['h'] }] } })
  const controller = createSelectionController({ store })
  const deps = { store, selectionManager: { clearSelection: controller.clear, setSelectionLevel: controller.setLevel }, showToast: vi.fn(), deformView: { isActive: () => true }, watchDeformState: vi.fn(), start: vi.fn(), exit: vi.fn(), setScope: vi.fn(), waitForIdle: () => Promise.resolve() }
  launcher = initDeformationToolLauncher(deps)
  return { ...deps, controller }
}
it.each(['bend', 'twist'])('retains mixed selection and automatically places planes for %s', async type => {
  const d = setup()
  const refs = [{ kind: 'cluster', id: 'c' }, { kind: 'domain', strandId: 's', domainIndex: 0 }]
  d.controller.replace(refs)
  launcher.open(type)
  expect(document.getElementById('def-current-selection').textContent).toContain('Domain · s [0]')
  expect(d.start).not.toHaveBeenCalled()
  await Promise.resolve()
  expect(d.setScope).toHaveBeenCalledWith(refs)
  expect(d.start).toHaveBeenCalledExactlyOnceWith(type)
  expect(d.store.getState().selection.items).toEqual(refs)
  expect(document.getElementById('def-change-selection')).not.toBeNull()
})
it('works without clusters and clear returns to empty selection without exiting the panel', async () => {
  const d = setup()
  d.store.setState({ currentDesign: { ...d.store.getState().currentDesign, cluster_transforms: [] } })
  launcher.open('bend')
  expect(document.getElementById('def-apply-btn').disabled).toBe(true)
  d.controller.replace([{ kind: 'strand', id: 's' }])
  await Promise.resolve()
  document.getElementById('def-clear-selection').click()
  await Promise.resolve()
  expect(d.store.getState().selection.items).toEqual([])
  expect(document.getElementById('def-apply-btn').disabled).toBe(true)
})
it('rejects unsupported targets and cancels on document replacement', () => {
  const d = setup(); launcher.open('twist')
  d.controller.replace([{ kind: 'protein', id: 'p' }])
  expect(document.getElementById('def-apply-btn').disabled).toBe(true)
  d.store.setState({ currentDesign: { id: 'other' } })
  expect(document.getElementById('def-current-selection').hidden).toBe(true)
})
it('Escape closes the waiting panel', () => {
  setup(); launcher.open('bend')
  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
  expect(document.getElementById('def-current-selection').hidden).toBe(true)
})

it.each(['bend', 'twist'])('starts %s with one-shot cluster picking and rearms on Clear', async type => {
  const d = setup()
  launcher.open(type)
  expect(d.controller.getState().level).toBe('cluster')
  d.controller.select({ kind: 'cluster', id: 'c' })
  await Promise.resolve()
  expect(d.controller.getState().level).toBe('default')
  expect(d.controller.getState().items).toEqual([{ kind: 'cluster', id: 'c' }])
  document.getElementById('def-clear-selection').click()
  await Promise.resolve()
  expect(d.controller.getState().level).toBe('cluster')
  launcher.cancel()
  expect(d.controller.getState().level).toBe('default')
})

it('waits for the complete selection gesture and ignores queued starts after cancellation', async () => {
  const d = setup()
  launcher.open('bend')
  d.controller.select({ kind: 'cluster', id: 'c' })
  d.controller.extend([{ kind: 'domain', strandId: 's', domainIndex: 0 }])
  await Promise.resolve()
  expect(d.setScope).toHaveBeenCalledExactlyOnceWith([
    { kind: 'cluster', id: 'c' }, { kind: 'domain', strandId: 's', domainIndex: 0 },
  ])
  launcher.cancel()
  d.start.mockClear()
  launcher.open('twist')
  launcher.cancel()
  await Promise.resolve()
  expect(d.start).not.toHaveBeenCalled()
})

it('shows a plane placement error without entering an invalid editing session', async () => {
  const d = setup()
  d.start.mockImplementation(() => { throw new Error('Select a span of at least two base positions.') })
  launcher.open('bend')
  d.controller.select({ kind: 'strand', id: 's' })
  await Promise.resolve()
  expect(d.showToast).toHaveBeenCalledWith('Select a span of at least two base positions.', { severity: 'error' })
  expect(document.getElementById('def-current-selection').textContent).toContain('at least two')
  expect(document.getElementById('def-change-selection')).toBeNull()
})
