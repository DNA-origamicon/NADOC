import { describe, it, expect } from 'vitest'
import { heatmapHex, hexFromInt, atomColorsFromLetters, BASE_HEX, computeAtomStrandColors, ATOM_STAPLE_PALETTE } from './color_util.js'

const rgb = (hex) => [(hex >> 16) & 0xff, (hex >> 8) & 0xff, hex & 0xff]

describe('heatmapHex', () => {
  it('returns a packed 0xRRGGBB int in range', () => {
    const h = heatmapHex(30)
    expect(Number.isInteger(h)).toBe(true)
    expect(h).toBeGreaterThanOrEqual(0)
    expect(h).toBeLessThanOrEqual(0xffffff)
  })

  it('clamps at/below the min (14 nt) to the blue end (hue 240)', () => {
    // t=0 → hue 240 → pure-ish blue: B dominant, R ~0.
    const [r, g, b] = rgb(heatmapHex(14))
    expect(b).toBeGreaterThan(r)
    expect(b).toBeGreaterThan(g)
    expect(heatmapHex(5)).toBe(heatmapHex(14)) // clamped below min
  })

  it('clamps at/above the max (60 nt) to the red end (hue 0)', () => {
    const [r, g, b] = rgb(heatmapHex(60))
    expect(r).toBeGreaterThan(g)
    expect(r).toBeGreaterThan(b)
    expect(heatmapHex(120)).toBe(heatmapHex(60)) // clamped above max
  })

  it('is monotonic-ish: midpoint differs from both ends', () => {
    expect(heatmapHex(37)).not.toBe(heatmapHex(14))
    expect(heatmapHex(37)).not.toBe(heatmapHex(60))
  })
})

describe('hexFromInt', () => {
  it('formats a packed int as #rrggbb', () => {
    expect(hexFromInt(0x74b9ff)).toBe('#74b9ff')
    expect(hexFromInt(0x000000)).toBe('#000000')
    expect(hexFromInt(0xffffff)).toBe('#ffffff')
  })
  it('zero-pads low values to 6 digits', () => {
    expect(hexFromInt(0x0000ff)).toBe('#0000ff')
    expect(hexFromInt(0xff)).toBe('#0000ff')
  })
  it('masks negatives and over-range ints to 24 bits', () => {
    expect(hexFromInt(-1)).toBe('#ffffff')          // (-1 >>> 0) & 0xffffff
    expect(hexFromInt(0x1abcdef)).toBe('#abcdef')   // high bits dropped
  })
})

describe('atomColorsFromLetters', () => {
  it('keys colours by strand:bp:dir using the base palette', () => {
    const nucLetter = new Map([
      [{ strand_id: 's1', bp_index: 0, direction: 'FORWARD' }, 'A'],
      [{ strand_id: 's1', bp_index: 1, direction: 'REVERSE' }, 'G'],
    ])
    const out = atomColorsFromLetters(nucLetter)
    expect(out.get('s1:0:FORWARD')).toBe(BASE_HEX.A)
    expect(out.get('s1:1:REVERSE')).toBe(BASE_HEX.G)
    expect(out.size).toBe(2)
  })
  it('returns an empty map for null/empty input', () => {
    expect(atomColorsFromLetters(null).size).toBe(0)
    expect(atomColorsFromLetters([]).size).toBe(0)
  })
})

