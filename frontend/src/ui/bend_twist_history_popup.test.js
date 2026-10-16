import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import * as popup from './bend_twist_popup.js'
import { store } from '../state/store.js'
import { validateDeformation } from '../api/client.js'
import { setDeformSessionClusterIds } from '../scene/deformation_editor.js'
vi.mock('../api/client.js', () => ({ validateDeformation: vi.fn(async () => ({ status: 'ok' })) }))
vi.mock('../scene/deformation_editor.js', () => ({ setDeformSessionClusterIds: vi.fn(async () => {}),
  getDeformDefaultClusterIds: () => ['live-group'], getDeformSessionTargets: () => null }))
vi.mock('./toast.js', () => ({ showToast: vi.fn() }))
const tick = async () => { for (let n = 0; n < 8; n++) await Promise.resolve() }
const params = { kind: 'bend', curvature_deg_per_bp: .123456789, direction_deg: 17.25 }
let previous
beforeEach(() => { previous = store.getState(); vi.useFakeTimers() })
afterEach(() => {
  popup.closePopup(); popup.setDeformationSelectionUI(null)
  store.setState(previous); document.body.innerHTML = ''; vi.useRealTimers(); vi.clearAllMocks()
})
function setup({ clusters = 2, targets = null, named = false, placementIds = [] } = {}) {
  document.body.innerHTML = '<div id="deform-panel" style="display:none"><div class="def-fields"></div></div>'
  const panel = document.querySelector('.def-fields')
  for (const name of ['panel-title', 'twist-controls', 'bend-controls', 'twist-value', 'twist-value-label', 'twist-unit',
    'twist-rh', 'twist-lh', 'twist-total-radio', 'twist-pernm-radio', 'bend-dir', 'bend-angle', 'bend-radius',
    'polymer-circle', 'polymer-circle-label', 'polymer-count', 'polymer-count-row', 'compass-arm', 'compass-handle',
    'preview-check', 'cancel-btn', 'apply-btn', 'plane-a-bp', 'plane-b-bp', 'plane-a-nm', 'plane-b-nm',
    'cluster-section', 'cluster-list', 'cluster-empty-msg', 'cluster-all-btn', 'cluster-none-btn', 'bend-hint', 'feasibility']) {
    const tag = name.endsWith('-btn') ? 'button' : ['cluster-list', 'cluster-section'].includes(name) ? 'div' : 'input'
    const node = document.createElement(tag); node.id = `def-${name}`
    if (['preview-check', 'polymer-circle'].includes(name)) node.type = 'checkbox'
    if (['twist-rh', 'twist-lh', 'twist-total-radio', 'twist-pernm-radio'].includes(name)) node.type = 'radio'
    panel.append(node)
  }
  document.getElementById('def-cluster-section').append(document.getElementById('def-cluster-list'))
  store.setState({ currentDesign: { id: 'live', cluster_transforms: [{ id: 'live-group', name: 'Later group', helix_ids: [] }],
    strands: [], forced_ligations: [] } })
  const creation = { onPreview: vi.fn(), onConfirm: vi.fn(), onCancel: vi.fn(), onPlaneChanged: vi.fn() }
  popup.initBendTwistPopup(creation); popup.setDeformationSelectionUI(null)
  const operation = { id: 'op', type: 'bend', plane_a_bp: 0, plane_b_bp: 100, params, cluster_ids: placementIds, targets }
  const design = { id: 'prefix', helices: [], deformations: [],
    strands: [{ id: 'prefix-strand', notes: 'polymerization connector', domains: [{ helix_id: 'h', start_bp: 0, end_bp: 90 }] }],
    forced_ligations: [{ is_periodic_seam: true, three_prime_bp: 0, five_prime_bp: 90 }],
    cluster_transforms: Array.from({ length: clusters }, (_, i) => ({ id: `prefix-${i}`, name: `Prefix ${i}`, helix_ids: ['h'], domain_ids: [] })) }
  if (named) design.group_organization = { version: 1, groups: ['prefix-0', 'other-org'].map(id => ({ id, name: `Organization ${id}`, helix_ids: ['h'], domain_ids: [] })) }
  const session = { design, operation, capabilities: { change_clusters: targets === null, change_targets: named && targets.every(t => t.kind === 'part_group') },
    onChange: vi.fn(async () => ({ feasibility: { status: 'ok' } })), onApply: vi.fn(async () => false),
    onCancel: vi.fn(async () => false), onPlaneChanged: vi.fn(),
    onResolvePublication: vi.fn(async () => false), onRefreshCommitted: vi.fn(async () => false) }
  popup.openPopup('bend', 0, 100, params, placementIds, true, session)
  return { session, creation }
}
const node = name => document.getElementById(`def-${name}`)
const input = (name, value, type = 'input') => { node(name).value = value; node(name).dispatchEvent(new Event(type)) }

