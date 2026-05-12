import { describe, expect, it } from 'vitest'
import { linkerLengthToBases, resolveLinkerAttachAnchor } from './overhang_link_arcs.js'

describe('overhang ss linker helpers', () => {
  it('converts persisted linker length to rendered base count', () => {
    expect(linkerLengthToBases({ length_value: 12, length_unit: 'bp' })).toBe(12)
    expect(linkerLengthToBases({ length_value: 4.0, length_unit: 'nm' })).toBe(12)
    expect(linkerLengthToBases({ length_value: 0, length_unit: 'bp' })).toBe(1)
  })

  it('anchors to the linker complement nucleotide when geometry contains it', () => {
    const nucs = [
      {
        overhang_id: 'oh_a_5p',
        helix_id: 'oh_helix',
        bp_index: 7,
        backbone_position: [1, 2, 3],
        is_five_prime: true,
      },
      {
        strand_id: '__lnk__conn1__a',
        helix_id: 'oh_helix',
        bp_index: 7,
        backbone_position: [9, 8, 7],
      },
    ]

    const anchor = resolveLinkerAttachAnchor(nucs, 'conn1', 'a', 'oh_a_5p', 'free_end')

    expect(anchor.usedLinkerComplement).toBe(true)
    expect(anchor.pos.toArray()).toEqual([9, 8, 7])
  })

  it('falls back to the overhang nucleotide before linker complement geometry exists', () => {
    const nucs = [{
      overhang_id: 'oh_a_5p',
      helix_id: 'oh_helix',
      bp_index: 0,
      backbone_position: [1, 2, 3],
      is_five_prime: true,
    }]

    const anchor = resolveLinkerAttachAnchor(nucs, 'conn1', 'a', 'oh_a_5p', 'free_end')

    expect(anchor.usedLinkerComplement).toBe(false)
    expect(anchor.pos.toArray()).toEqual([1, 2, 3])
  })

  it('ss linker: anchors on the single __s strand instead of __a/__b', () => {
    // Single-strand ss topology (Phase 7): the complement nucleotides live
    // on `__lnk__{conn}__s`, NOT on per-side __a / __b. The anchor lookup
    // must reach them when caller passes linkerType='ss'.
    const nucs = [
      {
        overhang_id: 'oh_a_5p',
        helix_id: 'oh_helix',
        bp_index: 7,
        backbone_position: [1, 2, 3],
        is_five_prime: true,
      },
      {
        // ss-style strand id — complement on side A's helix at same bp.
        strand_id: '__lnk__conn1__s',
        helix_id: 'oh_helix',
        bp_index: 7,
        backbone_position: [9, 8, 7],
      },
    ]

    // Default (linkerType='ds') misses the __s strand → falls back to OH nuc.
    const dsAnchor = resolveLinkerAttachAnchor(nucs, 'conn1', 'a', 'oh_a_5p', 'free_end')
    expect(dsAnchor.usedLinkerComplement).toBe(false)
    expect(dsAnchor.pos.toArray()).toEqual([1, 2, 3])

    // Passing linkerType='ss' finds the __s complement.
    const ssAnchor = resolveLinkerAttachAnchor(nucs, 'conn1', 'a', 'oh_a_5p', 'free_end', 'ss')
    expect(ssAnchor.usedLinkerComplement).toBe(true)
    expect(ssAnchor.pos.toArray()).toEqual([9, 8, 7])
  })
})
