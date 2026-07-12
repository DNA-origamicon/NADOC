import { describe, it, expect } from 'vitest'
import {
  encodeOption, decodeOption, revcomp, connectionBody, canGenerate,
} from './assembly_overhang_connections_panel.js'

describe('assembly_overhang_connections_panel pure helpers', () => {
  it('encode/decode option round-trips (ids with colons survive)', () => {
    const v = encodeOption('inst-A', 'ns::oh_5p')
    expect(decodeOption(v)).toEqual({ instanceId: 'inst-A', overhangId: 'ns::oh_5p' })
    expect(decodeOption('')).toBeNull()
    expect(decodeOption(null)).toBeNull()
  })

  it('revcomp: reverse Watson-Crick complement, N-safe', () => {
    expect(revcomp('AAAC')).toBe('GTTT')
    expect(revcomp('acgt')).toBe('ACGT')       // self-RC, upcased
    expect(revcomp('ANG')).toBe('CNT')
  })

  it('connectionBody: attach pair + linker_type + length from the variant', () => {
    const A = { instanceId: 'iA', overhangId: 'oA_5p' }
    const B = { instanceId: 'iB', overhangId: 'oB_3p' }
    // ds end-to-end: attach free_end/free_end, linker ds, length passed through
    expect(connectionBody('end-to-end-dsdna-linker', A, B, 21)).toEqual({
      instance_a_id: 'iA', overhang_a_id: 'oA_5p', overhang_a_attach: 'free_end',
      instance_b_id: 'iB', overhang_b_id: 'oB_3p', overhang_b_attach: 'free_end',
      linker_type: 'ds', length_value: 21, length_unit: 'bp',
    })
    // indirect → length forced to 0 regardless of the field
    expect(connectionBody('root-to-root-indirect', A, B, 99).length_value).toBe(0)
    expect(connectionBody('root-to-root-indirect', A, B, 99).linker_type).toBe('ss')
  })

  it('canGenerate: needs both sides, cross-part, allowed polarity, valid length', () => {
    const A = { instanceId: 'iA', overhangId: 'oA_5p' }
    const B = { instanceId: 'iB', overhangId: 'oB_5p' }   // same polarity (5p/5p)
    // ds end-to-end requires SAME polarity → 5p/5p allowed; length needed
    expect(canGenerate({ A, B, variant: 'end-to-end-dsdna-linker', length: 12 })).toBe(true)
    expect(canGenerate({ A, B, variant: 'end-to-end-dsdna-linker', length: 0 })).toBe(false)   // bad length
    // same instance → not cross-part
    expect(canGenerate({ A, B: { ...B, instanceId: 'iA' }, variant: 'end-to-end-dsdna-linker', length: 12 })).toBe(false)
    // forbidden polarity: ss end-to-end needs OPPOSITE, 5p/5p is forbidden
    expect(canGenerate({ A, B, variant: 'end-to-end-ssdna-linker', length: 12 })).toBe(false)
    // direct variant (end-to-root needs SAME polarity, here 5p/5p): no length required
    expect(canGenerate({ A, B, variant: 'end-to-root', length: NaN })).toBe(true)
    // end-to-root with OPPOSITE polarity (5p/3p) is forbidden
    expect(canGenerate({ A, B: { instanceId: 'iB', overhangId: 'oB_3p' }, variant: 'end-to-root', length: NaN })).toBe(false)
    // missing side
    expect(canGenerate({ A: null, B, variant: 'end-to-root', length: 5 })).toBe(false)
  })
})
