import { describe, it, expect } from 'vitest'
import { resolveAtomColor } from './color_resolver.js'
import { ELEMENTS, C_HIGHLIGHT } from './atom_palette.js'

const atom = (over = {}) => ({
  element: 'C', strand_id: 's0', helix_id: 'h0', bp_index: 3, direction: 'FORWARD', ...over,
})

describe('resolveAtomColor — scalar overlay (oxDNA flexibility map)', () => {
  it('paints an atom by its nucleotide scalar colour when nothing is selected', () => {
    const scalarColors = new Map([['h0:3:FORWARD', 0x123456]])
    const ctx = { colorMode: 'cpk', strandColors: new Map(), baseColors: new Map(), scalarColors }
    expect(resolveAtomColor(ctx, atom(), null, false)).toBe(0x123456)
  })

  it('falls back to CPK for a nucleotide missing from the scalar map', () => {
    const scalarColors = new Map([['h0:99:FORWARD', 0x123456]])
    const ctx = { colorMode: 'cpk', strandColors: new Map(), baseColors: new Map(), scalarColors }
    expect(resolveAtomColor(ctx, atom(), null, false)).toBe(ELEMENTS.C.color)
  })

  it('a selection leaves unselected atoms at their scalar-overlay colour', () => {
    const scalarColors = new Map([['h0:3:FORWARD', 0x123456]])
    const ctx = { colorMode: 'cpk', strandColors: new Map(), baseColors: new Map(), scalarColors }
    const sel = { strandIds: ['other'], domains: [], bases: [] }
    expect(resolveAtomColor(ctx, atom(), sel, true)).toBe(0x123456)
  })

  it('selection never darkens unrelated atoms in CPK, strand, or base colouring', () => {
    const sel = { strandIds: ['selected'], domains: [], bases: [] }
    const cases = [
      [{ colorMode: 'cpk', strandColors: new Map(), baseColors: new Map(), scalarColors: null }, ELEMENTS.C.color],
      [{ colorMode: 'strand', strandColors: new Map([['s0', 0xabcdef]]), baseColors: new Map(), scalarColors: null }, 0xabcdef],
      [{ colorMode: 'base', strandColors: new Map(), baseColors: new Map([['s0:3:FORWARD', 0x123456]]), scalarColors: null }, 0x123456],
    ]
    for (const [ctx, expected] of cases) {
      expect(resolveAtomColor(ctx, atom(), sel, true)).toBe(expected)
    }
  })

  it('no overlay → ordinary CPK colouring is unchanged', () => {
    const ctx = { colorMode: 'cpk', strandColors: new Map(), baseColors: new Map(), scalarColors: null }
    expect(resolveAtomColor(ctx, atom(), null, false)).toBe(ELEMENTS.C.color)
  })
})

describe('resolveAtomColor — crossover extra bases and extension tails', () => {
  // A crossover extra base is marked by aux_helix_id (its lerp destination helix).  An
  // extension tail has no aux_helix_id but carries its ANCHOR nucleotide's helix/bp/dir —
  // so neither has a base-letter key of its own.
  const XB  = atom({ element: 'N', aux_helix_id: 'h1', aux_t: 0.5 })
  const EXT = atom({ element: 'N', extension_id: 'ext1', ext_k: 2 })
  const STRAND_MAP = new Map([['s0', 0xff0000]])
  const ctxFor = (colorMode, baseColors = new Map()) =>
    ({ colorMode, strandColors: STRAND_MAP, baseColors, scalarColors: null })

  it('CPK paints extra bases and tails by ELEMENT, not by strand', () => {
    // The reported bug: these two were the only atoms on screen that ignored CPK.
    for (const a of [XB, EXT]) {
      expect(resolveAtomColor(ctxFor('cpk'), a, null, false)).toBe(ELEMENTS.N.color)
    }
  })

  it('strand mode still gives them their strand colour', () => {
    for (const a of [XB, EXT]) {
      expect(resolveAtomColor(ctxFor('strand'), a, null, false)).toBe(0xff0000)
    }
  })

  it('highlights only atoms belonging to a selected extension ref', () => {
    const selection = { strandIds: [], domains: [], bases: [], extensionIds: ['ext1'] }
    expect(resolveAtomColor(ctxFor('cpk'), EXT, selection, true)).toBe(C_HIGHLIGHT)
    expect(resolveAtomColor(ctxFor('cpk'), atom({ extension_id: 'ext2' }), selection, true))
      .toBe(ELEMENTS.C.color)
  })

  it('highlights atoms on a selected whole-cluster helix', () => {
    const selection = { strandIds: [], domains: [], bases: [], extensionIds: [], helixIds: ['h0'] }
    expect(resolveAtomColor(ctxFor('cpk'), atom(), selection, true)).toBe(C_HIGHLIGHT)
    expect(resolveAtomColor(ctxFor('cpk'), atom({ helix_id: 'other' }), selection, true))
      .toBe(ELEMENTS.C.color)
  })

  it('base mode keeps an extra base on its strand colour — it has no letter key', () => {
    // Its stored key is the SOURCE nucleotide's, so a base lookup would paint it with a
    // neighbouring base's letter.  Strand colour is the honest fallback.
    const base = new Map([['s0:3:FORWARD', 0x00ff00]])
    expect(resolveAtomColor(ctxFor('base', base), XB, null, false)).toBe(0xff0000)
  })

  it('the scalar (flexibility) overlay still wins over every mode', () => {
    const ctx = { ...ctxFor('cpk'), scalarColors: new Map([['h0:3:FORWARD', 0x123456]]) }
    expect(resolveAtomColor(ctx, XB, null, false)).toBe(0x123456)
  })

  it('uses the full synthetic keys for crossover inserts and extension tails', () => {
    const xb = atom({ helix_id: '__xb__', bp_index: -1, direction: '', scalar_key: '__xb__:xo7:2:0' })
    const ext = atom({ helix_id: '__ext_tail7', bp_index: 3, direction: 'REVERSE',
      scalar_key: '__ext_tail7:3:REVERSE:0' })
    const ctx = { ...ctxFor('cpk'), scalarColors: new Map([
      ['__xb__:xo7:2:0', 0x112233],
      ['__ext_tail7:3:REVERSE:0', 0x445566],
    ]) }
    expect(resolveAtomColor(ctx, xb, null, false)).toBe(0x112233)
    expect(resolveAtomColor(ctx, ext, null, false)).toBe(0x445566)
  })

  it('does not collapse a loop copy onto its parent nucleotide colour', () => {
    const copied = atom({ copy_k: 1 })
    const ctx = { ...ctxFor('cpk'), scalarColors: new Map([
      ['h0:3:FORWARD:0', 0x111111],
      ['h0:3:FORWARD:1', 0xeeeeee],
    ]) }
    expect(resolveAtomColor(ctx, copied, null, false)).toBe(0xeeeeee)
  })

  it('an ordinary atom is unaffected in every mode', () => {
    const base = new Map([['s0:3:FORWARD', 0x00ff00]])
    expect(resolveAtomColor(ctxFor('cpk'), atom(), null, false)).toBe(ELEMENTS.C.color)
    expect(resolveAtomColor(ctxFor('strand'), atom(), null, false)).toBe(0xff0000)
    expect(resolveAtomColor(ctxFor('base', base), atom(), null, false)).toBe(0x00ff00)
  })
})
