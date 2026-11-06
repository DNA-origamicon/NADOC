import { describe, it, expect } from 'vitest'
import { duplexThermodynamics, domainMeltingTemperature, loopClosureEntropy, stapleFoldingTemperature, estimateStapleTemperatures } from './staple_temperature.js'

const dom = (helix, start, end, direction = 'REVERSE') => ({ helix_id: helix, start_bp: start, end_bp: end, direction })
const sequence = 'ACGTACGTACGTACGT'
function design() {
  return { helices: [{ id: 'h' }], strands: [
    { id: 'sc', strand_type: 'scaffold', domains: [dom('h', 0, 63, 'FORWARD')], sequence: sequence.repeat(4) },
    { id: 's', strand_type: 'staple', domains: [dom('h', 15, 0), dom('h', 47, 32)], sequence: sequence.repeat(2) },
  ] }
}

describe('staple thermodynamics', () => {
  it('uses the 2004 terminal/initiation and nearest-neighbor terms', () => {
    expect(duplexThermodynamics('AT').h).toBeCloseTo(-2.6, 8)
    expect(duplexThermodynamics('AT').s).toBeCloseTo(-12.3, 8)
    const t = duplexThermodynamics('CGTTCCAAAGATGTGGGCATGAGCTTAC')
    expect(t.h).toBeCloseTo(-221.7, 8)
    expect(t.s).toBeCloseTo(-599, 8)
  })
  it('matches an independent NN4/Owczarzy reference at 10 mM Mg and excess 200 nM', () => {
    expect(domainMeltingTemperature('CGTTCCAAAGATGTGGGCATGAGCTTAC')).toBeCloseTo(71.82146192, 2) // Biopython NN4/saltcorr=7; R rounded to 1.987 there
    expect(domainMeltingTemperature('acgtacgtacgtacgt')).toBe(domainMeltingTemperature(sequence))
  })
  it('never guesses GC content for absent/ambiguous/one-base sequences', () => {
    for (const s of ['', 'NACGT', 'A', undefined]) expect(domainMeltingTemperature(s)).toBeNull()
  })
  it('42-nt domains melt above 21-nt domains of identical composition', () => {
    const domain21 = 'ACGTACGTACGTACGTACGTA'
    expect(domainMeltingTemperature(domain21.repeat(2))).toBeGreaterThan(domainMeltingTemperature(domain21))
  })
  it('charges a loop entropy and concentration once for a whole staple', () => {
    expect(loopClosureEntropy(100)).toBeCloseTo(-15.10659257, 7)
    expect(stapleFoldingTemperature([sequence, sequence], [100])).toBeCloseTo(66.44283105, 7)
    expect(stapleFoldingTemperature([sequence, sequence], [1000])).toBeLessThan(stapleFoldingTemperature([sequence, sequence], [100]))
    expect(stapleFoldingTemperature([sequence], [100])).toBeNull()
    expect(loopClosureEntropy(0)).toBeNull()
  })
})

describe('read-only design projection', () => {
  it('calculates domain and total estimates without changing topology or sequence', () => {
    const d = design(), before = JSON.stringify(d)
    const result = estimateStapleTemperatures(d)
    expect(result.has('sc')).toBe(false)
    expect(result.get('s').domains.map(d => d.tm)).toEqual([domainMeltingTemperature(sequence), domainMeltingTemperature(sequence)])
    expect(result.get('s').total).toBeCloseTo(stapleFoldingTemperature([sequence, sequence], [32]), 8)
    expect(JSON.stringify(d)).toBe(before)
  })
  it('uses the shortest circular scaffold distance between domain centers', () => {
    const d = design()
    d.strands[1].domains[1] = dom('h', 63, 48)
    expect(estimateStapleTemperatures(d).get('s').total).toBeCloseTo(stapleFoldingTemperature([sequence, sequence], [16]), 8)
  })
  it('does not color mismatched, undefined, or unpaired DNA with a valid Tm', () => {
    const d = design()
    d.strands[1].sequence = 'T'.repeat(32)
    expect(estimateStapleTemperatures(d).get('s').total).toBeNull()
    expect(estimateStapleTemperatures(d).get('s').domains[0].tm).toBeNull()
    d.strands[1].sequence = null
    expect(estimateStapleTemperatures(d).get('s').domains[0].tm).toBeNull()
    d.strands.shift()
    expect(estimateStapleTemperatures(d).get('s').total).toBeNull()
  })
  it('accounts for loop/skip sequence offsets and copies', () => {
    const d = design()
    d.helices[0].loop_skips = [{ bp_index: 3, delta: 1 }, { bp_index: 5, delta: -1 }]
    d.strands[0].sequence = null // pairing is assigned but sequence unknown
    const result = estimateStapleTemperatures(d).get('s')
    expect(result.domains[0].keys).toHaveLength(16)
    expect(result.domains[0].keys).toContain('h:3:REVERSE:1')
    expect(result.domains[0].keys).not.toContain('h:5:REVERSE')
    expect(result.domains[1].sequence).toBe(sequence)
    expect(result.total).not.toBeNull()
  })
  it('unwraps a domain crossing the primary sequence-start nick before finding its center', () => {
    const d = design()
    d.strands[0].domains = [dom('h', 32, 63, 'FORWARD'), dom('h', 0, 31, 'FORWARD')]
    d.strands[0].sequence = 'T'.repeat(64)
    d.strands[1].domains = [dom('h', 47, 16), dom('h', 15, 0)]
    d.strands[1].sequence = 'A'.repeat(48)
    const r = estimateStapleTemperatures(d).get('s')
    expect(r.domains[0].center).toBe(63.5)
    expect(r.total).toBeCloseTo(stapleFoldingTemperature(['A'.repeat(32), 'A'.repeat(16)], [24]), 8)
  })
  it('excludes terminal ss tails without shifting the binding-domain sequence', () => {
    const d = design()
    d.strands[1].domains.unshift({ ...dom('h', 67, 64), overhang_id: 'tail' })
    d.strands[1].sequence = 'AAAA' + sequence.repeat(2)
    const r = estimateStapleTemperatures(d).get('s')
    expect(r.domains[0].tm).toBeNull()
    expect(r.domains[1].sequence).toBe(sequence)
    expect(r.total).toBeCloseTo(stapleFoldingTemperature([sequence, sequence], [32]), 8)
  })
  it('declines internal unpaired domains and junction inserts instead of concatenating', () => {
    const d = design()
    d.strands[1].domains.splice(1, 0, { ...dom('h', 67, 64), overhang_id: 'internal' })
    d.strands[1].sequence = sequence + 'AAAA' + sequence
    expect(estimateStapleTemperatures(d).get('s').total).toBeNull()
    const clean = design()
    clean.crossovers = [{ id: 'x', half_a: { helix_id: 'h', index: 0, strand: 'REVERSE' },
      half_b: { helix_id: 'h', index: 47, strand: 'REVERSE' }, extra_bases: 'TT' }]
    expect(estimateStapleTemperatures(clean).get('s').total).toBeNull()
    expect(estimateStapleTemperatures(clean).get('s').domains[1].sequence).toBe(sequence)
  })
  it('keeps valid domain estimates on secondary scaffolds but declines mixed-scaffold totals', () => {
    const d = design()
    d.strands[0].domains = [dom('h', 0, 31, 'FORWARD')]
    d.strands.push({ id: 'sc2', strand_type: 'scaffold', domains: [dom('h', 32, 63, 'FORWARD')], sequence: sequence.repeat(2) })
    const result = estimateStapleTemperatures(d).get('s')
    expect(result.domains.every(d => d.tm != null)).toBe(true)
    expect(result.total).toBeNull()
  })
})

