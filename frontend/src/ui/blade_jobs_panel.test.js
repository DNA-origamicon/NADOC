/**
 * Pure-helper tests for the BLADE jobs panel + metrics card.
 *
 * These pin the decisions that are easy to get silently wrong when a panel is cloned from an
 * engine with different physics: which jobs block a launch, what the status line says while an
 * external process is running, and — the BLADE-specific ones — that a sim-guard-refused job and
 * a silent CUDA→CPU fallback both surface instead of looking like nothing happened.
 */
import { describe, it, expect } from 'vitest'
import {
  formatProgress, jobDisplayName, bladeJobIsActive, launchBlocked, runningJob, seedReady,
  correctionLabel, modeLabel, solveDetailText, detailStatusText, stageChip, formatSummary,
} from './blade_jobs_panel.js'
import { summaryRows, renderSummaryHTML } from './blade_metrics_card.js'

const job = (over = {}) => ({ job_id: 'j1', status: 'completed', mode: 'relax', ...over })

describe('activity + launch gating', () => {
  it.each(['queued', 'preparing', 'running'])('treats %s as active', (status) => {
    expect(bladeJobIsActive(job({ status }))).toBe(true)
  })

  it.each(['completed', 'failed', 'stopped'])('treats %s as inactive', (status) => {
    expect(bladeJobIsActive(job({ status }))).toBe(false)
  })

  it('blocks a launch while one is mid-flight, even with no jobs yet', () => {
    expect(launchBlocked(true, [], null)).toBe(true)
  })

  it('blocks a launch while any BLADE job is still active', () => {
    expect(launchBlocked(false, [job({ status: 'running' })], null)).toBe(true)
  })

  it('allows a launch when every job has finished', () => {
    expect(launchBlocked(false, [job(), job({ status: 'failed' })], null)).toBe(false)
  })

  it('targets Stop at the in-flight job, not the selected one', () => {
    const done = job({ job_id: 'old' })
    const live = job({ job_id: 'new', status: 'running' })
    expect(runningJob([done, live])?.job_id).toBe('new')
  })

  it('has nothing for Stop to act on when all jobs are terminal', () => {
    expect(runningJob([job()])).toBeNull()
  })

  it('offers a NAMD seed only from a completed relax', () => {
    // Only a completed relax has a relaxed.pdb to hand off; anything else must not.
    expect(seedReady(job({ status: 'completed' }))).toBe(true)
    for (const status of ['queued', 'preparing', 'running', 'failed', 'stopped']) {
      expect(seedReady(job({ status }))).toBe(false)
    }
    expect(seedReady(null)).toBe(false)
  })
})

describe('naming', () => {
  it('prefers the source-path stem over the recorded design name', () => {
    expect(jobDisplayName(job({ design_source_path: '/ws/designs/6hb_v3.nadoc', design_name: 'x' })))
      .toBe('6hb_v3')
  })

  it('falls back to the design name when there is no source path', () => {
    expect(jobDisplayName(job({ design_name: 'curved' }))).toBe('curved')
  })

  it('distinguishes the baseline from the learned correction', () => {
    expect(correctionLabel(job())).toBe('CHARMM+OBC2')
    expect(correctionLabel(job({ correction: 'unified' }))).toContain('learned correction')
  })

  it('labels the run mode', () => {
    expect(modeLabel(job())).toBe('Relax')
    expect(modeLabel(job({ mode: 'seed_namd' }))).toBe('Seed NAMD')
  })
})

describe('progress text', () => {
  it('is 100% for a completed job regardless of the progress payload', () => {
    expect(formatProgress(job(), null)).toBe('100%')
  })

  it('is blank for failed/stopped jobs', () => {
    expect(formatProgress(job({ status: 'failed' }), { overall: 0.5 })).toBe('')
    expect(formatProgress(job({ status: 'stopped' }), { overall: 0.5 })).toBe('')
  })

  it('rounds the live fraction while running', () => {
    expect(formatProgress(job({ status: 'running' }), { overall: 0.423 })).toBe('42%')
  })

  it('shows an ellipsis for a running job that has not reported yet', () => {
    expect(formatProgress(job({ status: 'running' }), null)).toBe('…')
  })
})

