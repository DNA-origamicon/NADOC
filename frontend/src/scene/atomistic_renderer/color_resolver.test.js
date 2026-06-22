import { describe, it, expect } from 'vitest'
import { resolveAtomColor } from './color_resolver.js'
import { ELEMENTS } from './atom_palette.js'

const atom = (over = {}) => ({
  element: 'C', strand_id: 's0', helix_id: 'h0', bp_index: 3, direction: 'FORWARD', ...over,
})

describe('resolveAtomColor — scalar overlay (oxDNA flexibility map)', () => {
  it('paints an atom by its nucleotide scalar colour when nothing is selected', () => {
    const scalarColors = new Map([['h0:3:FORWARD', 0x123456]])
    const ctx = { colorMode: 'cpk', strandColors: new Map(), baseColors: new Map(), scalarColors }
    expect(resolveAtomColor(ctx, atom(), null, [], false)).toBe(0x123456)
  })

  it('falls back to CPK for a nucleotide missing from the scalar map', () => {
    const scalarColors = new Map([['h0:99:FORWARD', 0x123456]])
    const ctx = { colorMode: 'cpk', strandColors: new Map(), baseColors: new Map(), scalarColors }
    expect(resolveAtomColor(ctx, atom(), null, [], false)).toBe(ELEMENTS.C.color)
  })

  it('a selection still wins over the scalar overlay', () => {
    const scalarColors = new Map([['h0:3:FORWARD', 0x123456]])
    const ctx = { colorMode: 'cpk', strandColors: new Map(), baseColors: new Map(), scalarColors }
    // hasSelection=true routes through colorForAtom (selection highlight/dim), not the overlay.
    const sel = { type: 'strand', data: { strand_id: 'other' } }
    expect(resolveAtomColor(ctx, atom(), sel, [], true)).not.toBe(0x123456)
  })

  it('no overlay → ordinary CPK colouring is unchanged', () => {
    const ctx = { colorMode: 'cpk', strandColors: new Map(), baseColors: new Map(), scalarColors: null }
    expect(resolveAtomColor(ctx, atom(), null, [], false)).toBe(ELEMENTS.C.color)
  })
})
