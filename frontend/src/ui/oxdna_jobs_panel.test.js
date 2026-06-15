// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mountIds, clearDom } from '../test-helpers/factory_dom.js'

// Mock the API client so the panel fetches a controlled job set.
vi.mock('../api/client.js', () => ({
  oxdnaAvailable: vi.fn().mockResolvedValue({ available: false }),
  listOxdnaJobs: vi.fn(),
  getOxdnaProgress: vi.fn().mockResolvedValue({ overall: 1, stage_fraction: 0 }),
  getOxdnaRmsd: vi.fn().mockResolvedValue({ ready: true, mean: 2.31, max: 2.53, n_frames: 10 }),
  getOxdnaRmsf: vi.fn().mockResolvedValue({ ready: true, n_frames: 10, positions: [], min_rmsf: 0.1, max_rmsf: 1.4, mean_rmsf: 0.7 }),
  createMdJob: vi.fn().mockResolvedValue({ job_id: 'md1', status: 'queued' }),
  lastErrorMessage: () => null,
}))

import * as api from '../api/client.js'
import {
  formatProgress, latestHealth, detailStatusText, stageChips, jobDisplayName,
  productionState, jobListStatus, formatEta, seedReady, initOxdnaJobsPanel,
} from './oxdna_jobs_panel.js'

describe('formatEta', () => {
  it('formats seconds / minutes / hours', () => {
    expect(formatEta(45)).toBe('45s')
    expect(formatEta(90)).toBe('1m 30s')
    expect(formatEta(120)).toBe('2m')
    expect(formatEta(3600)).toBe('1h')
    expect(formatEta(3960)).toBe('1h 6m')
  })
  it('returns empty for unknown/invalid', () => {
    expect(formatEta(null)).toBe('')
    expect(formatEta(-5)).toBe('')
    expect(formatEta(Infinity)).toBe('')
  })
})

describe('productionState / jobListStatus', () => {
  it('productionState reflects the production stage', () => {
    expect(productionState({ stages: [{ kind: 'mc' }, { kind: 'equil' }] })).toBe('none')
    expect(productionState({ stages: [{ kind: 'production', status: 'running' }] })).toBe('running')
    expect(productionState({ stages: [{ kind: 'production', status: 'done' }] })).toBe('done')
    expect(productionState({ stages: [{ kind: 'production', status: 'failed' }] })).toBe('failed')
  })
  it('a completed relaxation with no production reads "production ready"', () => {
    expect(jobListStatus({ status: 'completed', stages: [{ kind: 'equil', status: 'done' }] }).label)
      .toBe('production ready')
  })
  it('running production reads "production"; completed reads "production done"', () => {
    expect(jobListStatus({ status: 'running', stages: [{ kind: 'production', status: 'running' }] }).label)
      .toBe('production')
    expect(jobListStatus({ status: 'completed', stages: [{ kind: 'production', status: 'done' }] }).label)
      .toBe('production done')
  })
  it('a still-relaxing job keeps its raw status', () => {
    expect(jobListStatus({ status: 'running', stages: [{ kind: 'md_relax', status: 'running' }] }).label)
      .toBe('running')
  })
})

describe('seedReady', () => {
  it('is true only when the relaxation has completed', () => {
    expect(seedReady({ status: 'completed' })).toBe(true)
    expect(seedReady({ status: 'running' })).toBe(false)
    expect(seedReady({ status: 'queued' })).toBe(false)
    expect(seedReady({ status: 'failed' })).toBe(false)
    expect(seedReady(null)).toBe(false)
  })
})

describe('jobDisplayName', () => {
  it('prefers the source-path file stem over a stale design_name', () => {
    expect(jobDisplayName({ design_name: '6hb_primitive', design_source_path: '6hb_OxDNA_test.nadoc' }))
      .toBe('6hb_OxDNA_test')
    expect(jobDisplayName({ design_name: 'old', design_source_path: '/ws/parts/My_Design.nadoc' }))
      .toBe('My_Design')
  })
  it('falls back to design_name when no source path', () => {
    expect(jobDisplayName({ design_name: 'foo' })).toBe('foo')
    expect(jobDisplayName({})).toBe('design')
  })
})