describe('solveDetailText', () => {
  it('renders the step counter on its own line', () => {
    const out = solveDetailText({ step: 1200, n_steps: 3000 })
    expect(out.startsWith('\n')).toBe(true)
    expect(out).toContain('step 1,200/3,000')
  })

  it('flags a CPU fallback, because it is a ~20x slowdown and not a detail', () => {
    expect(solveDetailText({ platform_used: 'CPU' })).toContain('~20x slower')
  })

  it('says nothing when CUDA was actually used', () => {
    expect(solveDetailText({ platform_used: 'CUDA' })).toBe('')
  })

  it('is empty with no progress payload', () => {
    expect(solveDetailText(null)).toBe('')
  })
})

describe('detailStatusText', () => {
  it('explains a sim-guard refusal instead of showing a bare "Queued"', () => {
    // The backend leaves a refused job queued WITH the reason rather than failing it, so this
    // line is the only place the user learns why Run appeared to do nothing.
    const t = detailStatusText(job({ status: 'queued', error: 'A heavy simulation is running' }), null)
    expect(t).toContain('Not started')
    expect(t).toContain('heavy simulation')
  })

  it('shows the ordinary queued message when there is no refusal', () => {
    expect(detailStatusText(job({ status: 'queued' }), null)).toBe('Queued — preparing to relax.')
  })

  it('names the phase while running, so a step-less build stage is not read as stuck', () => {
    const t = detailStatusText(job({ status: 'running' }), { overall: 0.1, phase: 'build' })
    expect(t).toContain('build')
  })

  it('includes the ETA when one is known', () => {
    const t = detailStatusText(job({ status: 'running' }), { overall: 0.5, eta_seconds: 30 })
    expect(t).toContain('~30s left')
  })

  it('reports atoms and platform on completion', () => {
    const t = detailStatusText(job({ sim_seconds: 72, n_atoms: 2600, platform_used: 'CUDA' }), null)
    expect(t).toContain('72s')
    expect(t).toContain('2,600 atoms')
    expect(t).toContain('CUDA')
  })

  it('surfaces the failure reason', () => {
    expect(detailStatusText(job({ status: 'failed', error: 'no OpenMM env' }), null))
      .toContain('no OpenMM env')
  })
})

describe('stageChip', () => {
  it('glyphs each stage by status', () => {
    const t = stageChip(job({ stages: [
      { name: 'build', status: 'done' }, { name: 'relax', status: 'running' }] }))
    expect(t).toBe('● build  ◐ relax')
  })

  it('falls back to a single relax stage when a job carries none', () => {
    expect(stageChip(job({ stages: [] }))).toContain('relax')
  })
})

describe('formatSummary', () => {
  it('is empty until the job completes', () => {
    expect(formatSummary(job({ status: 'running' }))).toBe('')
  })

  it('leads with how far the structure actually moved', () => {
    const html = formatSummary(job({ n_atoms: 2600, rmsd_moved_A: 3.14159, rg_before_A: 50, rg_after_A: 48 }))
    expect(html).toContain('moved 3.14 Å RMSD')
    expect(html).toContain('2,600 atoms')
    expect(html).toContain('50.0 → 48.0 Å')
  })
})

describe('metrics card summary rows', () => {
  it('shows nothing for an incomplete job', () => {
    expect(summaryRows(job({ status: 'running' }))).toEqual([])
    expect(renderSummaryHTML([])).toBe('')
  })

  it('spells out a CUDA→CPU fallback rather than just saying "CPU"', () => {
    const rows = summaryRows(job({ platform: 'CUDA', platform_used: 'CPU' }))
    const platform = rows.find(([k]) => k === 'Platform')
    expect(platform[1]).toContain('CUDA unavailable')
  })

  it('reports a deliberate CPU run plainly, with no fallback wording', () => {
    const rows = summaryRows(job({ platform: 'CPU', platform_used: 'CPU' }))
    expect(rows.find(([k]) => k === 'Platform')[1]).toBe('CPU')
  })

  it('includes the bbox diagonal only when the summary carries it', () => {
    const without = summaryRows(job())
    expect(without.some(([k]) => k === 'Bounding-box diagonal')).toBe(false)
    const with_ = summaryRows(job({ summary: { bbox_diag_before_A: 300, bbox_diag_after_A: 290 } }))
    expect(with_.find(([k]) => k === 'Bounding-box diagonal')[1]).toBe('300.0 → 290.0 Å')
  })

  it('renders rows as a two-column grid', () => {
    const html = renderSummaryHTML([['A', 'B']])
    expect(html).toContain('grid-template-columns')
    expect(html).toContain('A')
    expect(html).toContain('B')
  })
})