describe('independent circular scaffolds', () => {
  function twoScaffolds() {
    return { helices: [{ id: 'a' }, { id: 'b' }], strands: [
      { id: 'scA', strand_type: 'scaffold', domains: [dom('a', 0, 63, 'FORWARD')] },
      { id: 'scB', strand_type: 'scaffold', domains: [dom('b', 0, 127, 'FORWARD')] },
      ...['a', 'b'].map(h => ({ id: 's' + h, strand_type: 'staple', sequence: sequence.repeat(2),
        domains: [dom(h, 15, 0), dom(h, 63, 48)] })),
    ] }
  }
  it('uses each scaffold length, rather than the first scaffold or a concatenated contour', () => {
    const design = twoScaffolds(), before = JSON.stringify(design)
    const result = estimateStapleTemperatures(design)
    expect(result.get('sa').scaffoldId).toBe('scA')
    expect(result.get('sb').scaffoldId).toBe('scB')
    expect(result.get('sa').total).toBeCloseTo(stapleFoldingTemperature([sequence, sequence], [16]), 8)
    expect(result.get('sb').total).toBeCloseTo(stapleFoldingTemperature([sequence, sequence], [48]), 8)
    const reordered = estimateStapleTemperatures({ ...design, strands: [...design.strands].reverse() })
    expect(reordered.get('sa')).toEqual(result.get('sa'))
    expect(reordered.get('sb')).toEqual(result.get('sb'))
    expect(JSON.stringify(design)).toBe(before)
  })
  it('unwraps secondary scaffold domains across their own sequence-start nick', () => {
    const design = twoScaffolds()
    design.strands[1].domains = [dom('b', 32, 127, 'FORWARD'), dom('b', 0, 31, 'FORWARD')]
    design.strands[3].domains = [dom('b', 47, 16), dom('b', 15, 0)]
    design.strands[3].sequence = sequence.repeat(3)
    const result = estimateStapleTemperatures(design).get('sb')
    expect(result.domains[0].center).toBe(127.5)
    expect(result.total).toBeCloseTo(stapleFoldingTemperature([sequence.repeat(2), sequence], [24]), 8)
  })
  it('does not turn a staple bridging different scaffolds into an intramolecular loop', () => {
    const design = twoScaffolds()
    design.strands[2].domains[1].helix_id = 'b'
    const result = estimateStapleTemperatures(design).get('sa')
    expect(result.domains.every(d => d.tm != null)).toBe(true)
    expect(result.scaffoldId).toBeNull()
    expect(result.total).toBeNull()
  })
  it('rejects ambiguous active scaffold occupancy, but ignores reference backdrops', () => {
    const design = twoScaffolds()
    design.strands.push({ ...design.strands[1], id: 'duplicate' })
    expect(estimateStapleTemperatures(design).get('sb').total).toBeNull()
    design.strands.at(-1).is_reference = true
    expect(estimateStapleTemperatures(design).get('sb').total).not.toBeNull()
  })
})
