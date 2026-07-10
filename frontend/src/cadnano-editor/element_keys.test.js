import { describe, it, expect } from 'vitest'
import {
  domainLineKey, domainEndKey, xoverKey, forcedLigKey, loopSkipKey,
  crossoverJunctionSlots,
  parseLineKey, parseEndKey, parseXoverKey, parseForcedLigKey, parseLoopSkipKey,
} from './element_keys.js'

// The motivating bug (issues_ledger ISSUE-7): negative-bp scaffold stubs were
// undeletable because the delete-path parsers used `\d+`, which can't match a
// leading '-'. These are the EXACT keys produced for the teeth.nadoc stubs on
// helices 0-7 (e.g. scaf_XY_0_0: h_XY_0_0, -17..-6, FORWARD).
describe('element_keys — negative-bp parsing (ISSUE-7 regression)', () => {
  it('parses a fully-negative domain line key', () => {
    expect(parseLineKey('line:h_XY_0_0_-17_-6_FORWARD')).toEqual({
      helix_id: 'h_XY_0_0', lo: -17, hi: -6, direction: 'FORWARD',
    })
  })

  it('parses a negative-bp end key', () => {
    expect(parseEndKey('end:h_XY_0_0_-17_FORWARD')).toEqual({
      helix_id: 'h_XY_0_0', bp: -17, direction: 'FORWARD',
    })
  })

  it('parses a span crossing zero (lo negative, hi positive)', () => {
    expect(parseLineKey('line:h_XY_2_0_-17_41_FORWARD')).toEqual({
      helix_id: 'h_XY_2_0', lo: -17, hi: 41, direction: 'FORWARD',
    })
  })

  it('parses a negative-index crossover key', () => {
    expect(parseXoverKey('xo:h_XY_0_0_-5_FORWARD')).toEqual({
      helix_id: 'h_XY_0_0', index: -5, strand: 'FORWARD',
    })
  })

  it('parses a negative-bp loop/skip key', () => {
    expect(parseLoopSkipKey('ls:h_XY_0_0_-17_skip')).toEqual({
      helix_id: 'h_XY_0_0', bp: -17, kind: 'skip',
    })
  })
})

describe('element_keys — build↔parse round-trips', () => {
  const cases = [
    { start_bp: -17, end_bp: -6,  direction: 'FORWARD',  helix_id: 'h_XY_0_0' },  // fully negative
    { start_bp: -6,  end_bp: -17, direction: 'REVERSE',  helix_id: 'h_XY_0_1' },  // reversed, negative
    { start_bp: -17, end_bp: 41,  direction: 'FORWARD',  helix_id: 'h_XY_2_0' },  // spans zero
    { start_bp: 0,   end_bp: 251, direction: 'FORWARD',  helix_id: 'h_XY_0_0' },  // positive (unchanged)
    { start_bp: 84,  end_bp: 125, direction: 'REVERSE',  helix_id: 'h_XY_3_3' },  // positive reversed
  ]

  for (const dom of cases) {
    const lo = Math.min(dom.start_bp, dom.end_bp)
    const hi = Math.max(dom.start_bp, dom.end_bp)
    it(`line round-trips ${dom.helix_id} ${dom.start_bp}->${dom.end_bp} ${dom.direction}`, () => {
      const p = parseLineKey(domainLineKey(dom))
      expect(p).toEqual({ helix_id: dom.helix_id, lo, hi, direction: dom.direction })
    })
    it(`end (5p/3p) round-trips ${dom.helix_id} ${dom.start_bp}->${dom.end_bp}`, () => {
      for (const which of ['5p', '3p']) {
        const p = parseEndKey(domainEndKey(dom, which))
        expect(p.helix_id).toBe(dom.helix_id)
        expect(p.direction).toBe(dom.direction)
        expect([lo, hi]).toContain(p.bp)
      }
    })
  }

  it('crossover key round-trips with a negative index', () => {
    const xo = { half_a: { helix_id: 'h_XY_1_3', index: -11, strand: 'FORWARD' } }
    expect(parseXoverKey(xoverKey(xo))).toEqual({ helix_id: 'h_XY_1_3', index: -11, strand: 'FORWARD' })
  })

  it('loop/skip key round-trips (delta sign → loop/skip)', () => {
    expect(parseLoopSkipKey(loopSkipKey('h_XY_0_0', -17, 2))).toEqual({ helix_id: 'h_XY_0_0', bp: -17, kind: 'loop' })
    expect(parseLoopSkipKey(loopSkipKey('h_XY_0_0', -17, -1))).toEqual({ helix_id: 'h_XY_0_0', bp: -17, kind: 'skip' })
  })

  it('forced-ligation key round-trips (no bp)', () => {
    expect(parseForcedLigKey(forcedLigKey({ id: 'abc-123' }))).toEqual({ id: 'abc-123' })
  })
})

describe('element_keys — non-matching keys return null', () => {
  it('wrong prefix → null', () => {
    expect(parseLineKey('end:h_XY_0_0_-17_FORWARD')).toBeNull()
    expect(parseEndKey('line:h_XY_0_0_-17_-6_FORWARD')).toBeNull()
    expect(parseXoverKey('ls:h_XY_0_0_-17_skip')).toBeNull()
    expect(parseForcedLigKey('xo:h_XY_0_0_-5_FORWARD')).toBeNull()
  })
})

// Mirrors backend crossover_junction_slots — reproduced from
// workspace/crossover_edge_cases.nadoc helices 0/1 (no junction) vs 2/3 (junction).
describe('crossoverJunctionSlots — occupied crossover junctions', () => {
  it('flags both slots of a multi-domain strand turn (helices 2/3)', () => {
    const design = { strands: [{
      domains: [
        { helix_id: 'h2', start_bp: 0, end_bp: 16, direction: 'FORWARD' },
        { helix_id: 'h3', start_bp: 16, end_bp: 0, direction: 'REVERSE' },
      ],
    }] }
    const slots = crossoverJunctionSlots(design)
    expect(slots.has('h2_16_FORWARD')).toBe(true)   // 3' exit of domain 0
    expect(slots.has('h3_16_REVERSE')).toBe(true)   // 5' entry of domain 1
    expect(slots.size).toBe(2)
  })

  it('does not flag single-domain strands / free termini (helices 0/1)', () => {
    const design = { strands: [
      { domains: [{ helix_id: 'h0', start_bp: 0, end_bp: 16, direction: 'FORWARD' }] },
      { domains: [{ helix_id: 'h1', start_bp: 16, end_bp: 0, direction: 'REVERSE' }] },
    ] }
    expect(crossoverJunctionSlots(design).size).toBe(0)
  })

  it('ignores same-helix domain boundaries (not a crossover)', () => {
    const design = { strands: [{
      domains: [
        { helix_id: 'hA', start_bp: 0, end_bp: 10, direction: 'FORWARD' },
        { helix_id: 'hA', start_bp: 11, end_bp: 20, direction: 'FORWARD' },
      ],
    }] }
    expect(crossoverJunctionSlots(design).size).toBe(0)
  })

  it('handles empty / missing design gracefully', () => {
    expect(crossoverJunctionSlots(null).size).toBe(0)
    expect(crossoverJunctionSlots({ strands: [] }).size).toBe(0)
  })
})
