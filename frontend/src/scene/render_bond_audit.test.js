import { describe, expect, it } from 'vitest'
import { auditRenderedBonds, inventoryRenderedElements } from './render_bond_audit.js'

const nuc = (strand_id, bp, position, extra = {}) => ({
  strand_id, helix_id: extra.helix_id ?? strand_id, bp_index: bp,
  direction: 'FORWARD', backbone_position: position, ...extra,
})

describe('render bond audit', () => {
  it('reports live rendered endpoint origins for every >2 nm connector', () => {
    const a = nuc('scaf', 4, [0, 0, 0], { strand_type: 'scaffold' })
    const b = nuc('cap0', 1_000_000, [0, 0, 1], { is_surface_capture: true })
    const entries = [{ nuc: a, pos: { x: 0, y: 0, z: 0 } },
      { nuc: b, pos: { x: 0, y: 0, z: 3 } }]
    const out = auditRenderedBonds(entries, [{ fromNuc: a, toNuc: b, strandId: 'scaf', isCrossHelix: true }], 2)
    expect(out.n_over_threshold).toBe(1)
    expect(out.over_threshold[0]).toMatchObject({ length_nm: 3, render_kind: 'cross_helix_arc',
      from: { strand_id: 'scaf', bp_index: 4 },
      to: { strand_id: 'cap0', is_surface_capture: true } })
  })

  it('inventories capture and ordinary renderer entries separately', () => {
    const a = nuc('scaf', 0, [0, 0, 0])
    const c = nuc('cap0', 1_000_000, [1, 0, 0], { is_surface_capture: true })
    expect(inventoryRenderedElements([{ nuc: a }, { nuc: c }], [{ nuc: c }],
      [{ fromNuc: c, toNuc: c }, { fromNuc: a, toNuc: a, isCrossHelix: true }]))
      .toMatchObject({ beads: 2, slabs: 1, bonds: 2, surface_capture_beads: 1,
        surface_capture_slabs: 1, surface_capture_bonds: 1, cross_helix_bonds: 1 })
  })

  it('flags the actual drawn matrix length even when logical endpoints look short', () => {
    const a = nuc('cap0', 1, [0, 0, 0], { is_surface_capture: true })
    const b = nuc('cap0', 2, [0, 0, 0.8], { is_surface_capture: true })
    const cone = { fromNuc: a, toNuc: b, strandId: 'cap0' }
    const out = auditRenderedBonds([{ nuc: a }, { nuc: b }], [cone], 2, () => 57)
    expect(out.over_threshold[0]).toMatchObject({ length_nm: 0.8, matrix_length_nm: 57,
      endpoint_matrix_delta_nm: 56.2 })
  })
})
