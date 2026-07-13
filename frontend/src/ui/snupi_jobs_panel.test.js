// @vitest-environment jsdom
import { describe, it, expect } from 'vitest'
import {
  formatProgress,
  jobDisplayName,
  snupiJobIsActive,
  launchBlocked,
  materialLabel,
  solverLabel,
  detailStatusText,
  stageChip,
  formatSummary,
} from './snupi_jobs_panel.js'

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
    expect(jobDisplayName({ design_source_path: 'a/b/6hbx100.nadoc', design_name: 'x' }))
      .toBe('6hbx100')
  })
  it('falls back to design_name', () => {
    expect(jobDisplayName({ design_name: 'bundle' })).toBe('bundle')
    expect(jobDisplayName({})).toBe('design')
    expect(jobDisplayName(null)).toBe('')
  })
})

describe('snupiJobIsActive', () => {
  it('is true for queued/preparing/running only', () => {
    for (const s of ['queued', 'preparing', 'running']) {
      expect(snupiJobIsActive({ status: s })).toBe(true)
    }
    for (const s of ['completed', 'failed', 'stopped']) {
      expect(snupiJobIsActive({ status: s })).toBe(false)
    }
    expect(snupiJobIsActive(null)).toBe(false)
  })
})

describe('launchBlocked', () => {
  it('blocks while launching', () => {
    expect(launchBlocked(true, [], null)).toBe(true)
  })
  it('blocks when any job in the list is active', () => {
    expect(launchBlocked(false, [{ status: 'completed' }, { status: 'running' }], null)).toBe(true)
  })
  it('blocks when the selected job is active', () => {
    expect(launchBlocked(false, [], { status: 'preparing' })).toBe(true)
  })
  it('allows when idle with no active jobs', () => {
    expect(launchBlocked(false, [{ status: 'completed' }], { status: 'completed' })).toBe(false)
  })
})

describe('materialLabel', () => {
  it('names snupi vs the cando baseline', () => {
    expect(materialLabel({ material: 'snupi' })).toBe('SNUPI')
    expect(materialLabel({ material: 'cando' })).toBe('CanDo (isotropic)')
    expect(materialLabel({})).toBe('SNUPI')   // default
    expect(materialLabel(null)).toBe('SNUPI')
  })
})

describe('solverLabel', () => {
  it('names Fine/Coarse from the nonlinear flag', () => {
    expect(solverLabel({ nonlinear: true })).toBe('Fine (nonlinear)')
    expect(solverLabel({ nonlinear: false })).toBe('Coarse (linear)')
  })
  it('names the Langevin dynamics modes when dynamics is set', () => {
    expect(solverLabel({ dynamics: true })).toBe('Dynamics (Langevin)')
    expect(solverLabel({ dynamics: true, hydrodynamics: true })).toBe('Dynamics (RPY)')
  })
})

describe('detailStatusText', () => {
  it('shows the material + solver + ETA while running', () => {
    const t = detailStatusText({ status: 'running', nonlinear: true, material: 'snupi' },
      { overall: 0.5, eta_seconds: 12 })
    expect(t).toContain('SNUPI')
    expect(t).toContain('Fine (nonlinear)')
    expect(t).toContain('50%')
    expect(t).toContain('12s left')
  })
  it('summarises a completed job', () => {
    const t = detailStatusText({ status: 'completed', nonlinear: false, material: 'cando',
      sim_seconds: 3.2, n_nodes: 210 })
    expect(t).toContain('CanDo (isotropic)')
    expect(t).toContain('Coarse (linear)')
    expect(t).toContain('3.2s')
    expect(t).toContain('210 bp nodes')
  })
  it('surfaces the failure error', () => {
    expect(detailStatusText({ status: 'failed', error: 'no duplex core' }))
      .toBe('Failed: no duplex core')
  })
  it('is blank for a null job', () => {
    expect(detailStatusText(null)).toBe('')
  })
})

describe('stageChip', () => {
  it('renders the single solver stage glyph', () => {
    expect(stageChip({ nonlinear: true, stages: [{ name: 'nonlinear', status: 'done' }] }))
      .toBe('● nonlinear')
    // no stages → synthesizes from the nonlinear flag
    expect(stageChip({ nonlinear: false })).toBe('○ linear')
  })
})

describe('formatSummary', () => {
  it('is blank unless completed', () => {
    expect(formatSummary({ status: 'running' })).toBe('')
    expect(formatSummary(null)).toBe('')
  })
  it('shows material, solver, nodes, and the RMSF range', () => {
    const html = formatSummary({ status: 'completed', nonlinear: true, material: 'snupi',
      n_nodes: 210, rmsf_min_nm: 0.12, rmsf_max_nm: 0.88 })
    expect(html).toContain('SNUPI')
    expect(html).toContain('210 bp nodes')
    expect(html).toContain('RMSF 0.12–0.88 nm')
  })
})
