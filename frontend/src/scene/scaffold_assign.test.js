import { describe, it, expect } from 'vitest'
import { ascWarningText, SCAFFOLD_LENGTHS, countScaffoldNt } from './scaffold_assign.js'

describe('SCAFFOLD_LENGTHS', () => {
  it('has the known scaffold lengths', () => {
    expect(SCAFFOLD_LENGTHS.M13mp18).toBe(7249)
    expect(SCAFFOLD_LENGTHS.p8064).toBe(8064)
  })
})

describe('ascWarningText', () => {
  it('warns when a custom sequence is shorter than the scaffold', () => {
    const t = ascWarningText({ customRaw: 'ACGT', totalNt: 10 })
    expect(t).toContain('Custom sequence (4 nt)')
    expect(t).toContain('6 bases will be assigned')
  })
  it('no warning when the custom sequence is long enough', () => {
    expect(ascWarningText({ customRaw: 'A'.repeat(10), totalNt: 10 })).toBeNull()
  })
  it('warns when scaffold exceeds the chosen reference (no custom seq)', () => {
    const t = ascWarningText({ customRaw: '', totalNt: 7300, scaffoldName: 'M13mp18', scaffoldLen: 7249 })
    expect(t).toContain('Scaffold (7300 nt) exceeds M13mp18 (7249 nt)')
    expect(t).toContain("51 bases will be assigned 'N'")
  })
  it('no warning when scaffold fits the reference', () => {
    expect(ascWarningText({ customRaw: '', totalNt: 5000, scaffoldLen: 7249 })).toBeNull()
  })
  it('custom-seq branch ignores scaffold length', () => {
    // Custom present + long enough → null even though scaffold would otherwise warn.
    expect(ascWarningText({ customRaw: 'A'.repeat(9000), totalNt: 8000, scaffoldLen: 100 })).toBeNull()
  })
})

describe('countScaffoldNt', () => {
  it('returns 0 when there is no scaffold strand', () => {
    expect(countScaffoldNt({ helices: [], strands: [{ strand_type: 'staple', domains: [] }] })).toBe(0)
  })
  it('returns 0 for null/empty design', () => {
    expect(countScaffoldNt(null)).toBe(0)
    expect(countScaffoldNt({})).toBe(0)
  })
  it('counts a plain forward domain (inclusive of both endpoints)', () => {
    const design = {
      helices: [],
      strands: [{ strand_type: 'scaffold', domains: [{ helix_id: 0, direction: 'FORWARD', start_bp: 0, end_bp: 9 }] }],
    }
    expect(countScaffoldNt(design)).toBe(10) // 0..9 inclusive
  })
  it('counts a reverse domain by walking downward', () => {
    const design = {
      helices: [],
      strands: [{ strand_type: 'scaffold', domains: [{ helix_id: 0, direction: 'REVERSE', start_bp: 9, end_bp: 0 }] }],
    }
    expect(countScaffoldNt(design)).toBe(10)
  })
  it('sums across multiple domains', () => {
    const design = {
      helices: [],
      strands: [{ strand_type: 'scaffold', domains: [
        { helix_id: 0, direction: 'FORWARD', start_bp: 0, end_bp: 4 },  // 5
        { helix_id: 1, direction: 'FORWARD', start_bp: 0, end_bp: 2 },  // 3
      ] }],
    }
    expect(countScaffoldNt(design)).toBe(8)
  })
  it('skips (delta=-1) contribute 0 nt; loops (delta=+1) contribute 2 nt', () => {
    const design = {
      helices: [{ id: 0, loop_skips: [
        { bp_index: 2, delta: -1 },  // skip → 0 nt at bp 2
        { bp_index: 4, delta: 1 },   // loop → 2 nt at bp 4
      ] }],
      strands: [{ strand_type: 'scaffold', domains: [{ helix_id: 0, direction: 'FORWARD', start_bp: 0, end_bp: 4 }] }],
    }
    // bp 0,1,3 → 1 nt each (3); bp 2 skip → 0; bp 4 loop → 2; total 5
    expect(countScaffoldNt(design)).toBe(5)
  })
  it('targets one scaffold strand by id (right-click "Assign sequence…")', () => {
    const design = {
      helices: [],
      strands: [
        { id: 'sA', strand_type: 'scaffold', domains: [{ helix_id: 0, direction: 'FORWARD', start_bp: 0, end_bp: 4 }] },   // 5
        { id: 'sB', strand_type: 'scaffold', domains: [{ helix_id: 1, direction: 'FORWARD', start_bp: 0, end_bp: 99 }] },  // 100
      ],
    }
    expect(countScaffoldNt(design, 'sB')).toBe(100)
    expect(countScaffoldNt(design, 'sA')).toBe(5)
    expect(countScaffoldNt(design)).toBe(5)  // no id → first scaffold
  })
  it('returns 0 for an unknown or non-scaffold target id', () => {
    const design = {
      helices: [],
      strands: [
        { id: 'sA', strand_type: 'scaffold', domains: [{ helix_id: 0, direction: 'FORWARD', start_bp: 0, end_bp: 4 }] },
        { id: 'st1', strand_type: 'staple', domains: [{ helix_id: 0, direction: 'REVERSE', start_bp: 4, end_bp: 0 }] },
      ],
    }
    expect(countScaffoldNt(design, 'nope')).toBe(0)
    expect(countScaffoldNt(design, 'st1')).toBe(0)
  })
  it('honours loop/skip deltas for a targeted strand', () => {
    const design = {
      helices: [{ id: 1, loop_skips: [{ bp_index: 2, delta: -1 }, { bp_index: 3, delta: 1 }] }],
      strands: [
        { id: 'sA', strand_type: 'scaffold', domains: [{ helix_id: 0, direction: 'FORWARD', start_bp: 0, end_bp: 9 }] },
        { id: 'sB', strand_type: 'scaffold', domains: [{ helix_id: 1, direction: 'FORWARD', start_bp: 0, end_bp: 4 }] },
      ],
    }
    // sB: bp 0,1,4 → 1 nt each (3); bp 2 skip → 0; bp 3 loop → 2; total 5
    expect(countScaffoldNt(design, 'sB')).toBe(5)
  })
  it('loop_skips are keyed per-helix, not applied across helices', () => {
    const design = {
      helices: [{ id: 0, loop_skips: [{ bp_index: 1, delta: -1 }] }],
      strands: [{ strand_type: 'scaffold', domains: [
        { helix_id: 0, direction: 'FORWARD', start_bp: 0, end_bp: 2 },  // bp1 skipped → 2 nt
        { helix_id: 1, direction: 'FORWARD', start_bp: 0, end_bp: 2 },  // no skips → 3 nt
      ] }],
    }
    expect(countScaffoldNt(design)).toBe(5)
  })
})
