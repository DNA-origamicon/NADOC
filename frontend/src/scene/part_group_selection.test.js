import { describe, expect, it } from 'vitest'
import { normalizeSelectionRef, isSelectionRefLive, selectionRefKey } from './selection_ref.js'
import { createSelectionState, reconcileSelection, selectedPartGroupIds, selectedClusterIds } from './selection_model.js'
import { selectionHighlightDescriptor } from './selection_highlight_model.js'
import { deformationTargets, targetState } from './deformation_targets.js'
import { sceneGroupRef, groupRefMemberFilter, groupSelectionMembers } from './part_group_selection.js'
import { matchTargetEntries, createTargetEntryMatcher, describeTarget } from './annotation_targets.js'

import { groupDesign } from '../test-helpers/part_groups.js'

const nuc = { helix_id: 'h', strand_id: 's', domain_index: 1 }

describe('organizational selection stays separate from placement', () => {
  it('normalizes equal IDs into distinct identities and projections', () => {
    const group = { kind: 'part_group', id: 'same', translation: [9, 0, 0] }
    expect(normalizeSelectionRef(group)).toEqual({ kind: 'part_group', id: 'same' })
    expect(selectionRefKey(group)).not.toBe(selectionRefKey({ kind: 'cluster', id: 'same' }))
    const state = createSelectionState({ items: [group, { kind: 'cluster', id: 'same' }] })
    expect(selectedPartGroupIds(state)).toEqual(['same'])
    expect(selectedClusterIds(state)).toEqual(['same'])
    expect(selectionHighlightDescriptor(state)).toMatchObject({ partGroupIds: ['same'], clusterIds: ['same'] })
  })
  it('drops only the deleted namespace during live reconciliation', () => {
    const design = groupDesign(), refs = [{ kind: 'part_group', id: 'same' }, { kind: 'cluster', id: 'same' }]
    design.group_organization.groups = []
    expect(reconcileSelection(createSelectionState({ items: refs }), ref => isSelectionRefLive(ref, design)).items).toEqual([refs[1]])
    expect(isSelectionRefLive(refs[0], { ...design, group_organization: null })).toBe(false)
  })
  it('picks current matching group then authored order, never placement fallback', () => {
    const design = groupDesign()
    expect(sceneGroupRef(nuc, design)).toEqual({ kind: 'part_group', id: 'same' })
    expect(sceneGroupRef(nuc, design, { selection: createSelectionState({ items: [{ kind: 'part_group', id: 'whole' }] }) })).toEqual({ kind: 'part_group', id: 'whole' })
    expect(sceneGroupRef({ ...nuc, helix_id: 'outside', strand_id: 'outside' }, design)).toBeNull()
    expect(sceneGroupRef(nuc, { ...design, group_organization: { version: 1, groups: [] } })).toBeNull()
    expect(sceneGroupRef(nuc, design, { mode: 'placements' })).toEqual({ kind: 'cluster', id: 'same' })
    expect(sceneGroupRef(nuc, { ...design, group_organization: null })).toEqual({ kind: 'cluster', id: 'same' })
  })
  it('uses domain precedence for click/hover/highlight matching', () => {
    const design = groupDesign()
    const matches = groupRefMemberFilter({ kind: 'part_group', id: 'same' }, design)
    expect(matches(nuc)).toBe(true)
    expect(matches({ ...nuc, domain_index: 0 })).toBe(false)
    expect(groupRefMemberFilter({ kind: 'part_group', id: 'empty' }, design)(nuc)).toBe(false)
    expect(groupRefMemberFilter({ kind: 'cluster', id: 'same' }, design)({ ...nuc, domain_index: 0 })).toBe(true)
  })
  it('captures exact selected domains for regrouping without widening strands to helices', () => {
    const design = groupDesign(), before = structuredClone(design)
    expect(groupSelectionMembers(design, [{ kind: 'domain', strandId: 's', domainIndex: 1 }])).toEqual({ helix_ids: ['h'], domain_ids: [{ strand_id: 's', domain_index: 1 }] })
    expect(groupSelectionMembers(design, [{ kind: 'strand', id: 's' }, { kind: 'domain', strandId: 's', domainIndex: 1 }]).domain_ids).toEqual([{ strand_id: 's', domain_index: 0 }, { strand_id: 's', domain_index: 1 }])
    expect(design).toEqual(before)
    expect(() => groupSelectionMembers(design, [{ kind: 'domain', strandId: 's', domainIndex: 9 }])).toThrow()
  })
  it('frames and labels the named group in both indexed and direct selection presentation', () => {
    const design = groupDesign()
    design.extensions = [{ id: 'five', strand_id: 's', end: 'five_prime' }, { id: 'three', strand_id: 's', end: 'three_prime' }]
    const entries = [
      { nuc: { ...nuc, domain_index: 0 }, pos: { x: 0, y: 0, z: 0 } },
      { nuc, pos: { x: 1, y: 0, z: 0 } },
      { nuc: { helix_id: '__ext_five' }, pos: { x: 2, y: 0, z: 0 } },
      { nuc: { helix_id: '__ext_three' }, pos: { x: 3, y: 0, z: 0 } },
    ]
    const refs = [{ kind: 'part_group', id: 'same' }]
    expect(matchTargetEntries(refs, design, entries)).toEqual([entries[1], entries[3]])
    expect(createTargetEntryMatcher()(refs, design, entries)).toEqual([entries[1], entries[3]])
    expect(describeTarget(refs, design)).toBe('Group · Named tail')
    expect(matchTargetEntries([{ kind: 'part_group', id: 'missing' }], design, entries)).toEqual([])
  })
})

describe('ordinary named deformation selection', () => {
  it('preserves named provenance and resolves only the selected native domain bounds', () => {
    const design = groupDesign(), refs = [{ kind: 'part_group', id: 'same' }]
    const before = structuredClone(design)
    expect(deformationTargets(targetState(design, refs))).toEqual({ targets: refs,
      ranges: [{ helixId: 'h', lo: 22, hi: 30 }], error: null })
    expect(design).toEqual(before)
  })
  it('uses the full native helix extent for a whole-helix named group', () => {
    expect(deformationTargets(targetState(groupDesign(), [{ kind: 'part_group', id: 'whole' }])).ranges).toEqual([{ helixId: 'h', lo: 10, hi: 39 }])
  })
  it.each(['missing', 'empty', 'legacy', 'bad-domain', 'bad-helix', 'bad-index'])('refuses %s without global or placement fallback', failure => {
    const design = groupDesign()
    let id = failure === 'missing' ? 'missing' : failure === 'empty' ? 'empty' : 'same'
    if (failure === 'legacy') design.group_organization = null
    if (failure === 'bad-domain') design.group_organization.groups[0].domain_ids[0].strand_id = 'missing'
    if (failure === 'bad-helix') design.strands[0].domains[1].helix_id = 'missing'
    if (failure === 'bad-index') design.group_organization.groups[0].domain_ids[0].domain_index = true
    const result = deformationTargets(targetState(design, [{ kind: 'part_group', id }]))
    expect(result.error).toBeTruthy()
    expect(result.ranges).toEqual([])
  })
})
