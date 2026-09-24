// @vitest-environment jsdom
import { describe, it, expect } from 'vitest'

import {
  PAIR_COLOR,
  dimerSvg,
  hairpinSvg,
  layoutHairpin,
  parseDimerStructure,
  parseHairpinStructure,
} from './hairpin_dimer_structure.js'

// The 24-mer from IDT OligoAnalyzer's hairpin window; primer3 output at 10 mM Mg²⁺.
const IDT_SEQ = 'TACACGTCCCCATGGGGACGTGTA'
const IDT_HIT = {
  tm: 85.32, dg: -9.97, offset: 0,
  structure: ['-/////////----\\\\\\\\\\\\\\\\\\-', IDT_SEQ],
}
// A stem with a 1×1 internal loop (VoltronCore overhang), primer3 output.
const BULGE_SEQ = 'TCGATGCTGGATCGGGCCGGCAATGAGC'
const WC = { A: 'T', T: 'A', G: 'C', C: 'G' }

function svgDoc(markup) {
  const host = document.createElement('div')
  host.innerHTML = markup
  return host.querySelector('svg')
}

describe('hairpin structure', () => {
  it('reads primer3 slash notation into the pairs IDT draws', () => {
    const { seq, pairs } = parseHairpinStructure(IDT_HIT)
    expect(seq).toBe(IDT_SEQ)
    // IDT: 2·23 … 10·15 (1-based), CATG loop, terminal T and A unpaired.
    expect(pairs).toEqual([[1, 22], [2, 21], [3, 20], [4, 19], [5, 18], [6, 17], [7, 16], [8, 15], [9, 14]])
    for (const [i, j] of pairs) expect(WC[seq[i]]).toBe(seq[j])   // Watson–Crick only
  })

  it('lays the stem out as a ladder with the loop above it', () => {
    const { seq, pairs } = parseHairpinStructure(IDT_HIT)
    const { pos } = layoutHairpin(seq, pairs)
    for (const [i, j] of pairs) {
      expect(pos[i][1]).toBeCloseTo(pos[j][1])                   // pair on one row
      expect(pos[i][0]).toBeLessThan(pos[j][0])                  // 5' strand on the left
    }
    const stemTop = pos[pairs.at(-1)[0]][1]
    for (let k = 10; k <= 13; k++) expect(pos[k][1]).toBeGreaterThan(stemTop)
    expect(pos[0][1]).toBeLessThan(pos[1][1])                    // tails hang below
    expect(pos[23][1]).toBeLessThan(pos[22][1])
  })

  it('draws IDT\'s picture: 6 G·C (red) + 3 A·T (blue), every base, ticks at 10 and 20', () => {
    const svg = svgDoc(hairpinSvg(IDT_HIT))
    expect(svg.querySelectorAll('.hd-pair--GC')).toHaveLength(6)
    expect(svg.querySelectorAll('.hd-pair--AT')).toHaveLength(3)
    expect(svg.querySelector('.hd-pair--GC').getAttribute('fill')).toBe(PAIR_COLOR.GC)
    expect([...svg.querySelectorAll('.hd-base')].map(t => t.textContent).join('')).toBe(IDT_SEQ)
    const ticks = [...svg.querySelectorAll('.hd-tick')]
    expect(ticks.map(t => t.textContent)).toEqual(['10', '20'])
    const x = t => Number(t.getAttribute('x'))
    const baseX = i => x(svg.querySelectorAll('.hd-base')[i])
    expect(x(ticks[0])).toBeLessThan(baseX(9))                   // position 10 labelled outboard-left
    expect(x(ticks[1])).toBeGreaterThan(baseX(19))               // position 20 outboard-right
    expect([...svg.querySelectorAll('.hd-end')].map(t => t.textContent)).toEqual(['5′', '3′'])
    expect(svg.querySelector('.hd-caption').textContent).toBe('ΔG = -9.97 kcal/mol · Tm = 85.3 °C')
  })

  it('keeps internal-loop bases off the pair rows', () => {
    const hit = { tm: 66.6, dg: -3.35, offset: 0, structure: ['----///-//------\\\\-\\\\\\------', BULGE_SEQ] }
    const { seq, pairs } = parseHairpinStructure(hit)
    const { pos } = layoutHairpin(seq, pairs)
    const pairRows = new Set(pairs.map(([i]) => pos[i][1].toFixed(3)))
    expect(pairRows.has(pos[7][1].toFixed(3))).toBe(false)       // the unpaired T, 5' side
    expect(pos[7][0]).toBeLessThan(pos[6][0])                     // bowed outward
    expect(svgDoc(hairpinSvg(hit)).querySelectorAll('.hd-pair')).toHaveLength(pairs.length)
  })

  it('elides long tails and counts bases outside primer3\'s window', () => {
    const core = 'AAGCGCGCGCAAAAGCGCGCGC'
    const window = 'T'.repeat(20) + core + 'T'.repeat(18)
    // 22 unpaired (20 T + AA) · 8-bp GC stem · AAAA loop · stem · 18 T; window = nt 31–90 of 100.
    const slash = '-'.repeat(22) + '/'.repeat(8) + '-'.repeat(4) + '\\'.repeat(8) + '-'.repeat(18)
    expect(slash).toHaveLength(window.length)
    const hit = { tm: 90, dg: -10, offset: 30, structure: [slash, window] }
    const svg = svgDoc(hairpinSvg(hit, { fullLength: 100 }))
    expect(svg.querySelectorAll('.hd-base')).toHaveLength(36)    // 8 tail bases kept per side
    const ends = [...svg.querySelectorAll('.hd-end')].map(t => t.textContent)
    expect(ends).toEqual(['5′ +44 nt', '3′ +20 nt'])            // 30 + 14 hidden; 100 − (30 + 50)
  })

  it('returns nothing to draw without pairs', () => {
    expect(hairpinSvg({ tm: 0, dg: 0, structure: ['------', 'ACGTAC'] })).toBe('')
  })
})

describe('dimer alignment', () => {
  const hit = {
    tm: 67.84, dg: -25.23, offset: 0,
    structure: ['          TTTT        TT', '  GCGCGCGC    GCGCGCGC', '  CGCGCGCG    CGCGCGCG', 'TT        TTTT        --'],
  }

  it('rebuilds both strands and marks only Watson–Crick columns', () => {
    const { top, bars, bottom } = parseDimerStructure(hit)
    expect(top.replace(/ /g, '')).toBe('GCGCGCGCTTTTGCGCGCGCTT')                         // 5'→3'
    expect([...bottom.replace(/ /g, '')].reverse().join('')).toBe('GCGCGCGCTTTTGCGCGCGCTT') // read 3'→5'
    const cols = [...bars].flatMap((b, c) => (b === '|' ? [c] : []))
    expect(cols).toHaveLength(16)
    for (const c of cols) expect(WC[top[c]]).toBe(bottom[c])
  })

  it('draws the IDT-style alignment with end labels and caption', () => {
    const svg = svgDoc(dimerSvg(hit))
    expect(svg.querySelectorAll('.hd-pair--GC')).toHaveLength(16)
    expect([...svg.querySelectorAll('.hd-end')].map(t => t.textContent)).toEqual(['5′', '3′', '3′', '5′'])
    expect(svg.querySelector('.hd-caption').textContent).toContain('ΔG = -25.23 kcal/mol · Tm = 67.8 °C')
  })
})
