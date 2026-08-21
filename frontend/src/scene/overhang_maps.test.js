import { describe, it, expect } from 'vitest'
import {
  buildSpecMap, buildDomainMapFromDesign, buildDomainMapFromGeom,
  buildJunctionMapFromXovers, buildJunctionMapFromDomains, buildRootMap,
} from './overhang_maps.js'

// Fixture: strand s1 with a parent domain on h1 and an overhang domain (o1) on h2.
const spec = { id: 'o1', strand_id: 's1', helix_id: 'h2' }
const strand = {
  id: 's1',
  domains: [
    { helix_id: 'h1', start_bp: 0, end_bp: 9, direction: 'FORWARD' },             // parent (domIdx 0)
    { helix_id: 'h2', start_bp: 3, end_bp: 8, direction: 'FORWARD', overhang_id: 'o1' }, // overhang (domIdx 1)
  ],
}
const design = {
  overhangs: [spec],
  strands: [strand],
  crossovers: [{ half_a: { helix_id: 'h2', index: 3, strand: 'FORWARD' }, half_b: { helix_id: 'h1', index: 9, strand: 'FORWARD' } }],
}

describe('buildSpecMap', () => {
  it('maps overhang id → spec', () => {
    const m = buildSpecMap(design)
    expect(m.get('o1')).toBe(spec)
    expect(m.size).toBe(1)
  })
  it('is empty for a design with no overhangs', () => {
    expect(buildSpecMap({}).size).toBe(0)
    expect(buildSpecMap(undefined).size).toBe(0)
  })
})

describe('buildDomainMapFromDesign', () => {
  it('resolves the overhang domain by overhang_id (not helix_id)', () => {
    const dm = buildDomainMapFromDesign(design, buildSpecMap(design))
    expect(dm.get('o1')).toEqual({ strand, domIdx: 1, domain: strand.domains[1] })
  })
  it('skips specs whose strand/domain is missing', () => {
    const dm = buildDomainMapFromDesign({ strands: [] }, buildSpecMap(design))
    expect(dm.size).toBe(0)
  })
})

describe('buildDomainMapFromGeom', () => {
  it('resolves via nuc.domain_index from backbone entries', () => {
    const entries = [{ nuc: { overhang_id: 'o1', strand_id: 's1', domain_index: 1 } }]
    const dm = buildDomainMapFromGeom(design, entries)
    expect(dm.get('o1')).toEqual({ strand, domIdx: 1, domain: strand.domains[1] })
  })
  it('ignores entries without an overhang_id and dedups repeats', () => {
    const entries = [
      { nuc: { strand_id: 's1', domain_index: 0 } },              // no overhang_id
      { nuc: { overhang_id: 'o1', strand_id: 's1', domain_index: 1 } },
      { nuc: { overhang_id: 'o1', strand_id: 's1', domain_index: 1 } }, // dup
    ]
    expect(buildDomainMapFromGeom(design, entries).size).toBe(1)
  })
})

describe('buildJunctionMapFromDomains', () => {
  it('uses start_bp for a non-first (3′-end) overhang domain', () => {
    const dm = buildDomainMapFromDesign(design, buildSpecMap(design))
    expect(buildJunctionMapFromDomains(dm).get('o1')).toEqual({ junctionBp: 3, junctionDir: 'FORWARD' })
  })
  it('uses end_bp for a first (5′-end) overhang domain', () => {
    const dm = new Map([['o2', { domIdx: 0, domain: { start_bp: 3, end_bp: 8, direction: 'REVERSE' } }]])
    expect(buildJunctionMapFromDomains(dm).get('o2')).toEqual({ junctionBp: 8, junctionDir: 'REVERSE' })
  })
})

describe('buildJunctionMapFromXovers', () => {
  it('reads the junction bp/dir from the matching crossover side', () => {
    const specMap = buildSpecMap(design)
    const domainMap = buildDomainMapFromDesign(design, specMap)
    expect(buildJunctionMapFromXovers(design, specMap, domainMap).get('o1'))
      .toEqual({ junctionBp: 3, junctionDir: 'FORWARD' })
  })
  it('skips when no crossover joins the overhang and parent helices', () => {
    const specMap = buildSpecMap(design)
    const domainMap = buildDomainMapFromDesign(design, specMap)
    expect(buildJunctionMapFromXovers({ ...design, crossovers: [] }, specMap, domainMap).size).toBe(0)
  })
  it('preserves the first matching crossover when a helix pair repeats', () => {
    const later = { half_a: { helix_id: 'h2', index: 99, strand: 'REVERSE' },
      half_b: { helix_id: 'h1', index: 99, strand: 'REVERSE' } }
    const repeated = { ...design, crossovers: [...design.crossovers, later] }
    const specMap = buildSpecMap(repeated)
    const domainMap = buildDomainMapFromDesign(repeated, specMap)
    expect(buildJunctionMapFromXovers(repeated, specMap, domainMap).get('o1'))
      .toEqual({ junctionBp: 3, junctionDir: 'FORWARD' })
  })
})

describe('buildRootMap', () => {
  it('looks up the bead entry via helixCtrl with the "helix:bp:dir" key', () => {
    const entry = { pos: [1, 2, 3] }
    const helixCtrl = { lookupEntry: (k) => (k === 'h2:3:FORWARD' ? entry : null) }
    const specMap = buildSpecMap(design)
    const junctionMap = buildJunctionMapFromDomains(buildDomainMapFromDesign(design, specMap))
    expect(buildRootMap(specMap, junctionMap, helixCtrl).get('o1')).toEqual({ entry, pos: [1, 2, 3] })
  })
  it('skips entries the helixCtrl cannot resolve', () => {
    const helixCtrl = { lookupEntry: () => null }
    const specMap = buildSpecMap(design)
    const junctionMap = buildJunctionMapFromDomains(buildDomainMapFromDesign(design, specMap))
    expect(buildRootMap(specMap, junctionMap, helixCtrl).size).toBe(0)
  })
})
