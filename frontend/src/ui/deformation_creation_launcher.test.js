// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest'
import { createMockStore } from '../test-helpers/mock_store.js'
import { createSelectionController } from '../scene/selection_controller.js'
import { initDeformationToolLauncher } from './deformation_tool_launcher.js'
import { initBendTwistPopup, closePopup } from './bend_twist_popup.js'

const fixtures = []
const tick = async () => { for (let i = 0; i < 16; i++) await Promise.resolve() }
function setup({ organized = true, owned = true } = {}) {
  document.body.innerHTML = '<button id="menu-tools-bend"></button><button id="menu-tools-twist"></button><div id="deform-panel"></div>'
  const panel = document.getElementById('deform-panel')
  for (const name of ['panel-title', 'twist-controls', 'bend-controls', 'twist-value', 'twist-value-label', 'twist-unit',
    'twist-rh', 'twist-lh', 'twist-total-radio', 'twist-pernm-radio', 'bend-dir', 'bend-angle', 'bend-radius',
    'polymer-circle', 'polymer-circle-label', 'polymer-count', 'polymer-count-row', 'compass-arm', 'compass-handle',
    'preview-check', 'cancel-btn', 'apply-btn', 'plane-a-bp', 'plane-b-bp', 'plane-a-nm', 'plane-b-nm']) {
    const node = document.createElement(name.endsWith('-btn') ? 'button' : 'input')
    node.id = `def-${name}`; panel.append(node)
  }
  initBendTwistPopup({ onCancel: vi.fn(), onPreview: vi.fn() })
  const design = { id: 'part', helices: [{ id: 'h', bp_start: 0, length_bp: 42 }],
    strands: [{ id: 's', domains: [{ helix_id: 'h', start_bp: 0, end_bp: 41, direction: 'FORWARD' }] }],
    cluster_transforms: [{ id: 'same', name: 'Placement', helix_ids: ['h'] }], deformations: [],
    ...(organized ? { group_organization: { version: 1, groups: [{ id: 'same', name: 'Group', helix_ids: ['h'], domain_ids: [] }] } } : {}) }
  const store = createMockStore({ currentDesign: design, assemblyActive: false })
  const selection = createSelectionController({ store })
  let active = false
  const closeOwned = async () => { active = false; return true }
  const ownedEditor = { openCreation: vi.fn(async () => { active = true; return true }), active: () => active,
    cancel: vi.fn(closeOwned) }
  const deps = { store, selectionManager: { clearSelection: selection.clear, setSelectionLevel: selection.setLevel },
    showToast: vi.fn(), deformView: { isActive: () => true }, watchDeformState: vi.fn(),
    start: vi.fn(), exit: vi.fn(), setScope: vi.fn(), waitForIdle: vi.fn(async () => {}),
    ownedEditor: owned ? ownedEditor : null }
  const launcher = initDeformationToolLauncher(deps)
  const f = { ...deps, launcher, selection, ownedEditor, design, closeOwned }
  fixtures.push(f); return f
}
afterEach(async () => {
  for (const f of fixtures.splice(0)) { await f.closeOwned(); await f.launcher.cancel() }
  closePopup(); await tick(); document.body.innerHTML = ''; vi.restoreAllMocks()
})

it.each(['bend', 'twist'])('the ordinary %s menu opens the owned creation workflow with named identity intact', async type => {
  const f = setup(), refs = [{ kind: 'part_group', id: 'same' }]
  f.selection.replace(refs)
  const original = JSON.stringify(f.design)
  document.getElementById(`menu-tools-${type}`).click(); await tick()
  expect(f.ownedEditor.openCreation).toHaveBeenCalledExactlyOnceWith({ type, targets: refs,
    clusterIds: [], placementHint: { kind: 'selection' },
    onUnsupported: expect.any(Function) })
  expect(f.start).not.toHaveBeenCalled(); expect(f.setScope).not.toHaveBeenCalled(); expect(f.exit).not.toHaveBeenCalled()
  expect(JSON.stringify(f.store.getState().currentDesign)).toBe(original)
  expect(f.store.getState().selection.items).toEqual(refs)
})

