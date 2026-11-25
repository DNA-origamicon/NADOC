import { afterEach, expect, it, vi } from 'vitest'
import { createArticleDesignSelection } from './article_design_selection.js'
let api
const q = s => document.querySelector(s)
afterEach(() => { api?.dispose(); document.body.replaceChildren() })
const candidate = id => ({ id, label: `Design ${id}`, context: 'caDNAno diagram', image: 'data:image/png;base64,AA==', rows: 6, branches: 12,
  observed_paths: [1, 2], route_hypotheses_tested: 2, limitations: ['Topology unverified.'], pairings: [{ list_id: 'list1', label: 'Pointer staples', list_rows: 161,
    basis: 'sequence agreement', direction_resolved: false, alternatives: [{ matched_staples: 3, list_rows: 161, scaffold_direction: 'reversed', staple_direction: 'drawn',
      scaffold_offset: 17, evidence_score: 4.2, paired_bases_verified: 90, unknown_bases: 4, calibration: { method: 'test scale', points_per_base: 2 } }] }] })
function mount(fetchImpl) {
  const body = document.createElement('div'); document.body.append(body)
  api = createArticleDesignSelection({ body, fetchImpl, readPayload: async () => ({ paper: { name: 'paper.pdf', data: 'eA==' } }) })
}
it('selects multiple detected designs and shows alternative directions for a chosen list', async () => {
  mount(vi.fn().mockResolvedValue({ ok: true, json: async () => ({ designs: [candidate('one'), candidate('two')], staple_lists: [{}], notes: [] }) }))
  q('[data-analyze]').click()
  await vi.waitFor(() => expect(document.querySelectorAll('.article-design-card')).toHaveLength(2))
  q('[data-design-id="one"]').click(); q('[data-design-id="two"]').click()
  expect(api.selectedDesigns()).toEqual(['one', 'two'])
  expect(q('[data-selection-status]').textContent).toContain('2 detected design(s) selected')
  const select = q('select'); select.value = 'list1'; select.dispatchEvent(new Event('change'))
  expect(q('[data-pairing-evidence]').textContent).toContain('Direction or register unresolved')
  expect(q('[data-pairing-evidence]').textContent).toContain('scaffold reversed')
  expect(q('[data-pairing-evidence]').textContent).toContain('not a reconstruction probability')
  api.reset()
  expect(api.selectedDesigns()).toEqual([])
  expect(document.querySelectorAll('.article-design-card')).toHaveLength(0)
})
it('cancels detection and ignores stale results', async () => {
  let resolve
  const fetchImpl = vi.fn(() => new Promise(r => { resolve = r }))
  mount(fetchImpl); q('[data-analyze]').click()
  await vi.waitFor(() => expect(fetchImpl).toHaveBeenCalledOnce())
  q('[data-analysis-cancel]').click()
  expect(fetchImpl.mock.calls[0][1].signal.aborted).toBe(true)
  resolve({ ok: true, json: async () => ({ designs: [candidate('late')], staple_lists: [], notes: [] }) })
  await Promise.resolve(); await Promise.resolve()
  expect(q('[data-analysis-status]').textContent).toBe('Analysis canceled.')
  expect(q('[data-designs]').children).toHaveLength(0)
})
it('reports missing inputs without manufacturing candidates', async () => {
  mount(vi.fn().mockResolvedValue({ ok: false, json: async () => ({ detail: 'Upload paper or supplement PDFs.' }) }))
  q('[data-analyze]').click()
  await vi.waitFor(() => expect(q('[data-analysis-status]').textContent).toContain('Upload paper'))
  expect(q('[data-designs]').children).toHaveLength(0)
  expect(q('[data-analyze]').disabled).toBe(false)
})

it('displays recovered topology separately from a molecular model', async () => {
  const design = candidate('pointer')
  design.pairings[0].routing_recovered = true
  design.pairings[0].routing = { directed_paths: { scaf: [[]], stap: Array.from({ length: 161 }, () => []) }, deletions: [[36, 126]] }
  mount(vi.fn().mockResolvedValue({ ok: true, json: async () => ({ designs: [design], staple_lists: [{}], notes: [] }) }))
  q('[data-analyze]').click()
  await vi.waitFor(() => expect(q('select')).not.toBeNull())
  q('select').value = 'list1'; q('select').dispatchEvent(new Event('change'))
  expect(q('[data-routing-recovered]').textContent).toContain('161 staples, 1 deletion')
  expect(q('[data-routing-recovered]').textContent).toContain('molecular geometry has not been built')
})

it('distinguishes publication endpoint evidence from complete reconstruction', async () => {
  const design = candidate('published')
  design.pairings[0].alternatives = []
  design.pairings[0].publication_evidence = { matched_staples: 217, table_rows: 217, lengths_agree: 217,
    base_index_offset: 0, scaffold_paths: 1, unclassified_paths: 0, unit_insertions_resolved: 360,
    unresolved_insertions: 0, limitation: 'Completeness remains unverified.' }
  mount(vi.fn().mockResolvedValue({ ok: true, json: async () => ({ designs: [design], staple_lists: [{}], notes: [] }) }))
  q('[data-analyze]').click()
  await vi.waitFor(() => expect(q('select')).not.toBeNull())
  q('select').value = 'list1'; q('select').dispatchEvent(new Event('change'))
  expect(q('[data-publication-routing]').textContent).toContain('217/217 published staple endpoint pairs')
  expect(q('[data-publication-routing]').textContent).toContain('360 unit insertions resolved')
  expect(q('[data-pairing-evidence]').textContent).toContain('sequence complementarity remains unverified')
  expect(q('[data-pairing-evidence]').textContent).not.toContain('shared caption/list labels only')
  expect(q('[data-routing-recovered]')).toBeNull()
})

