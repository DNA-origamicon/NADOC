import { describe, expect, it } from 'vitest'
import { patternOrganizationChoices } from './pattern_organization.js'

function design() {
  return {
    helices: [{ id: 'h' }, { id: 'outside' }, { id: 'reference' }],
    strands: [{ id: 's', domains: [{ helix_id: 'h' }, { helix_id: 'outside' }] },
      { id: 'ref', is_reference: true, domains: [{ helix_id: 'reference' }] }],
    cluster_transforms: [{ id: 'same', helix_ids: ['h', 'reference'] }],
    group_organization: { version: 1, groups: [
      { id: 'same', name: 'Different namespace', helix_ids: ['outside'] },
      { id: 'whole', name: 'Whole', helix_ids: ['h'] },
      { id: 'partial', name: 'Partial', helix_ids: ['outside'], domain_ids: [{ strand_id: 's', domain_index: 0 }] },
      { id: 'projected-only', helix_ids: ['h'], domain_ids: [{ strand_id: 's', domain_index: 1 }] },
      { id: 'empty-required', helix_ids: [], domain_ids: [] },
      { id: 'reference-only', helix_ids: ['reference'] },
    ] },
    deformations: [{ affected_helix_ids: ['h'], targets: [{ kind: 'part_group', id: 'empty-required' }] }],
  }
}

describe('pattern organization choices', () => {
  it('defaults intersecting group metadata with domain precedence and separate placement identities', () => {
    const source = design(), before = JSON.stringify(source)
    const choices = patternOrganizationChoices(source, ['same'])
    expect(choices.defaultIds).toEqual(['whole', 'partial', 'empty-required'])
    expect(choices.requiredIds).toEqual(['empty-required'])
    expect(choices.missingIds).toEqual([])
    expect(choices.groups.map(group => group.id)).toEqual(['whole', 'partial', 'empty-required'])
    expect(JSON.stringify(source)).toBe(before)
  })

  it('reports missing named targets instead of substituting a same-text placement', () => {
    const source = design()
    source.deformations[0].targets = [{ kind: 'part_group', id: 'missing' }]
    source.cluster_transforms.push({ id: 'missing', helix_ids: ['h'] })
    expect(patternOrganizationChoices(source, ['same']).missingIds).toEqual(['missing'])
  })

  it('only requires targets of deformations actually copied by the native affected-helix rule', () => {
    const source = design()
    source.deformations.push(
      { affected_helix_ids: [], targets: [{ kind: 'part_group', id: 'unscoped' }] },
      { affected_helix_ids: ['outside'], targets: [{ kind: 'part_group', id: 'elsewhere' }] },
      { affected_helix_ids: ['reference'], targets: [{ kind: 'part_group', id: 'ref' }] },
      { affected_helix_ids: ['h'], targets: [{ kind: 'cluster', id: 'placement-only' }] },
    )
    expect(patternOrganizationChoices(source, ['same']).requiredIds).toEqual(['empty-required'])
    expect(patternOrganizationChoices(source, ['same']).missingIds).toEqual([])
  })

  it('returns no organization contract for legacy input and never falls back from a missing placement', () => {
    const source = design()
    expect(patternOrganizationChoices(source, ['absent']).defaultIds).toEqual([])
    delete source.group_organization
    expect(patternOrganizationChoices(source, ['same'])).toBeNull()
  })

  it('keeps mixed reference and authored helices eligible under the native reference rule', () => {
    const source = design()
    source.strands.push({ id: 'authored', domains: [{ helix_id: 'reference' }] })
    expect(patternOrganizationChoices(source, ['same']).defaultIds).toContain('reference-only')
  })
})
