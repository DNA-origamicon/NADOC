// @vitest-environment jsdom
import { describe, it, expect } from 'vitest'
import {
  formatProgress,
  jobDisplayName,
  mrdnaJobIsActive,
  detailStatusText,
  coarseStageChip,
  formatCurvature,
} from './mrdna_jobs_panel.js'

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
})

describe('jobDisplayName', () => {
  it('prefers the source-path stem', () => {
    expect(jobDisplayName({ design_source_path: 'a/b/6hb_test.nadoc', design_name: 'x' }))
      .toBe('6hb_test')
  })
  it('falls back to design_name', () => {
    expect(jobDisplayName({ design_name: 'mydesign' })).toBe('mydesign')
    expect(jobDisplayName({})).toBe('design')
  })
})

describe('mrdnaJobIsActive', () => {
  it('is true for queued/preparing/running only', () => {
    for (const s of ['queued', 'preparing', 'running']) {
      expect(mrdnaJobIsActive({ status: s })).toBe(true)
    }
    for (const s of ['completed', 'failed', 'stopped']) {
      expect(mrdnaJobIsActive({ status: s })).toBe(false)
    }
  })
})

describe('detailStatusText', () => {
  it('shows an ETA while running', () => {
    const t = detailStatusText({ status: 'running' }, { overall: 0.5, eta_seconds: 12 })
    expect(t).toContain('50%')
    expect(t).toContain('12s left')
  })
  it('summarises a completed run', () => {
    const t = detailStatusText({ status: 'completed', sim_seconds: 8.4, n_beads: 635 })
    expect(t).toContain('8.4s')
    expect(t).toContain('635 CG beads')
  })
  it('surfaces the failure message', () => {
    expect(detailStatusText({ status: 'failed', error: 'boom' })).toContain('boom')
  })
})

describe('coarseStageChip', () => {
  it('glyphs each stage (coarse, and fine when present)', () => {
    expect(coarseStageChip({ stages: [{ name: 'coarse', status: 'done' }] })).toBe('● coarse')
    expect(coarseStageChip({ stages: [{ name: 'coarse', status: 'running' }] })).toBe('◐ coarse')
    expect(coarseStageChip({ stages: [{ name: 'coarse', status: 'failed' }] })).toBe('✗ coarse')
    expect(coarseStageChip({})).toBe('○ coarse')
    expect(coarseStageChip({ stages: [
      { name: 'coarse', status: 'done' }, { name: 'fine', status: 'running' }] }))
      .toBe('● coarse  ◐ fine')
  })
})

describe('formatCurvature', () => {
  const analytic = { has_marks: true, radius_nm: 36, kappa_deg_per_nm: 1.58, bend_deg: 88 }

  it('says nothing to bend when the design has no marks', () => {
    expect(formatCurvature({ analytic: { has_marks: false } })).toMatch(/nothing to bend/)
    expect(formatCurvature(null)).toMatch(/nothing to bend/)
  })
  it('shows the designed curvature', () => {
    const html = formatCurvature({ analytic, measured: null })
    expect(html).toMatch(/Designed/)
    expect(html).toMatch(/36 nm/)
    expect(html).toMatch(/88°/)
  })
  it('nudges to run Fine when the run was coarse-only', () => {
    const html = formatCurvature({ analytic, measured: { radius_nm: 300, bend_deg: 3 }, fine: false })
    expect(html).toMatch(/Coarse run/)
    expect(html).toMatch(/Run <b>Fine<\/b>/)
  })
  it('shows simulated vs designed with a ratio for a fine run', () => {
    const html = formatCurvature({
      analytic, measured: { radius_nm: 45, bend_deg: 70 }, fine: true, ratio: 0.8 })
    expect(html).toMatch(/Simulated/)
    expect(html).toMatch(/45 nm/)
    expect(html).toMatch(/80% of designed/)
  })
  it('flags the CG under-reproduction caveat on a low ratio', () => {
    const html = formatCurvature({
      analytic, measured: { radius_nm: 900, bend_deg: 4 }, fine: true, ratio: 0.05 })
    expect(html).toMatch(/under-reproduces loop\/skip curvature/)
    expect(html).toMatch(/5% of designed/)
  })
  it('formats a straight (infinite-radius) measurement', () => {
    const html = formatCurvature({
      analytic, measured: { radius_nm: Infinity, bend_deg: 1 }, fine: true, ratio: null })
    expect(html).toMatch(/straight/)
  })
})