it('shows exhaustive sequence validation separately from native reconstruction', async () => {
  const design = candidate('aligned')
  design.pairings[0].alternatives = []
  design.pairings[0].publication_evidence = { matched_staples: 217, table_rows: 217, lengths_agree: 217,
    base_index_offset: 0, scaffold_paths: 1, unclassified_paths: 0, limitation: 'Geometry remains unverified.',
    sequence_search: { resolved: true, scaffold_name: 'p8064', candidates_tested: 16128, best_ties: 1,
      runner_up_mismatches: 5551, nick_note: 'Physical nick is not moved.',
      best: { mismatches: 0, compared_bases: 7919, exact_staples: 217, offset: 0, reverse: false } } }
  mount(vi.fn().mockResolvedValue({ ok: true, json: async () => ({ designs: [design], staple_lists: [{}], notes: [] }) }))
  q('[data-analyze]').click()
  await vi.waitFor(() => expect(q('select')).not.toBeNull())
  q('select').value = 'list1'; q('select').dispatchEvent(new Event('change'))
  expect(q('[data-sequence-search]').textContent).toContain('16128 direction/shift candidates tested')
  expect(q('[data-sequence-search]').textContent).toContain('0 mismatches across 7919 paired bases')
  expect(q('[data-pairing-evidence]').textContent).not.toContain('sequence complementarity remains unverified')
})

it('shows incomplete table coverage even when recovered routes align exactly', async () => {
  const design = candidate('partial')
  design.pairings[0].alternatives = []
  design.pairings[0].publication_evidence = { matched_staples: 187, table_rows: 197, lengths_agree: 187,
    base_index_offset: 0, scaffold_paths: 1, unclassified_paths: 0, limitation: 'Incomplete evidence.',
    sequence_search: { resolved: false, alignment_resolved: true, scaffold_name: 'custom', candidates_tested: 100,
      best_ties: 1, runner_up_mismatches: 33, unmatched_table_rows: 10, invalid_staple_rows: [],
      selection_basis: 'user-supplied sequence', nick_note: 'Physical nick is not moved.',
      best: { mismatches: 0, compared_bases: 50, exact_staples: 187, offset: 7, reverse: false, unknown_bases: 0 } } }
  mount(vi.fn().mockResolvedValue({ ok: true, json: async () => ({ designs: [design], staple_lists: [{}], notes: [] }) }))
  q('[data-analyze]').click()
  await vi.waitFor(() => expect(q('select')).not.toBeNull())
  q('select').value = 'list1'; q('select').dispatchEvent(new Event('change'))
  expect(q('[data-sequence-search]').textContent).toContain('Unmatched table rows: 10')
  expect(q('[data-pairing-evidence]').textContent).not.toContain('matches every supplied staple exactly')
})

it('shows supported loops and penalizes the off-by-one candidate without calling it exact reconstruction', async () => {
  const design = candidate('loops')
  design.pairings[0].alternatives = []
  design.pairings[0].publication_evidence = { matched_staples: 187, table_rows: 197, lengths_agree: 187,
    base_index_offset: 0, scaffold_paths: 1, unclassified_paths: 0, limitation: 'Incomplete topology.',
    sequence_search: { resolved: false, status: 'supported_with_length_discrepancy', scaffold_name: 'p7704',
      candidates_tested: 100, best_ties: 1, runner_up_mismatches: 408, length_discrepancy: 1,
      represented_length: 7703, scaffold_length: 7704, length_discrepancy_note: 'No topology was changed.',
      best: { mismatches: 0, compared_bases: 6686, exact_staples: 129, offset: 0, reverse: false },
      insertion_hypothesis: { sequence_supported: true, counts: [[30,119,39], [42,119,39]] },
      confidence: { score: 80.96, kind: 'Heuristic evidence score, not a probability.',
        penalties: [{ reason: 'one-base scaffold length discrepancy', points: 10 }] } } }
  mount(vi.fn().mockResolvedValue({ ok: true, json: async () => ({ designs: [design], staple_lists: [{}], notes: [] }) }))
  q('[data-analyze]').click()
  await vi.waitFor(() => expect(q('select')).not.toBeNull())
  q('select').value = 'list1'; q('select').dispatchEvent(new Event('change'))
  expect(q('[data-scaffold-loops]').textContent).toContain('helix 30, base 119: 39 inserted bases')
  expect(q('[data-sequence-confidence]').textContent).toContain('−10.00 points')
  expect(q('[data-length-discrepancy]').textContent).toContain('7703 bases; sequence: 7704 bases')
  expect(q('[data-pairing-evidence]').textContent).not.toContain('matches every supplied staple exactly')
})
