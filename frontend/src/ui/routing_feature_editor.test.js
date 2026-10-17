import { afterEach, expect, it, vi } from 'vitest'
import { editRoutingFeature, isNativeRoutingChild, ROUTING_HISTORY_EDITOR_ENABLED } from './routing_feature_editor.js'

const site = { helix_id: 'h1', bp_index: 5, direction: 'FORWARD' }
const placement = id => ({ ...(id ? { crossover_id: id } : {}), half_a: { helix_id: 'h1', index: 5, strand: 'FORWARD' },
  half_b: { helix_id: 'h2', index: 5, strand: 'REVERSE' }, nick_bp_a: 4, nick_bp_b: 6, process_id: 'manual' })
const cases = [
  ['strand-end-resize', { entries: [{ strand_id: 's1', helix_id: 'h1', end: '3p', delta_bp: 2 }] }, 'Entry 1 Delta (bp)', '-3', ['entries', 0, 'delta_bp'], -3],
  ['domain-shift', { entries: [{ strand_id: 's1', domain_index: 0, delta_bp: 2 }] }, 'Entry 1 Domain index', '1', ['entries', 0, 'domain_index'], 1],
  ['nick', site, 'Base index', '7', ['bp_index'], 7],
  ['nick-batch', { nicks: [site] }, 'Nick 1 Direction', 'REVERSE', ['nicks', 0, 'direction'], 'REVERSE'],
  ['ligate', site, 'Helix ID', 'h2', ['helix_id'], 'h2'],
  ['forced-ligation-create', { three_prime_strand_id: 's1', five_prime_strand_id: 's2', is_periodic_seam: false, _fl_id: 'created-fl' }, 'Periodic seam', true, ['is_periodic_seam'], true],
  ['forced-ligation-delete', { fl_id: 'fl1' }, 'Forced ligation ID', 'fl2', ['fl_id'], 'fl2'],
  ['forced-ligation-delete-batch', { forced_ligation_ids: ['fl1'] }, 'Forced ligation 1 ID', 'fl2', ['forced_ligation_ids', 0], 'fl2'],
  ['forced-ligation-extra-bases', { fl_id: 'fl1', sequence: 'ACGT' }, 'Sequence', '', ['sequence'], ''],
  ['crossover-place', placement('a0000000-0000-4000-8000-000000000001'), 'Half B Direction', 'FORWARD', ['half_b', 'strand'], 'FORWARD'],
  ['crossover-place-batch', { placements: [placement('a0000000-0000-4000-8000-000000000001')] }, 'Placement 1 Nick B (bp)', '8', ['placements', 0, 'nick_bp_b'], 8],
  ['crossover-move', { crossover_id: 'x1', new_index: 6 }, 'Crossover ID', 'x2', ['crossover_id'], 'x2'],
  ['crossover-move-batch', { moves: [{ crossover_id: 'x1', new_index: 6 }] }, 'Move 1 New index', '8', ['moves', 0, 'new_index'], 8],
  ['crossover-delete', { crossover_id: 'x1' }, 'Crossover ID', 'x2', ['crossover_id'], 'x2'],
  ['crossover-delete-batch', { crossover_ids: ['x1'] }, 'Crossover 1 ID', 'x2', ['crossover_ids', 0], 'x2'],
  ['crossover-extra-bases', { crossover_id: 'x1', sequence: 'AC' }, 'Sequence', 'NN', ['sequence'], 'NN'],
  ['crossover-extra-bases-batch', { entries: [{ crossover_id: 'x1', sequence: 'AC' }] }, 'Entry 1 Sequence', '', ['entries', 0, 'sequence'], ''],
  ['loop-skip-insert', { helix_id: 'h1', bp_index: 5, delta: 1 }, 'Loop/skip change', '0', ['delta'], 0],
  ['loop-skip-twist', { helix_ids: ['h1'], plane_a_bp: 1, plane_b_bp: 10, target_twist_deg: 30 }, 'Target twist (degrees)', '-15', ['target_twist_deg'], -15],
  ['loop-skip-bend', { helix_ids: ['h1'], plane_a_bp: 1, plane_b_bp: 10, radius_nm: 20, direction_deg: 0 }, 'Direction (degrees)', '45', ['direction_deg'], 45],
  ['loop-skip-clear', { helix_ids: ['h1'], plane_a_bp: 1, plane_b_bp: 10 }, 'End plane (bp)', '12', ['plane_b_bp'], 12],
]
export function packet(kind, params) {
  return { kind, params: { ...structuredClone(params), _proof_version: 1 }, source_design_id: 'part', source_revision: 7,
    feature_id: 'routing', child_id: 'child', prefix: {
      helices: ['h1', 'h2'].map(id => ({ id, bp_start: 0, length_bp: 20 })),
      strands: ['s1', 's2'].map(id => ({ id, domains: [{ helix_id: 'h1', start_bp: 0, end_bp: 9, direction: 'FORWARD' }, { helix_id: 'h2', start_bp: 9, end_bp: 0, direction: 'REVERSE' }] })),
      crossovers: ['x1', 'x2'].map(id => ({ id, half_a: placement().half_a, half_b: placement().half_b })),
      forced_ligations: ['fl1', 'fl2'].map(id => ({ id, three_prime_strand_id: 's1', five_prime_strand_id: 's2' })),
    } }
}
const button = label => [...document.querySelectorAll('button')].find(node => node.textContent === label)
function set(label, value) {
  const node = document.querySelector(`[aria-label="${label}"]`)
  expect(node, label).not.toBeNull()
  if (node.type === 'checkbox') node.checked = value
  else node.value = value
  node.dispatchEvent(new Event(node.tagName === 'SELECT' || node.type === 'checkbox' ? 'change' : 'input'))
}
const tick = async () => { await Promise.resolve(); await Promise.resolve(); await Promise.resolve() }
afterEach(() => { window.dispatchEvent(new Event('nadoc:document-reset')); document.body.innerHTML = '' })