describe('formatProgress', () => {
  it('prefers the progress payload overall fraction', () => {
    const job = { stages: [{ status: 'done' }, { status: 'running' }, { status: 'pending' }] }
    expect(formatProgress(job, { overall: 0.5 })).toEqual({ pct: 50, done: 1, total: 3 })
  })

  it('falls back to done/total when no progress payload', () => {
    const job = { stages: [{ status: 'done' }, { status: 'done' }, { status: 'pending' }] }
    expect(formatProgress(job, null)).toEqual({ pct: 67, done: 2, total: 3 })
  })

  it('handles a job with no stages', () => {
    expect(formatProgress({ stages: [] }, null)).toEqual({ pct: 0, done: 0, total: 0 })
    expect(formatProgress(null, null)).toEqual({ pct: 0, done: 0, total: 0 })
  })
})

describe('latestHealth', () => {
  it('returns the last health sample', () => {
    const job = { health_samples: [{ stage: '1_mc_relax' }, { stage: '2_md_relax' }] }
    expect(latestHealth(job)).toEqual({ stage: '2_md_relax' })
  })
  it('returns null when there are no samples', () => {
    expect(latestHealth({ health_samples: [] })).toBe(null)
    expect(latestHealth({})).toBe(null)
    expect(latestHealth(null)).toBe(null)
  })
})

describe('detailStatusText — begin / monitor / finish statuses', () => {
  const stages = [
    { name: '1_mc_relax', kind: 'mc', status: 'pending' },
    { name: '2_md_relax', kind: 'md_relax', status: 'pending' },
    { name: '3_equil', kind: 'equil', status: 'pending' },
  ]

  it('beginning: a queued job reads queued with 0 done', () => {
    const job = { status: 'queued', current_stage_idx: 0, stages }
    expect(detailStatusText(job, { overall: 0 })).toBe('queued · 0/3 stages')
  })

  it('monitoring: a running job names the active stage and percent', () => {
    const running = [
      { name: '1_mc_relax', kind: 'mc', status: 'done' },
      { name: '2_md_relax', kind: 'md_relax', status: 'running' },
      { name: '3_equil', kind: 'equil', status: 'pending' },
    ]
    const job = { status: 'running', current_stage_idx: 1, stages: running }
    expect(detailStatusText(job, { overall: 0.5 })).toBe('Running · 1/3 stages · 2_md_relax · 50%')
  })

  it('finishing: a completed job reads completed with all stages done', () => {
    const done = stages.map((s) => ({ ...s, status: 'done' }))
    const job = { status: 'completed', current_stage_idx: 3, stages: done }
    expect(detailStatusText(job, { overall: 1 })).toBe('completed · 3/3 stages')
  })

  it('failure: a failed job reads failed', () => {
    const failed = [
      { name: '1_mc_relax', kind: 'mc', status: 'done' },
      { name: '2_md_relax', kind: 'md_relax', status: 'failed' },
      { name: '3_equil', kind: 'equil', status: 'pending' },
    ]
    const job = { status: 'failed', current_stage_idx: 1, stages: failed }
    expect(detailStatusText(job, null)).toBe('failed · 1/3 stages')
  })
})

describe('stageChips — timeline glyphs reflect stage status', () => {
  it('maps each stage status to its glyph', () => {
    const job = { stages: [
      { kind: 'mc', status: 'done' },
      { kind: 'md_relax', status: 'running' },
      { kind: 'equil', status: 'pending' },
    ] }
    expect(stageChips(job)).toEqual([
      { kind: 'mc', status: 'done', glyph: '●' },
      { kind: 'md_relax', status: 'running', glyph: '○' },
      { kind: 'equil', status: 'pending', glyph: '·' },
    ])
  })
  it('marks a failed stage with ✗', () => {
    const job = { stages: [{ kind: 'md_relax', status: 'failed' }] }
    expect(stageChips(job)[0].glyph).toBe('✗')
  })
  it('handles a job with no stages', () => {
    expect(stageChips({})).toEqual([])
    expect(stageChips(null)).toEqual([])
  })
})

