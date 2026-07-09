/**
 * buildStapleColorMap — staple palette stability.
 *
 * The bug this pins: staple colours were derived from each strand's *array
 * position* in design.strands on every rebuild, so any edit that reshuffles the
 * array (a scaffold nick/crossover, a forced-ligation delete that splits a strand
 * and appends the fragments) silently recoloured untouched staples. The fix pins
 * a palette slot per strand.id on first encounter (keyed by design.id).
 */
import { describe, it, expect, beforeEach } from 'vitest'
import { buildStapleColorMap, STAPLE_PALETTE, _resetStapleColorPins } from './palette.js'

// Minimal strand/nuc factories. A nuc only needs strand_id + strand_type here.
function strand(id, type = 'staple') {
  return { id, strand_type: type, domains: [] }
}
function geomFor(strands) {
  // One nucleotide per strand, in strand-array order (matches how geometry is
  // emitted — staples in design.strands order).
  return strands.map(s => ({ strand_id: s.id, strand_type: s.strand_type }))
}

beforeEach(() => _resetStapleColorPins())

describe('buildStapleColorMap', () => {
  it('first encounter: staple slot = its index in design.strands (initial-load parity)', () => {
    const strands = [strand('scaf', 'scaffold'), strand('A'), strand('B'), strand('C')]
    const design = { id: 'D1', strands, crossovers: [] }
    const map = buildStapleColorMap(geomFor(strands), design)
    // scaffold at index 0 is skipped (no palette entry); A/B/C keep their array slot.
    expect(map.get('A')).toBe(STAPLE_PALETTE[1])
    expect(map.get('B')).toBe(STAPLE_PALETTE[2])
    expect(map.get('C')).toBe(STAPLE_PALETTE[3])
    expect(map.has('scaf')).toBe(false)
  })

  it('reshuffling design.strands (FL delete / scaffold edit) does NOT recolour untouched staples', () => {
    const scaf = strand('scaf', 'scaffold')
    const A = strand('A'), B = strand('B'), C = strand('C')
    const before = buildStapleColorMap(geomFor([scaf, A, B, C]), { id: 'D2', strands: [scaf, A, B, C], crossovers: [] })

    // Simulate delete_forced_ligation: the scaffold strand splits and the two
    // fragments are appended at the END → every staple's array index shifts down.
    const scafA = strand('scafA', 'scaffold'), scafB = strand('scafB', 'scaffold')
    const reshuffled = [A, B, C, scafA, scafB]
    const after = buildStapleColorMap(geomFor(reshuffled), { id: 'D2', strands: reshuffled, crossovers: [] })

    // A/B/C are topologically untouched → same colours as before, NOT palette[0/1/2].
    expect(after.get('A')).toBe(before.get('A'))
    expect(after.get('B')).toBe(before.get('B'))
    expect(after.get('C')).toBe(before.get('C'))
  })

  it('a genuinely new strand gets a fresh palette slot (not a pinned one)', () => {
    const A = strand('A'), B = strand('B')
    buildStapleColorMap(geomFor([A, B]), { id: 'D3', strands: [A, B], crossovers: [] })
    const N = strand('N')
    const map = buildStapleColorMap(geomFor([A, B, N]), { id: 'D3', strands: [A, B, N], crossovers: [] })
    expect(map.get('A')).toBe(STAPLE_PALETTE[0])   // pinned
    expect(map.get('B')).toBe(STAPLE_PALETTE[1])   // pinned
    expect(map.get('N')).toBe(STAPLE_PALETTE[2])   // new → slot 2
  })

  it('pins are isolated per design.id (assembly parts keep independent palettes)', () => {
    const strands = [strand('A'), strand('B')]
    const m1 = buildStapleColorMap(geomFor(strands), { id: 'partX', strands, crossovers: [] })
    // Same strand ids, different design → its own first-encounter assignment,
    // unaffected by partX's pins.
    const m2 = buildStapleColorMap(geomFor(strands), { id: 'partY', strands, crossovers: [] })
    expect(m2.get('A')).toBe(m1.get('A'))   // both slot 0, but independently pinned
    expect(m2.get('B')).toBe(m1.get('B'))
  })
})
