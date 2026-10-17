import { describe, expect, it } from 'vitest'
import { validateDnaComparisonComponent } from './part_dna_comparison_model.js'
import { decodeDnaComparisonRecords } from './part_dna_comparison_codec.js'
import { validatePartComparisonEnvelope } from './part_comparison_model.js'
import { comparisonBinding } from '../test-helpers/part_comparison.js'
import { dnaComponent, dnaEnvelope, dnaRecord, dnaRow } from '../test-helpers/part_dna_comparison.js'

describe('closed DNA comparison transport', () => {
  it('decodes every fixed-row value exactly and accepts only an explicitly requested version', () => {
    const value = dnaEnvelope(), before = JSON.stringify(value)
    expect(decodeDnaComparisonRecords(JSON.parse(JSON.stringify(value.published.dna.nucleotides)))).toEqual([dnaRecord(0), dnaRecord(1)])
    expect(() => validatePartComparisonEnvelope(value, comparisonBinding())).toThrow()
    expect(validatePartComparisonEnvelope(value, { ...comparisonBinding(), projectionVersion: 2 })).toBe(value)
    expect(JSON.stringify(value)).toBe(before)
  })

  it.each([
    ['extra family', d => { d.display_topology.duplexes = [] }],
    ['reapplied pose', d => { d.display_topology.helices[0].pose = [] }],
    ['unknown component', d => { d.component_version = 1 }],
    ['unbounded empty helix', d => { d.display_topology.helices[0].length_bp = 1e8 }],
    ['remote tail', d => { d.display_topology.strands[0].domains[0].end_bp = 1e6 }],
    ['missing record', d => { d.nucleotides.pop() }],
    ['duplicate record', d => { d.nucleotides[1] = d.nucleotides[0] }],
    ['unknown row field', d => { d.nucleotides[0].push(true) }],
    ['missing row field', d => { d.nucleotides[0].pop() }],
    ['nonfinite coordinate', d => { d.nucleotides[0] = dnaRow({ ...dnaRecord(), backbone_position: [NaN, 0, 0] }) }],
    ['missing axis', d => { d.helix_axes = [] }],
    ['missing domain segment', d => { d.helix_axes[0].segments = [] }],
    ['ambiguous occupancy', d => { d.display_topology.strands[0].domains.push({ ...d.display_topology.strands[0].domains[0] }) }],
    ['owner change', d => { d.nucleotides[0] = dnaRow({ ...dnaRecord(), strand_id: 'other' }) }],
    ['flexible segment', d => { d.nucleotides[0] = dnaRow({ ...dnaRecord(), is_flexible_segment: true }) }],
    ['unresolved overhang', d => { d.display_topology.strands[0].domains[0].overhang_id = 'missing' }],
    ['extra bases', d => { d.display_topology.crossovers = [{ id: 'x', half_a: {}, half_b: {}, extra_bases: 'T' }] }],
  ])('refuses %s before native scene allocation', (_name, mutate) => {
    const value = dnaComponent(); mutate(value)
    expect(() => validateDnaComparisonComponent(value)).toThrow()
  })

  it('preserves distinct insertion copies and reference ownership', () => {
    const value = dnaComponent()
    value.display_topology.helices[0].loop_skips = [{ bp_index: 0, delta: 1 }]
    value.display_topology.strands[0].is_reference = true
    value.nucleotides = [dnaRow({ ...dnaRecord(), is_reference: true }),
      dnaRow({ ...dnaRecord(), copy_k: 1, is_reference: true }), dnaRow({ ...dnaRecord(1), is_reference: true })]
    expect(validateDnaComparisonComponent(value)).toBe(value)
    const records = decodeDnaComparisonRecords(value.nucleotides)
    expect(records.map(n => n.copy_k)).toEqual([0, 1, 0])
    expect(records.every(n => n.is_reference)).toBe(true)
  })

  it('requires frozen display provenance to identify the exact bounded domain', () => {
    const value = dnaComponent()
    value.display_topology.deformations = [{ id: 'd', type: 'bend', affected_helix_ids: ['h'],
      plane_a_bp: 0, plane_b_bp: 1, params: { curvature_deg_per_bp: 2 },
      target_ranges: [{ helix_id: 'h', start_bp: 0, end_bp: 1, direction: 'FORWARD', strand_id: 's', domain_index: 0 }] }]
    expect(validateDnaComparisonComponent(value)).toBe(value)
    value.display_topology.deformations[0].target_ranges[0].end_bp = 2
    expect(() => validateDnaComparisonComponent(value)).toThrow(/owner/)
  })
})