it('opens from the prepared prefix without preview work or a canonical validation request', async () => {
  const f = setup(); await vi.advanceTimersByTimeAsync(130)
  expect(node('cluster-list').textContent).toContain('Prefix 0')
  expect(node('cluster-list').textContent).not.toContain('Later group')
  expect(f.session.onChange).not.toHaveBeenCalled()
  expect(validateDeformation).not.toHaveBeenCalled()
  expect(f.creation.onPreview).not.toHaveBeenCalled()
})

it('untouched Apply preserves exact original curvature and explicit unscoped [] even with one cluster', async () => {
  const f = setup({ clusters: 1 }); node('apply-btn').click(); await tick()
  expect(f.session.onApply).toHaveBeenCalledOnce()
  const patch = f.session.onApply.mock.calls[0][0]
  expect(patch).not.toHaveProperty('params')
  expect(patch.cluster_ids ?? []).toEqual([])
  expect(node('deform-panel')?.style.display ?? document.getElementById('deform-panel').style.display).not.toBe('none')
  expect(f.creation.onConfirm).not.toHaveBeenCalled()
})

it('sends current checked groups with the edited parameters and never output authority', async () => {
  const f = setup()
  const check = node('cluster-list').querySelector('input[value="prefix-1"]')
  check.checked = true; check.dispatchEvent(new Event('change')); await tick()
  input('bend-dir', '95')
  node('apply-btn').click(); await tick()
  const patch = f.session.onApply.mock.calls[0][0]
  expect(patch.cluster_ids).toEqual(['prefix-1'])
  expect(patch.params.direction_deg).toBe(95)
  for (const key of ['id', 'affected_helix_ids', 'targets', 'target_ranges', 'design', 'feature_id']) expect(patch).not.toHaveProperty(key)
  expect(setDeformSessionClusterIds).toHaveBeenCalledWith(['prefix-1'])
})

it('visual preview off still evaluates the current prefix inputs with geometry disabled', async () => {
  const f = setup()
  node('preview-check').checked = false; node('preview-check').dispatchEvent(new Event('change'))
  await tick(); input('bend-angle', '60'); await tick()
  expect(f.session.onChange.mock.lastCall).toEqual([expect.objectContaining({ params: expect.objectContaining({ curvature_deg_per_bp: .6 }) }),
    { includeGeometry: false }])
  expect(validateDeformation).not.toHaveBeenCalled(); expect(f.creation.onPreview).not.toHaveBeenCalled()
})

it('polymer circle uses fixed-prefix seam data rather than unrelated latest geometry', async () => {
  const f = setup()
  expect(node('polymer-circle').disabled).toBe(false)
  node('polymer-count').value = '3'; node('polymer-circle').checked = true
  node('polymer-circle').dispatchEvent(new Event('change')); await tick()
  expect(f.session.onChange.mock.lastCall[0].params.curvature_deg_per_bp).toBeCloseTo(120 / 90, 7)
  expect(f.session.onChange.mock.lastCall[0].params.polymer_circle_count).toBe(3)
})

it('explicit target labels use prefix names and retain fixed membership', () => {
  setup({ targets: [{ kind: 'strand', id: 'prefix-strand' }] })
  expect(document.getElementById('def-current-selection').textContent).toContain('prefix-strand')
  expect(node('cluster-section').style.display).toBe('none')
  expect(document.getElementById('def-change-selection')).toBeNull()
})

it('plane changes send current popup parameters and private plane notifications', async () => {
  const f = setup(); input('bend-dir', '120'); input('plane-b-bp', '80', 'change'); await tick()
  expect(f.session.onPlaneChanged).toHaveBeenCalledWith('B', 80)
  expect(f.session.onChange.mock.lastCall[0]).toMatchObject({ plane_a_bp: 0, plane_b_bp: 80,
    params: expect.objectContaining({ direction_deg: 120 }) })
  expect(f.creation.onPlaneChanged).not.toHaveBeenCalled()
})

