import { describe, it, expect } from 'vitest'
import { computeGroupHiddenInstanceIds, collectGroupMemberInstanceIds, findOwningGroupId, resolveGroupClickThrough } from './assembly_groups_util.js'

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

describe('resolveGroupClickThrough', () => {
  const asm = { groups: [
    { id: 'g1', instance_ids: ['a', 'b'] },
    { id: 'g2', instance_ids: ['c'] },
  ] }

  it('no hit → none (click on empty space)', () => {
    expect(resolveGroupClickThrough({ assembly: asm, hitInstanceId: null, activeGroupId: null })
      .action).toBe('none')
  })

  it('ungrouped part → none (falls through to normal select)', () => {
    expect(resolveGroupClickThrough({ assembly: asm, hitInstanceId: 'ungrouped', activeGroupId: null })
      .action).toBe('none')
  })

  it('first click on a grouped part → selectGroup with full reset patch', () => {
    const r = resolveGroupClickThrough({ assembly: asm, hitInstanceId: 'a', activeGroupId: null, groupDiveStack: [] })
    expect(r.action).toBe('selectGroup')
    expect(r.patch).toEqual({
      activeGroupId: 'g1', activeInstanceId: null, multiSelectedInstanceIds: [], groupDiveStack: [],
    })
  })

  it('click a grouped part while a DIFFERENT group is active → selectGroup (switch)', () => {
    const r = resolveGroupClickThrough({ assembly: asm, hitInstanceId: 'c', activeGroupId: 'g1' })
    expect(r.action).toBe('selectGroup')
    expect(r.patch.activeGroupId).toBe('g2')
  })

  it('click a member of the ACTIVE group → enterGroup, pushes gid onto dive stack', () => {
    const r = resolveGroupClickThrough({ assembly: asm, hitInstanceId: 'b', activeGroupId: 'g1', groupDiveStack: [] })
    expect(r.action).toBe('enterGroup')
    expect(r.patch).toEqual({ activeGroupId: null, groupDiveStack: ['g1'] })
  })

  it('enterGroup preserves an existing dive stack (append, not replace)', () => {
    const r = resolveGroupClickThrough({ assembly: asm, hitInstanceId: 'a', activeGroupId: 'g1', groupDiveStack: ['gx'] })
    expect(r.patch.groupDiveStack).toEqual(['gx', 'g1'])
  })

  it('does not mutate the passed-in dive stack', () => {
    const stack = ['gx']
    resolveGroupClickThrough({ assembly: asm, hitInstanceId: 'a', activeGroupId: 'g1', groupDiveStack: stack })
    expect(stack).toEqual(['gx'])
  })
})
