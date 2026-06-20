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
  getOxdnaTrajectory: vi.fn().mockResolvedValue({ ready: true, n_frames: 4, keys: [], frames: [[]], markers: [], stages: [] }),
  createMdJob: vi.fn().mockResolvedValue({ job_id: 'md1', status: 'queued' }),
  lastErrorMessage: () => null,
}))

import * as api from '../api/client.js'
import {
  formatProgress, latestHealth, detailStatusText, stageChips, jobDisplayName,
  productionState, jobListStatus, formatEta, seedReady, initOxdnaJobsPanel,
  jobIsActive, isRelaxRunning, isProductionRunning, makeSpinner,
  productionRunCount, hasTrajectory, isResumable, startButtonLabel, flexConfidenceText,
  resumeNote, flattenJobTree, descendantIds, fieldChildTitle, deleteConfirmMessage, samplingState,
  runConfigForJob, healthForDisplay,
} from './oxdna_jobs_panel.js'

describe('healthForDisplay (live mid-stage vs end-of-stage sample)', () => {
  const sample = { bp_retained_fraction: 0.9, potential_energy: -1.4, steps_per_s: 2000 }
  const live   = { bp_retained_fraction: 0.5, potential_energy: -0.8, steps_per_s: 1500 }

  it('uses the live snapshot from progress while the job is running', () => {
    const job = { status: 'running', health_samples: [sample] }
    expect(healthForDisplay(job, { live_health: live })).toBe(live)
  })
  it('falls back to the last persisted sample when not running', () => {
    const job = { status: 'completed', health_samples: [sample] }
    expect(healthForDisplay(job, { live_health: live })).toBe(sample)
  })
  it('falls back to the last sample when running but progress has no live_health', () => {
    const job = { status: 'running', health_samples: [sample] }
    expect(healthForDisplay(job, { live_health: null })).toBe(sample)
    expect(healthForDisplay(job, null)).toBe(sample)
  })
  it('returns null when there is nothing to show', () => {
    expect(healthForDisplay({ status: 'running', health_samples: [] }, null)).toBeNull()
  })
})

describe('runConfigForJob (echoes a run\'s conditions into the cards)', () => {
  it('extracts the relaxation advanced settings + surface + anchors', () => {
    const job = {
      backend: 'CPU', device: '1', salt_concentration: 0.6,
      run_config: {
        kind: 'relax', mc_steps: 500, md_relax_steps: 7000, equil_steps: 800,
        min_bp_retained: 0.4, surface: { dir: [0, 1, 0], offset_nm: 2, stiff: 5 },
        anchors: [{ kind: 'overhang', id: 'o1' }],
      },
    }
    const cfg = runConfigForJob(job)
    expect(cfg.advanced).toMatchObject({
      backend: 'CPU', device: '1', salt: 0.6,
      mcSteps: 500, mdSteps: 7000, equilSteps: 800, bpGate: 0.4,
    })
    expect(cfg.surface).toEqual({ dir: [0, 1, 0], offset_nm: 2, stiff: 5 })
    expect(cfg.anchors).toEqual([{ kind: 'overhang', id: 'o1' }])
    expect(cfg.field).toBeNull()
  })

  it('a field child has no advanced block and carries field + anchors', () => {
    const job = {
      parent_job_id: 'p1',
      run_config: { kind: 'field', steps: 2000, field: { field_pN: 3, dir: [1, 0, 0] },
                    anchors: [{ kind: 'domain', strandId: 's1', domainIndex: 2 }] },
    }
    const cfg = runConfigForJob(job)
    expect(cfg.advanced).toBeNull()
    expect(cfg.field).toEqual({ field_pN: 3, dir: [1, 0, 0] })
    expect(cfg.anchors).toEqual([{ kind: 'domain', strandId: 's1', domainIndex: 2 }])
    expect(cfg.prodSteps).toBe(2000)
  })

  it('falls back to stages + efield for jobs saved before run_config existed', () => {
    const job = {
      parent_job_id: 'p1', efield: { force_pN: 4, dir: [0, 0, 1] },
      stages: [{ kind: 'field', steps: 5000 }],
    }
    const cfg = runConfigForJob(job)
    expect(cfg.field).toEqual({ field_pN: 4, dir: [0, 0, 1] })
  })

  it('falls back to stage steps for an old relaxation job', () => {
    const job = {
      backend: 'CUDA',
      stages: [{ kind: 'mc', steps: 1000 }, { kind: 'md_relax', steps: 50000 },
               { kind: 'equil', steps: 2000 }],
    }
    const cfg = runConfigForJob(job)
    expect(cfg.advanced.mcSteps).toBe(1000)
    expect(cfg.advanced.mdSteps).toBe(50000)
    expect(cfg.advanced.equilSteps).toBe(2000)
  })
})