it('keeps public rollout off and rejects unversioned, unknown, and generated definitions', () => {
  expect(ROUTING_HISTORY_EDITOR_ENABLED).toBe(false)
  const parent = { feature_type: 'routing-cluster', id: 'routing' }
  const child = { feature_type: 'minor', id: 'child', op_subtype: 'nick', params: { ...site, _proof_version: 1 } }
  expect(isNativeRoutingChild(parent, child)).toBe(true)
  for (const params of [{ ...site }, { ...child.params, _proof_version: 2 }, { ...child.params, _generator: {} }])
    expect(isNativeRoutingChild(parent, { ...child, params })).toBe(false)
  expect(isNativeRoutingChild(parent, { ...child, op_subtype: 'auto-crossover' })).toBe(false)
  expect(isNativeRoutingChild({ ...parent, feature_type: 'snapshot' }, child)).toBe(false)
})

it.each(cases)('edits native %s inputs without altering the source or protected metadata', async (kind, params, label, value, path, expected) => {
  const source = packet(kind, params), before = structuredClone(source), save = vi.fn(async () => ({ accepted: true }))
  const pending = editRoutingFeature(source, { onSave: save }); set(label, value); button('Apply').click()
  const submitted = await pending
  expect(path.reduce((v, key) => v[key], submitted)).toEqual(expected)
  expect(submitted._proof_version).toBe(1)
  if (params._fl_id) expect(submitted._fl_id).toBe(params._fl_id)
  if (kind === 'crossover-place') expect(submitted.crossover_id).toBe(params.crossover_id)
  expect(save).toHaveBeenCalledOnce(); expect(source).toEqual(before)
})

