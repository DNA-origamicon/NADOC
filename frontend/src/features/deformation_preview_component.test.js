import { describe, expect, it } from 'vitest'
import { validateDeformationPreviewComponent, validateDnaComparisonComponent } from './part_dna_comparison_model.js'
import { dnaComponent } from '../test-helpers/part_dna_comparison.js'

function component() {
  return { ...dnaComponent(), component_kind: 'deformation-preview-dna', component_version: 1 }
}

describe('separately versioned native deformation display', () => {
  it('accepts complete native inventory and preserves scoped curved samples without mutation', () => {
    const value = component(), segment = value.helix_axes[0].segments[0]
    segment.samples = [[0, 0, 0], [.1, .2, .17], [0, 0, .34]]
    const before = structuredClone(value)
    expect(validateDeformationPreviewComponent(value)).toBe(value)
    expect(value).toEqual(before)
    expect(() => validateDnaComparisonComponent(value)).toThrow()
  })

  it('does not silently reinterpret the comparison v2 schema', () => {
    const value = dnaComponent()
    expect(validateDnaComparisonComponent(value)).toBe(value)
    expect(() => validateDeformationPreviewComponent(value)).toThrow()
    value.helix_axes[0].segments[0].samples = [[0, 0, 0]]
    expect(() => validateDnaComparisonComponent(value)).toThrow()
  })

  it.each([
    ['wrong family', d => { d.component_kind = 'comparison-dna' }],
    ['wrong version', d => { d.component_version = 2 }],
    ['omitted family', d => { delete d.component_kind }],
    ['extra family', d => { d.display_topology.duplexes = [] }],
    ['omitted nucleotide', d => { d.nucleotides.pop() }],
    ['nonfinite sample', d => { d.helix_axes[0].segments[0].samples = [[NaN, 0, 0]] }],
    ['malformed sample', d => { d.helix_axes[0].segments[0].samples = [[0, 0]] }],
    ['unbounded samples', d => { d.helix_axes[0].segments[0].samples = Array.from({ length: 2049 }, () => [0, 0, 0]) }],
    ['null samples', d => { d.helix_axes[0].segments[0].samples = null }],
    ['unknown segment data', d => { d.helix_axes[0].segments[0].pose = [] }],
  ])('refuses %s', (_name, mutate) => {
    const value = component(); mutate(value)
    expect(() => validateDeformationPreviewComponent(value)).toThrow()
  })

  it('counts every scoped sample occurrence together with global samples and endpoints', () => {
    const value = component(), axis = value.helix_axes[0]
    axis.samples = Array.from({ length: 1022 }, () => [0, 0, 0])
    axis.segments[0].samples = axis.samples
    expect(validateDeformationPreviewComponent(value)).toBe(value) // 2 + 1022 + 2 + 1022
    axis.segments[0].samples = [...axis.samples, [0, 0, 0]]
    expect(() => validateDeformationPreviewComponent(value)).toThrow(/allowance/)
  })
})
