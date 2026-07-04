// @vitest-environment jsdom
import { describe, it, expect } from 'vitest'
import {
  formatProgress,
  jobDisplayName,
  candoJobIsActive,
  solverLabel,
  detailStatusText,
  stageChip,
  formatSummary,
} from './cando_jobs_panel.js'

describe('formatProgress', () => {
  it('is 100% when completed, blank when failed/stopped', () => {
    expect(formatProgress({ status: 'completed' })).toBe('100%')
    expect(formatProgress({ status: 'failed' })).toBe('')
    expect(formatProgress({ status: 'stopped' })).toBe('')
  })
  it('rounds the running overall fraction', () => {
    expect(formatProgress({ status: 'running' }, { overall: 0.42 })).toBe('42%')
    expect(formatProgress({ status: 'running' }, { overall: 0 })).toBe('…')
  })
  it('is blank for a null job', () => {
    expect(formatProgress(null)).toBe('')
  })
})

describe('jobDisplayName', () => {
  it('prefers the source-path stem', () => {
    expect(jobDisplayName({ design_source_path: 'a/b/6hb_test.nadoc', design_name: 'x' }))
      .toBe('6hb_test')
  })
  it('falls back to design_name', () => {
    expect(jobDisplayName({ design_name: 'my6hb' })).toBe('my6hb')
    expect(jobDisplayName({})).toBe('design')
  })
})

describe('candoJobIsActive', () => {
  it('is true for queued/preparing/running only', () => {
    for (const s of ['queued', 'preparing', 'running']) {
      expect(candoJobIsActive({ status: s })).toBe(true)
    }
    for (const s of ['completed', 'failed', 'stopped']) {
      expect(candoJobIsActive({ status: s })).toBe(false)
    }
    expect(candoJobIsActive(null)).toBe(false)
  })
})

describe('solverLabel', () => {
  it('names the solver mode', () => {
    expect(solverLabel({ nonlinear: true })).toBe('Fine (nonlinear)')
    expect(solverLabel({ nonlinear: false })).toBe('Coarse (linear)')
  })
})

describe('detailStatusText', () => {
  it('reports the solver mode + ETA while running', () => {
    const t = detailStatusText({ status: 'running', nonlinear: true },
                               { overall: 0.5, eta_seconds: 12 })
    expect(t).toContain('Fine (nonlinear)')
    expect(t).toContain('50%')
    expect(t).toContain('~12s left')
  })
  it('reports the solve time + node count when completed', () => {
    const t = detailStatusText({ status: 'completed', nonlinear: false,
                                 sim_seconds: 4.3, n_nodes: 504 })
    expect(t).toContain('Coarse (linear)')
    expect(t).toContain('4.3s')
    expect(t).toContain('504 bp nodes')
  })
  it('surfaces the error when failed', () => {
    expect(detailStatusText({ status: 'failed', error: 'singular' }))
      .toContain('singular')
  })
})

describe('stageChip', () => {
  it('renders a filled glyph for a done stage', () => {
    expect(stageChip({ nonlinear: true, stages: [{ name: 'nonlinear', status: 'done' }] }))
      .toBe('● nonlinear')
  })
  it('falls back to the solver-derived stage name for a stage-less job', () => {
    expect(stageChip({ nonlinear: false })).toBe('○ linear')
  })
})

describe('formatSummary', () => {
  it('is blank unless completed', () => {
    expect(formatSummary({ status: 'running' })).toBe('')
    expect(formatSummary(null)).toBe('')
  })
  it('lists solver, node count and RMSF range', () => {
    const s = formatSummary({ status: 'completed', nonlinear: true, n_nodes: 504,
                              rmsf_min_nm: 0.296, rmsf_max_nm: 0.676 })
    expect(s).toContain('Fine (nonlinear)')
    expect(s).toContain('504 bp nodes')
    expect(s).toContain('0.30–0.68 nm')
  })
  it('omits the RMSF range when it was not computed', () => {
    const s = formatSummary({ status: 'completed', nonlinear: false, n_nodes: 504 })
    expect(s).toContain('Coarse (linear)')
    expect(s).not.toContain('RMSF')
  })
})