describe('samplingState (flex-map gating: production OR field)', () => {
  it('treats a field run as a sampling run', () => {
    expect(samplingState({ stages: [{ kind: 'field', status: 'done' }] })).toBe('done')
    expect(samplingState({ stages: [{ kind: 'field', status: 'running' }] })).toBe('running')
  })
  it('still covers production and ignores relaxation stages', () => {
    expect(samplingState({ stages: [{ kind: 'production', status: 'done' }] })).toBe('done')
    expect(samplingState({ stages: [{ kind: 'equil', status: 'done' }] })).toBe('none')
    expect(samplingState({ stages: [] })).toBe('none')
  })
})

describe('deleteConfirmMessage', () => {
  it('warns about cascade when a relaxed parent has field children', () => {
    const m = deleteConfirmMessage({ job_id: 'P' }, 3)
    expect(m.message).toMatch(/3 electric-field runs/)
    expect(m.message).toMatch(/all 3 field runs/)
    expect(m.confirmLabel).toBe('Delete all (4)')
  })
  it('singular wording for one child', () => {
    expect(deleteConfirmMessage({ job_id: 'P' }, 1).message).toMatch(/1 electric-field run\b/)
  })
  it('plain warning for a field child or a childless job', () => {
    expect(deleteConfirmMessage({ parent_job_id: 'P' }, 0).title).toBe('Delete field run')
    expect(deleteConfirmMessage({ job_id: 'P' }, 0).title).toBe('Delete oxDNA job')
  })
})

describe('flattenJobTree', () => {
  it('nests field children under their parent, numbered by run order, roots newest first', () => {
    const jobs = [
      { job_id: 'P', created_at: 100 },
      { job_id: 'F2', parent_job_id: 'P', created_at: 220 },
      { job_id: 'F1', parent_job_id: 'P', created_at: 210 },
      { job_id: 'Q', created_at: 50 },
    ]
    const rows = flattenJobTree(jobs)
    // P (newest root) + its children by created_at, then Q.
    expect(rows.map(r => r.job.job_id)).toEqual(['P', 'F1', 'F2', 'Q'])
    expect(rows.map(r => r.depth)).toEqual([0, 1, 1, 0])
    expect(rows.map(r => r.index)).toEqual([0, 1, 2, 0])   // global run numbers
  })
  it('pre-order flattens a chained lineage with increasing depth', () => {
    const jobs = [
      { job_id: 'R', created_at: 100 },
      { job_id: 'A', parent_job_id: 'R', created_at: 110 },
      { job_id: 'B', parent_job_id: 'A', created_at: 120 },   // grandchild
    ]
    const rows = flattenJobTree(jobs)
    expect(rows.map(r => r.job.job_id)).toEqual(['R', 'A', 'B'])
    expect(rows.map(r => r.depth)).toEqual([0, 1, 2])
    expect(rows.map(r => r.index)).toEqual([0, 1, 2])
  })
  it('an orphan child (parent absent) is treated as its own root', () => {
    const rows = flattenJobTree([{ job_id: 'F', parent_job_id: 'gone', created_at: 1 }])
    expect(rows.map(r => r.job.job_id)).toEqual(['F'])
    expect(rows[0].depth).toBe(0)
  })
})

describe('descendantIds', () => {
  it('collects the full subtree (children + grandchildren)', () => {
    const jobs = [
      { job_id: 'R' },
      { job_id: 'A', parent_job_id: 'R' },
      { job_id: 'B', parent_job_id: 'A' },
      { job_id: 'C', parent_job_id: 'R' },
      { job_id: 'X' },   // unrelated
    ]
    expect([...descendantIds(jobs, 'R')].sort()).toEqual(['A', 'B', 'C'])
    expect([...descendantIds(jobs, 'A')]).toEqual(['B'])
    expect([...descendantIds(jobs, 'X')]).toEqual([])
  })
})

