import { afterEach, expect, it, vi } from 'vitest'
import { appendRasterEvidence, appendTableEvidence } from './article_import_evidence.js'
afterEach(() => document.body.replaceChildren())
it('distinguishes raster traces from registered nucleotide paths', () => {
  appendRasterEvidence(document.body, { path_count: 4, placements: [{}, {}], unresolved: ['Polarity unknown.'], truncated: true })
  expect(document.body.textContent).toContain('base registration unresolved')
  expect(document.body.textContent).toContain('Trace limit reached')
})
it('retains unsupported chemistry and selects modules without merging variants', () => {
  const change = vi.fn()
  appendTableEvidence(document.body, { rows: [{ modifications: [{ name: 'Pal', status: 'unsupported_lipid' }], overhang_annotations: [{ label: 'toehold' }] }], pages: [46, 47], notices: [], module_counts: { Top_A: 20, Top_B: 20 } }, change)
  expect(document.body.textContent).toContain('Pal: unsupported lipid')
  expect(document.body.textContent).toContain('toehold: labeled native overhang pending route')
  const select = document.querySelector('select')
  expect(select.selectedOptions.length).toBe(0)
  select.options[0].selected = true; select.dispatchEvent(new Event('change'))
  expect(change).toHaveBeenCalledWith(['Top_A'])
})
it('reports supported image overlap separately from molecular connections', () => {
  appendRasterEvidence(document.body, { path_count: 4, placements: [{}, {}], unresolved: [], truncated: false,
    panel_registration: { comparisons: [{ status: 'supported_image_overlap' }, { status: 'ambiguous_or_no_overlap' }] } })
  expect(document.body.textContent).toContain('1 supported panel overlap(s)')
  expect(document.body.textContent).toContain('without assigning molecular connections')
})
it('reports classified staple traces without claiming complete strands', () => {
  appendRasterEvidence(document.body, { path_count: 4, placements: [{}], unresolved: [],
    classified_tracing: { panels: [{ lane_classification: { status: 'panel_pattern_supported' },
      traces: [{ kind: 'staple', status: 'unbranched_staple_trace' }, { kind: 'staple', status: 'staple_trace_fragment' }, { kind: 'scaffold', status: 'scaffold_trace' }] }] } })
  expect(document.body.textContent).toContain('1/1 panel placements support scaffold/staple lane classification')
  expect(document.body.textContent).toContain('2 classified staple traces (1 unbranched)')
  expect(document.body.textContent).toContain('fragments, not complete strands')
  expect(document.body.textContent).toContain('scaffold strokes are excluded')
})
it('shows connector drawings separately from unresolved hypotheses and marker evidence', () => {
  appendRasterEvidence(document.body, { path_count: 0, placements: [{}], unresolved: [],
    classified_tracing: { connector_drawing_count: 2, connector_candidate_count: 5, offset_marker_count: 1,
      panels: [{ lane_classification: { status: 'panel_pattern_supported' }, traces: [] }] } })
  expect(document.body.textContent).toContain('2 same-helix connector drawing(s)')
  expect(document.body.textContent).toContain('5 unresolved connector hypothesis/hypotheses')
  expect(document.body.textContent).toContain('1 offset endpoint-marker observation(s)')
  expect(document.body.textContent).toContain('drawing lengths are excluded from base counts')
})
