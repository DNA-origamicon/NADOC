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
  autorefineJobStatusText,
  autorefineJobResultHtml,
  refineImproved,
  refineMarkCounts,
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
  it('summarises the final mark count + before/after deviation on done', () => {
    const run = { state: 'done', result: {
      edits_kept: [{}, {}, {}],
      converged_marks: { h0: { 10: -1, 20: -1 }, h1: { 15: 1 } },   // 3 marks total
      metrics: { before: { deviation: 2.19 }, after: { deviation: 1.99 } } } }
    expect(autorefineStatusText(run)).toBe('Done · 3 marks · deviation 1.99 nm (was 2.19 nm)')
  })
  it('counts the density-swept skips (edits_kept empty) on done', () => {
    // THE regression: a SQUARE density sweep lands its skips in converged_marks with zero greedy
    // edits — the status must report those marks, not "0 marks".
    const run = { state: 'done', result: {
      edits_kept: [],
      converged_marks: { h0: { 10: -1, 30: -1 }, h1: { 20: -1 } },   // 3 skips, 0 greedy edits
      density: { best_period: 40 },
      metrics: { before: { deviation: 1.73 }, after: { deviation: 0.46 } } } }
    expect(autorefineStatusText(run)).toBe('Done · 3 marks · deviation 0.46 nm (was 1.73 nm)')
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
  it('renders before→after rows with the target and greedy edit count', () => {
    const html = autorefineResultHtml({ mode: 'loops_and_skips',
      edits_kept: [{}, {}], converged_marks: { h0: { 5: -1 }, h1: { 9: 1 } },
      metrics: { before: { deviation: 2.19, bend_deg: 39.3, twist_deg: -2.1 },
                 after:  { deviation: 1.99, bend_deg: 45.9, twist_deg: -2.7 },
                 target: { bend_deg: 72.3, twist_deg: -1.7 } } })
    expect(html).toContain('1 skip + 1 loop kept')
    expect(html).toContain('deviation 2.19 nm → <b>1.99 nm</b> (target 0)')
    expect(html).toContain('curvature 39.3° → <b>45.9°</b> (target 72.3°)')
  })
  it('headlines the density sweep (period → deletions) for a square strut', () => {
    const html = autorefineResultHtml({ mode: 'skips_only', edits_kept: [],
      converged_marks: { h0: { 10: -1, 30: -1 }, h1: { 20: -1 } },
      density: { best_period: 40 },
      metrics: { before: { deviation: 1.73 }, after: { deviation: 0.46 }, target: {} } })
    expect(html).toContain('skip density: period 40 → 3 deletions')
    expect(html).toContain('deviation 1.73 nm → <b>0.46 nm</b> (target 0)')
  })
  it('is blank for no result', () => {
    expect(autorefineResultHtml(null)).toBe('')
  })
})

describe('autorefine JOB status/result', () => {
  const doneApplied = {
    status: 'completed', refine_applied: true, refine_n_marks: 26, refine_period: 36,
    refine_before_rmsd: 0.7154, refine_after_rmsd: 0.1919,
    refine_note: 'Applied 26 marks (period 36) · deviation 0.72→0.19 nm',
  }
  it('status text uses the server-built refine_note across states', () => {
    expect(autorefineJobStatusText(doneApplied)).toContain('Applied 26 marks')
    expect(autorefineJobStatusText({ status: 'running', refine_note: 'Sweeping skip density: period 40…' }))
      .toBe('Sweeping skip density: period 40…')
    expect(autorefineJobStatusText({ status: 'running' })).toBe('Autorefining…')
    expect(autorefineJobStatusText({ status: 'failed', error: 'boom' })).toBe('Failed: boom')
    expect(autorefineJobStatusText(null)).toBe('')
  })
  it('result HTML reports the applied marks + period + before/after, no Apply button', () => {
    const html = autorefineJobResultHtml(doneApplied)
    expect(html).toContain('Applied 26 loop/skip marks')
    expect(html).toContain('period 36')
    expect(html).toContain('deviation 0.72 nm → <b>0.19 nm</b>')
    expect(html).toContain('Feature Log')
  })
  it('result HTML says nothing-applied when no improvement', () => {
    const html = autorefineJobResultHtml({ status: 'completed', refine_applied: false, refine_before_rmsd: 0.3 })
    expect(html).toContain('No improving loop/skip program found')
    expect(html).toContain('Nothing applied')
  })
  it('result HTML is blank until completed', () => {
    expect(autorefineJobResultHtml({ status: 'running', refine_applied: true })).toBe('')
    expect(autorefineJobResultHtml(null)).toBe('')
  })
})

describe('refineImproved / refineMarkCounts', () => {
  it('refineImproved is true when RMSD dropped even with zero greedy edits (density sweep)', () => {
    expect(refineImproved({ before: { rmsd: 1.73 }, after: { rmsd: 0.46 }, edits_kept: [] }))
      .toBe(true)
    expect(refineImproved({ before: { rmsd: 1.0 }, after: { rmsd: 1.0 }, edits_kept: [] }))
      .toBe(false)
    expect(refineImproved(null)).toBe(false)
  })
  it('refineMarkCounts sums skips and loops across helices', () => {
    const c = refineMarkCounts({ converged_marks: { h0: { 1: -1, 2: -1 }, h1: { 3: 1 } } })
    expect(c).toEqual({ skips: 2, loops: 1, total: 3 })
    expect(refineMarkCounts({}).total).toBe(0)
  })
})
