import { afterEach, expect, it, vi } from 'vitest'
import { editExtrusionFeature, isNativeExtrusionFeature } from './extrusion_feature_editor.js'

const field = label => document.querySelector(`[aria-label="${label}"]`)
const button = text => [...document.querySelectorAll('button')].find(node => node.textContent === text)
function input(label, value) { const node = field(label); node.value = String(value); node.dispatchEvent(new Event(node.tagName === 'SELECT' ? 'change' : 'input')) }
const flush = async () => { await Promise.resolve(); await Promise.resolve() }
const common = { history_seed: 'saved-seed', _proof_version: 1, separate_fresh_extrusions: true, cells: [[0, 0], [1, 0]], length_bp: 21, plane: 'XY' }
const rows = {
  'bundle-create': { ...common, name: 'Original', lattice_type: 'HONEYCOMB', strand_filter: 'both', ligate_adjacent: true },
  'extrude-segment': { ...common, offset_nm: 3, strand_filter: 'both', ligate_adjacent: true },
  'extrude-continuation': { ...common, offset_nm: 3, source_frame_id: 'saved-frame', extend_inplace: true, strand_filter: 'both', ligate_adjacent: true, _source_helix_ids: ['saved-source'] },
  'extrude-deformed-continuation': { ...common, ref_helix_id: 'saved-helix', source_bp: 21, grid_origin: [1, 2, 3], axis_dir: [0, 0, 1], frame_right: [1, 0, 0], frame_up: [0, 1, 0] },
  'circle-segment': { ...common, length_bp: undefined, cell_lengths: [21, 35], offset_nm: 3, strand_filter: 'both', ligate_adjacent: true },
  'extrude-frame': { ...common, name: 'Frame', translation_nm: [1, 2, 3], rotation_xyzw: [0, 0, 0, 1], source_frame_id: null, source_legacy_plane: false },
  'overhang-extrude': { history_seed: 'saved-seed', _proof_version: 1, helix_id: 'saved-helix', bp_index: 13, direction: 'FORWARD', is_five_prime: false, neighbor_row: 1, neighbor_col: 2, length_bp: 7, reuse_existing_helix: true },
}
function entry(kind, patch = {}) { return { id: 'feature', feature_type: 'snapshot', op_kind: kind, label: kind, params: structuredClone(rows[kind]), ...patch } }
afterEach(() => { window.dispatchEvent(new Event('nadoc:document-reset')); document.body.innerHTML = '' })

it.each(Object.keys(rows))('recognizes native %s independently of evicted recovery', kind => {
  const value = entry(kind, { evicted: true })
  expect(isNativeExtrusionFeature(value)).toBe(true)
  for (const patch of [{ params: { ...value.params, _proof_version: 2 } }, { feature_type: 'minor' }, { params: { ...value.params, _proof_version: true } }, { params: { ...value.params, history_seed: null } }, { params: { ...value.params, _generated_scope: {} } }, { params: { ...value.params, _generator: {} } }]) expect(isNativeExtrusionFeature({ ...value, ...patch })).toBe(false)
})

it.each([
  ['bundle-create', 'Name', 'Renamed', { name: 'Renamed' }],
  ['extrude-segment', 'Length (bp)', -14, { length_bp: -14 }],
  ['extrude-continuation', 'Source frame ID', 'other-frame', { source_frame_id: 'other-frame' }],
  ['extrude-deformed-continuation', 'Source bp', -7, { source_bp: -7 }],
  ['circle-segment', 'Cell 2 length (bp)', 42, { cell_lengths: [21, 42] }],
  ['extrude-frame', 'Translation X (nm)', -5, { translation_nm: [-5, 2, 3] }],
  ['overhang-extrude', 'Neighbor column', -3, { neighbor_col: -3 }],
])('edits full %s inputs while preserving hidden identities', async (kind, label, value, expected) => {
  const original = entry(kind), before = structuredClone(original), onSave = vi.fn(async () => ({}))
  const pending = editExtrusionFeature(original, { onSave })
  input(label, value); button('Save').click()
  expect(await pending).toMatchObject(expected)
  expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ ...expected, history_seed: 'saved-seed', _proof_version: 1 }))
  expect(original).toEqual(before)
  expect(document.querySelector('textarea')).toBeNull()
})

it('edits cells with paired circle lengths and preserves order when adding/removing', async () => {
  const pending = editExtrusionFeature(entry('circle-segment'))
  input('Cell 1 row', -2); button('Add cell').click()
  input('Cell 3 row', 4); input('Cell 3 column', 5); input('Cell 3 length (bp)', 11)
  field('Remove cell 2').click(); button('Save').click()
  expect(await pending).toMatchObject({ cells: [[-2, 0], [4, 5]], cell_lengths: [21, 11] })
})