describe('deleteConfirmMessage (chained child)', () => {
  it('warns about cascade when a field child has its own branches', () => {
    const m = deleteConfirmMessage({ job_id: 'F', parent_job_id: 'P' }, 2)
    expect(m.title).toBe('Delete field run + branches')
    expect(m.confirmLabel).toBe('Delete all (3)')
    expect(m.message).toMatch(/2 electric-field runs/)
  })
})

describe('fieldChildTitle', () => {
  it('summarizes the field params for the hover tooltip', () => {
    const t = fieldChildTitle({ efield: { force_pN: 2.5, dir: [0, 0, 1], n_anchored: 12 } })
    expect(t).toBe('E-field 2.5 pN/nt · dir (0.00, 0.00, 1.00) · 12 anchored')
  })
})

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

describe('resume button label (incomplete-job detection)', () => {
  it('queued job reads Start; stopped/failed read Resume', () => {
    expect(isResumable({ status: 'queued' })).toBe(false)
    expect(isResumable({ status: 'stopped' })).toBe(true)
    expect(isResumable({ status: 'failed' })).toBe(true)
    expect(startButtonLabel({ status: 'queued' })).toContain('Start')
    expect(startButtonLabel({ status: 'stopped' })).toContain('Resume')
    expect(startButtonLabel({ status: 'failed' })).toContain('Resume')
  })

  it('resumeNote flags a running stage resumed from its checkpoint', () => {
    const resumed = { status: 'running', current_stage_idx: 1, stages: [{ resumed: false }, { resumed: true }] }
    const fresh = { status: 'running', current_stage_idx: 1, stages: [{ resumed: false }, { resumed: false }] }
    expect(resumeNote(resumed).toLowerCase()).toContain('resuming from checkpoint')
    expect(resumeNote(fresh)).toBe('')
    expect(resumeNote({ status: 'completed', current_stage_idx: 1, stages: [{ resumed: true }] })).toBe('')
  })
})

