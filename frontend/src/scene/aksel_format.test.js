import { describe, it, expect } from 'vitest'
import { formatScoreSummary, formatGraphSummary } from './aksel_format.js'

describe('formatScoreSummary', () => {
  it('formats a populated report', () => {
    const lines = formatScoreSummary({ summary: {
      staple_count: 10, scored_staple_count: 8, total_bound_nt: 420,
      length_violation_count: 2, warning_count: 1, Q_origami: 0.0012345,
    } })
    expect(lines).toEqual([
      'Staples: 10 (8 scored)',
      'Bound nt: 420',
      'Length violations: 2',
      'Warnings: 1',
      'Q: 1.234e-3',
    ])
  })
  it('defaults missing fields to 0 and Q to n/a', () => {
    expect(formatScoreSummary({})).toEqual([
      'Staples: 0 (0 scored)', 'Bound nt: 0', 'Length violations: 0', 'Warnings: 0', 'Q: n/a',
    ])
    expect(formatScoreSummary(undefined)[4]).toBe('Q: n/a')
  })
})

describe('formatGraphSummary', () => {
  it('formats a populated report', () => {
    const lines = formatGraphSummary({ summary: {
      complete_precursor_count: 3, precursor_count: 5, edge_count: 12,
      best_total_bound_nt: 500, best_Q_origami: 0.00042,
    } })
    expect(lines).toEqual([
      'Precursors: 3/5 complete',
      'Candidate edges: 12',
      'Best bound nt: 500',
      'Best Q: 4.200e-4',
    ])
  })
  it('defaults missing fields and best Q to n/a', () => {
    expect(formatGraphSummary({})).toEqual([
      'Precursors: 0/0 complete', 'Candidate edges: 0', 'Best bound nt: 0', 'Best Q: n/a',
    ])
  })
})
