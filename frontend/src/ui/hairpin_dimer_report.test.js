// @vitest-environment jsdom
import { describe, it, expect } from 'vitest'

import {
  HAIRPIN_DIMER_THRESHOLD_C,
  buildHairpinDimerIndex,
  createHairpinDimerIndexCache,
  domainsSignature,
  formatHairpinDimerCompact,
  formatHairpinDimerConditions,
  formatHairpinDimerLine,
  formatHairpinDimerTooltip,
  hairpinDimerHits,
  HAIRPIN_DIMER_COLORS,
  hairpinDimerCheckLevel,
  hairpinDimerIconEl,
  hairpinDimerLevel,
  hairpinDimerMarkers,
  hairpinDimerRecheckTargets,
  hairpinDimerStrandWarnings,
  hairpinDimerTargets,
  isHairpinDimerCheckCurrent,
  mergeHairpinDimerReport,
} from './hairpin_dimer_report.js'
import { LINKER, OA, OB, makeDesign, makeReport, makeWarningReport } from '../test-helpers/hairpin_dimer_fixture.js'

const withOverhangSeq = (design, id, sequence) => ({
  ...design,
  overhangs: design.overhangs.map(o => (o.id === id ? { ...o, sequence } : o)),
})

describe('mergeHairpinDimerReport', () => {
  it('a full-scope response replaces the report', () => {
    const prev = makeReport()
    const next = { ...makeReport(), checks: [makeReport().checks[1]] }
    expect(mergeHairpinDimerReport(prev, next).checks.map(c => c.key)).toEqual([`overhang:${OB}`])
  })

  it('a partial response replaces only its own keys', () => {
    const prev = makeReport()
    const recheck = { ...makeReport().checks[0], flagged: false, max_tm: 12 }
    const merged = mergeHairpinDimerReport(prev, { ...makeReport({ scope: 'partial' }), checks: [recheck] })
    expect(merged.checks).toHaveLength(3)
    expect(merged.checks.find(c => c.key === `overhang:${OA}`).max_tm).toBe(12)
    expect(merged.scope).toBe('all')
  })

  it('a response for another design starts over', () => {
    const other = { ...makeReport({ scope: 'partial' }), design_id: 'd2', checks: [] }
    expect(mergeHairpinDimerReport(makeReport(), other).checks).toEqual([])
  })
})

describe('staleness', () => {
  it('uses the backend domain-signature format', () => {
    const linker = makeDesign().strands.find(s => s.id === LINKER)
    expect(domainsSignature(linker)).toBe('h_a:21:0:REVERSE|__lnk__c1:0:5:FORWARD|h_b:21:0:REVERSE')
  })

  it('every check is current against the design it was computed from', () => {
    const design = makeDesign()
    for (const check of makeReport().checks) expect(isHairpinDimerCheckCurrent(check, design)).toBe(true)
  })

  it('editing an overhang sequence stales its checks and its linker', () => {
    const design = withOverhangSeq(makeDesign(), OA, 'T'.repeat(22))
    const [a, b, linker] = makeReport().checks
    expect(isHairpinDimerCheckCurrent(a, design)).toBe(false)
    expect(isHairpinDimerCheckCurrent(b, design)).toBe(true)
    expect(isHairpinDimerCheckCurrent(linker, design)).toBe(false)
  })

  it('resizing the backing domain stales the check (bases become N)', () => {
    const d = makeDesign()
    d.strands[0] = { ...d.strands[0], domains: [{ ...d.strands[0].domains[0], end_bp: 23 }] }
    expect(isHairpinDimerCheckCurrent(makeReport().checks[0], d)).toBe(false)
  })

  it('a bridge edit, a linker re-route, or a deleted strand stales the linker check', () => {
    const linker = makeReport().checks[2]
    const d1 = makeDesign()
    d1.overhang_connections = [{ ...d1.overhang_connections[0], bridge_sequence: 'TTTTTT' }]
    expect(isHairpinDimerCheckCurrent(linker, d1)).toBe(false)
    const d2 = makeDesign()
    d2.strands[2] = { ...d2.strands[2], domains: d2.strands[2].domains.slice(0, 2) }
    expect(isHairpinDimerCheckCurrent(linker, d2)).toBe(false)
    const d3 = makeDesign()
    d3.strands = d3.strands.slice(0, 2)
    expect(isHairpinDimerCheckCurrent(linker, d3)).toBe(false)
  })
})