it('shows clear-all as a no-input operation, without a fake scope or redundant Apply', async () => {
  const save = vi.fn(), result = editRoutingFeature(packet('loop-skip-clear-all', {}), { onSave: save })
  expect(document.querySelector('[role="dialog"]').textContent).toMatch(/all loop.*skip/i)
  expect(document.querySelector('[role="dialog"] input')).toBeNull()
  expect(button('Apply')).toBeUndefined()
  expect(document.querySelector('[role="dialog"]').textContent).toMatch(/revert|delete/i)
  button('Close').click(); expect(await result).toBeNull(); expect(save).not.toHaveBeenCalled()
})

it('reorders and removes existing placement slots while newly added slots omit the output ID', async () => {
  const result = editRoutingFeature(packet('crossover-place-batch', { placements: [placement('a0000000-0000-4000-8000-000000000001'), placement('b0000000-0000-4000-8000-000000000002')] }))
  expect(document.querySelector('[aria-label="Placement 1 Output crossover ID"]').tagName).toBe('OUTPUT')
  expect(document.querySelector('[aria-label="Placement 1 Output crossover ID"]').textContent).toBe('a0000000-0000-4000-8000-000000000001')
  document.querySelector('[aria-label="Move placement 2 up"]').click()
  document.querySelector('[aria-label="Remove placement 2"]').click()
  button('Add placement').click()
  set('Placement 2 Half A Helix ID', 'h1'); set('Placement 2 Half B Helix ID', 'h2')
  button('Apply').click()
  const params = await result
  expect(params.placements[0].crossover_id).toBe('b0000000-0000-4000-8000-000000000002')
  expect(params.placements[1]).not.toHaveProperty('crossover_id')
  expect(params.placements).toHaveLength(2)
})

it('exposes prefix choices including domain ordinals rather than consulting current geometry', () => {
  editRoutingFeature(packet('domain-shift', { entries: [{ strand_id: 's1', domain_index: 0, delta_bp: 1 }] }))
  const list = document.querySelector('[aria-label="Entry 1 Strand ID"]').getAttribute('list')
  expect([...document.getElementById(list).options].map(option => option.value)).toEqual(['s1', 's2'])
  expect(document.querySelector('[role="dialog"]').textContent).toContain('1: h2 9→0')
})

it.each([
  ['nick', site, 'Base index', '1.5'],
  ['loop-skip-bend', { helix_ids: ['h1'], plane_a_bp: 0, plane_b_bp: 10, radius_nm: 10 }, 'Radius (nm)', '0'],
  ['crossover-extra-bases', { crossover_id: 'x1', sequence: 'AC' }, 'Sequence', 'AXB'],
])('keeps invalid %s drafts local', async (kind, params, label, value) => {
  const save = vi.fn(); editRoutingFeature(packet(kind, params), { onSave: save })
  set(label, value); button('Apply').click(); await tick()
  expect(save).not.toHaveBeenCalled(); expect(document.querySelector('[role="alert"]').hidden).toBe(false)
})

it('retains a refused draft and refuses a later stale retry without another request', async () => {
  let current = true
  const save = vi.fn(async () => null); const pending = editRoutingFeature(packet('nick', site), { onSave: save, isCurrent: () => current })
  set('Base index', '8'); button('Apply').click(); await tick()
  expect(document.querySelector('[aria-label="Base index"]').value).toBe('8')
  expect(document.querySelector('[role="alert"]').textContent).toMatch(/not accepted/i)
  current = false; button('Apply').click(); await tick(); expect(save).toHaveBeenCalledOnce()
  button('Cancel').click(); expect(await pending).toBeNull()
})

it('retires held publication on same-ID reset and cannot close a replacement editor', async () => {
  let finish
  const old = editRoutingFeature(packet('nick', site), { onSave: () => new Promise(resolve => { finish = resolve }) })
  button('Apply').click(); window.dispatchEvent(new Event('nadoc:document-reset'))
  expect(await old).toBeNull()
  const next = editRoutingFeature(packet('ligate', site))
  finish({ accepted: true }); await tick()
  expect(document.querySelector('[role="dialog"]').textContent).toContain('Ligate')
  button('Cancel').click(); expect(await next).toBeNull()
})
