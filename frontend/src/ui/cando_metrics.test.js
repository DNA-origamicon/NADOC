import { describe, it, expect } from 'vitest'
import {
  CANDO_METRIC_META, rmsfRows, deviationRows, helixSeries, candoMetricCSV, buildCandoSpec,
} from './cando_metrics.js'

describe('rmsfRows', () => {
  it('maps rmsf entries to per-bp rows', () => {
    const resp = { rmsf: [
      { helix_id: 0, bp_index: 0, rmsf_nm: 0.5 },
      { helix_id: 0, bp_index: 1, rmsf_nm: 0.7 },
      { helix_id: 1, bp_index: 0, rmsf_nm: 1.2 },
    ] }
    expect(rmsfRows(resp)).toEqual([
      { helix: 0, bp: 0, val: 0.5 },
      { helix: 0, bp: 1, val: 0.7 },
      { helix: 1, bp: 0, val: 1.2 },
    ])
  })
  it('drops non-finite values and empty/not-ready responses', () => {
    expect(rmsfRows({ rmsf: [{ helix_id: 0, bp_index: 0, rmsf_nm: null }] })).toEqual([])
    expect(rmsfRows({ ready: false, rmsf: [] })).toEqual([])
    expect(rmsfRows(null)).toEqual([])
  })
})

describe('deviationRows', () => {
  it('averages multiple nucleotides (strands + loop copies) at one (helix,bp) station', () => {
    const resp = { positions: [
      { helix_id: 0, bp_index: 0, direction: true,  copy: 0, deviation: 2.0 },
      { helix_id: 0, bp_index: 0, direction: false, copy: 0, deviation: 4.0 },   // → mean 3.0
      { helix_id: 0, bp_index: 1, direction: true,  copy: 0, deviation: 1.0 },
    ] }
    const rows = deviationRows(resp)
    expect(rows).toContainEqual({ helix: 0, bp: 0, val: 3.0 })
    expect(rows).toContainEqual({ helix: 0, bp: 1, val: 1.0 })
    expect(rows).toHaveLength(2)
  })
  it('returns [] for empty / not-ready', () => {
    expect(deviationRows({ ready: false, positions: [] })).toEqual([])
    expect(deviationRows(null)).toEqual([])
  })
})

describe('helixSeries', () => {
  it('groups rows into one series per string-id helix, numeric-aware sorted, bp-sorted incl. negatives', () => {
    // Real helix_id are strings like "h_XY_0_1"; bp_index can be negative (ss/loop ends).
    const rows = [
      { helix: 'h_XY_0_10', bp: 2, val: 9 },
      { helix: 'h_XY_0_2', bp: 1, val: 5 },
      { helix: 'h_XY_0_2', bp: -5, val: 4 },
      { helix: 'h_XY_0_10', bp: 0, val: 8 },
    ]
    const series = helixSeries(rows)
    // numeric-aware: _2 sorts before _10 (plain string sort would flip these)
    expect(series.map((s) => s.label)).toEqual(['helix h_XY_0_2', 'helix h_XY_0_10'])
    expect(series[0].points).toEqual([[-5, 4], [1, 5]])     // bp-sorted, negatives first
    expect(series[1].points).toEqual([[0, 8], [2, 9]])
    expect(series[0].color).not.toBe(series[1].color)       // distinct hues
  })
  it('returns [] for no rows', () => {
    expect(helixSeries([])).toEqual([])
    expect(helixSeries(null)).toEqual([])
  })
})

describe('candoMetricCSV', () => {
  it('emits a numeric-aware-sorted helix,bp,value table with the metric header', () => {
    const rows = [
      { helix: 'hA', bp: 0, val: 8 },
      { helix: 'h9', bp: 1, val: 5 },
      { helix: 'h9', bp: 0, val: 4 },
    ]
    expect(candoMetricCSV(rows, 'rmsf_nm')).toBe(
      'helix_id,bp_index,rmsf_nm\nh9,0,4\nh9,1,5\nhA,0,8\n')
  })
  it('handles empty rows', () => {
    expect(candoMetricCSV([], 'deviation_nm')).toBe('helix_id,bp_index,deviation_nm\n')
  })
})

describe('buildCandoSpec', () => {
  it('builds a non-empty spec with metric axis labels from rows', () => {
    const rows = [{ helix: 0, bp: 0, val: 0.5 }, { helix: 0, bp: 1, val: 0.9 }]
    const spec = buildCandoSpec('rmsf', rows)
    expect(spec.empty).toBe(false)
    expect(spec.yLabel).toBe(CANDO_METRIC_META.rmsf.yLabel)
    expect(spec.xLabel).toBe(CANDO_METRIC_META.rmsf.xLabel)
    expect(spec.series).toHaveLength(1)
  })
  it('yields an empty spec when there are no rows', () => {
    expect(buildCandoSpec('deviation', []).empty).toBe(true)
  })
})
