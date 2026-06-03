import { describe, it, expect } from 'vitest'
import { computeGroupHiddenInstanceIds, collectGroupMemberInstanceIds, findOwningGroupId } from './assembly_groups_util.js'

const set = (s) => [...s].sort()

describe('computeGroupHiddenInstanceIds', () => {
  it('empty when there are no groups', () => {
    expect([...computeGroupHiddenInstanceIds({})]).toEqual([])
    expect([...computeGroupHiddenInstanceIds(undefined)]).toEqual([])
  })

  it('collects instance ids of a hidden group', () => {
    const assembly = { groups: [{ id: 'g1', visible: false, instance_ids: ['a', 'b'] }] }
    expect(set(computeGroupHiddenInstanceIds(assembly))).toEqual(['a', 'b'])
  })

  it('ignores visible groups', () => {
    const assembly = { groups: [{ id: 'g1', visible: true, instance_ids: ['a'] }, { id: 'g2', instance_ids: ['b'] }] }
    expect([...computeGroupHiddenInstanceIds(assembly)]).toEqual([])
  })

  it('recurses into subgroups of a hidden group', () => {
    const assembly = { groups: [
      { id: 'g1', visible: false, instance_ids: ['a'], subgroup_ids: ['g2'] },
      { id: 'g2', instance_ids: ['b', 'c'], subgroup_ids: ['g3'] },
      { id: 'g3', instance_ids: ['d'] },
    ] }
    expect(set(computeGroupHiddenInstanceIds(assembly))).toEqual(['a', 'b', 'c', 'd'])
  })

  it('a visible subgroup under a hidden parent is still hidden (parent drives)', () => {
    const assembly = { groups: [
      { id: 'g1', visible: false, subgroup_ids: ['g2'] },
      { id: 'g2', visible: true, instance_ids: ['x'] },
    ] }
    expect(set(computeGroupHiddenInstanceIds(assembly))).toEqual(['x'])
  })

  it('tolerates a dangling subgroup id', () => {
    const assembly = { groups: [{ id: 'g1', visible: false, instance_ids: ['a'], subgroup_ids: ['missing'] }] }
    expect(set(computeGroupHiddenInstanceIds(assembly))).toEqual(['a'])
  })
})

describe('collectGroupMemberInstanceIds', () => {
  it('collects a group\'s instance ids, recursing subgroups (order preserved)', () => {
    const asm = { groups: [
      { id: 'g1', instance_ids: ['a', 'b'], subgroup_ids: ['g2'] },
      { id: 'g2', instance_ids: ['c'], subgroup_ids: ['g3'] },
      { id: 'g3', instance_ids: ['d'] },
    ] }
    expect(collectGroupMemberInstanceIds(asm, 'g1').sort()).toEqual(['a', 'b', 'c', 'd'])
  })
  it('returns only the subtree under the requested group', () => {
    const asm = { groups: [
      { id: 'g1', instance_ids: ['a'] },
      { id: 'g2', instance_ids: ['b'] },
    ] }
    expect(collectGroupMemberInstanceIds(asm, 'g2')).toEqual(['b'])
  })
  it('empty for an unknown group or null assembly', () => {
    expect(collectGroupMemberInstanceIds({ groups: [] }, 'nope')).toEqual([])
    expect(collectGroupMemberInstanceIds(null, 'g1')).toEqual([])
  })
})

describe('findOwningGroupId', () => {
  const asm = { groups: [
    { id: 'g1', instance_ids: ['a', 'b'] },
    { id: 'g2', instance_ids: ['c'] },
  ] }
  it('finds the group directly containing the instance', () => {
    expect(findOwningGroupId(asm, 'c')).toBe('g2')
    expect(findOwningGroupId(asm, 'a')).toBe('g1')
  })
  it('null when no group owns it / null assembly', () => {
    expect(findOwningGroupId(asm, 'zzz')).toBeNull()
    expect(findOwningGroupId(null, 'a')).toBeNull()
  })
})