describe('buildHairpinDimerIndex', () => {
  it('indexes flagged, current checks by strand, overhang and connection', () => {
    const idx = buildHairpinDimerIndex(makeReport(), makeDesign())
    expect([...idx.byStrand.keys()].sort()).toEqual([LINKER, 's_a'].sort())
    expect([...idx.byOverhang.keys()]).toEqual([OA])       // the linker does not flag OH-A/OH-B
    expect([...idx.byConnection.keys()]).toEqual(['c1'])
    expect(idx.flagged).toHaveLength(2)
  })

  it('indexes a cross-dimer under both of its overhangs', () => {
    const pair = { key: `overhang_pair:${OA}|${OB}`, kind: 'overhang_pair', strand_id: 's_a',
      overhang_ids: [OA, OB], flagged: true, dimer: { tm: 40, dg: -3 }, hairpin: null,
      inputs: { overhangs: makeReport().checks[2].inputs.overhangs } }
    const idx = buildHairpinDimerIndex({ ...makeReport(), checks: [pair] }, makeDesign())
    expect(idx.byOverhang.get(OA)).toEqual([pair])
    expect(idx.byOverhang.get(OB)).toEqual([pair])
  })

  it('is empty without a report, for another design, or once stale', () => {
    expect(buildHairpinDimerIndex(null, makeDesign()).flagged).toEqual([])
    expect(buildHairpinDimerIndex({ ...makeReport(), design_id: 'x' }, makeDesign()).flagged).toEqual([])
    const edited = withOverhangSeq(makeDesign(), OA, 'T'.repeat(22))
    expect(buildHairpinDimerIndex(makeReport(), edited).byStrand.has('s_a')).toBe(false)
  })

  it('the cache recomputes only when the report or design identity changes', () => {
    const cache = createHairpinDimerIndexCache()
    const report = makeReport(), design = makeDesign()
    const first = cache.get(report, design)
    expect(cache.get(report, design)).toBe(first)
    expect(cache.get(report, makeDesign())).not.toBe(first)
  })
})

describe('text', () => {
  const [a, b, linker] = makeReport().checks

  it('lists only structures above threshold, strongest first', () => {
    expect(hairpinDimerHits(a).map(h => h.label)).toEqual(['hairpin', 'self-dimer'])
    expect(hairpinDimerHits(a, 70).map(h => h.label)).toEqual(['hairpin'])
    expect(hairpinDimerHits(b)).toEqual([])
    expect(HAIRPIN_DIMER_THRESHOLD_C).toBe(30)
  })

  it('names the overhang and gives Tm + ΔG', () => {
    const line = formatHairpinDimerLine(a, { nameOf: id => (id === OA ? 'OH-A' : id) })
    expect(line).toBe('Overhang OH-A (22 nt): hairpin Tm 96.6 °C (ΔG₃₇ -12.5 kcal/mol); '
      + 'self-dimer Tm 67.8 °C (ΔG₃₇ -25.2 kcal/mol)')
    expect(formatHairpinDimerLine(linker)).toMatch(/^Linker strand \(50 nt\): hairpin Tm 90\.2 °C/)
    expect(formatHairpinDimerCompact([a])).toBe('hairpin Tm 96.6 °C · self-dimer Tm 67.8 °C')
  })

  it('tooltip carries a header, one line per check and optionally the structure', () => {
    const tip = formatHairpinDimerTooltip([a, linker], { withStructure: true })
    const lines = tip.split('\n')
    expect(lines[0]).toBe('⚠ Strong secondary structure — Tm > 50 °C')     // both > 50 °C
    expect(formatHairpinDimerTooltip(makeWarningReport().checks.slice(0, 1)).split('\n')[0])
      .toBe('⚠ Secondary structure with Tm > 30 °C')
    expect(lines.filter(l => /Tm \d/.test(l))).toHaveLength(2)
    expect(tip).toContain('Strongest (hairpin):')
    expect(tip).toContain('GCGCGCGCTTTTGCGCGCGCTT')
  })

  it('strand warnings map every flagged strand to its tooltip', () => {
    const design = makeDesign()
    const m = hairpinDimerStrandWarnings(buildHairpinDimerIndex(makeReport(), design), design)
    expect([...m.keys()].sort()).toEqual([LINKER, 's_a'].sort())
    expect(m.get('s_a').text).toContain('Overhang OH-A')
    expect(m.get('s_a').level).toBe('critical')
  })

  it('states the origami buffer the report was computed for', () => {
    expect(formatHairpinDimerConditions(makeReport().conditions)).toBe('10 mM Mg²⁺, 0 mM Na⁺, 200 nM oligo')
  })

  it('a ⚠ with a handler is a button that swallows the click', () => {
    let opened = 0, rowClicks = 0
    const row = document.createElement('div')
    row.addEventListener('click', () => { rowClicks++ })
    const icon = hairpinDimerIconEl('tip', document, () => { opened++ })
    row.appendChild(icon)
    icon.click()
    icon.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
    expect(opened).toBe(2)
    expect(rowClicks).toBe(0)
    expect(icon.getAttribute('role')).toBe('button')
    expect(hairpinDimerIconEl('tip').getAttribute('role')).toBeNull()   // tooltip-only form
  })
})

