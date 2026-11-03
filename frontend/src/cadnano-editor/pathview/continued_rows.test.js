import { describe, expect, it } from 'vitest'
import { buildContinuedRows, continuedHelixGroups, continuedHelixLabels, helixAtRowBp, reorderContinuedRows, rowPaintRanges } from './continued_rows.js'

// Minimal topology records, not authored/saved NADOC documents.
function input() {
  const h = (id, bp, frame, cell = [0, 1]) => ({ id, bp_start: bp, length_bp: 42,
    lattice_frame_id: frame, grid_pos: cell, direction: 'FORWARD' })
  const d = (id, a, b, direction = 'FORWARD') => ({ helix_id: id, start_bp: a, end_bp: b, direction })
  return {
    helices: [h('a', 0, 'original'), h('b', 0, 'original', [1, 1]), h('s', 42, 'sweep')],
    strands: [{ domains: [d('a', 0, 41), d('s', 42, 83)] },
      { domains: [d('s', 83, 42, 'REVERSE'), d('a', 41, 0, 'REVERSE')] }],
    deformations: [{ type: 'sweep', plane_a_bp: 42, plane_b_bp: 83,
      affected_helix_ids: ['s'], params: { start_step: 1, direction: 1 } }],
  }
}
const options = { cellOf: h => ({ row: h.grid_pos[0], col: h.grid_pos[1] }), forwardOf: () => true }
const ids = design => continuedHelixGroups(design).map(group => group.map(h => h.id))

describe('continued helix rows', () => {
  it('uses one row for a certified Sweep continuation and preserves native identities', () => {
    const design = input(), before = structuredClone(design)
    const { rows, rowMap } = buildContinuedRows(design, options)
    expect(rows).toHaveLength(2)
    expect(rowMap.get('a')).toBe(rowMap.get('s'))
    expect(rowMap.get('b').fwdY).not.toBe(rowMap.get('a').fwdY)
    expect(continuedHelixLabels(design).get('s')).toBe(0)
    expect(design).toEqual(before)
  })

  it('resolves picking and painting to the actual segment at the boundary and outer ends', () => {
    const row = buildContinuedRows(input(), options).rows[0]
    expect([-5, 0, 41, 42, 83, 90].map(bp => helixAtRowBp(row, bp)))
      .toEqual(['a', 'a', 'a', 's', 's', 's'])
    expect(rowPaintRanges(row, 38, 45)).toEqual([
      { helixId: 'a', lo: 38, hi: 41 }, { helixId: 's', lo: 42, hi: 45 },
    ])
    expect(rowPaintRanges(row, -2, 90)).toEqual([
      { helixId: 'a', lo: -2, hi: 41 }, { helixId: 's', lo: 42, hi: 90 },
    ])
    expect(helixAtRowBp(null, 0)).toBeNull()
  })

  it('moves complete rows in both display orientations and retains every member', () => {
    const design = input()
    const normal = buildContinuedRows(design, options).rows
    expect(reorderContinuedRows(normal, new Set(['s']), 2, true)).toEqual(['b', 'a', 's'])
    expect(reorderContinuedRows(normal, new Set(['a']), 0, true)).toBeNull()
    const reversed = buildContinuedRows(design, { ...options, nativeOrientation: false }).rows
    expect(reversed.map(r => r.hid)).toEqual(['b', 'a'])
    expect(reorderContinuedRows(reversed, new Set(['s']), 0, false)).toEqual(['b', 'a', 's'])
  })

  it('does not merge disconnected duplicate cells, detached sweeps or reference strands', () => {
    for (const change of [d => { d.strands = [] }, d => { d.deformations = [] },
      d => { d.deformations[0].params.start_step = 0 },
      d => { d.strands.forEach(s => { s.is_reference = true }) }]) {
      const design = input(); change(design)
      expect(ids(design)).toEqual([['a'], ['b'], ['s']])
    }
  })

  it('retains the row when a nick interrupts only one complementary strand', () => {
    const design = input()
    design.strands.shift()
    expect(ids(design)).toEqual([['a', 's'], ['b']])
  })

  it('retains certified attached rows after both strands are nicked, but not detached rows', () => {
    const design = input()
    design.strands = []
    design.deformations[0].id = 'sweep_123'
    design.feature_log = [{ op_kind: 'sweep', params: { sweep_id: '123', source_helix_id: 'a', detach_source: false } }]
    expect(ids(design)).toEqual([['a', 's'], ['b']])
    design.feature_log[0].params.detach_source = true
    expect(ids(design)).toEqual([['a'], ['b'], ['s']])
  })

  it('handles attachments at the starting face and repeated Sweeps', () => {
    const design = input()
    design.helices[2].bp_start = -42
    design.strands = [{ domains: [
      { helix_id: 's', start_bp: -42, end_bp: -1, direction: 'FORWARD' },
      { helix_id: 'a', start_bp: 0, end_bp: 41, direction: 'FORWARD' },
    ] }]
    Object.assign(design.deformations[0], { plane_a_bp: -42, plane_b_bp: -1 })
    design.deformations[0].params.direction = -1
    expect(ids(design)).toEqual([['a', 's'], ['b']])
    const row = buildContinuedRows(design, options).rows[0]
    expect(helixAtRowBp(row, -1)).toBe('s')
    expect(helixAtRowBp(row, 0)).toBe('a')

    const chain = input()
    chain.helices.push({ ...chain.helices[2], id: 's2', bp_start: 84, lattice_frame_id: 'sweep2' })
    chain.strands[0].domains.push({ helix_id: 's2', start_bp: 84, end_bp: 125, direction: 'FORWARD' })
    chain.deformations.push({ type: 'sweep', plane_a_bp: 84, plane_b_bp: 125, affected_helix_ids: ['s2'], params: { start_step: 1, direction: 1 } })
    expect(ids(chain)).toEqual([['a', 's', 's2'], ['b']])
  })

  it('leaves inserted junctions and ambiguous overlapping continuations separate', () => {
    const design = input()
    design.helices.push({ ...design.helices[2], id: 'other' })
    design.deformations[0].affected_helix_ids.push('other')
    design.strands.push({ domains: [design.strands[0].domains[0], { ...design.strands[0].domains[1], helix_id: 'other' }] })
    expect(ids(design)).toEqual([['a'], ['b'], ['s'], ['other']])
    const noSweep = input()
    noSweep.deformations = []
    noSweep.forced_ligations = [{ three_prime_helix_id: 'a', three_prime_bp: 41, three_prime_direction: 'FORWARD',
      five_prime_helix_id: 's', five_prime_bp: 42, five_prime_direction: 'FORWARD', extra_bases: 'A' }]
    expect(ids(noSweep)).toEqual([['a'], ['b'], ['s']])
    noSweep.forced_ligations[0].extra_bases = ''
    expect(ids(noSweep)).toEqual([['a', 's'], ['b']])
  })
})
