import { describe, it, expect } from 'vitest'
import { _overhangLabelAnchorsLocal, _OVHG_RADIAL_OFFSET } from './assembly_overhang_labels.js'

// Pins the pure anchor math after the assembly_renderer.js split. Both render
// paths derive their overhang-name sprite positions from this one function.

const nuc = (o) => ({ direction: 'FORWARD', base_normal: null, ...o })

describe('_overhangLabelAnchorsLocal', () => {
  it('returns [] when the design has no overhangs or the geometry is empty', () => {
    expect(_overhangLabelAnchorsLocal(null, [])).toEqual([])
    expect(_overhangLabelAnchorsLocal({ overhangs: [] }, [nuc({ overhang_id: 'o1' })])).toEqual([])
    expect(_overhangLabelAnchorsLocal({ overhangs: [{ id: 'o1', label: 'A' }] }, [])).toEqual([])
  })

  it('skips overhangs with no label and overhangs with no nucleotides', () => {
    const design = { overhangs: [{ id: 'o1', label: '' }, { id: 'o2', label: 'B' }, { id: 'o3', label: 'C' }] }
    const nucs = [
      nuc({ overhang_id: 'o1', bp_index: 0, backbone_position: [0, 0, 0] }),
      nuc({ overhang_id: 'o2', bp_index: 0, backbone_position: [1, 2, 3] }),
      // o3 has a label but no geometry
    ]
    const out = _overhangLabelAnchorsLocal(design, nucs)
    expect(out.map(a => a.overhangId)).toEqual(['o2'])
  })

  it('anchors at the MIDDLE nucleotide of the overhang, ordered by bp_index', () => {
    const design = { overhangs: [{ id: 'o1', label: 'tag' }] }
    // deliberately unsorted; midpoint of 3 sorted nucs is index 1 → z = 20
    const nucs = [
      nuc({ overhang_id: 'o1', bp_index: 2, backbone_position: [0, 0, 30] }),
      nuc({ overhang_id: 'o1', bp_index: 0, backbone_position: [0, 0, 10] }),
      nuc({ overhang_id: 'o1', bp_index: 1, backbone_position: [0, 0, 20] }),
    ]
    const [a] = _overhangLabelAnchorsLocal(design, nucs)
    expect(a).toMatchObject({ overhangId: 'o1', label: 'tag', x: 0, y: 0, z: 20 })
  })

  it('REVERSE strands sort descending, so the midpoint is taken from the 3′ walk', () => {
    const design = { overhangs: [{ id: 'o1', label: 'r' }] }
    const nucs = [
      nuc({ overhang_id: 'o1', direction: 'REVERSE', bp_index: 0, backbone_position: [0, 0, 10] }),
      nuc({ overhang_id: 'o1', direction: 'REVERSE', bp_index: 1, backbone_position: [0, 0, 20] }),
      nuc({ overhang_id: 'o1', direction: 'REVERSE', bp_index: 2, backbone_position: [0, 0, 30] }),
    ]
    // descending sort → [30, 20, 10]; midpoint index 1 is still z=20
    expect(_overhangLabelAnchorsLocal(design, nucs)[0].z).toBe(20)
  })

  it('offsets the anchor radially along the normalized base_normal (x/y only)', () => {
    const design = { overhangs: [{ id: 'o1', label: 'n' }] }
    const nucs = [nuc({ overhang_id: 'o1', bp_index: 0, backbone_position: [1, 1, 5], base_normal: [3, 4, 99] })]
    const [a] = _overhangLabelAnchorsLocal(design, nucs)
    expect(a.x).toBeCloseTo(1 + 0.6 * _OVHG_RADIAL_OFFSET, 10)
    expect(a.y).toBeCloseTo(1 + 0.8 * _OVHG_RADIAL_OFFSET, 10)
    expect(a.z).toBe(5)   // z is never offset
  })

  it('applies no offset for a degenerate (zero-length in xy) base_normal', () => {
    const design = { overhangs: [{ id: 'o1', label: 'n' }] }
    const nucs = [nuc({ overhang_id: 'o1', bp_index: 0, backbone_position: [7, 8, 9], base_normal: [0, 0, 1] })]
    const [a] = _overhangLabelAnchorsLocal(design, nucs)
    expect([a.x, a.y, a.z]).toEqual([7, 8, 9])
  })

  it('ignores nucleotides that belong to no overhang', () => {
    const design = { overhangs: [{ id: 'o1', label: 'x' }] }
    const nucs = [
      nuc({ bp_index: 0, backbone_position: [99, 99, 99] }),          // no overhang_id
      nuc({ overhang_id: 'o1', bp_index: 0, backbone_position: [1, 0, 0] }),
    ]
    expect(_overhangLabelAnchorsLocal(design, nucs)).toHaveLength(1)
  })
})
