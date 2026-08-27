import { describe, it, expect } from 'vitest'
import {
  niceTicks, dataToPixel, buildChartSpec, metricSeries, metricCSVs,
} from './metric_graph.js'
import { metricSpecs } from './metric_graph_popup.js'

describe('niceTicks', () => {
  it('spans the range with round values', () => {
    const t = niceTicks(0, 60, 5)
    expect(t[0]).toBeLessThanOrEqual(0)
    expect(t[t.length - 1]).toBeGreaterThanOrEqual(60)
    expect(t).toContain(20)                       // round step
  })
  it('handles degenerate/flat ranges', () => {
    expect(niceTicks(5, 5)).toEqual([5])
    expect(niceTicks(NaN, NaN)).toEqual([0])
  })
})

describe('dataToPixel', () => {
  it('maps endpoints and midpoint', () => {
    expect(dataToPixel(0, 0, 10, 100, 200)).toBe(100)
    expect(dataToPixel(10, 0, 10, 100, 200)).toBe(200)
    expect(dataToPixel(5, 0, 10, 100, 200)).toBe(150)
  })
  it('centres a degenerate domain', () => {
    expect(dataToPixel(3, 5, 5, 0, 100)).toBe(50)
  })
})

describe('buildChartSpec', () => {
  it('flags empty when no points', () => {
    expect(buildChartSpec({ series: [{ label: 'a', points: [] }] }).empty).toBe(true)
  })
  it('maps a series into the plot area with inverted y', () => {
    const spec = buildChartSpec({
      series: [{ label: 'a', color: '#fff', points: [[0, 0], [10, 100]] }],
      width: 400, height: 300, zeroLine: true,
    })
    expect(spec.empty).toBe(false)
    const [p0, p1] = spec.series[0].pts
    // x increases left→right
    expect(p1[0]).toBeGreaterThan(p0[0])
    // larger data value → smaller pixel-y (top of canvas)
    expect(p1[1]).toBeLessThan(p0[1])
    // all pixels inside the plot box
    for (const [x, y] of spec.series[0].pts) {
      expect(x).toBeGreaterThanOrEqual(spec.plot.x0 - 1e-6)
      expect(x).toBeLessThanOrEqual(spec.plot.x1 + 1e-6)
      expect(y).toBeLessThanOrEqual(spec.plot.y0 + 1e-6)
      expect(y).toBeGreaterThanOrEqual(spec.plot.y1 - 1e-6)
    }
    expect(spec.zeroY).not.toBeNull()             // range spans 0 → zero line drawn
  })
  it('adds a legend only for multiple series', () => {
    const one = buildChartSpec({ series: [{ label: 'a', color: '#f00', points: [[0, 1]] }] })
    const two = buildChartSpec({ series: [
      { label: 'a', color: '#f00', points: [[0, 1]] },
      { label: 'b', color: '#0f0', points: [[0, 2]] }] })
    expect(one.legend.length).toBe(0)
    expect(two.legend.length).toBe(2)
  })
})

const RESULT = {
  twist: {
    temporal: { per_frame: [1, 2, 3, 4], boundaries: [
      { job_id: 'aaa111', start_frame: 0 }, { job_id: 'bbb222', start_frame: 2 }] },
    spatial: [
      { job_id: 'aaa111', points: [[0, 0], [5, 10]] },
      { job_id: 'bbb222', points: [[0, 0], [5, 12]] }],
  },
  energy: {
    temporal: { per_frame: [-1000, -1010], x_values: [0.25, 0.5], boundaries: [
      { job_id: 'aaa111', start_x: 0 }, { job_id: 'bbb222', start_x: 0.5 }] },
    spatial: [],
  },
  rmsd: {
    temporal: { per_frame: [0, 0.12], frame_indices: [0, 8], boundaries: [] },
    spatial: [],
  },
}

describe('metricSeries', () => {
  it('temporal → one series indexed by frame', () => {
    const s = metricSeries(RESULT, 'twist', 'temporal')
    expect(s.length).toBe(1)
    expect(s[0].points).toEqual([[0, 1], [1, 2], [2, 3], [3, 4]])
  })
  it('spatial → one overlay series per job', () => {
    const s = metricSeries(RESULT, 'twist', 'spatial')
    expect(s.length).toBe(2)
    expect(s[0].points).toEqual([[0, 0], [5, 10]])
    expect(s[0].color).not.toBe(s[1].color)
  })
  it('empty for a missing metric', () => {
    expect(metricSeries(RESULT, 'nope', 'temporal')).toEqual([])
  })
  it('uses explicit simulation-time x values for NAMD scalar series', () => {
    expect(metricSeries(RESULT, 'energy', 'temporal')[0].points)
      .toEqual([[0.25, -1000], [0.5, -1010]])
  })
  it('uses sampled trajectory frame indices for aligned RMSD', () => {
    expect(metricSeries(RESULT, 'rmsd', 'temporal')[0].points)
      .toEqual([[0, 0], [8, 0.12]])
  })
})

describe('metricCSVs', () => {
  it('emits temporal (with job column when chained) + spatial CSV', () => {
    const { temporal, spatial } = metricCSVs(RESULT, 'twist')
    expect(temporal.split('\n')[0]).toBe('frame,value,job_id')
    expect(temporal).toContain('0,1,aaa111')
    expect(temporal).toContain('2,3,bbb222')       // boundary switches job at frame 2
    expect(spatial.split('\n')[0]).toBe('job_id,axial_nm,value')
    expect(spatial).toContain('aaa111,0,0')
    expect(spatial).toContain('bbb222,5,12')
  })
  it('uses measurement-specific headers and time boundaries for energy CSV', () => {
    const { temporal, spatial } = metricCSVs(RESULT, 'energy')
    expect(temporal.split('\n')[0])
      .toBe('simulation_time_ns,total_energy_kcal_per_mol,job_id')
    expect(temporal).toContain('0.25,-1000,aaa111')
    expect(temporal).toContain('0.5,-1010,bbb222')
    expect(spatial).toBe('job_id,axial_nm,value\n')
  })
  it('exports aligned RMSD with its unit-bearing value header', () => {
    const { temporal, spatial } = metricCSVs(RESULT, 'rmsd')
    expect(temporal).toBe('frame,aligned_dna_rmsd_nm\n0,0\n8,0.12\n')
    expect(spatial).toBe('job_id,axial_nm,value\n')
  })
})

describe('metricSpecs', () => {
  it('builds energy as a simulation-time graph without a fictional spatial graph', () => {
    const specs = metricSpecs('energy', RESULT, 'latest')
    expect(specs.spatial).toBeNull()
    expect(specs.temporal.empty).toBe(false)
    expect(specs.temporal.xLabel).toBe('simulation time (ns)')
    expect(specs.temporal.yLabel).toBe('total energy (kcal/mol)')
  })
  it('builds RMSD as a frame graph without a fictional spatial graph', () => {
    const specs = metricSpecs('rmsd', RESULT, 'latest')
    expect(specs.spatial).toBeNull()
    expect(specs.temporal.empty).toBe(false)
    expect(specs.temporal.xLabel).toBe('frame')
    expect(specs.temporal.yLabel).toBe('aligned RMSD (nm)')
  })
})