describe('initOxdnaJobsPanel — per-design job filtering', () => {
  const IDS = [
    'oxdna-jobs-panel', 'oxdna-jobs-heading', 'oxdna-jobs-arrow', 'oxdna-jobs-body',
    'oxdna-jobs-status', 'oxdna-jobs-run-btn', 'oxdna-jobs-prod-btn', 'oxdna-jobs-prod-status',
    'oxdna-jobs-list', 'oxdna-jobs-detail', 'oxdna-jobs-show-all',
  ]
  let currentPath

  beforeEach(() => {
    clearDom()
    mountIds(IDS)
    currentPath = 'AlphaJob.nadoc'
    api.listOxdnaJobs.mockResolvedValue([
      { job_id: 'a1', design_name: 'A', design_source_path: 'AlphaJob.nadoc', status: 'completed', created_at: 2, stages: [] },
      { job_id: 'b1', design_name: 'B', design_source_path: 'BetaJob.nadoc', status: 'completed', created_at: 1, stages: [] },
    ])
  })
  afterEach(() => clearDom())

  const listText = () => document.getElementById('oxdna-jobs-list').textContent

  it('shows only the current design’s jobs, not other designs’', async () => {
    const panel = initOxdnaJobsPanel({ getWorkspacePath: () => currentPath })
    await panel.refresh()
    expect(listText()).toContain('AlphaJob')
    expect(listText()).not.toContain('BetaJob')   // other design's job filtered out
  })

  it('re-filters when the open design changes (workspace-path-change)', async () => {
    const panel = initOxdnaJobsPanel({ getWorkspacePath: () => currentPath })
    await panel.refresh()
    currentPath = 'BetaJob.nadoc'
    window.dispatchEvent(new CustomEvent('nadoc:workspace-path-change', { detail: { path: 'BetaJob.nadoc' } }))
    await Promise.resolve()
    expect(listText()).toContain('BetaJob')
    expect(listText()).not.toContain('AlphaJob')
  })

  it('shows a "no jobs yet" note for a new design with no matching jobs', async () => {
    const panel = initOxdnaJobsPanel({ getWorkspacePath: () => currentPath })
    await panel.refresh()
    currentPath = 'new_design.nadoc'                 // a fresh design, no jobs
    window.dispatchEvent(new CustomEvent('nadoc:workspace-path-change', { detail: { path: 'new_design.nadoc' } }))
    await Promise.resolve()
    expect(listText().toLowerCase()).toContain('no oxdna jobs')
  })

  it('shows the note when there is no open file path (brand-new unsaved design)', async () => {
    currentPath = null
    const panel = initOxdnaJobsPanel({ getWorkspacePath: () => currentPath })
    await panel.refresh()
    expect(listText().toLowerCase()).toContain('no oxdna jobs')   // never leaks other designs' jobs
  })
})