it('exposes common plane, filter, ligation and separation without inventing source receipts', async () => {
  const pending = editExtrusionFeature(entry('extrude-continuation'))
  input('Plane', 'YZ'); input('Strands', 'staples'); input('Offset (nm)', -2.5)
  field('Ligate adjacent ends').click(); field('Separate fresh extrusions').click(); field('Extend existing helix in place').click()
  button('Save').click()
  expect(await pending).toMatchObject({ plane: 'YZ', strand_filter: 'staples', offset_nm: -2.5, ligate_adjacent: false,
    separate_fresh_extrusions: false, extend_inplace: false, _source_helix_ids: ['saved-source'] })
})

it('makes recomputed deformed-frame vectors read-only, and permits explicit saved-frame mode', async () => {
  const pending = editExtrusionFeature(entry('extrude-deformed-continuation'))
  expect(field('Grid origin X (nm)').disabled).toBe(true)
  input('Frame definition', 'saved')
  expect(field('Grid origin X (nm)').disabled).toBe(false)
  input('Grid origin X (nm)', 8); input('Reference helix ID', 'other')
  button('Save').click()
  expect(await pending).toMatchObject({ source_bp: null, ref_helix_id: 'other', grid_origin: [8, 2, 3] })
})

it.each(['source', 'legacy'])('switches frame extrusion to explicit %s mode without ambiguous free placement', async mode => {
  const pending = editExtrusionFeature(entry('extrude-frame'))
  input('Frame source', mode)
  if (mode === 'source') input('Source frame ID', 'selected-frame')
  expect(field('Translation X (nm)').disabled).toBe(true)
  button('Save').click()
  expect(await pending).toMatchObject({ source_frame_id: mode === 'source' ? 'selected-frame' : null,
    source_legacy_plane: mode === 'legacy', translation_nm: [0, 0, 0], rotation_xyzw: [0, 0, 0, 1] })
})

it('edits every overhang endpoint selector including polarity, end and reuse', async () => {
  const pending = editExtrusionFeature(entry('overhang-extrude'))
  input('Source helix ID', 'new-source'); input('Endpoint bp', 5); input('Direction', 'REVERSE'); input('Strand end', '5')
  input('Neighbor row', -2); field('Reuse existing helix').click(); button('Save').click()
  expect(await pending).toMatchObject({ helix_id: 'new-source', bp_index: 5, direction: 'REVERSE', is_five_prime: true,
    neighbor_row: -2, reuse_existing_helix: false })
})

it.each([
  ['extrude-segment', 'Length (bp)', 0], ['extrude-segment', 'Cell 1 row', 0.5],
  ['circle-segment', 'Cell 1 length (bp)', -1], ['overhang-extrude', 'Length (bp)', -1],
  ['extrude-frame', 'Rotation W', 0],
])('keeps invalid %s %s draft without sending', async (kind, label, value) => {
  const onSave = vi.fn(); const pending = editExtrusionFeature(entry(kind), { onSave })
  input(label, value); button('Save').click(); await flush()
  expect(onSave).not.toHaveBeenCalled(); expect(document.querySelector('[role="alert"]').textContent).toBeTruthy()
  button('Cancel').click(); expect(await pending).toBeNull()
})

it('retains refused drafts and blocks stale retry without reading current source choices', async () => {
  let current = true
  const onSave = vi.fn(async () => null), pending = editExtrusionFeature(entry('extrude-segment'), { onSave, isCurrent: () => current })
  input('Length (bp)', -28); button('Save').click(); await flush()
  expect(field('Length (bp)').value).toBe('-28'); expect(document.querySelector('[role="alert"]').textContent).toMatch(/accept|refus|fail/i)
  current = false; button('Save').click(); await flush(); expect(onSave).toHaveBeenCalledTimes(1)
  expect(document.querySelector('[role="alert"]').textContent).toMatch(/changed/i)
  button('Cancel').click(); expect(await pending).toBeNull()
})

it.each([
  ['extrude-segment', 'Length (bp)', -25_001],
  ['circle-segment', 'Cell 1 length (bp)', 50_000],
  ['overhang-extrude', 'Length (bp)', 50_001],
])('shows the existing work limit before submitting %s', async (kind, label, value) => {
  const onSave = vi.fn(), pending = editExtrusionFeature(entry(kind), { onSave })
  input(label, value); button('Save').click(); await flush()
  expect(onSave).not.toHaveBeenCalled()
  expect(document.querySelector('[role="alert"]').textContent).toMatch(/50,000/)
  expect(field(label).value).toBe(String(value))
  button('Cancel').click(); expect(await pending).toBeNull()
})

it('retires a held save on reset and its late result cannot close a replacement modal', async () => {
  let finish
  const old = editExtrusionFeature(entry('extrude-segment'), { onSave: () => new Promise(resolve => { finish = resolve }) })
  button('Save').click(); window.dispatchEvent(new Event('nadoc:document-reset')); expect(await old).toBeNull()
  const next = editExtrusionFeature(entry('overhang-extrude'))
  finish({}); await flush(); expect(field('Source helix ID')).not.toBeNull()
  button('Cancel').click(); expect(await next).toBeNull()
})
