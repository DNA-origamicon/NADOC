import { describe, expect, it } from 'vitest'
import { canConvertExtraThymines } from './cpd_selection.js'
import { transformTargetsForSelection } from './nucleotide_transform_tool.js'
const keys = ['__xb__:a:0', '__xb__:b:1']
const design = { crossovers: [{ id: 'a', extra_bases: 'T' }, { id: 'b', extra_bases: 'AT' }] }
const formed = { ...design, photoproduct_junctions: [{ base_key_1: keys[0], base_key_2: keys[1], design_coordinates: { [keys[0]]: { C5: [0, 0, 0] } } }] }
describe('CPD authoring selection', () => {
  it('offers conversion only for two distinct, unused extra thymines', () => {
    expect(canConvertExtraThymines(design, keys)).toBe(true)
    for (const bad of [[keys[0]], [keys[0], keys[0]], [keys[0], '__xb__:b:0'], [keys[0], 'h:1:FORWARD']]) expect(canConvertExtraThymines(design, bad)).toBe(false)
    expect(canConvertExtraThymines(formed, keys)).toBe(false)
  })
  it('moves the entire product from either base or either crossover', () => {
    for (const ref of [{ kind: 'base', key: keys[0] }, { kind: 'base', key: keys[1] }, { kind: 'crossover', id: 'a' }, { kind: 'crossover', id: 'b' }]) {
      const targets = transformTargetsForSelection({ currentDesign: formed, selection: { items: [ref] } })
      expect(targets.map(t => `${t.crossover_id}:${t.k}`).sort()).toEqual(['a:0', 'b:1'])
    }
  })
})
