import { describe, it, expect } from 'vitest'
import {
  CT_VARIANTS, endOf, ctIsForbidden, ctForbiddenReason, ctTileSvg,
  ctAttachPair, ctIsDirect, ctIsIndirect, ctLinkerType, ctVariantForConnection,
} from './ct_icons.js'

describe('endOf', () => {
  it('parses the 5p/3p suffix from an overhang id', () => {
    expect(endOf('ovhg_h1_5_5p')).toBe('5p')
    expect(endOf('ovhg_h2_9_3p')).toBe('3p')
  })
  it('returns null for ids without a polarity suffix or non-strings', () => {
    expect(endOf('ovhg_h1_5')).toBeNull()
    expect(endOf('')).toBeNull()
    expect(endOf(null)).toBeNull()
    expect(endOf(undefined)).toBeNull()
    expect(endOf(42)).toBeNull()
  })
})

describe('CT_VARIANTS', () => {
  it('lists all 12 connection-type variants with id + label', () => {
    expect(CT_VARIANTS).toHaveLength(12)
    for (const v of CT_VARIANTS) {
      expect(typeof v.id).toBe('string')
      expect(typeof v.label).toBe('string')
    }
    const ids = CT_VARIANTS.map(v => v.id)
    expect(ids).toContain('end-to-root')
    expect(ids).toContain('root-to-end-dsdna-linker')
    expect(new Set(ids).size).toBe(12)   // no duplicate ids
  })
})

describe('ctIsForbidden — Watson-Crick polarity-pairing rule', () => {
  it('never forbids when either side is unselected (null polarity)', () => {
    expect(ctIsForbidden('end-to-root', null, '5p')).toBe(false)
    expect(ctIsForbidden('end-to-root', '5p', null)).toBe(false)
    expect(ctIsForbidden('root-to-root', null, null)).toBe(false)
  })

  it('direct end-to-root: forbidden iff polarities differ', () => {
    expect(ctIsForbidden('end-to-root', '5p', '3p')).toBe(true)
    expect(ctIsForbidden('end-to-root', '5p', '5p')).toBe(false)
  })

  it('direct root-to-root: forbidden iff polarities match', () => {
    expect(ctIsForbidden('root-to-root', '5p', '5p')).toBe(true)
    expect(ctIsForbidden('root-to-root', '5p', '3p')).toBe(false)
  })

  it('same-attach ds linker: forbidden iff polarities differ', () => {
    expect(ctIsForbidden('end-to-end-dsdna-linker', '5p', '3p')).toBe(true)
    expect(ctIsForbidden('root-to-root-dsdna-linker', '3p', '3p')).toBe(false)
  })

  it('same-attach ss linker: forbidden iff polarities match', () => {
    expect(ctIsForbidden('end-to-end-ssdna-linker', '5p', '5p')).toBe(true)
    expect(ctIsForbidden('root-to-root-ssdna-linker', '5p', '3p')).toBe(false)
    expect(ctIsForbidden('end-to-end-indirect', '3p', '3p')).toBe(true)
  })

  it('mixed-attach families invert vs. same-attach', () => {
    // ds mixed forbidden when MATCH; ss mixed forbidden when DIFFER.
    expect(ctIsForbidden('end-to-root-dsdna-linker', '5p', '5p')).toBe(true)
    expect(ctIsForbidden('end-to-root-dsdna-linker', '5p', '3p')).toBe(false)
    expect(ctIsForbidden('root-to-end-ssdna-linker', '5p', '3p')).toBe(true)
    expect(ctIsForbidden('root-to-end-ssdna-linker', '5p', '5p')).toBe(false)
  })
})

describe('ctForbiddenReason', () => {
  it('returns null for an allowed combination', () => {
    expect(ctForbiddenReason('end-to-root', '5p', '5p')).toBeNull()
    expect(ctForbiddenReason('root-to-root', null, '3p')).toBeNull()
  })
  it('returns an explanatory string for a forbidden combination', () => {
    const reason = ctForbiddenReason('end-to-root', '5p', '3p')
    expect(typeof reason).toBe('string')
    expect(reason).toMatch(/parallel duplex/)
  })
})

describe('variant → backend mapping helpers', () => {
  it('ctAttachPair: longest-prefix dispatch (mixed before same-attach)', () => {
    expect(ctAttachPair('end-to-root-dsdna-linker')).toEqual(['free_end', 'root'])
    expect(ctAttachPair('root-to-end-ssdna-linker')).toEqual(['root', 'free_end'])
    expect(ctAttachPair('root-to-root-dsdna-linker')).toEqual(['root', 'root'])
    expect(ctAttachPair('end-to-end-ssdna-linker')).toEqual(['free_end', 'free_end'])
    expect(ctAttachPair(null)).toEqual(['root', 'root'])
  })

  it('ctIsDirect / ctIsIndirect classify the special families', () => {
    expect(ctIsDirect('end-to-root')).toBe(true)
    expect(ctIsDirect('root-to-root')).toBe(true)
    expect(ctIsDirect('end-to-end-ssdna-linker')).toBe(false)
    expect(ctIsIndirect('root-to-root-indirect')).toBe(true)
    expect(ctIsIndirect('end-to-end-indirect')).toBe(true)
    expect(ctIsIndirect('end-to-root')).toBe(false)
  })

  it('ctLinkerType maps dsdna→ds, everything else→ss', () => {
    expect(ctLinkerType('end-to-end-dsdna-linker')).toBe('ds')
    expect(ctLinkerType('end-to-end-ssdna-linker')).toBe('ss')
    expect(ctLinkerType('root-to-root-indirect')).toBe('ss')
  })

  it('ctVariantForConnection round-trips a connection back to its variant id', () => {
    expect(ctVariantForConnection({
      linker_type: 'ss', overhang_a_attach: 'free_end', overhang_b_attach: 'root',
    })).toBe('end-to-root-ssdna-linker')
    expect(ctVariantForConnection({
      linker_type: 'ds', overhang_a_attach: 'root', overhang_b_attach: 'root',
    })).toBe('root-to-root-dsdna-linker')
    expect(ctVariantForConnection(null)).toBeNull()
  })
})

describe('ctTileSvg', () => {
  it('draws a 5p square marker for a selected 5p side', () => {
    const svg = ctTileSvg('end-to-root', '5p', null, false)
    expect(svg).toContain('<rect')   // 5p = square
  })
  it('overlays the yellow warning triangle only when forbidden', () => {
    const warn = ctTileSvg('end-to-root', '5p', '3p', true)
    const ok   = ctTileSvg('end-to-root', '5p', '5p', false)
    expect(warn).toContain('#f5c518')   // warning fill
    expect(ok).not.toContain('#f5c518')
  })
})
