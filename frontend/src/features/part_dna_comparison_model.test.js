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

  it('keeps frozen addresses historical while validating actual live geometry owners', () => {
    const value = dnaComponent()
    value.display_topology.deformations = [{ id: 'd', type: 'bend', affected_helix_ids: ['h'],
      plane_a_bp: 0, plane_b_bp: 1, params: { curvature_deg_per_bp: 2 },
      target_ranges: [{ helix_id: 'h', start_bp: 0, end_bp: 7, direction: 'FORWARD', strand_id: 'old-strand', domain_index: 9 }] }]
    expect(validateDnaComparisonComponent(value)).toBe(value)
    value.helix_axes[0].segments[0].domain_ids[0].domain_index = 9
    expect(() => validateDnaComparisonComponent(value)).toThrow(/domain/)
  })

  it.each([
    ['missing helix', r => { r.helix_id = 'missing' }],
    ['one-sided address', r => { r.strand_id = null }],
    ['missing ordinal', r => { r.domain_index = null }],
    ['boolean ordinal', r => { r.domain_index = true }],
    ['negative ordinal', r => { r.domain_index = -1 }],
    ['unbounded interval', r => { r.end_bp = 1000001 }],
    ['unordered range', r => { r.start_bp = 8 }],
  ])('refuses malformed historical frozen provenance: %s', (_name, mutate) => {
    const value = dnaComponent(), range = { helix_id: 'h', start_bp: 0, end_bp: 7, direction: 'REVERSE', strand_id: 'old', domain_index: 9 }
    value.display_topology.deformations = [{ id: 'd', type: 'twist', affected_helix_ids: ['h'],
      plane_a_bp: 0, plane_b_bp: 1, params: {}, target_ranges: [range] }]
    mutate(range); expect(() => validateDnaComparisonComponent(value)).toThrow()
  })

  it('carries organization membership independently from same-named placement owners', () => {
    const value = dnaComponent(), before = structuredClone(value)
    value.display_topology.cluster_transforms = [{ id: 'same', name: 'Placement', is_default: false,
      helix_ids: ['h'], domain_ids: [], color: null, auto_created: false }]
    value.display_topology.group_organization = { version: 1, groups: [{ id: 'same', name: 'Organization',
      helix_ids: [], domain_ids: [{ strand_id: 's', domain_index: 0 }], color: '#123456', opacity: .5,
      is_default: false, auto_created: false }] }
    expect(validateDnaComparisonComponent(value)).toBe(value)
    expect(value.nucleotides).toEqual(before.nucleotides)
    expect(value.helix_axes).toEqual(before.helix_axes)
    value.display_topology.group_organization.groups[0].domain_ids[0].domain_index = 9
    expect(() => validateDnaComparisonComponent(value)).toThrow(/domain/)
  })

  it.each([
    ['version', org => { org.version = true }],
    ['pose', org => { org.groups[0].translation = [0, 0, 0] }],
    ['unknown owner', org => { org.groups[0].helix_ids = ['missing'] }],
    ['duplicate identity', org => { org.groups.push({ ...org.groups[0] }) }],
    ['opacity', org => { org.groups[0].opacity = 2 }],
    ['duplicate member', org => { org.groups[0].helix_ids = ['h', 'h'] }],
  ])('refuses unsupported organization %s', (_name, mutate) => {
    const value = dnaComponent()
    value.display_topology.group_organization = { version: 1, groups: [{ id: 'org', name: 'Arm', helix_ids: ['h'],
      domain_ids: [], color: null, opacity: 1, is_default: false, auto_created: false }] }
    mutate(value.display_topology.group_organization)
    expect(() => validateDnaComparisonComponent(value)).toThrow()
  })
})


it('charges organization groups and membership occurrences against the shared selector budget', () => {
  const value = dnaComponent(), group = { id: 'g'.repeat(512), name: 'Arm', helix_ids: ['h'], domain_ids: [],
    color: null, opacity: 1, is_default: false, auto_created: false }
  value.display_topology.group_organization = { version: 1, groups: [group] }
  expect(validateDnaComparisonComponent(value)).toBe(value)
  value.display_topology.group_organization.groups = Array.from({ length: 256 }, (_, i) => ({ ...group, id: `g${i}` }))
  expect(validateDnaComparisonComponent(value)).toBe(value)
  value.display_topology.cluster_transforms = [{ id: 'p', name: 'Placement', helix_ids: ['h'], domain_ids: [],
    color: null, is_default: false, auto_created: false }]
  expect(() => validateDnaComparisonComponent(value)).toThrow(/selector allowance/)
})