describe('computeAtomStrandColors', () => {
  it('normalizes base strandColors (string + int) to packed ints', () => {
    const state = { strandColors: { s1: '#74b9ff', s2: 0xff0000 }, currentDesign: null }
    const out = computeAtomStrandColors(state, null)
    expect(out.get('s1')).toBe(0x74b9ff)
    expect(out.get('s2')).toBe(0xff0000)
  })

  it('applies strand-group colours, overriding base for grouped strands', () => {
    const state = {
      strandColors: { s1: 0x111111 },
      strandGroups: [{ color: '#00ff00', strandIds: ['s1', 's2'] }],
      currentDesign: null,
    }
    const out = computeAtomStrandColors(state, null)
    expect(out.get('s1')).toBe(0x00ff00)
    expect(out.get('s2')).toBe(0x00ff00)
  })

  it('paints unassigned scaffold strands cadnano blue (0x0070bb)', () => {
    const state = {
      strandColors: {},
      currentDesign: { strands: [
        { id: 'sc', strand_type: 'scaffold' },
        { id: 'st', strand_type: 'staple' },
      ] },
    }
    const out = computeAtomStrandColors(state, null)
    expect(out.get('sc')).toBe(0x0070bb)
    expect(out.has('st')).toBe(false) // no palette → staple unassigned
  })

  it('does not override an already-coloured scaffold strand', () => {
    const state = {
      strandColors: { sc: 0xabcdef },
      currentDesign: { strands: [{ id: 'sc', strand_type: 'scaffold' }] },
    }
    expect(computeAtomStrandColors(state, null).get('sc')).toBe(0xabcdef)
  })

  it('fills unassigned staples from the staple palette (only when not already set)', () => {
    const state = {
      strandColors: { s1: 0x111111 },
      currentDesign: { strands: [{ id: 's1' }, { id: 's2' }, { id: 's3' }] },
    }
    const palette = new Map([['s1', 0x222222], ['s2', 0x333333]]) // s3 absent
    const out = computeAtomStrandColors(state, palette)
    expect(out.get('s1')).toBe(0x111111) // base wins, palette skipped
    expect(out.get('s2')).toBe(0x333333) // filled from palette
    expect(out.has('s3')).toBe(false)    // palette has no entry → left unassigned
  })

  it('highlights loop/circular strands red (0xff3333) outside cluster mode', () => {
    const state = {
      strandColors: { s1: 0x111111 },
      loopStrandIds: ['s1'],
      coloringMode: 'strand',
      currentDesign: null,
    }
    expect(computeAtomStrandColors(state, null).get('s1')).toBe(0xff3333)
  })

  it('skips the loop-red highlight in cluster mode', () => {
    const state = {
      strandColors: { s1: 0x111111 },
      loopStrandIds: ['s1'],
      coloringMode: 'cluster',
      currentDesign: { strands: [], cluster_transforms: [] }, // no cluster_transforms length → no override either
    }
    // cluster_transforms empty → cluster block also skipped → base colour survives
    expect(computeAtomStrandColors(state, null).get('s1')).toBe(0x111111)
  })

  it('cluster mode: colours strands by their domain-mapped cluster from ATOM_STAPLE_PALETTE', () => {
    const state = {
      strandColors: {},
      coloringMode: 'cluster',
      currentDesign: {
        strands: [
          { id: 's0', domains: [{ helix_id: 10 }] },
          { id: 's1', domains: [{ helix_id: 20 }] },
        ],
        cluster_transforms: [
          { helix_ids: [10] }, // cluster 0
          { helix_ids: [20] }, // cluster 1
        ],
      },
    }
    const out = computeAtomStrandColors(state, null)
    expect(out.get('s0')).toBe(ATOM_STAPLE_PALETTE[0])
    expect(out.get('s1')).toBe(ATOM_STAPLE_PALETTE[1])
  })

  it('cluster mode: domain_ids mapping wins over helix_ids for bridge helices', () => {
    const state = {
      strandColors: {},
      coloringMode: 'cluster',
      currentDesign: {
        strands: [{ id: 's0', domains: [{ helix_id: 5 }] }],
        cluster_transforms: [
          // cluster 0 owns s0:domain0 explicitly; its bridge helix 5 is excluded from helixCluster
          { domain_ids: [{ strand_id: 's0', domain_index: 0 }], helix_ids: [5] },
          { helix_ids: [5] }, // cluster 1 would claim helix 5, but domain mapping resolves first
        ],
      },
    }
    expect(computeAtomStrandColors(state, null).get('s0')).toBe(ATOM_STAPLE_PALETTE[0])
  })
})