describe('live targets, re-check and markers', () => {
  it('targets mirror the backend scope: backed, non-auxiliary overhangs + linker strands', () => {
    const d = makeDesign()
    d.overhangs = [...d.overhangs,
      { id: 'aux', auxiliary_endpoint: true, strand_id: 's_a', sub_domains: [] },
      { id: 'orphan', strand_id: 'gone', sub_domains: [] }]
    expect(hairpinDimerTargets(d)).toEqual({ overhangIds: [OA, OB], linkerIds: [LINKER] })
  })

  it('nothing to re-check right after a full check; everything for another design', () => {
    expect(hairpinDimerRecheckTargets(makeReport(), makeDesign())).toEqual({ overhang_ids: [], strand_ids: [] })
    const other = { ...makeDesign(), id: 'd2' }
    expect(hairpinDimerRecheckTargets(makeReport(), other)).toEqual({ overhang_ids: [OA, OB], strand_ids: [LINKER] })
  })

  it('an edited overhang re-checks itself and the linker bound to it', () => {
    const d = withOverhangSeq(makeDesign(), OA, 'T'.repeat(22))
    expect(hairpinDimerRecheckTargets(makeReport(), d)).toEqual({ overhang_ids: [OA], strand_ids: [LINKER] })
  })

  it('one marker per flagged strand, anchored on the flagged overhang or the linker', () => {
    const markers = hairpinDimerMarkers(makeReport(), makeDesign())
    const byStrand = Object.fromEntries(markers.map(m => [m.strandId, m]))
    expect(Object.keys(byStrand).sort()).toEqual([LINKER, 's_a'].sort())
    expect(byStrand.s_a.domains).toEqual([expect.objectContaining({ helix_id: 'h_a', overhang_id: OA })])
    expect(byStrand.s_a.label).toBe('OH-A')
    expect(byStrand.s_a.tooltip).toContain('hairpin Tm 96.6 °C')
    expect(byStrand[LINKER].domains).toHaveLength(3)
    expect(hairpinDimerMarkers(null, makeDesign())).toEqual([])
  })
})

describe('severity levels (amber > 30 °C, red > 50 °C)', () => {
  it('uses the backend severity, else max_tm against the critical threshold', () => {
    const [a, b] = makeReport().checks
    expect(hairpinDimerCheckLevel(a)).toBe('critical')
    expect(hairpinDimerCheckLevel(b)).toBeNull()
    expect(hairpinDimerCheckLevel(makeWarningReport().checks[0])).toBe('warning')
    const noField = { flagged: true, max_tm: 50 }                 // strict: 50.0 is not > 50
    expect(hairpinDimerCheckLevel(noField)).toBe('warning')
    expect(hairpinDimerCheckLevel({ ...noField, max_tm: 50.01 })).toBe('critical')
    expect(hairpinDimerCheckLevel(noField, 40)).toBe('critical')
  })

  it('a strand takes its worst level', () => {
    const w = makeWarningReport().checks[0], c = makeReport().checks[0]
    expect(hairpinDimerLevel([w])).toBe('warning')
    expect(hairpinDimerLevel([w, c])).toBe('critical')
    expect(hairpinDimerLevel([])).toBeNull()
  })

  it('markers and icons carry the level colour', () => {
    expect(hairpinDimerMarkers(makeReport(), makeDesign()).every(m => m.level === 'critical')).toBe(true)
    expect(hairpinDimerMarkers(makeWarningReport(), makeDesign()).map(m => m.level)).toEqual(['warning'])
    const red = hairpinDimerIconEl('t', document, null, 'critical')
    expect(red.classList.contains('hd-warn-icon--critical')).toBe(true)
    expect(red.style.color).toBe('rgb(248, 81, 73)')               // HAIRPIN_DIMER_COLORS.critical
    expect(hairpinDimerIconEl('t').style.color).toBe('rgb(210, 153, 34)')
    expect(HAIRPIN_DIMER_COLORS).toEqual({ warning: '#d29922', critical: '#f85149' })
  })
})
