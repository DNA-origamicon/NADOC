import { describe, it, expect } from 'vitest'
import { endTagFor, selectionClass, groupOverhangs } from './assembly_overhang_list_panel.js'

describe('assembly_overhang_list_panel pure helpers', () => {
  it('endTagFor: 5p/3p suffix → tag, else empty', () => {
    expect(endTagFor('oh-A_5p')).toBe("5'")
    expect(endTagFor('oh-B_3p')).toBe("3'")
    expect(endTagFor('oh-mid')).toBe('')
    expect(endTagFor(null)).toBe('')
  })

  it('selectionClass: order → Side A / Side B / generic', () => {
    expect(selectionClass(0)).toBe('ct-selected-a')
    expect(selectionClass(1)).toBe('ct-selected-b')
    expect(selectionClass(2)).toBe('is-selected')
    expect(selectionClass(5)).toBe('is-selected')
  })

  it('groupOverhangs: groups per instance, sorts by label, carries end tag', () => {
    const designs = {
      'inst-A': { overhangs: [{ id: 'oh-A-link_5p', label: 'z-link' }, { id: 'oh-A-bind_5p', label: 'a-bind' }] },
      'inst-B': { overhangs: [{ id: 'oh-B_3p' }] },   // no label → falls back to id
    }
    const assembly = {
      instances: [
        { id: 'inst-A', name: 'PartA' },
        { id: 'inst-B', name: 'PartB', source: { design: designs['inst-B'] } },
      ],
    }
    // inst-A resolved via injected resolver; inst-B via inline source fallback.
    const resolve = (inst) => designs[inst.id] ?? inst?.source?.design ?? null
    const groups = groupOverhangs(assembly, resolve)
    expect(groups.map(g => g.name)).toEqual(['PartA', 'PartB'])
    // sorted by label: 'a-bind' before 'z-link'
    expect(groups[0].overhangs.map(o => o.label)).toEqual(['a-bind', 'z-link'])
    expect(groups[0].overhangs[0].endTag).toBe("5'")
    // inst-B label falls back to id; 3' tag
    expect(groups[1].overhangs[0].label).toBe('oh-B_3p')
    expect(groups[1].overhangs[0].endTag).toBe("3'")
  })

  it('groupOverhangs: unresolved design → empty overhang list, still lists the part', () => {
    const groups = groupOverhangs({ instances: [{ id: 'x', name: 'X' }] }, () => null)
    expect(groups).toEqual([{ instanceId: 'x', name: 'X', overhangs: [] }])
  })

  it('groupOverhangs: null assembly → []', () => {
    expect(groupOverhangs(null, () => null)).toEqual([])
  })
})
