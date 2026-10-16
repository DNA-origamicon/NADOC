import { describe, expect, it } from 'vitest'
import {
  hasOrganization, partGroupById, partGroupMemberFilter, partGroupIdsForNucleotide,
  partGroupNucKeys, partGroupNucKeysFor, withPartGroupDisplay,
} from './part_group_display.js'
import { clusterAlphaKeys, clusterAlphaForNuc, clusterDisplaySignature } from './cluster_entries.js'
import { buildClusterColorLookup } from './helix_renderer/palette.js'
import { computeAtomNucColors, computeAtomNucAlphas, computeAtomStrandColors,
  computeAtomStrandAlphas } from './color_util.js'

function source() {
  return {
    strands: [
      { id: 's', domains: [
        { helix_id: 'h1', start_bp: 0, end_bp: 1, direction: 'FORWARD' },
        { helix_id: 'h2', start_bp: 1, end_bp: 0, direction: 'REVERSE' },
      ] },
      { id: 'other', domains: [{ helix_id: 'h2', start_bp: 0, end_bp: 1, direction: 'FORWARD' }] },
    ],
    extensions: [{ id: 'five', strand_id: 's', end: 'five_prime' },
      { id: 'three', strand_id: 's', end: 'three_prime' }],
    cluster_transforms: [{ id: 'same', helix_ids: ['h1', 'h2'], color: '#00ff00', opacity: .01,
      translation: [4, 5, 6], rotation: [0, 0, 0, 1] }],
    group_organization: { version: 1, groups: [
      { id: 'whole', helix_ids: ['h1', 'h2'], domain_ids: [], color: '#0000ff', opacity: .4 },
      { id: 'same', helix_ids: ['h1', 'h2'], domain_ids: [{ strand_id: 's', domain_index: 1 }],
        color: '#ff0000', opacity: .8 },
      { id: 'empty', helix_ids: [], domain_ids: [], color: '#ffffff', opacity: 0 },
    ] },
  }
}
const nuc = (helix_id, strand_id, domain_index) => ({ helix_id, strand_id, domain_index })
const selected = nuc('h2', 's', 1)

describe('organization display uses one membership policy', () => {
  it('keeps the same-text placement separate and gives domain refs exclusive precedence', () => {
    const design = source(), group = partGroupById(design, 'same')
    expect(hasOrganization(design)).toBe(true)
    expect(group).toBe(design.group_organization.groups[1])
    const member = partGroupMemberFilter(group, design)
    expect(member(selected)).toBe(true)
    expect(member(nuc('h1', 's', 0))).toBe(false)
    expect(member(nuc('h2', 'other', 0))).toBe(false)
    expect(partGroupIdsForNucleotide(selected, design)).toEqual(['whole', 'same'])
    expect(partGroupIdsForNucleotide(nuc('h1', 's', 0), design)).toEqual(['whole'])
  })

  it('allows domain-only groups and leaves empty groups empty', () => {
    const design = source()
    const only = { id: 'only', helix_ids: [], domain_ids: [{ strand_id: 's', domain_index: 1 }] }
    expect(partGroupMemberFilter(only, design)(selected)).toBe(true)
    expect(partGroupMemberFilter(partGroupById(design, 'empty'), design)(selected)).toBe(false)
    expect(partGroupNucKeys(partGroupById(design, 'empty'), design)).toEqual(new Set())
  })

  it('extends only the selected terminal domain into its own tail', () => {
    const design = source(), group = partGroupById(design, 'same')
    expect(partGroupNucKeys(group, design)).toEqual(new Set(['d:s:1', 'h:__ext_three']))
    const member = partGroupMemberFilter(group, design)
    expect(member(nuc('__ext_three', 's', 2))).toBe(true)
    expect(member(nuc('__ext_five', 's', -1))).toBe(false)
    expect(partGroupNucKeysFor(design, ['same', 'missing', 'empty']))
      .toEqual(new Set(['d:s:1', 'h:__ext_three']))
  })

  it('does not fall back to placement styles for an empty or unsupported active wrapper', () => {
    for (const organization of [{ version: 1, groups: [] }, { version: 99, groups: [] }]) {
      const design = { ...source(), group_organization: organization }
      expect(hasOrganization(design)).toBe(true)
      expect(buildClusterColorLookup(design)(selected)).toBeUndefined()
      expect(clusterAlphaKeys(design).size).toBe(0)
      expect(partGroupById(design, 'same')).toBeNull()
    }
  })

  it('shares immutable snapshot membership without retaining returned mutable key sets', () => {
    const design = source(), group = partGroupById(design, 'same')
    const member = partGroupMemberFilter(group, design)
    expect(partGroupMemberFilter(group, design)).toBe(member)
    const keys = partGroupNucKeys(group, design)
    keys.clear()
    expect(partGroupNucKeys(group, design).size).toBe(2)
    const changed = { ...design, group_organization: { version: 1, groups: [
      { ...group, domain_ids: [{ strand_id: 's', domain_index: 0 }] },
    ] } }
    expect(partGroupIdsForNucleotide(selected, changed)).toEqual([])
    expect(member(selected)).toBe(true)
  })

  it('does not index topology when no organizational IDs are requested', () => {
    const design = { group_organization: { version: 1, groups: [] },
      get strands() { throw new Error('No membership lookup is needed') } }
    expect(partGroupNucKeysFor(design, [])).toEqual(new Set())
    expect(partGroupNucKeysFor(design, new Set())).toEqual(new Set())
    expect(partGroupNucKeysFor(design)).toEqual(new Set())
  })
})

