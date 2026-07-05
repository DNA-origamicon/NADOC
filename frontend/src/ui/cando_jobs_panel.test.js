// @vitest-environment jsdom
import { describe, it, expect } from 'vitest'
import {
  formatProgress,
  jobDisplayName,
  candoJobIsActive,
  launchBlocked,
  solverLabel,
  detailStatusText,
  stageChip,
  formatSummary,
  autorefineStatusText,
  autorefineResultHtml,
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

describe('launchBlocked', () => {
  it('blocks while a launch is mid-flight (before any job registers)', () => {
    expect(launchBlocked(true, [], null)).toBe(true)
  })
  it('blocks while any job in the list is still active', () => {
    expect(launchBlocked(false, [{ status: 'completed' }, { status: 'running' }], null)).toBe(true)
    expect(launchBlocked(false, [{ status: 'queued' }], null)).toBe(true)
  })
  it('blocks while the selected job is active even if not in the filtered list', () => {
    expect(launchBlocked(false, [], { status: 'preparing' })).toBe(true)
  })
  it('allows a launch when idle: no launch in-flight and every job finished', () => {
    expect(launchBlocked(false, [{ status: 'completed' }, { status: 'failed' }], null)).toBe(false)
    expect(launchBlocked(false, [], null)).toBe(false)
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

describe('autorefineStatusText', () => {
  it('shows iteration index + current→target twist/curve/deviation while running', () => {
    const run = { state: 'running', last_event: { phase: 'iteration', iteration: 2, n_hotspots: 4,
      current: { deviation: 2.07, bend_deg: 42.2, twist_deg: 1.0 },
      target:  { deviation: 0.0, bend_deg: 72.3, twist_deg: -1.7 } } }
    const s = autorefineStatusText(run)
    expect(s).toContain('Iteration 2/4')
    expect(s).toContain('dev 2.07 nm→0.00 nm')
    expect(s).toContain('curve 42.2°→72.3°')
    expect(s).toContain('twist 1.0°→-1.7°')
  })
  it('renders — for an unresolved (null) metric', () => {
    const run = { state: 'running', last_event: { phase: 'iteration', iteration: 1,
      current: { deviation: 1.0, bend_deg: null, twist_deg: null }, target: { deviation: 0 } } }
    expect(autorefineStatusText(run)).toContain('curve —→—')
  })
  it('summarises edits + before/after deviation on done', () => {
    const run = { state: 'done', result: { edits_kept: [{}, {}, {}],
      metrics: { before: { deviation: 2.19 }, after: { deviation: 1.99 } } } }
    expect(autorefineStatusText(run)).toBe('Done · 3 edits · deviation 1.99 nm (was 2.19 nm)')
  })
  it('reports baseline / hotspots phases and errors', () => {
    expect(autorefineStatusText({ state: 'running', last_event: { phase: 'baseline' } }))
      .toBe('Solving baseline shape…')
    expect(autorefineStatusText({ state: 'running', last_event: { phase: 'hotspots', n: 1 } }))
      .toBe('Found 1 deviation hotspot…')
    expect(autorefineStatusText({ state: 'error', error: 'boom' })).toBe('Failed: boom')
    expect(autorefineStatusText(null)).toBe('')
  })
})

describe('autorefineResultHtml', () => {
  it('renders before→after rows with the target and edit count', () => {
    const html = autorefineResultHtml({ mode: 'loops_and_skips', edits_kept: [{}, {}],
      metrics: { before: { deviation: 2.19, bend_deg: 39.3, twist_deg: -2.1 },
                 after:  { deviation: 1.99, bend_deg: 45.9, twist_deg: -2.7 },
                 target: { bend_deg: 72.3, twist_deg: -1.7 } } })
    expect(html).toContain('2 loops+skips edits kept')
    expect(html).toContain('deviation 2.19 nm → <b>1.99 nm</b> (target 0)')
    expect(html).toContain('curvature 39.3° → <b>45.9°</b> (target 72.3°)')
  })
  it('is blank for no result', () => {
    expect(autorefineResultHtml(null)).toBe('')
  })
})