it('uses the same owned entry for unorganized parts instead of manufacturing a canonical preview', async () => {
  const f = setup({ organized: false }), refs = [{ kind: 'strand', id: 's' }, { kind: 'domain', strandId: 's', domainIndex: 0 }]
  f.selection.replace(refs); f.launcher.open('bend'); await tick()
  expect(f.ownedEditor.openCreation).toHaveBeenCalledWith({ type: 'bend', targets: refs,
    clusterIds: [], placementHint: { kind: 'selection' },
    onUnsupported: expect.any(Function) })
  expect(f.start).not.toHaveBeenCalled(); expect(f.setScope).not.toHaveBeenCalled()
})

it('preserves explicit placement context separately from a same-text named group selection', async () => {
  const f = setup(), refs = [{ kind: 'part_group', id: 'same' }, { kind: 'cluster', id: 'same' }]
  f.selection.replace(refs); f.launcher.open('bend'); await tick()
  expect(f.ownedEditor.openCreation).toHaveBeenCalledExactlyOnceWith({ type: 'bend', targets: refs,
    clusterIds: ['same'], placementHint: { kind: 'selection' },
    onUnsupported: expect.any(Function) })
  expect(f.setScope).not.toHaveBeenCalled(); expect(f.start).not.toHaveBeenCalled()
})

it('continues an unsupported part (e.g. legacy saved history) in the legacy tool session', async () => {
  const f = setup({ organized: false }), refs = [{ kind: 'strand', id: 's' }]
  f.ownedEditor.openCreation.mockImplementation(async ({ onUnsupported }) => onUnsupported())
  f.selection.replace(refs); f.launcher.open('bend'); await tick()
  expect(f.setScope).toHaveBeenCalledWith(refs); expect(f.start).toHaveBeenCalledWith('bend')
  expect(f.watchDeformState).toHaveBeenCalled()
  // Legacy previews mutate the canonical design; that must not reset this tool session.
  f.store.setState({ currentDesign: { ...f.store.getState().currentDesign, deformations: [{ id: 'preview' }] } }); await tick()
  expect(f.exit).not.toHaveBeenCalled()
  await f.launcher.cancel(); expect(f.exit).toHaveBeenCalledOnce()
})

it('refuses legacy fallback for organized parts with the organization message', async () => {
  const f = setup(), refs = [{ kind: 'part_group', id: 'same' }]
  f.ownedEditor.openCreation.mockImplementation(async ({ onUnsupported }) => onUnsupported())
  f.selection.replace(refs); f.launcher.open('bend'); await tick()
  expect(f.start).not.toHaveBeenCalled()
  expect(f.showToast).toHaveBeenCalledWith(expect.stringMatching(/organized parts/), { severity: 'error' })
})

it('waits for a valid complete selection before preparing, and rejects unsupported selections', async () => {
  const f = setup(); f.launcher.open('twist'); await tick()
  expect(f.ownedEditor.openCreation).not.toHaveBeenCalled()
  expect(document.getElementById('def-apply-btn').disabled).toBe(true)
  f.selection.replace([{ kind: 'protein', id: 'protein' }]); await tick()
  expect(f.ownedEditor.openCreation).not.toHaveBeenCalled()
  f.selection.replace([{ kind: 'part_group', id: 'same' }])
  f.selection.extend([{ kind: 'domain', strandId: 's', domainIndex: 0 }]); await tick()
  expect(f.ownedEditor.openCreation).toHaveBeenCalledOnce()
  expect(f.ownedEditor.openCreation.mock.lastCall[0].targets).toEqual([
    { kind: 'part_group', id: 'same' }, { kind: 'domain', strandId: 's', domainIndex: 0 },
  ])
})

it('a refused owned preparation never falls back to live legacy creation', async () => {
  const f = setup(); f.ownedEditor.openCreation.mockResolvedValue(false)
  f.selection.replace([{ kind: 'part_group', id: 'same' }]); f.launcher.open('bend'); await tick()
  expect(f.ownedEditor.openCreation).toHaveBeenCalledOnce()
  expect(f.start).not.toHaveBeenCalled(); expect(f.setScope).not.toHaveBeenCalled(); expect(f.exit).not.toHaveBeenCalled()
  expect(document.getElementById('def-apply-btn').disabled).toBe(true)
})