it('Apply failure remains visible; only an explicit successful callback closes the popup', async () => {
  const f = setup()
  f.session.onApply.mockRejectedValueOnce(new Error('The upstream source changed')).mockResolvedValueOnce(true)
  node('apply-btn').click(); await tick()
  expect(document.getElementById('deform-panel').style.display).not.toBe('none')
  expect(document.getElementById('def-history-status').textContent).toContain('upstream source changed')
  node('apply-btn').click(); await tick()
  expect(document.getElementById('deform-panel').style.display).toBe('none')
})

it('Cancel and window close keep an unresolved commit open and never invoke creation cancellation', async () => {
  const f = setup(); node('cancel-btn').click(); await tick()
  expect(document.getElementById('deform-panel').style.display).not.toBe('none')
  document.querySelector('.tool-popup__header button').click(); await tick()
  expect(f.session.onCancel).toHaveBeenCalledTimes(2)
  expect(f.creation.onCancel).not.toHaveBeenCalled()
})

it('busy, expiry and errors are visible without resetting inputs or permitting another Apply', () => {
  setup(); input('bend-dir', '81')
  popup.setHistoryPopupStatus({ busy: 'apply', expired: false, error: null })
  expect(node('apply-btn').disabled).toBe(true)
  expect(document.getElementById('def-history-status').textContent).toMatch(/apply|applying/i)
  popup.setHistoryPopupStatus({ busy: null, expired: true, error: new Error('Preview expired') })
  expect(node('apply-btn').disabled).toBe(true)
  expect(document.getElementById('def-history-status').textContent).toMatch(/expired/i)
  expect(node('bend-dir').value).toBe('81')
})

it('offers explicit publication status/refresh recovery without repeating Apply', async () => {
  const f = setup()
  popup.setHistoryPopupStatus({ publicationUnknown: true, refreshNeeded: false, busy: null })
  document.getElementById('def-history-resolve').click(); await tick()
  expect(f.session.onResolvePublication).toHaveBeenCalledOnce()
  expect(node('apply-btn').disabled).toBe(true)
  popup.setHistoryPopupStatus({ publicationUnknown: false, refreshNeeded: true, busy: null })
  document.getElementById('def-history-refresh').click(); await tick()
  expect(f.session.onRefreshCommitted).toHaveBeenCalledOnce()
  expect(f.session.onApply).not.toHaveBeenCalled()
  expect(document.getElementById('deform-panel').style.display).not.toBe('none')
})

it('sends an explicit original group selection after reversing a previously previewed change', async () => {
  const f = setup(), check = node('cluster-list').querySelector('input[value="prefix-1"]')
  check.checked = true; check.dispatchEvent(new Event('change')); await tick()
  expect(f.session.onChange.mock.lastCall[0].cluster_ids).toEqual(['prefix-1'])
  check.checked = false; check.dispatchEvent(new Event('change')); await tick()
  expect(f.session.onChange.mock.lastCall[0].cluster_ids).toEqual([])
  node('apply-btn').click(); await tick()
  expect(f.session.onApply.mock.lastCall[0].cluster_ids).toEqual([])
})

it('reversing plane-only edits restores original planes and exact original curvature in the accumulated draft', async () => {
  const f = setup()
  input('plane-b-bp', '80', 'change'); await tick()
  expect(f.session.onChange.mock.lastCall[0].plane_b_bp).toBe(80)
  input('plane-b-bp', '100', 'change'); await tick()
  expect(f.session.onChange.mock.lastCall[0]).toMatchObject({ plane_a_bp: 0, plane_b_bp: 100, params })
  node('apply-btn').click(); await tick()
  expect(f.session.onApply.mock.lastCall[0]).toMatchObject({ plane_a_bp: 0, plane_b_bp: 100, params })
})

it('reversing planes retains explicitly edited scalar controls', async () => {
  const f = setup()
  input('bend-dir', '91'); input('plane-b-bp', '80', 'change'); await tick()
  input('plane-b-bp', '100', 'change'); await tick()
  node('apply-btn').click(); await tick()
  expect(f.session.onApply.mock.lastCall[0]).toMatchObject({ plane_a_bp: 0, plane_b_bp: 100,
    params: expect.objectContaining({ direction_deg: 91 }) })
})