describe('organization color and opacity agree across display representations', () => {
  it('takes minimum opacity across whole-helix and domain overlaps without placement alpha', () => {
    const design = source()
    expect(clusterAlphaForNuc(clusterAlphaKeys(design), selected)).toBe(.4)
    expect(clusterAlphaForNuc(clusterAlphaKeys(design), nuc('h1', 's', 0))).toBe(.4)
    expect(computeAtomNucAlphas(design).get('h2:1:REVERSE')).toBe(.4)
    expect(computeAtomNucAlphas(design).get('__ext_three')).toBe(.4)
    const faded = withPartGroupDisplay(design, 'same', { opacity: .2 })
    expect(clusterAlphaForNuc(clusterAlphaKeys(faded), selected)).toBe(.2)
    expect(computeAtomNucAlphas(faded).get('h2:0:FORWARD')).toBe(.4)
    expect(computeAtomStrandAlphas(faded).get('s')).toBe(.2)
  })

  it('uses the same domain-tier color for beads, atoms, tails and the old strand fallback', () => {
    const design = source(), color = buildClusterColorLookup(design)
    expect(color(selected)).toBe(0xff0000)
    expect(color(nuc('h1', 's', 0))).toBe(0x0000ff)
    expect(color(nuc('h2', 'other', 0))).toBe(0x0000ff)
    expect(color(nuc('__ext_three', 's', 2))).toBe(0xff0000)
    expect(color(nuc('__ext_five', 's', -1))).toBe(0x0000ff)
    const state = { currentDesign: design, coloringMode: 'cluster', strandColors: {} }
    const colors = computeAtomNucColors(state)
    expect(colors.get('h2:1:REVERSE')).toBe(0xff0000)
    expect(colors.get('__ext_three')).toBe(0xff0000)
    expect(colors.get('__ext_five')).toBe(0x0000ff)
    expect(computeAtomStrandColors(state, null).get('s')).toBe(0x0000ff)
  })

  it('keeps a terminal domain color when a whole-helix group appears later in authored order', () => {
    const design = source()
    design.group_organization.groups.reverse()
    const color = buildClusterColorLookup(design)
    expect(color(selected)).toBe(0xff0000)
    expect(color(nuc('__ext_three', 's', 2))).toBe(0xff0000)
  })

  it('ranks manual over auto, explicit over palette and later equal-rank groups last', () => {
    const design = source(), manual = design.group_organization.groups[1]
    design.group_organization.groups.push(
      { ...manual, id: 'palette', color: null },
      { ...manual, id: 'automatic', auto_created: true, color: '#ffffff' },
    )
    expect(buildClusterColorLookup(design)(selected)).toBe(0xff0000)
    const later = { ...design, group_organization: { version: 1, groups: [
      ...design.group_organization.groups, { ...manual, id: 'later', color: '#ffff00' },
    ] } }
    expect(buildClusterColorLookup(later)(selected)).toBe(0xffff00)
    expect(computeAtomNucColors({ currentDesign: later, coloringMode: 'cluster' }).get('h2:1:REVERSE'))
      .toBe(0xffff00)
  })

  it('style preview changes only the explicit organization, never ordered placement models', () => {
    const design = source(), before = JSON.stringify(design)
    const updated = withPartGroupDisplay(design, 'same', { color: '', opacity: .25,
      translation: [9, 9, 9], helix_ids: ['wrong'] })
    expect(updated.cluster_transforms).toBe(design.cluster_transforms)
    expect(updated.group_organization.groups[0]).toBe(design.group_organization.groups[0])
    expect(partGroupById(updated, 'same')).toEqual({ ...partGroupById(design, 'same'), color: null, opacity: .25 })
    expect(JSON.stringify(design)).toBe(before)
    expect(withPartGroupDisplay(design, 'absent', { opacity: 0 })).toBe(design)
  })

  it('display invalidation follows organization membership/style, not numerical pose', () => {
    const design = source(), before = clusterDisplaySignature(design)
    expect(clusterDisplaySignature({ ...design, cluster_transforms: [
      { ...design.cluster_transforms[0], translation: [8, 9, 10], color: '#ffffff' },
    ] })).toBe(before)
    expect(clusterDisplaySignature(withPartGroupDisplay(design, 'same', { color: '#aaaaaa' }))).not.toBe(before)
    const changed = { ...design, group_organization: { version: 1, groups: [
      { ...partGroupById(design, 'same'), domain_ids: [{ strand_id: 's', domain_index: 0 }] },
    ] } }
    expect(clusterDisplaySignature(changed)).not.toBe(before)
  })
})