it('cancels queued selection work before it can open an owned editor', async () => {
  const f = setup(); f.selection.replace([{ kind: 'part_group', id: 'same' }])
  f.launcher.open('bend'); await f.launcher.cancel(); await tick()
  expect(f.ownedEditor.openCreation).not.toHaveBeenCalled(); expect(f.start).not.toHaveBeenCalled()
})

it('same-ID document reset retires queued opening and the active private owner', async () => {
  const f = setup(); f.selection.replace([{ kind: 'part_group', id: 'same' }])
  f.launcher.open('bend'); window.dispatchEvent(new Event('nadoc:document-reset')); await tick()
  expect(f.ownedEditor.openCreation).not.toHaveBeenCalled()
  f.launcher.open('bend'); await tick(); expect(f.ownedEditor.active()).toBe(true)
  f.ownedEditor.cancel.mockClear()
  window.dispatchEvent(new Event('nadoc:document-reset')); await tick()
  expect(f.ownedEditor.cancel).toHaveBeenCalled()
  expect(f.start).not.toHaveBeenCalled(); expect(f.exit).not.toHaveBeenCalled()
})

it('Change selection waits for owned cancellation and starts a fresh private request', async () => {
  const f = setup(); f.selection.replace([{ kind: 'part_group', id: 'same' }])
  f.launcher.open('bend'); await tick()
  let release
  f.ownedEditor.cancel.mockImplementationOnce(() => new Promise(resolve => {
    release = async () => { await f.closeOwned(); resolve(true) }
  }))
  document.getElementById('def-change-selection').click(); await tick()
  expect(f.ownedEditor.openCreation).toHaveBeenCalledOnce()
  await release(); await tick()
  f.selection.replace([{ kind: 'domain', strandId: 's', domainIndex: 0 }]); await tick()
  expect(f.ownedEditor.openCreation).toHaveBeenCalledTimes(2)
  expect(f.ownedEditor.openCreation.mock.lastCall[0].targets).toEqual([{ kind: 'domain', strandId: 's', domainIndex: 0 }])
  expect(f.exit).not.toHaveBeenCalled()
})

it('does not abandon an unknown Apply to launch another creation', async () => {
  const f = setup(); f.selection.replace([{ kind: 'part_group', id: 'same' }])
  f.launcher.open('bend'); await tick()
  f.ownedEditor.cancel.mockResolvedValue(false)
  f.launcher.open('twist'); await tick()
  expect(f.ownedEditor.openCreation).toHaveBeenCalledOnce()
  expect(f.start).not.toHaveBeenCalled(); expect(f.exit).not.toHaveBeenCalled()
})

it('keeps the disabled rollout legacy path unchanged and organized fallback explicitly refused', async () => {
  const f = setup({ organized: false, owned: false })
  f.selection.replace([{ kind: 'strand', id: 's' }]); f.launcher.open('bend'); await tick()
  expect(f.start).toHaveBeenCalledExactlyOnceWith('bend')
  expect(f.ownedEditor.openCreation).not.toHaveBeenCalled()
  await f.launcher.cancel(); f.start.mockClear(); f.exit.mockClear()
  f.store.setState({ currentDesign: { ...f.design, group_organization: { version: 1, groups: [] } } })
  f.launcher.open('twist'); await tick()
  expect(f.start).not.toHaveBeenCalled(); expect(f.exit).not.toHaveBeenCalled()
  expect(f.showToast.mock.lastCall[0]).toContain('owned preview')
})

it('does not claim assembly support or open the part-owned lifecycle there', async () => {
  const f = setup(); f.store.setState({ assemblyActive: true })
  f.launcher.open('bend'); await tick()
  expect(f.ownedEditor.openCreation).not.toHaveBeenCalled(); expect(f.start).not.toHaveBeenCalled()
  expect(f.showToast).toHaveBeenCalled()
})