describe('initOxdnaJobsPanel — production buttons + flexibility map', () => {
  const SPEC = {
    'oxdna-jobs-panel': 'div', 'oxdna-jobs-heading': 'div', 'oxdna-jobs-arrow': 'div',
    'oxdna-jobs-body': 'div', 'oxdna-jobs-status': 'div', 'oxdna-jobs-prod-status': 'div',
    'oxdna-jobs-list': 'div', 'oxdna-jobs-detail': 'div', 'oxdna-jobs-detail-status': 'div',
    'oxdna-jobs-detail-error': 'div', 'oxdna-jobs-progress': 'div', 'oxdna-jobs-timeline': 'div',
    'oxdna-jobs-health': 'div', 'oxdna-jobs-show-all': 'input',
    'oxdna-jobs-run-btn': 'button', 'oxdna-jobs-prod-btn': 'button', 'oxdna-jobs-prod-steps': 'input',
    'oxdna-jobs-start-btn': 'button', 'oxdna-jobs-stop-btn': 'button', 'oxdna-jobs-delete-btn': 'button',
    'oxdna-jobs-display-toggle': 'input', 'oxdna-jobs-display-status': 'div',
    'oxdna-jobs-flex-toggle': 'input', 'oxdna-jobs-flex-status': 'div',
    'oxdna-jobs-flex-bar': 'div', 'oxdna-jobs-flex-legend': 'div',
    'oxdna-jobs-export-btn': 'button',
    'oxdna-jobs-seed-btn': 'button', 'oxdna-jobs-seed-status': 'div',
    // workspace colour-scale widget (middle-right)
    'flex-scale': 'div', 'flex-scale-max': 'input', 'flex-scale-min': 'input', 'flex-scale-reset': 'button',
  }
  const fakeDisplay = () => {
    let mode = null
    return {
      displayJob: vi.fn(async () => { mode = 'relaxed'; return { ok: true, n: 5, stage: 's' } }),
      displayRmsf: vi.fn(async () => { mode = 'rmsf'; return { ok: true, n: 5, min: 0.1, max: 1.4, mean: 0.7 } }),
      stopAndRestore: vi.fn(() => { mode = null }),
      isActive: () => mode !== null,
      mode: () => mode,
      activeJobId: () => null,
    }
  }
  const $ = (id) => document.getElementById(id)
  const relaxStages = (...extra) => [
    { kind: 'mc', status: 'done' }, { kind: 'md_relax', status: 'done' }, { kind: 'equil', status: 'done' }, ...extra,
  ]

  beforeEach(() => {
    clearDom(); mountIds(SPEC)
    api.oxdnaAvailable.mockResolvedValue({ available: true, oxdna_bin: 'x' })
  })
  afterEach(() => clearDom())

  async function selectFirstJob(panel) {
    await panel.refresh()
    $('oxdna-jobs-list').querySelector('div')?.click()
    await Promise.resolve(); await Promise.resolve(); await Promise.resolve()
  }

  it('a completed relaxation → Production enabled, Flexibility map disabled (waiting for production)', async () => {
    api.listOxdnaJobs.mockResolvedValue([{ job_id: 'j1', design_source_path: 'A.nadoc', status: 'completed',
      created_at: 1, current_stage_idx: 3, stages: relaxStages() }])
    const panel = initOxdnaJobsPanel({ getWorkspacePath: () => 'A.nadoc' })
    await selectFirstJob(panel)
    expect($('oxdna-jobs-prod-btn').disabled).toBe(false)     // production ready
    expect($('oxdna-jobs-flex-toggle').disabled).toBe(true)   // no production run yet
    expect($('oxdna-jobs-flex-status').textContent.toLowerCase()).toContain('waiting for production')
  })

  it('while production runs → both Relax and Production greyed; bar shows steps + ETA', async () => {
    api.getOxdnaProgress.mockResolvedValue({ overall: 0.8, stage_fraction: 0.4, eta_seconds: 200 })
    api.listOxdnaJobs.mockResolvedValue([{ job_id: 'j2', design_source_path: 'A.nadoc', status: 'running',
      created_at: 1, current_stage_idx: 3, stages: relaxStages({ kind: 'production', status: 'running', steps: 5000000 }) }])
    const panel = initOxdnaJobsPanel({ getWorkspacePath: () => 'A.nadoc' })
    await selectFirstJob(panel)
    expect($('oxdna-jobs-run-btn').disabled).toBe(true)
    expect($('oxdna-jobs-prod-btn').disabled).toBe(true)
    const prog = $('oxdna-jobs-progress').textContent
    expect(prog).toContain('2,000,000 / 5,000,000 steps')   // 0.4 × 5e6
    expect(prog).toContain('ETA ~3m 20s')                    // 200 s
  })

  it('after production completes → Flexibility map toggle unlocks; toggling it calls displayRmsf + shows the legend', async () => {
    const disp = fakeDisplay()
    api.listOxdnaJobs.mockResolvedValue([{ job_id: 'j3', design_source_path: 'A.nadoc', status: 'completed',
      created_at: 1, current_stage_idx: 4, stages: relaxStages({ kind: 'production', status: 'done', steps: 5000000 }) }])
    const panel = initOxdnaJobsPanel({ getWorkspacePath: () => 'A.nadoc', oxdnaDisplay: disp })
    await selectFirstJob(panel)

    const flex = $('oxdna-jobs-flex-toggle')
    expect(flex.disabled).toBe(false)
    flex.checked = true
    flex.dispatchEvent(new Event('change'))
    await Promise.resolve(); await Promise.resolve(); await Promise.resolve()

    expect(disp.displayRmsf).toHaveBeenCalledWith('j3')
    expect($('oxdna-jobs-flex-bar').innerHTML.toLowerCase()).toContain('ready')   // ✓ check
    expect($('oxdna-jobs-flex-legend').innerHTML.toLowerCase()).toContain('flexible')
    expect($('oxdna-jobs-flex-status').textContent.toLowerCase()).toContain('rmsf')
    // The workspace scale appears, seeded with the data min→max from displayRmsf.
    expect($('flex-scale').style.display).not.toBe('none')
    expect($('flex-scale-min').value).toBe('0.10')
    expect($('flex-scale-max').value).toBe('1.40')
  })

  it('editing the workspace scale bounds recolours via oxdnaDisplay.recolorRmsf', async () => {
    const disp = fakeDisplay()
    disp.recolorRmsf = vi.fn()
    api.listOxdnaJobs.mockResolvedValue([{ job_id: 'jB', design_source_path: 'A.nadoc', status: 'completed',
      created_at: 1, current_stage_idx: 4, stages: relaxStages({ kind: 'production', status: 'done', steps: 100 }) }])
    const panel = initOxdnaJobsPanel({ getWorkspacePath: () => 'A.nadoc', oxdnaDisplay: disp })
    await selectFirstJob(panel)
    const flex = $('oxdna-jobs-flex-toggle')
    flex.checked = true; flex.dispatchEvent(new Event('change'))
    await Promise.resolve(); await Promise.resolve(); await Promise.resolve()

    $('flex-scale-max').value = '0.8'
    $('flex-scale-max').dispatchEvent(new Event('change'))
    expect(disp.recolorRmsf).toHaveBeenLastCalledWith(0.1, 0.8)
  })

  it('flexibility map and OxDNA display are mutually exclusive', async () => {
    const disp = fakeDisplay()
    api.listOxdnaJobs.mockResolvedValue([{ job_id: 'jX', design_source_path: 'A.nadoc', status: 'completed',
      created_at: 1, current_stage_idx: 4, stages: relaxStages({ kind: 'production', status: 'done', steps: 100 }) }])
    const panel = initOxdnaJobsPanel({ getWorkspacePath: () => 'A.nadoc', oxdnaDisplay: disp })
    await selectFirstJob(panel)

    // Turn on the relaxed display first.
    const display = $('oxdna-jobs-display-toggle')
    display.checked = true; display.dispatchEvent(new Event('change'))
    await Promise.resolve(); await Promise.resolve()
    expect(disp.displayJob).toHaveBeenCalled()

    // Turning on the flexibility map must switch the relaxed display off.
    const flex = $('oxdna-jobs-flex-toggle')
    flex.checked = true; flex.dispatchEvent(new Event('change'))
    await Promise.resolve(); await Promise.resolve(); await Promise.resolve()
    expect(disp.displayRmsf).toHaveBeenCalled()
    expect($('oxdna-jobs-display-toggle').checked).toBe(false)
  })

  it('a completed relaxation → "Use as NAMD seed" enabled; click POSTs an MD job seeded from this oxDNA job', async () => {
    api.createMdJob.mockClear()
    api.listOxdnaJobs.mockResolvedValue([{ job_id: 'jSeed', design_source_path: 'A.nadoc', status: 'completed',
      created_at: 1, current_stage_idx: 3, stages: relaxStages() }])
    const panel = initOxdnaJobsPanel({ getWorkspacePath: () => 'A.nadoc' })
    await selectFirstJob(panel)

    const seed = $('oxdna-jobs-seed-btn')
    expect(seed.disabled).toBe(false)
    seed.click()
    await Promise.resolve(); await Promise.resolve(); await Promise.resolve()

    expect(api.createMdJob).toHaveBeenCalledTimes(1)
    const body = api.createMdJob.mock.calls[0][0]
    expect(body.oxdna_job_id).toBe('jSeed')
    expect(body.design_source_path).toBe('A.nadoc')
    expect($('oxdna-jobs-seed-status').textContent.toLowerCase()).toContain('namd seed job created')
  })

  it('on seed success → collapses the oxDNA panel and clicks the MD panel heading open', async () => {
    // oxDNA panel open, MD panel collapsed (so seed should collapse oxDNA + open MD).
    localStorage.setItem('nadoc.leftSidebar.sections.v1', JSON.stringify({
      dynamics: { 'oxdna-jobs-panel': false, 'md-jobs-panel': true },
    }))
    const mdHeading = document.createElement('div'); mdHeading.id = 'md-jobs-panel-heading'
    document.body.appendChild(mdHeading)
    let mdClicked = 0; mdHeading.addEventListener('click', () => { mdClicked++ })

    api.createMdJob.mockResolvedValue({ job_id: 'md9', status: 'queued' })
    api.listOxdnaJobs.mockResolvedValue([{ job_id: 'jSeed2', design_source_path: 'A.nadoc', status: 'completed',
      created_at: 1, current_stage_idx: 3, stages: relaxStages() }])
    const panel = initOxdnaJobsPanel({ getWorkspacePath: () => 'A.nadoc' })
    await selectFirstJob(panel)

    expect($('oxdna-jobs-body').style.display).not.toBe('none')   // open before
    $('oxdna-jobs-seed-btn').click()
    await Promise.resolve(); await Promise.resolve(); await Promise.resolve()

    expect($('oxdna-jobs-body').style.display).toBe('none')        // oxDNA collapsed
    expect(mdClicked).toBe(1)                                      // MD opened (was collapsed by default)
  })

  it('a still-running job → "Use as NAMD seed" stays disabled', async () => {
    api.listOxdnaJobs.mockResolvedValue([{ job_id: 'jRun', design_source_path: 'A.nadoc', status: 'running',
      created_at: 1, current_stage_idx: 1, stages: [{ kind: 'mc', status: 'done' }, { kind: 'md_relax', status: 'running' }] }])
    const panel = initOxdnaJobsPanel({ getWorkspacePath: () => 'A.nadoc' })
    await selectFirstJob(panel)
    expect($('oxdna-jobs-seed-btn').disabled).toBe(true)
  })
})