it('a delayed history group update cannot preview after its popup was closed', async () => {
  const f = setup()
  let release
  setDeformSessionClusterIds.mockImplementationOnce(() => new Promise(resolve => { release = resolve }))
  const check = node('cluster-list').querySelector('input[value="prefix-1"]')
  check.checked = true; check.dispatchEvent(new Event('change'))
  popup.closePopup(); release(); await tick()
  expect(f.session.onChange).not.toHaveBeenCalled()
  expect(f.creation.onPreview).not.toHaveBeenCalled()
  expect(validateDeformation).not.toHaveBeenCalled()
})

it('edits named group selection privately without replacing independent placement IDs', async () => {
  const f = setup({ named: true, targets: [{ kind: 'part_group', id: 'prefix-0' }], placementIds: ['prefix-0'] })
  const canonical = store.getState().currentDesign, original = structuredClone(f.session.operation)
  const selection = document.getElementById('def-current-selection')
  expect(selection.textContent).toContain('Organization prefix-0')
  expect(selection.textContent).not.toContain('Later group')
  const current = selection.querySelector('input[value="prefix-0"]'), other = selection.querySelector('input[value="other-org"]')
  expect(current.checked).toBe(true)
  other.checked = true; other.dispatchEvent(new Event('change')); await tick()
  current.checked = false; current.dispatchEvent(new Event('change')); await tick()
  input('bend-dir', '40'); node('apply-btn').click(); await tick()
  const patch = f.session.onApply.mock.lastCall[0]
  expect(patch.targets).toEqual([{ kind: 'part_group', id: 'other-org' }])
  expect(patch).not.toHaveProperty('cluster_ids')
  expect(patch).not.toHaveProperty('target_ranges')
  expect(patch).not.toHaveProperty('affected_helix_ids')
  expect(patch.params.direction_deg).toBe(40)
  expect(f.session.operation).toEqual(original)
  expect(store.getState().currentDesign).toBe(canonical)
  expect(validateDeformation).not.toHaveBeenCalled()
  expect(setDeformSessionClusterIds).not.toHaveBeenCalled()
})

it('restores named selection explicitly after reversal and blocks empty named Apply', async () => {
  const f = setup({ named: true, targets: [{ kind: 'part_group', id: 'prefix-0' }] })
  const check = document.querySelector('#def-current-selection input[value="prefix-0"]')
  check.checked = false; check.dispatchEvent(new Event('change')); await tick()
  node('apply-btn').click(); await tick()
  expect(f.session.onApply).not.toHaveBeenCalled()
  expect(document.getElementById('def-current-selection').textContent).toMatch(/select.*group/i)
  check.checked = true; check.dispatchEvent(new Event('change')); await tick()
  node('apply-btn').click(); await tick()
  expect(f.session.onApply.mock.lastCall[0].targets).toEqual([{ kind: 'part_group', id: 'prefix-0' }])
})

it('mixed named and primitive scopes remain read-only and preserve placement context', async () => {
  const f = setup({ named: true, targets: [{ kind: 'part_group', id: 'prefix-0' }, { kind: 'strand', id: 'prefix-strand' }], placementIds: ['prefix-1'] })
  const selection = document.getElementById('def-current-selection')
  expect(selection.textContent).toContain('Organization prefix-0')
  expect(selection.textContent).toContain('prefix-strand')
  expect(selection.querySelector('input')).toBeNull()
  node('apply-btn').click(); await tick()
  expect(f.session.onApply.mock.lastCall[0]).toEqual({})
})

it('retired named controls cannot dispatch after Cancel or another session opens', async () => {
  const f = setup({ named: true, targets: [{ kind: 'part_group', id: 'prefix-0' }] })
  const check = document.querySelector('#def-current-selection input[value="other-org"]')
  f.session.onCancel.mockResolvedValue(true)
  node('cancel-btn').click(); await tick()
  check.checked = true; check.dispatchEvent(new Event('change')); await tick()
  expect(f.session.onChange).not.toHaveBeenCalled()
  expect(f.creation.onPreview).not.toHaveBeenCalled()
})