describe('flexConfidenceText', () => {
  it('shows frames pooled + statistical error and flags preliminary', () => {
    const trusted = flexConfidenceText({ confidence: { n_frames: 200, rel_error: 0.05, preliminary: false } })
    expect(trusted.text).toContain('200 frames pooled')
    expect(trusted.text).toContain('±5%')
    expect(trusted.preliminary).toBe(false)

    const short = flexConfidenceText({ confidence: { n_frames: 6, rel_error: 0.29, preliminary: true }, running: false })
    expect(short.preliminary).toBe(true)
    expect(short.text.toLowerCase()).toContain('preliminary')
    expect(short.text.toLowerCase()).toContain('short run')
  })
  it('mid-run preliminary mentions production still running', () => {
    const r = flexConfidenceText({ confidence: { n_frames: 8, rel_error: 0.25, preliminary: true }, running: true })
    expect(r.text.toLowerCase()).toContain('still running')
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

describe('multi-production helpers', () => {
  const stages = (...prods) => [
    { kind: 'mc', status: 'done' }, { kind: 'equil', status: 'done' },
    ...prods.map(st => ({ kind: 'production', status: st })),
  ]
  it('productionState reflects the LATEST production run', () => {
    expect(productionState({ status: 'running', stages: stages('done', 'running') })).toBe('running')
    expect(productionState({ status: 'completed', stages: stages('done', 'done') })).toBe('done')
  })
  it('productionRunCount counts production stages', () => {
    expect(productionRunCount({ stages: stages() })).toBe(0)
    expect(productionRunCount({ stages: stages('done', 'done', 'running') })).toBe(3)
  })
  it('hasTrajectory is true once any stage has started/finished', () => {
    expect(hasTrajectory({ stages: [{ kind: 'mc', status: 'pending' }] })).toBe(false)
    expect(hasTrajectory({ stages: [{ kind: 'mc', status: 'running' }] })).toBe(true)
    expect(hasTrajectory({ stages: [{ kind: 'mc', status: 'done' }] })).toBe(true)
  })
})

describe('activity-state helpers (spinner drivers)', () => {
  const prod = (status) => ({ status: 'running', stages: [{ kind: 'equil', status: 'done' }, { kind: 'production', status }] })

  it('jobIsActive is true for queued/preparing/running only', () => {
    for (const s of ['queued', 'preparing', 'running']) expect(jobIsActive({ status: s })).toBe(true)
    for (const s of ['completed', 'failed', 'stopped']) expect(jobIsActive({ status: s })).toBe(false)
    expect(jobIsActive(null)).toBe(false)
  })

  it('isRelaxRunning: running on a relaxation stage, but NOT during production', () => {
    expect(isRelaxRunning({ status: 'running', stages: [{ kind: 'md_relax', status: 'running' }] })).toBe(true)
    expect(isRelaxRunning(prod('running'))).toBe(false)   // production running ≠ relax
    expect(isRelaxRunning({ status: 'completed' })).toBe(false)
    expect(isRelaxRunning(null)).toBe(false)
  })

  it('isProductionRunning: only while the production stage is active', () => {
    expect(isProductionRunning(prod('running'))).toBe(true)
    expect(isProductionRunning({ ...prod('done'), status: 'completed' })).toBe(false)
    expect(isProductionRunning({ status: 'running', stages: [{ kind: 'mc', status: 'running' }] })).toBe(false)
    expect(isProductionRunning(null)).toBe(false)
  })
})

describe('makeSpinner', () => {
  it('builds a .nadoc-spinner span with the requested colour + size', () => {
    const s = makeSpinner('#e0a800', 10)
    expect(s.className).toBe('nadoc-spinner')
    expect(s.style.color).toBe('rgb(224, 168, 0)')
    expect(s.style.width).toBe('10px')
    expect(s.getAttribute('aria-hidden')).toBe('true')
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
    'oxdna-jobs-traj-toggle': 'input', 'oxdna-jobs-traj-status': 'div',
    'oxdna-jobs-traj-controls': 'div', 'oxdna-jobs-traj-play': 'button',
    'oxdna-jobs-traj-slider': 'input', 'oxdna-jobs-traj-markers': 'div', 'oxdna-jobs-traj-label': 'div',
    // workspace colour-scale widget (middle-right)
    'flex-scale': 'div', 'flex-scale-max': 'input', 'flex-scale-min': 'input', 'flex-scale-reset': 'button',
  }
  const fakeDisplay = () => {
    let mode = null
    return {
      displayJob: vi.fn(async () => { mode = 'relaxed'; return { ok: true, n: 5, stage: 's' } }),
      displayRmsf: vi.fn(async () => {
        mode = 'rmsf'
        return { ok: true, n: 5, min: 0.1, max: 1.4, mean: 0.7, nFrames: 120,
                 confidence: { n_frames: 120, rel_error: 0.064, preliminary: false }, running: false }
      }),
      loadTrajectory: vi.fn(async () => {
        mode = 'trajectory'
        return { ok: true, n_frames: 6, markers: [{ frame: 3, kind: 'production' }],
                 stages: [{ kind: 'equil' }, { kind: 'production' }] }
      }),
      showFrame: vi.fn(),
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
    expect($('oxdna-jobs-flex-toggle').disabled).toBe(true)   // no production/field run yet
    expect($('oxdna-jobs-flex-status').textContent.toLowerCase()).toContain('waiting for a production or field run')
  })

  it('selecting a job dispatches nadoc:oxdna-job-selected (so the E-field Run button reacts)', async () => {
    api.listOxdnaJobs.mockResolvedValue([{ job_id: 'jSel', design_source_path: 'A.nadoc', status: 'completed',
      created_at: 1, current_stage_idx: 3, stages: relaxStages() }])
    const panel = initOxdnaJobsPanel({ getWorkspacePath: () => 'A.nadoc' })
    const spy = vi.fn()
    window.addEventListener('nadoc:oxdna-job-selected', spy)
    await selectFirstJob(panel)
    expect(spy).toHaveBeenCalled()
    window.removeEventListener('nadoc:oxdna-job-selected', spy)
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

  // ── Activity spinners (reload-safe: driven by live job state, no selection) ──
  it('a running relaxation spins the list row + Relax button (no selection needed)', async () => {
    api.listOxdnaJobs.mockResolvedValue([{ job_id: 'jRlx', design_source_path: 'A.nadoc', status: 'running',
      created_at: 1, current_stage_idx: 1, stages: [{ kind: 'mc', status: 'done' }, { kind: 'md_relax', status: 'running' }] }])
    const panel = initOxdnaJobsPanel({ getWorkspacePath: () => 'A.nadoc' })
    await panel.refresh()
    await Promise.resolve(); await Promise.resolve()
    expect($('oxdna-jobs-list').querySelector('.nadoc-spinner')).toBeTruthy()
    expect($('oxdna-jobs-run-btn').querySelector('.nadoc-spinner')).toBeTruthy()
    expect($('oxdna-jobs-prod-btn').querySelector('.nadoc-spinner')).toBeFalsy()
  })

  it('a running production spins the list row + Production button, not Relax', async () => {
    api.listOxdnaJobs.mockResolvedValue([{ job_id: 'jPrd', design_source_path: 'A.nadoc', status: 'running',
      created_at: 1, current_stage_idx: 3, stages: relaxStages({ kind: 'production', status: 'running', steps: 5000000 }) }])
    const panel = initOxdnaJobsPanel({ getWorkspacePath: () => 'A.nadoc' })
    await panel.refresh()
    await Promise.resolve(); await Promise.resolve()
    expect($('oxdna-jobs-prod-btn').querySelector('.nadoc-spinner')).toBeTruthy()
    expect($('oxdna-jobs-list').querySelector('.nadoc-spinner')).toBeTruthy()
    expect($('oxdna-jobs-run-btn').querySelector('.nadoc-spinner')).toBeFalsy()
  })

  it('a completed job shows no spinners (static status dot, idle buttons)', async () => {
    api.listOxdnaJobs.mockResolvedValue([{ job_id: 'jFin', design_source_path: 'A.nadoc', status: 'completed',
      created_at: 1, current_stage_idx: 3, stages: relaxStages() }])
    const panel = initOxdnaJobsPanel({ getWorkspacePath: () => 'A.nadoc' })
    await panel.refresh()
    await Promise.resolve(); await Promise.resolve()
    expect($('oxdna-jobs-list').querySelector('.nadoc-spinner')).toBeFalsy()
    expect($('oxdna-jobs-run-btn').querySelector('.nadoc-spinner')).toBeFalsy()
    expect($('oxdna-jobs-prod-btn').querySelector('.nadoc-spinner')).toBeFalsy()
    expect($('oxdna-jobs-run-btn').textContent.trim()).toBe('▶ Relax')
  })

  // ── Continue production + View trajectory ─────────────────────────────────
  it('a completed job WITH a production run keeps Production enabled to continue', async () => {
    api.listOxdnaJobs.mockResolvedValue([{ job_id: 'jc', design_source_path: 'A.nadoc', status: 'completed',
      created_at: 1, current_stage_idx: 5, stages: relaxStages({ kind: 'production', status: 'done', steps: 5000000 }) }])
    const panel = initOxdnaJobsPanel({ getWorkspacePath: () => 'A.nadoc' })
    await selectFirstJob(panel)
    expect($('oxdna-jobs-prod-btn').disabled).toBe(false)                       // continue allowed
    expect($('oxdna-jobs-prod-status').textContent.toLowerCase()).toContain('continue')
  })

  it('View trajectory toggle loads frames and reveals the player controls', async () => {
    const disp = fakeDisplay()
    api.listOxdnaJobs.mockResolvedValue([{ job_id: 'jt', design_source_path: 'A.nadoc', status: 'completed',
      created_at: 1, current_stage_idx: 5, stages: relaxStages({ kind: 'production', status: 'done', steps: 5000000 }) }])
    const panel = initOxdnaJobsPanel({ getWorkspacePath: () => 'A.nadoc', oxdnaDisplay: disp })
    await selectFirstJob(panel)
    expect($('oxdna-jobs-traj-toggle').disabled).toBe(false)                    // has trajectory
    $('oxdna-jobs-traj-toggle').checked = true
    $('oxdna-jobs-traj-toggle').dispatchEvent(new Event('change'))
    await Promise.resolve(); await Promise.resolve(); await Promise.resolve()
    expect(disp.loadTrajectory).toHaveBeenCalledWith('jt')
    expect($('oxdna-jobs-traj-controls').style.display).not.toBe('none')
    expect($('oxdna-jobs-traj-slider').max).toBe('5')                           // 6 frames → max idx 5
  })

  it('enabling View trajectory turns off the OxDNA display (shared overlay)', async () => {
    const disp = fakeDisplay()
    api.listOxdnaJobs.mockResolvedValue([{ job_id: 'jx', design_source_path: 'A.nadoc', status: 'completed',
      created_at: 1, current_stage_idx: 5, stages: relaxStages({ kind: 'production', status: 'done', steps: 5000000 }) }])
    const panel = initOxdnaJobsPanel({ getWorkspacePath: () => 'A.nadoc', oxdnaDisplay: disp })
    await selectFirstJob(panel)
    $('oxdna-jobs-display-toggle').checked = true
    $('oxdna-jobs-display-toggle').dispatchEvent(new Event('change'))
    await Promise.resolve(); await Promise.resolve()
    $('oxdna-jobs-traj-toggle').checked = true
    $('oxdna-jobs-traj-toggle').dispatchEvent(new Event('change'))
    await Promise.resolve(); await Promise.resolve(); await Promise.resolve()
    expect($('oxdna-jobs-display-toggle').checked).toBe(false)
    expect(disp.mode()).toBe('trajectory')
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
    const status = $('oxdna-jobs-flex-status').textContent.toLowerCase()
    expect(status).toContain('120 frames pooled')   // confidence readout
    expect(status).not.toContain('preliminary')      // 120 frames → trustworthy
    // The workspace scale appears, seeded with the data min→max from displayRmsf.
    expect($('flex-scale').style.display).not.toBe('none')
    expect($('flex-scale-min').value).toBe('0.10')
    expect($('flex-scale-max').value).toBe('1.40')
  })

  it('a stopped (killed) job → Start button reads "Resume"', async () => {
    api.listOxdnaJobs.mockResolvedValue([{ job_id: 'jKilled', design_source_path: 'A.nadoc', status: 'stopped',
      created_at: 1, current_stage_idx: 1, stages: relaxStages({ kind: 'production', status: 'running', steps: 5000 }) }])
    const panel = initOxdnaJobsPanel({ getWorkspacePath: () => 'A.nadoc' })
    await selectFirstJob(panel)
    const start = $('oxdna-jobs-start-btn')
    expect(start.style.display).not.toBe('none')
    expect(start.textContent).toContain('Resume')
  })

  it('flexibility map unlocks mid-run + flags the map preliminary while production runs', async () => {
    const disp = fakeDisplay()
    disp.displayRmsf = vi.fn(async () => ({
      ok: true, n: 5, min: 0.2, max: 0.9, mean: 0.5, nFrames: 7,
      confidence: { n_frames: 7, rel_error: 0.27, preliminary: true }, running: true,
    }))
    api.listOxdnaJobs.mockResolvedValue([{ job_id: 'jMid', design_source_path: 'A.nadoc', status: 'running',
      created_at: 1, current_stage_idx: 3, stages: relaxStages({ kind: 'production', status: 'running', steps: 5000 }) }])
    const panel = initOxdnaJobsPanel({ getWorkspacePath: () => 'A.nadoc', oxdnaDisplay: disp })
    await selectFirstJob(panel)

    const flex = $('oxdna-jobs-flex-toggle')
    expect(flex.disabled).toBe(false)                 // unlocked while production runs
    flex.checked = true
    flex.dispatchEvent(new Event('change'))
    await Promise.resolve(); await Promise.resolve(); await Promise.resolve()

    expect(disp.displayRmsf).toHaveBeenCalledWith('jMid')
    const status = $('oxdna-jobs-flex-status').textContent.toLowerCase()
    expect(status).toContain('7 frames pooled')
    expect(status).toContain('preliminary')
    expect(status).toContain('still running')
  })

  it('a resumed running production labels the progress "Resuming from checkpoint"', async () => {
    api.getOxdnaProgress.mockResolvedValue({ overall: 0.02, stage_fraction: 0.02 })
    api.listOxdnaJobs.mockResolvedValue([{ job_id: 'jResumed', design_source_path: 'A.nadoc', status: 'running',
      created_at: 1, current_stage_idx: 3,
      stages: relaxStages({ kind: 'production', status: 'running', steps: 5000, resumed: true }) }])
    const panel = initOxdnaJobsPanel({ getWorkspacePath: () => 'A.nadoc' })
    await selectFirstJob(panel)
    expect($('oxdna-jobs-progress').textContent.toLowerCase()).toContain('resuming from checkpoint')
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
