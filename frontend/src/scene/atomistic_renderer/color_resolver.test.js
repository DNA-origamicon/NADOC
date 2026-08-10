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

  it('a selection leaves unselected atoms at their scalar-overlay colour', () => {
    const scalarColors = new Map([['h0:3:FORWARD', 0x123456]])
    const ctx = { colorMode: 'cpk', strandColors: new Map(), baseColors: new Map(), scalarColors }
    const sel = { type: 'strand', data: { strand_id: 'other' } }
    expect(resolveAtomColor(ctx, atom(), sel, [], true)).toBe(0x123456)
  })

  it('selection never darkens unrelated atoms in CPK, strand, or base colouring', () => {
    const sel = { type: 'strand', data: { strand_id: 'selected' } }
    const cases = [
      [{ colorMode: 'cpk', strandColors: new Map(), baseColors: new Map(), scalarColors: null }, ELEMENTS.C.color],
      [{ colorMode: 'strand', strandColors: new Map([['s0', 0xabcdef]]), baseColors: new Map(), scalarColors: null }, 0xabcdef],
      [{ colorMode: 'base', strandColors: new Map(), baseColors: new Map([['s0:3:FORWARD', 0x123456]]), scalarColors: null }, 0x123456],
    ]
    for (const [ctx, expected] of cases) {
      expect(resolveAtomColor(ctx, atom(), sel, [], true)).toBe(expected)
    }
  })

  it('no overlay → ordinary CPK colouring is unchanged', () => {
    const ctx = { colorMode: 'cpk', strandColors: new Map(), baseColors: new Map(), scalarColors: null }
    expect(resolveAtomColor(ctx, atom(), null, [], false)).toBe(ELEMENTS.C.color)
  })
})

describe('resolveAtomColor — crossover extra bases and extension tails', () => {
  // A crossover extra base is marked by aux_helix_id (its lerp destination helix).  An
  // extension tail has no aux_helix_id but carries its ANCHOR nucleotide's helix/bp/dir —
  // so neither has a base-letter key of its own.
  const XB  = atom({ element: 'N', aux_helix_id: 'h1', aux_t: 0.5 })
  const EXT = atom({ element: 'N' })          // anchor's key, no aux
  const STRAND_MAP = new Map([['s0', 0xff0000]])
  const ctxFor = (colorMode, baseColors = new Map()) =>
    ({ colorMode, strandColors: STRAND_MAP, baseColors, scalarColors: null })

  it('CPK paints extra bases and tails by ELEMENT, not by strand', () => {
    // The reported bug: these two were the only atoms on screen that ignored CPK.
    for (const a of [XB, EXT]) {
      expect(resolveAtomColor(ctxFor('cpk'), a, null, [], false)).toBe(ELEMENTS.N.color)
    }
  })

  it('strand mode still gives them their strand colour', () => {
    for (const a of [XB, EXT]) {
      expect(resolveAtomColor(ctxFor('strand'), a, null, [], false)).toBe(0xff0000)
    }
  })

  it('base mode keeps an extra base on its strand colour — it has no letter key', () => {
    // Its stored key is the SOURCE nucleotide's, so a base lookup would paint it with a
    // neighbouring base's letter.  Strand colour is the honest fallback.
    const base = new Map([['s0:3:FORWARD', 0x00ff00]])
    expect(resolveAtomColor(ctxFor('base', base), XB, null, [], false)).toBe(0xff0000)
  })

  it('the scalar (flexibility) overlay still wins over every mode', () => {
    const ctx = { ...ctxFor('cpk'), scalarColors: new Map([['h0:3:FORWARD', 0x123456]]) }
    expect(resolveAtomColor(ctx, XB, null, [], false)).toBe(0x123456)
  })

  it('an ordinary atom is unaffected in every mode', () => {
    const base = new Map([['s0:3:FORWARD', 0x00ff00]])
    expect(resolveAtomColor(ctxFor('cpk'), atom(), null, [], false)).toBe(ELEMENTS.C.color)
    expect(resolveAtomColor(ctxFor('strand'), atom(), null, [], false)).toBe(0xff0000)
    expect(resolveAtomColor(ctxFor('base', base), atom(), null, [], false)).toBe(0x00ff00)
  })
})
