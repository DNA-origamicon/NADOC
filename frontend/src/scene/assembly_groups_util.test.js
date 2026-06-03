import { describe, it, expect } from 'vitest'
import { computeGroupHiddenInstanceIds } from './assembly_groups_util.js'

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
