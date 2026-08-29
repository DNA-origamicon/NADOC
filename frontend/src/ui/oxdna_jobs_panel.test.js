// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mountIds, clearDom } from '../test-helpers/factory_dom.js'
import { initFlexScale } from './flex_scale.js'

// Mock the API client so the panel fetches a controlled job set.
vi.mock('../api/client.js', () => ({
  oxdnaAvailable: vi.fn().mockResolvedValue({ available: false }),
  listOxdnaJobs: vi.fn(),
  startOxdnaJob: vi.fn().mockResolvedValue({ ok: true }),
  deleteOxdnaJob: vi.fn().mockResolvedValue({ ok: true, deleted: ['j1'] }),
  getOxdnaProgress: vi.fn().mockResolvedValue({ overall: 1, stage_fraction: 0 }),
  getOxdnaRmsd: vi.fn().mockResolvedValue({ ready: true, mean: 2.31, max: 2.53, n_frames: 10 }),
  getOxdnaRmsf: vi.fn().mockResolvedValue({ ready: true, n_frames: 10, positions: [], min_rmsf: 0.1, max_rmsf: 1.4, mean_rmsf: 0.7 }),
  getOxdnaTrajectory: vi.fn().mockResolvedValue({ ready: true, n_frames: 4, keys: [], frames: [[]], markers: [], stages: [] }),
  createMdJob: vi.fn().mockResolvedValue({ job_id: 'md1', status: 'queued' }),
  copyOxdnaJob: vi.fn().mockResolvedValue({
    job: { job_id: 'j-copy', status: 'queued' }, seed: 987654,
  }),
  updateOxdnaJobSettings: vi.fn().mockResolvedValue({ job_id: 'j1', status: 'queued' }),
  getOxdnaErrorLog: vi.fn().mockResolvedValue({
    error: 'Health gate failed after 2_md_relax: base-pair retention 24% below gate 50%',
    stage: '2_md_relax', log: 'INFO: END OF THE SIMULATION, everything went OK!',
    log_path: '/w/2_md_relax/oxdna.log',
    diagnostics: { requested_backend: 'CUDA', oxdna_bin: '/x/oxDNA', cuda_capable: true },
  }),
  // Graphs & Metrics card (initOxdnaMetricsCard) statically imports these — the mock
  // must expose them or vitest throws "No export defined" at panel init.
  startOxdnaMetrics: vi.fn().mockResolvedValue({ metrics_id: 'm1' }),
  getOxdnaMetricsRun: vi.fn().mockResolvedValue({ state: 'complete', metrics: {} }),
  // Shape comparison card (initShapeCompareCard) is wired from the panel with these.
  startShapeCompare: vi.fn().mockResolvedValue({ metrics_id: 's1' }),
  getShapeCompareRun: vi.fn().mockResolvedValue({ state: 'done', result: { ready: false } }),
  // Export-trajectory card (initOxdnaExportCard) is wired from the panel with these.
  getOxdnaTrajectoryMeta: vi.fn().mockResolvedValue({ ready: false, n_frames: 0, stages: [] }),
  exportOxdnaTrajectory: vi.fn().mockResolvedValue('design_frames0-0.pdb'),
  getOxdnaExportProgress: vi.fn().mockResolvedValue({ active: false }),
  lastErrorMessage: () => null,
}))

import * as api from '../api/client.js'

// Drain the microtask queue. The concurrent-job guard adds an async hop (it awaits
// the active-jobs query) before a launch proceeds, so launch-flow assertions flush
// generously rather than counting exact ticks.
const flush = async (n = 12) => { for (let i = 0; i < n; i++) await Promise.resolve() }

import {
  formatProgress, latestHealth, detailStatusText, stageChips, jobDisplayName,
  productionState, jobListStatus, formatEta, seedReady, initOxdnaJobsPanel,
  jobIsActive, isRelaxRunning, isProductionRunning, makeSpinner,
  productionRunCount, hasTrajectory, isResumable, startButtonLabel, flexConfidenceText,
  isProductionResumable, isRelaxResumable,
  resumeNote, flattenJobTree, descendantIds, fieldChildTitle, deleteConfirmMessage, samplingState,
  runConfigForJob, healthForDisplay, productionRunAnchors, runElements, runIndicatorTags, runRowLabel, runChildTitle,
  jobHasFailure, errorLogText, jobOutOfDate, jobSelectionSignature,
  trajectoryFrameEstimate, relaxIndexMap, relaxRowLabel,
  captureStrandRunPlan, renderLammpsDisplayProgress, oxdnaJobEditable,
} from './oxdna_jobs_panel.js'

describe('oxdnaJobEditable', () => {
  const queued = (over = {}) => ({
    status: 'queued', parent_job_id: null, run_config: { kind: 'relax' },
    stages: [{ status: 'pending' }], ...over,
  })

  it('allows local and unsubmitted remote relaxation jobs', () => {
    expect(oxdnaJobEditable(queued({ execution_target: 'local' }))).toBe(true)
    expect(oxdnaJobEditable(queued({ execution_target: 'alpine' }))).toBe(true)
    expect(oxdnaJobEditable(queued({ execution_target: 'runpod' }))).toBe(true)
  })

  it('allows an unstarted derived run and rejects submitted or started jobs', () => {
    expect(oxdnaJobEditable(queued({ parent_job_id: 'parent', run_config: { kind: 'run' } }))).toBe(true)
    expect(oxdnaJobEditable(queued({ slurm_job_id: '123' }))).toBe(false)
    expect(oxdnaJobEditable(queued({ runpod_pod_id: 'pod-1' }))).toBe(false)
    expect(oxdnaJobEditable(queued({ status: 'running' }))).toBe(false)
    expect(oxdnaJobEditable(queued({ stages: [{ status: 'running' }] }))).toBe(false)
  })
})

describe('relaxIndexMap / relaxRowLabel (root job naming)', () => {
  const j = (id, created_at, over = {}) =>
    ({ job_id: id, created_at, design_source_path: 'A.nadoc', ...over })

  it('numbers ROOTS by creation order, oldest first', () => {
    const m = relaxIndexMap([j('r2', 20), j('r1', 10), j('r3', 30)])
    expect([m.get('r1'), m.get('r2'), m.get('r3')]).toEqual([1, 2, 3])
  })
  it('skips child jobs — only relaxations get a number', () => {
    const m = relaxIndexMap([j('r1', 10), j('c1', 20, { parent_job_id: 'r1' }), j('r2', 30)])
    expect(m.get('c1')).toBeUndefined()
    expect(m.get('r2')).toBe(2)      // the child did not consume a relax number
  })
  it('numbers per design, so each design starts at relax 1', () => {
    const m = relaxIndexMap([
      j('a1', 10, { design_source_path: 'A.nadoc' }),
      j('b1', 20, { design_source_path: 'B.nadoc' }),
      j('a2', 30, { design_source_path: 'A.nadoc' }),
    ])
    expect([m.get('a1'), m.get('a2'), m.get('b1')]).toEqual([1, 2, 1])
  })
  it('treats an ORPHAN child (parent absent) as its own root', () => {
    const m = relaxIndexMap([j('c1', 10, { parent_job_id: 'gone' })])
    expect(m.get('c1')).toBe(1)
  })
  it('a new relaxation does NOT renumber the existing ones', () => {
    const before = relaxIndexMap([j('r1', 10), j('r2', 20)])
    const after = relaxIndexMap([j('r1', 10), j('r2', 20), j('r3', 30)])
    expect(after.get('r1')).toBe(before.get('r1'))
    expect(after.get('r2')).toBe(before.get('r2'))
  })
  it('labels a numbered root "relax N", and falls back to the design stem', () => {
    expect(relaxRowLabel(j('r1', 10), 2)).toBe('relax 2')
    expect(relaxRowLabel({ design_source_path: '/ws/6hb_v3.nadoc' }, undefined)).toBe('6hb_v3')
  })
  it('tolerates empty / null input', () => {
    expect(relaxIndexMap(null).size).toBe(0)
    expect(relaxIndexMap([]).size).toBe(0)
  })
})

describe('jobSelectionSignature (edge-triggered job-selected event)', () => {
  const job = (over = {}) => ({
    job_id: 'J1', status: 'running', stages: [{ status: 'running' }], ...over,
  })
  it('is stable across re-renders of an unchanged job', () => {
    expect(jobSelectionSignature(job())).toBe(jobSelectionSignature(job()))
  })
  it('changes when the job, its status, or a stage status changes', () => {
    const base = jobSelectionSignature(job())
    expect(jobSelectionSignature(job({ job_id: 'J2' }))).not.toBe(base)
    expect(jobSelectionSignature(job({ status: 'completed' }))).not.toBe(base)
    expect(jobSelectionSignature(job({ stages: [{ status: 'done' }] }))).not.toBe(base)
  })
  it('is empty for no job, so a deselect always re-announces', () => {
    expect(jobSelectionSignature(null)).toBe('')
  })
  it('tolerates a job with no stages array', () => {
    expect(jobSelectionSignature({ job_id: 'J1', status: 'queued' })).toBe('J1|queued|')
  })
})

describe('jobHasFailure', () => {
  it('true when the job status is failed', () => {
    expect(jobHasFailure({ status: 'failed', stages: [] })).toBe(true)
  })
  it('true when any stage failed even if job status is not failed', () => {
    expect(jobHasFailure({ status: 'stopped', stages: [{ status: 'done' }, { status: 'failed' }] })).toBe(true)
  })
  it('false for a healthy/running job and for null', () => {
    expect(jobHasFailure({ status: 'running', stages: [{ status: 'running' }] })).toBe(false)
    expect(jobHasFailure(null)).toBe(false)
  })
})

describe('errorLogText', () => {
  it('leads with a CUDA-vs-CPU-binary diagnosis when that is the mismatch', () => {
    const t = errorLogText({
      error: "oxDNA failed for 2_md_relax (rc=1).", stage: '2_md_relax',
      log: "ERROR: Backend 'CUDA' not supported",
      log_path: '/w/2_md_relax/oxdna.log',
      diagnostics: { requested_backend: 'CUDA', oxdna_bin: '/conda/oxDNA', cuda_capable: false },
    })
    expect(t).toMatch(/DIAGNOSIS/)
    expect(t).toMatch(/CPU-only/)
    expect(t).toMatch(/oxdna-doctor --fix/)
    expect(t).toMatch(/Backend 'CUDA' not supported/)   // raw log still included
    expect(t).toMatch(/2_md_relax/)
  })
  it('omits the CUDA diagnosis when the binary is CUDA-capable', () => {
    const t = errorLogText({
      error: 'something else', log: 'boom',
      diagnostics: { requested_backend: 'CUDA', oxdna_bin: '/o/oxDNA', cuda_capable: true },
    })
    expect(t).not.toMatch(/DIAGNOSIS/)
    expect(t).toMatch(/boom/)
  })
  it('handles a missing payload gracefully', () => {
    expect(errorLogText(null)).toMatch(/No error details/)
  })
})

describe('jobOutOfDate (design edited after relax)', () => {
  it('reflects the backend out_of_date flag', () => {
    expect(jobOutOfDate({ out_of_date: true })).toBe(true)
    expect(jobOutOfDate({ out_of_date: false })).toBe(false)
    expect(jobOutOfDate({})).toBe(false)
    expect(jobOutOfDate(null)).toBe(false)
  })
})

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

describe('runElements / runIndicatorTags / runRowLabel (run job-name indicators)', () => {
  const fieldJob = { parent_job_id: 'p', run_config: { kind: 'run', field: { field_pN: 3, dir: [1, 0, 0] }, anchors: [{ kind: 'overhang', id: 'o1' }] } }
  const surfaceOnly = { parent_job_id: 'p', run_config: { kind: 'run', surface: { dir: [0, 1, 0], offset_nm: 2, stiff: 5 } } }
  const anchorsOnly = { parent_job_id: 'p', run_config: { kind: 'run', anchors: [{ kind: 'cluster', id: 'c1' }] } }
  const deposition = { parent_job_id: 'p', run_config: { kind: 'surface_deposition', surface: { dir: [0, 1, 0], offset_nm: 2, stiff: 5 }, surface_anchors: [{ kind: 'base', helixId: 'h1', bp: 2, direction: 'FORWARD' }] } }
  const plain = { parent_job_id: 'p', run_config: { kind: 'run' } }

  it('detects which elements a run added', () => {
    expect(runElements(fieldJob)).toEqual({ anchors: true, surface: false, field: true, surfaceDeposition: false })
    expect(runElements(surfaceOnly)).toEqual({ anchors: false, surface: true, field: false, surfaceDeposition: false })
    expect(runElements(anchorsOnly)).toEqual({ anchors: true, surface: false, field: false, surfaceDeposition: false })
    expect(runElements(deposition)).toEqual({ anchors: true, surface: true, field: false, surfaceDeposition: true })
    expect(runElements(plain)).toEqual({ anchors: false, surface: false, field: false, surfaceDeposition: false })
  })

  it('falls back to efield.n_anchored for old field children without run_config anchors', () => {
    const old = { parent_job_id: 'p', efield: { force_pN: 4, dir: [0, 0, 1], n_anchored: 8 }, stages: [{ kind: 'field' }] }
    expect(runElements(old)).toEqual({ anchors: true, surface: false, field: true, surfaceDeposition: false })
  })

  it('orders indicator tags [A][H][E]', () => {
    const all = { parent_job_id: 'p', run_config: { kind: 'run', field: { field_pN: 3, dir: [1, 0, 0] }, surface: { dir: [0, 1, 0], offset_nm: 2, stiff: 5 }, anchors: [{ kind: 'overhang', id: 'o1' }] } }
    expect(runIndicatorTags(all)).toBe('[A][H][E]')
    expect(runIndicatorTags(surfaceOnly)).toBe('[H]')
    expect(runIndicatorTags(anchorsOnly)).toBe('[A]')
    expect(runIndicatorTags(fieldJob)).toBe('[A][E]')
    expect(runIndicatorTags(deposition)).toBe('[A][SD]')
    expect(runIndicatorTags(plain)).toBe('')
  })

  it('builds a "Run N" row label with indicators (no lightning bolt)', () => {
    expect(runRowLabel(fieldJob, 2)).toBe('Run 2 [A][E]')
    expect(runRowLabel(deposition, 2)).toBe('Run 2 [A][SD]')
    expect(runRowLabel(plain, 1)).toBe('Run 1')
    expect(runRowLabel(fieldJob, 3)).not.toContain('⚡')
  })

  it('hover title describes a field run via fieldChildTitle, else its elements', () => {
    const f = { parent_job_id: 'p', efield: { force_pN: 3, dir: [1, 0, 0], n_anchored: 5 }, run_config: { kind: 'run', field: { field_pN: 3, dir: [1, 0, 0] }, anchors: [{ kind: 'overhang' }] } }
    expect(runChildTitle(f)).toMatch(/^E-field /)
    expect(runChildTitle(surfaceOnly)).toBe('Production run · hard surface')
    expect(runChildTitle(deposition)).toBe('Production run · surface deposition · 1 anchored')
    expect(runChildTitle(anchorsOnly)).toBe('Production run · 1 anchored')
    expect(runChildTitle(plain)).toBe('Production run')
  })
})

describe('productionRunAnchors', () => {
  const ordinary = { kind: 'base', helixId: 'h1', bp: 4, direction: 'FORWARD' }
  const surface = { kind: 'base', helixId: 'h2', bp: 8, direction: 'REVERSE' }

  it('carries surface-deposition anchors into a Full Sim continuation', () => {
    expect(productionRunAnchors({ anchors: [], surfaceAnchors: [surface] })).toEqual([surface])
  })

  it('combines both anchor cards without applying duplicate traps', () => {
    expect(productionRunAnchors({
      anchors: [ordinary, surface], surfaceAnchors: [surface],
    })).toEqual([ordinary, surface])
  })
})

describe('trajectoryFrameEstimate', () => {
  it('divides steps by steps-per-frame (floor), like oxDNA print_conf_interval', () => {
    expect(trajectoryFrameEstimate(5_000_000, 10_000, 0).frames).toBe(500)
    expect(trajectoryFrameEstimate(1_000_000, 100_000, 0).frames).toBe(10)
    // Partial trailing interval writes no frame.
    expect(trajectoryFrameEstimate(15_000, 10_000, 0).frames).toBe(1)
  })
  it('sizes the trajectory at ~130 B/nt/frame + an 80 B header', () => {
    // Matches disk_guard.oxdna_run_output_bytes' per-frame term exactly (pre-safety).
    const { frames, bytes } = trajectoryFrameEstimate(100_000, 10_000, 1000)
    expect(frames).toBe(10)
    expect(bytes).toBe(10 * (1000 * 130 + 80))
  })
  it('reports frames but zero bytes when the nucleotide count is unknown', () => {
    expect(trajectoryFrameEstimate(100_000, 10_000, undefined)).toEqual({ frames: 10, bytes: 0 })
    expect(trajectoryFrameEstimate(100_000, 10_000, 0).bytes).toBe(0)
  })
  it('returns nothing for invalid input rather than NaN/Infinity', () => {
    expect(trajectoryFrameEstimate(0, 10_000, 100)).toEqual({ frames: 0, bytes: 0 })
    expect(trajectoryFrameEstimate(1000, 0, 100)).toEqual({ frames: 0, bytes: 0 })
    expect(trajectoryFrameEstimate(NaN, 10_000, 100)).toEqual({ frames: 0, bytes: 0 })
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
  // Rows are named "relax N", not by design, so identity comes off the row's job id.
  const listedIds = () => [...document.getElementById('oxdna-jobs-list')
    .querySelectorAll('[data-job-id]')].map(r => r.dataset.jobId)

  it('shows only the current design’s jobs, not other designs’', async () => {
    const panel = initOxdnaJobsPanel({ getWorkspacePath: () => currentPath })
    await panel.refresh()
    expect(listedIds()).toEqual(['a1'])            // other design's job filtered out
  })

  it('re-filters when the open design changes (workspace-path-change)', async () => {
    const panel = initOxdnaJobsPanel({ getWorkspacePath: () => currentPath })
    await panel.refresh()
    currentPath = 'BetaJob.nadoc'
    window.dispatchEvent(new CustomEvent('nadoc:workspace-path-change', { detail: { path: 'BetaJob.nadoc' } }))
    await flush()   // the always-open panel now re-fetches (async) on a design switch
    expect(listedIds()).toEqual(['b1'])
  })

  it('shows a "no jobs yet" note for a new design with no matching jobs', async () => {
    const panel = initOxdnaJobsPanel({ getWorkspacePath: () => currentPath })
    await panel.refresh()
    currentPath = 'new_design.nadoc'                 // a fresh design, no jobs
    window.dispatchEvent(new CustomEvent('nadoc:workspace-path-change', { detail: { path: 'new_design.nadoc' } }))
    await flush()   // the always-open panel now re-fetches (async) on a design switch
    expect(listText().toLowerCase()).toContain('no oxdna jobs')
  })

  it('shows the note when there is no open file path (brand-new unsaved design)', async () => {
    currentPath = null
    const panel = initOxdnaJobsPanel({ getWorkspacePath: () => currentPath })
    await panel.refresh()
    expect(listText().toLowerCase()).toContain('no oxdna jobs')   // never leaks other designs' jobs
  })

  it('fires nadoc:sim-jobs-changed when the job set changes, so the master list wakes', async () => {
    const panel = initOxdnaJobsPanel({ getWorkspacePath: () => currentPath })
    let fired = 0
    const onChange = () => { fired++ }
    window.addEventListener('nadoc:sim-jobs-changed', onChange)
    try {
      await panel.refresh()          // baseline fetch (2 completed jobs)
      fired = 0
      // A production run now exists in the backend list for this design.
      api.listOxdnaJobs.mockResolvedValue([
        { job_id: 'a1', design_name: 'A', design_source_path: 'AlphaJob.nadoc', status: 'completed', created_at: 2, stages: [] },
        { job_id: 'a2', design_name: 'A', design_source_path: 'AlphaJob.nadoc', status: 'running', created_at: 3, stages: [], parent_job_id: 'a1' },
      ])
      await panel.refresh()
      expect(fired).toBeGreaterThanOrEqual(1)   // the master gets woken on the new running job
    } finally {
      window.removeEventListener('nadoc:sim-jobs-changed', onChange)
    }
  })
})

describe('initOxdnaJobsPanel — production buttons + flexibility map', () => {
  const SPEC = {
    'oxdna-jobs-panel': 'div', 'oxdna-jobs-heading': 'div', 'oxdna-jobs-arrow': 'div',
    'oxdna-jobs-body': 'div', 'oxdna-jobs-status': 'div', 'oxdna-jobs-prod-status': 'div',
    'oxdna-jobs-list': 'div', 'oxdna-jobs-detail': 'div', 'oxdna-jobs-detail-status': 'div',
    'oxdna-jobs-detail-error': 'div', 'oxdna-jobs-errorlog-btn': 'button',
    'oxdna-jobs-progress': 'div', 'oxdna-jobs-timeline': 'div',
    'oxdna-jobs-health': 'div', 'oxdna-jobs-show-all': 'input',
    'oxdna-jobs-run-btn': 'button', 'oxdna-jobs-prod-btn': 'button', 'oxdna-jobs-prod-steps': 'input',
    'oxdna-jobs-prod-steps-per-frame': 'input', 'oxdna-jobs-prod-frames-hint': 'div',
    'oxdna-jobs-stop-btn': 'button',   // production-phase Stop (Archive/Delete consolidated into the master card)
    'oxdna-jobs-display-toggle': 'input', 'oxdna-jobs-align-toggle': 'input',
    'oxdna-jobs-display-status': 'div',
    'oxdna-jobs-flex-toggle': 'input', 'oxdna-jobs-flex-status': 'div',
    'oxdna-jobs-flex-bar': 'div', 'oxdna-jobs-flex-legend': 'div',
    'oxdna-jobs-export-btn': 'button',
    'oxdna-jobs-seed-btn': 'button', 'oxdna-jobs-seed-status': 'div',
    'oxdna-jobs-traj-toggle': 'input', 'oxdna-jobs-traj-full-toggle': 'input',
    'oxdna-jobs-traj-status': 'div', 'oxdna-jobs-traj-load-progress': 'div',
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
  const fakeLammpsDisplay = () => ({
    displayJob: vi.fn(async () => ({ ok: true, n: 7 })),
    displayRmsf: vi.fn(async () => ({ ok: true, min: 0.1, max: 1, mean: 0.5, nFrames: 100 })),
    displayDeviation: vi.fn(async () => ({ ok: true, min: 0, max: 2, mean: 1, nFrames: 100 })),
    loadTrajectory: vi.fn(async () => ({ ok: true, n_frames: 5, markers: [] })),
    recolorRmsf: vi.fn(), recolorDeviation: vi.fn(), showFrame: vi.fn(), stopAndRestore: vi.fn(),
    mode: () => null, isActive: () => false,
  })
  const $ = (id) => document.getElementById(id)
  const relaxStages = (...extra) => [
    { kind: 'mc', status: 'done' }, { kind: 'md_relax', status: 'done' }, { kind: 'equil', status: 'done' }, ...extra,
  ]

  beforeEach(() => {
    clearDom(); mountIds(SPEC)
    $('oxdna-jobs-align-toggle').checked = true
    api.oxdnaAvailable.mockResolvedValue({ available: true, oxdna_bin: 'x' })
  })
  afterEach(() => clearDom())

  async function selectFirstJob(panel) {
    await panel.refresh()
    $('oxdna-jobs-list').querySelector('div')?.click()
    await Promise.resolve(); await Promise.resolve(); await Promise.resolve()
  }

  it('clicking "View error log" on a failed job opens the modal (regression: modal.open was missing)', async () => {
    api.listOxdnaJobs.mockResolvedValue([{ job_id: 'j1', design_source_path: 'A.nadoc', status: 'failed',
      created_at: 1, current_stage_idx: 1,
      error: 'Health gate failed after 2_md_relax: base-pair retention 24% below gate 50%',
      stages: [{ kind: 'mc', status: 'done' }, { kind: 'md_relax', status: 'failed' }, { kind: 'equil', status: 'pending' }] }])
    const panel = initOxdnaJobsPanel({ getWorkspacePath: () => 'A.nadoc' })
    await selectFirstJob(panel)
    const btn = $('oxdna-jobs-errorlog-btn')
    expect(btn.style.display).not.toBe('none')          // button visible for a failed job
    expect(document.querySelector('.modal__overlay')).toBeNull()   // nothing open yet
    btn.click()
    await flush()
    expect(document.querySelector('.modal__overlay')).toBeTruthy()  // modal actually opened
    expect(document.querySelector('.modal__overlay').textContent).toContain('everything went OK')
  })

  it('deleteSelected() opens the confirm modal and calls deleteOxdnaJob (Archive/Delete are consolidated into the master card, which dispatches here; regression: descendantIds was re-exported but not imported → the call threw ReferenceError so delete silently did nothing)', async () => {
    api.listOxdnaJobs.mockResolvedValue([{ job_id: 'j1', design_source_path: 'A.nadoc', status: 'completed',
      created_at: 1, current_stage_idx: 3, stages: relaxStages() }])
    api.deleteOxdnaJob.mockClear()
    const panel = initOxdnaJobsPanel({ getWorkspacePath: () => 'A.nadoc' })
    await selectFirstJob(panel)
    const delPromise = panel.deleteSelected()             // must NOT throw ReferenceError
    await flush()
    // The handler ran past descendantIds() → the confirm modal actually opened.
    const overlay = document.querySelector('.modal__overlay')
    expect(overlay).toBeTruthy()
    const confirmBtn = [...overlay.querySelectorAll('button')].find(b => /^Delete/.test(b.textContent.trim()))
    confirmBtn.click()
    await delPromise
    await flush()
    expect(api.deleteOxdnaJob).toHaveBeenCalledWith('j1')
  })

  it('a completed relaxation → Production enabled, Flexibility map disabled (waiting for production)', async () => {
    api.listOxdnaJobs.mockResolvedValue([{ job_id: 'j1', design_source_path: 'A.nadoc', status: 'completed',
      created_at: 1, current_stage_idx: 3, stages: relaxStages() }])
    const panel = initOxdnaJobsPanel({ getWorkspacePath: () => 'A.nadoc' })
    await selectFirstJob(panel)
    expect($('oxdna-jobs-prod-btn').disabled).toBe(false)     // production ready
    expect($('oxdna-jobs-flex-toggle').disabled).toBe(true)   // no production/field run yet
    expect($('oxdna-jobs-flex-status').textContent.toLowerCase()).toContain('waiting for a production or field run')
  })

  it('locks the OxDNA display / flex / trajectory toggles while a live session runs', async () => {
    api.listOxdnaJobs.mockResolvedValue([{ job_id: 'j1', design_source_path: 'A.nadoc', status: 'completed',
      created_at: 1, current_stage_idx: 3, stages: relaxStages({ kind: 'production', status: 'done' }) }])
    let liveOn = false
    const oxdnaLive = { isOn: () => liveOn, stop: vi.fn() }
    const panel = initOxdnaJobsPanel({ getWorkspacePath: () => 'A.nadoc', oxdnaDisplay: fakeDisplay(), oxdnaLive })
    await selectFirstJob(panel)
    // A completed+produced job → all three overlays usable.
    expect($('oxdna-jobs-display-toggle').disabled).toBe(false)
    expect($('oxdna-jobs-flex-toggle').disabled).toBe(false)
    expect($('oxdna-jobs-traj-toggle').disabled).toBe(false)
    // Live starts → all three locked so a click can't fight the live overlay.
    liveOn = true
    window.dispatchEvent(new CustomEvent('nadoc:oxdna-live-start'))
    expect($('oxdna-jobs-display-toggle').disabled).toBe(true)
    expect($('oxdna-jobs-flex-toggle').disabled).toBe(true)
    expect($('oxdna-jobs-traj-toggle').disabled).toBe(true)
    // Live stops → normal gating restored.
    liveOn = false
    window.dispatchEvent(new CustomEvent('nadoc:oxdna-live-stop'))
    expect($('oxdna-jobs-display-toggle').disabled).toBe(false)
    expect($('oxdna-jobs-flex-toggle').disabled).toBe(false)
    expect($('oxdna-jobs-traj-toggle').disabled).toBe(false)
  })

  it('an active oxDNA display is torn down when leaving Dynamics for an EDITING tab', async () => {
    api.listOxdnaJobs.mockResolvedValue([{ job_id: 'j1', design_source_path: 'A.nadoc', status: 'completed',
      created_at: 1, current_stage_idx: 3, stages: relaxStages({ kind: 'production', status: 'done' }) }])
    const disp = fakeDisplay()
    const panel = initOxdnaJobsPanel({ getWorkspacePath: () => 'A.nadoc', oxdnaDisplay: disp })
    await selectFirstJob(panel)
    $('oxdna-jobs-display-toggle').checked = true
    $('oxdna-jobs-display-toggle').dispatchEvent(new Event('change'))
    await Promise.resolve(); await Promise.resolve()
    expect(disp.isActive()).toBe(true)
    window.dispatchEvent(new CustomEvent('nadoc:left-tab-change', { detail: { activeTab: 'design' } }))
    expect(disp.stopAndRestore).toHaveBeenCalled()
  })

  it('an active oxDNA display SURVIVES switching to the Photo tab (so it can be photographed)', async () => {
    api.listOxdnaJobs.mockResolvedValue([{ job_id: 'j1', design_source_path: 'A.nadoc', status: 'completed',
      created_at: 1, current_stage_idx: 3, stages: relaxStages({ kind: 'production', status: 'done' }) }])
    const disp = fakeDisplay()
    const panel = initOxdnaJobsPanel({ getWorkspacePath: () => 'A.nadoc', oxdnaDisplay: disp })
    await selectFirstJob(panel)
    $('oxdna-jobs-display-toggle').checked = true
    $('oxdna-jobs-display-toggle').dispatchEvent(new Event('change'))
    await Promise.resolve(); await Promise.resolve()
    expect(disp.isActive()).toBe(true)
    window.dispatchEvent(new CustomEvent('nadoc:left-tab-change', { detail: { activeTab: 'photo' } }))
    expect(disp.stopAndRestore).not.toHaveBeenCalled()
    expect(disp.isActive()).toBe(true)   // relaxed frame still on the shared bead overlay
  })

  it('switching flex map → OxDNA display clears the flex legend (radios pre-uncheck the flex toggle, so tear down by MODE not checkbox)', async () => {
    api.listOxdnaJobs.mockResolvedValue([{ job_id: 'j1', design_source_path: 'A.nadoc', status: 'completed',
      created_at: 1, current_stage_idx: 4, stages: relaxStages({ kind: 'production', status: 'done' }) }])
    const disp = fakeDisplay()
    const flexScale = { show: vi.fn(), hide: vi.fn() }
    const panel = initOxdnaJobsPanel({ getWorkspacePath: () => 'A.nadoc', oxdnaDisplay: disp, flexScale })
    await selectFirstJob(panel)
    // Turn on the flexibility map → legend shows, mode becomes 'rmsf'.
    $('oxdna-jobs-flex-toggle').checked = true
    $('oxdna-jobs-flex-toggle').dispatchEvent(new Event('change'))
    await flush()
    expect(disp.displayRmsf).toHaveBeenCalled()
    expect(flexScale.show).toHaveBeenCalled()
    expect(disp.mode()).toBe('rmsf')
    flexScale.hide.mockClear()
    // Switch to OxDNA display. A radio group auto-unchecks the flex toggle BEFORE this
    // handler runs — the old checkbox-gated cleanup would miss it and leave the legend up.
    $('oxdna-jobs-flex-toggle').checked = false            // the browser's radio uncheck
    $('oxdna-jobs-display-toggle').checked = true
    $('oxdna-jobs-display-toggle').dispatchEvent(new Event('change'))
    await flush()
    expect(disp.displayJob).toHaveBeenCalled()             // relaxed frame now shown
    expect(flexScale.hide).toHaveBeenCalled()              // legend cleared (the fix)
  })

  // ── Click-the-selected-row-to-deselect ──────────────────────────────────────
  // Deselecting is NOT a job switch: whatever was loaded for that job (here a scrubbable
  // trajectory) has to stay on screen and in the controller, so re-selecting costs nothing.
  // Only picking a DIFFERENT job unloads it (with the "Unload trajectory?" confirm).
  it('clicking the selected row deselects it WITHOUT unloading the loaded trajectory', async () => {
    api.listOxdnaJobs.mockResolvedValue([{ job_id: 'j1', design_source_path: 'A.nadoc', status: 'completed',
      created_at: 1, current_stage_idx: 4, stages: relaxStages({ kind: 'production', status: 'done' }) }])
    const disp = fakeDisplay()
    const panel = initOxdnaJobsPanel({ getWorkspacePath: () => 'A.nadoc', oxdnaDisplay: disp })
    await selectFirstJob(panel)
    expect(panel.getSelectedJob()?.job_id).toBe('j1')

    $('oxdna-jobs-traj-toggle').checked = true
    $('oxdna-jobs-traj-toggle').dispatchEvent(new Event('change'))
    await flush()
    expect(disp.mode()).toBe('trajectory')

    $('oxdna-jobs-list').querySelector('div').click()   // second click on the SAME row
    await flush()
    expect(panel.getSelectedJob()).toBe(null)                     // deselected
    expect($('oxdna-jobs-detail').style.display).toBe('none')     // detail cleared
    // …and nothing was thrown away:
    expect(disp.stopAndRestore).not.toHaveBeenCalled()
    expect(disp.mode()).toBe('trajectory')
    expect($('oxdna-jobs-traj-toggle').checked).toBe(true)
    expect($('oxdna-jobs-traj-controls').style.display).not.toBe('none')
  })

  it('re-clicking the row after a deselect selects it again (the cached trajectory is still there)', async () => {
    api.listOxdnaJobs.mockResolvedValue([{ job_id: 'j1', design_source_path: 'A.nadoc', status: 'completed',
      created_at: 1, current_stage_idx: 4, stages: relaxStages({ kind: 'production', status: 'done' }) }])
    const disp = fakeDisplay()
    const panel = initOxdnaJobsPanel({ getWorkspacePath: () => 'A.nadoc', oxdnaDisplay: disp })
    await selectFirstJob(panel)
    $('oxdna-jobs-traj-toggle').checked = true
    $('oxdna-jobs-traj-toggle').dispatchEvent(new Event('change'))
    await flush()
    const loads = disp.loadTrajectory.mock.calls.length

    $('oxdna-jobs-list').querySelector('div').click()   // deselect
    await flush()
    $('oxdna-jobs-list').querySelector('div').click()   // select again
    await flush()
    expect(panel.getSelectedJob()?.job_id).toBe('j1')
    expect($('oxdna-jobs-detail').style.display).not.toBe('none')
    expect(disp.loadTrajectory.mock.calls.length).toBe(loads)   // no reload — it never left
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

  // ── Activity spinners (reload-safe: driven by live job state) ──
  // The Run button is the context control (▶ Run ⇄ ■ Stop ⇄ ↻ Resume) tied to the
  // SELECTED job, so with nothing selected it reads "▶ Run" (disabled, no spinner); a running relax
  // still shows activity on its list row. SELECTING the running relax flips it to Stop.
  it('a running relaxation spins its list row; the Relax button reflects the selected job', async () => {
    api.listOxdnaJobs.mockResolvedValue([{ job_id: 'jRlx', design_source_path: 'A.nadoc', status: 'running',
      created_at: 1, current_stage_idx: 1, stages: [{ kind: 'mc', status: 'done' }, { kind: 'md_relax', status: 'running' }] }])
    const panel = initOxdnaJobsPanel({ getWorkspacePath: () => 'A.nadoc' })
    await panel.refresh()
    await Promise.resolve(); await Promise.resolve()
    expect($('oxdna-jobs-list').querySelector('.nadoc-spinner')).toBeTruthy()   // row shows activity
    expect($('oxdna-jobs-run-btn').textContent.trim()).toBe('▶ Run')
    expect($('oxdna-jobs-prod-btn').querySelector('.nadoc-spinner')).toBeFalsy()

    await selectFirstJob(panel)   // select the running relaxation → Run flips to Stop
    expect($('oxdna-jobs-run-btn').textContent).toContain('Stop Run')
    expect($('oxdna-jobs-run-btn').dataset.runAction).toBe('stop')
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
    expect($('oxdna-jobs-run-btn').textContent.trim()).toBe('▶ Run')
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
    expect(disp.loadTrajectory).toHaveBeenCalledWith(
      'jt', true, 'lineage', undefined, expect.any(Function),
    )                                                                          // sparse = whole lineage + progress
    expect($('oxdna-jobs-traj-controls').style.display).not.toBe('none')
    expect($('oxdna-jobs-traj-slider').max).toBe('5')                           // 6 frames → max idx 5
  })

  it('View FULL trajectory toggle loads this job only, unstrided', async () => {
    const disp = fakeDisplay()
    api.listOxdnaJobs.mockResolvedValue([{ job_id: 'jt', design_source_path: 'A.nadoc', status: 'completed',
      created_at: 1, current_stage_idx: 5, stages: relaxStages({ kind: 'production', status: 'done', steps: 5000000 }) }])
    const panel = initOxdnaJobsPanel({ getWorkspacePath: () => 'A.nadoc', oxdnaDisplay: disp })
    await selectFirstJob(panel)
    expect($('oxdna-jobs-traj-full-toggle').disabled).toBe(false)               // same gate as sparse
    $('oxdna-jobs-traj-full-toggle').checked = true
    $('oxdna-jobs-traj-full-toggle').dispatchEvent(new Event('change'))
    await Promise.resolve(); await Promise.resolve(); await Promise.resolve()
    // scope 'job' = drop the ancestors, keep every frame written (no stride).
    expect(disp.loadTrajectory).toHaveBeenCalledWith(
      'jt', true, 'job', undefined, expect.any(Function),
    )
    expect($('oxdna-jobs-traj-controls').style.display).not.toBe('none')
  })

  it('shows byte-level transfer progress while a full trajectory downloads', async () => {
    let finish
    const disp = fakeDisplay()
    disp.loadTrajectory = vi.fn(() => new Promise(resolve => { finish = resolve }))
    api.listOxdnaJobs.mockResolvedValue([{ job_id: 'jt', design_source_path: 'A.nadoc', status: 'completed',
      created_at: 1, current_stage_idx: 3, stages: relaxStages({ kind: 'production', status: 'done' }) }])
    const panel = initOxdnaJobsPanel({ getWorkspacePath: () => 'A.nadoc', oxdnaDisplay: disp })
    await selectFirstJob(panel)
    $('oxdna-jobs-traj-full-toggle').checked = true
    $('oxdna-jobs-traj-full-toggle').dispatchEvent(new Event('change'))
    await flush()

    window.dispatchEvent(new CustomEvent('nadoc:oxdna-trajectory-transfer', {
      detail: { jobId: 'jt', loaded: 300, total: 400 },
    }))
    expect($('oxdna-jobs-traj-status').textContent).toContain('75%')
    expect($('oxdna-jobs-traj-load-progress').textContent).toContain('Transferring and decoding… 75%')

    finish({ ok: true, n_frames: 1, markers: [], stages: [] })
    await flush()
  })

  it('a LAMMPS run shows in the SAME viz card — the radios drive the LAMMPS loader', async () => {
    const oxdnaDisplay = fakeDisplay()
    const lammps = fakeLammpsDisplay()
    const panel = initOxdnaJobsPanel({ getWorkspacePath: () => 'A.nadoc', oxdnaDisplay, lammpsDisplay: lammps })
    panel.selectLammpsJob({ engine: 'lammps', job_id: 'lm7', viewable: true })
    expect($('oxdna-jobs-display-toggle').disabled).toBe(false)          // enabled by viewability
    expect($('oxdna-jobs-detail').style.display).toBe('none')            // oxDNA stage detail hidden
    // Display radio → LAMMPS loader (not the oxDNA one)
    $('oxdna-jobs-display-toggle').checked = true
    $('oxdna-jobs-display-toggle').dispatchEvent(new Event('change'))
    await Promise.resolve(); await Promise.resolve()
    expect(lammps.displayJob).toHaveBeenCalledWith('lm7', expect.anything(), expect.any(Function))
    expect(oxdnaDisplay.displayJob).not.toHaveBeenCalled()
    // Trajectory radio → LAMMPS trajectory + reveals the shared player
    $('oxdna-jobs-traj-toggle').checked = true
    $('oxdna-jobs-traj-toggle').dispatchEvent(new Event('change'))
    await Promise.resolve(); await Promise.resolve(); await Promise.resolve()
    expect(lammps.loadTrajectory).toHaveBeenCalledWith('lm7', true, expect.any(Function))
    expect($('oxdna-jobs-traj-controls').style.display).not.toBe('none')
  })

  it('renders a labelled progress bar for every LAMMPS display subprocess', () => {
    const status = $('oxdna-jobs-display-status')
    renderLammpsDisplayProgress(status, new Map([
      ['final-frame', { done: 1, total: 1 }],
      ['transform', { done: 0, total: 1 }],
      ['apply', { done: 0, total: 1 }],
    ]))
    expect(status.querySelectorAll('[data-lammps-display-phase]')).toHaveLength(3)
    expect(status.textContent).toContain('Read and align final frame')
    expect(status.textContent).toContain('Transform final coordinates')
    expect(status.textContent).toContain('Apply final structure')
  })

  it('a LAMMPS run whose sim is unfinished (not viewable) leaves the viz radios disabled', () => {
    const panel = initOxdnaJobsPanel({ getWorkspacePath: () => 'A.nadoc', oxdnaDisplay: fakeDisplay(), lammpsDisplay: fakeLammpsDisplay() })
    panel.selectLammpsJob({ engine: 'lammps', job_id: 'lm8', viewable: false })
    expect($('oxdna-jobs-display-toggle').disabled).toBe(true)
    expect($('oxdna-jobs-traj-toggle').disabled).toBe(true)
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
    const panel = initOxdnaJobsPanel({ getWorkspacePath: () => 'A.nadoc', oxdnaDisplay: disp, flexScale: initFlexScale() })
    await selectFirstJob(panel)

    const flex = $('oxdna-jobs-flex-toggle')
    expect(flex.disabled).toBe(false)
    flex.checked = true
    flex.dispatchEvent(new Event('change'))
    await Promise.resolve(); await Promise.resolve(); await Promise.resolve()

    expect(disp.displayRmsf).toHaveBeenCalledWith('j3', { align: true })
    $('oxdna-jobs-align-toggle').checked = false
    $('oxdna-jobs-align-toggle').dispatchEvent(new Event('change'))
    await Promise.resolve(); await Promise.resolve(); await Promise.resolve()
    expect(disp.displayRmsf).toHaveBeenLastCalledWith('j3', { align: false })
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

  it('an interrupted relaxation is resumed from the Relax control', async () => {
    api.listOxdnaJobs.mockResolvedValue([{ job_id: 'jKilled', design_source_path: 'A.nadoc', status: 'stopped',
      created_at: 1, current_stage_idx: 1,
      stages: [{ kind: 'mc', status: 'done' }, { kind: 'md_relax', status: 'running' }, { kind: 'equil', status: 'pending' }] }])
    const panel = initOxdnaJobsPanel({ getWorkspacePath: () => 'A.nadoc' })
    await selectFirstJob(panel)
    const run = $('oxdna-jobs-run-btn')
    expect(run.textContent).toContain('Resume')
    expect(run.dataset.runAction).toBe('resume')
    expect($('oxdna-jobs-prod-btn').textContent).toBe('Full Sim')
  })

  it('a prepared job is selected first, then started from the Run control', async () => {
    const job = { job_id: 'jReady', design_source_path: 'A.nadoc', status: 'queued',
      created_at: 1, current_stage_idx: 0, backend: 'CPU', stages: relaxStages() }
    api.listOxdnaJobs.mockResolvedValue([job])
    api.startOxdnaJob.mockClear()
    const panel = initOxdnaJobsPanel({ getWorkspacePath: () => 'A.nadoc' })
    await selectFirstJob(panel)
    const run = $('oxdna-jobs-run-btn')
    expect(run.textContent).toContain('Run')
    expect(run.disabled).toBe(false)
    expect($('oxdna-jobs-list').querySelector('.nadoc-spinner')).toBeTruthy()
    run.click()
    await flush()
    expect(api.startOxdnaJob).toHaveBeenCalledWith('jReady')
  })

  it('an interrupted full run is resumed from Full Sim, not Relax', async () => {
    const job = { job_id: 'jRun2', design_source_path: 'voltronCoreArm.nadoc', status: 'stopped',
      created_at: 1, current_stage_idx: 3,
      stages: relaxStages({ kind: 'production', status: 'running', steps: 5000 }) }
    api.listOxdnaJobs.mockResolvedValue([job])
    const panel = initOxdnaJobsPanel({ getWorkspacePath: () => 'voltronCoreArm.nadoc' })
    await selectFirstJob(panel)

    expect($('oxdna-jobs-run-btn').textContent).toContain('Run')
    expect($('oxdna-jobs-run-btn').dataset.runAction).toBe('run')
    expect($('oxdna-jobs-prod-btn').textContent).toContain('Resume Run')
    expect(isProductionResumable(job)).toBe(true)
    expect(isRelaxResumable(job)).toBe(false)

    $('oxdna-jobs-prod-btn').click()
    await flush()
    expect(api.startOxdnaJob).toHaveBeenCalledWith('jRun2')
  })

  it('a completed full run stays production done and offers a new Full Sim', async () => {
    api.listOxdnaJobs.mockResolvedValue([{ job_id: 'jRun2', design_source_path: 'voltronCoreArm.nadoc',
      status: 'completed', created_at: 1, current_stage_idx: 4,
      stages: relaxStages({ kind: 'production', status: 'done', steps: 5000 }) }])
    const panel = initOxdnaJobsPanel({ getWorkspacePath: () => 'voltronCoreArm.nadoc' })
    await selectFirstJob(panel)

    const badge = $('oxdna-jobs-list').querySelector('[title="Production done"]')
    expect(badge?.textContent).toBe('■')
    expect(badge?.style.color).toBe('rgb(74, 158, 255)')
    expect($('oxdna-jobs-prod-btn').textContent).toBe('Full Sim')
    expect($('oxdna-jobs-prod-btn').disabled).toBe(false)
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

    expect(disp.displayRmsf).toHaveBeenCalledWith('jMid', { align: true })
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
    const panel = initOxdnaJobsPanel({ getWorkspacePath: () => 'A.nadoc', oxdnaDisplay: disp, flexScale: initFlexScale() })
    await selectFirstJob(panel)
    const flex = $('oxdna-jobs-flex-toggle')
    flex.checked = true; flex.dispatchEvent(new Event('change'))
    await Promise.resolve(); await Promise.resolve(); await Promise.resolve()

    $('flex-scale-max').value = '0.8'
    $('flex-scale-max').dispatchEvent(new Event('change'))
    expect(disp.recolorRmsf).toHaveBeenLastCalledWith(0.1, 0.8, 'viridis')
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
    await flush()

    expect(api.createMdJob).toHaveBeenCalledTimes(1)
    const body = api.createMdJob.mock.calls[0][0]
    expect(body.oxdna_job_id).toBe('jSeed')
    expect(body.design_source_path).toBe('A.nadoc')
    // Deferred-prep: the seed button creates a DRAFT (no solvation) that autostarts
    // when the user later presses "Relax from oxDNA".
    expect(body.draft).toBe(true)
    expect(body.autostart).toBe(true)
    expect($('oxdna-jobs-seed-status').textContent.toLowerCase()).toContain('draft')
  })

  it('on seed success → keeps the oxDNA panel OPEN (cards stay) + fires nadoc:md-job-created for the tab switch', async () => {
    // Regression: the old reveal collapsed THIS panel (hiding every oxDNA card) and
    // clicked a removed `md-jobs-panel-heading`. The panels are tab-fronted now — main.js
    // switches to the NAMD tab on the event; the panel must NOT collapse itself.
    api.createMdJob.mockResolvedValue({ job_id: 'md9', status: 'queued' })
    api.listOxdnaJobs.mockResolvedValue([{ job_id: 'jSeed2', design_source_path: 'A.nadoc', status: 'completed',
      created_at: 1, current_stage_idx: 3, stages: relaxStages() }])
    const panel = initOxdnaJobsPanel({ getWorkspacePath: () => 'A.nadoc' })
    await selectFirstJob(panel)

    let seeded = null
    window.addEventListener('nadoc:md-job-created', (e) => { seeded = e.detail?.jobId }, { once: true })

    expect($('oxdna-jobs-body').style.display).not.toBe('none')   // open before
    $('oxdna-jobs-seed-btn').click()
    await flush()

    expect($('oxdna-jobs-body').style.display).not.toBe('none')   // STILL open — cards preserved
    expect(seeded).toBe('md9')                                    // event drives the NAMD-tab switch
  })

  it('a still-running job → "Use as NAMD seed" stays disabled', async () => {
    api.listOxdnaJobs.mockResolvedValue([{ job_id: 'jRun', design_source_path: 'A.nadoc', status: 'running',
      created_at: 1, current_stage_idx: 1, stages: [{ kind: 'mc', status: 'done' }, { kind: 'md_relax', status: 'running' }] }])
    const panel = initOxdnaJobsPanel({ getWorkspacePath: () => 'A.nadoc' })
    await selectFirstJob(panel)
    expect($('oxdna-jobs-seed-btn').disabled).toBe(true)
  })
})

// PARITY oracle for the shared-scaffold convergence (U3 slice 2c-3a): the section
// collapse (arrow via the `is-collapsed` class idiom — NOT the advanced drawer,
// which stays bespoke because oxDNA's `_advOpen` boolean flips the first click
// opposite to the base's display-reading model) and the open+active poll gate must
// behave identically whether oxDNA drives its own bespoke `_collapsed`/
// `_scheduleNextPoll` or the shared `initJobsPanelBase`. Written & run GREEN against
// the bespoke code FIRST, then re-run post-rewire (adapted-code in-place-first pin).
// UNIFIED-PANEL UPDATE: the per-engine section no longer collapses — the *Simulate*
// header owns the one collapse and the engine header is a static label
// (`collapsible:false` on initJobsPanelBase). These pins now assert the panel is
// PERMANENTLY OPEN (heading click is a no-op) and polls whenever a job is active.
describe('initOxdnaJobsPanel — permanently-open section (no per-engine collapse) + poll', () => {
  const IDS = [
    'oxdna-jobs-panel', 'oxdna-jobs-heading', 'oxdna-jobs-arrow', 'oxdna-jobs-body',
    'oxdna-jobs-status', 'oxdna-jobs-run-btn', 'oxdna-jobs-prod-btn', 'oxdna-jobs-prod-status',
    'oxdna-jobs-list', 'oxdna-jobs-detail', 'oxdna-jobs-show-all',
  ]
  const $ = (id) => document.getElementById(id)
  const heading = () => $('oxdna-jobs-heading')

  beforeEach(() => {
    clearDom(); mountIds(IDS)
    localStorage.clear()
    api.oxdnaAvailable.mockResolvedValue({ available: true, oxdna_bin: 'x' })
    vi.clearAllMocks()
    api.oxdnaAvailable.mockResolvedValue({ available: true, oxdna_bin: 'x' })
  })
  afterEach(() => { clearDom(); vi.useRealTimers() })

  it('starts OPEN regardless of persisted state; the heading click does not collapse it', async () => {
    // Seed a stale "collapsed" preference — a non-collapsible section must ignore it.
    localStorage.setItem('nadoc.leftSidebar.sections.v1',
      JSON.stringify({ dynamics: { 'oxdna-jobs-panel': true } }))
    api.listOxdnaJobs.mockResolvedValue([])
    initOxdnaJobsPanel({ getWorkspacePath: () => 'A.nadoc' })
    await flush()
    expect($('oxdna-jobs-body').style.display).not.toBe('none')        // forced open

    heading().click(); await flush()                                   // no-op now
    expect($('oxdna-jobs-body').style.display).not.toBe('none')        // still open
  })

  it('polls listOxdnaJobs on the interval while a run is active (section is always open)', async () => {
    api.listOxdnaJobs.mockResolvedValue([{ job_id: 'r1', design_source_path: 'A.nadoc', status: 'running',
      created_at: 1, current_stage_idx: 1, stages: [{ kind: 'mc', status: 'done' }, { kind: 'md_relax', status: 'running' }] }])
    vi.useFakeTimers()
    initOxdnaJobsPanel({ getWorkspacePath: () => 'A.nadoc' })          // opens + fetches + schedules on init
    await vi.advanceTimersByTimeAsync(0)
    const n0 = api.listOxdnaJobs.mock.calls.length
    await vi.advanceTimersByTimeAsync(1500)                            // one poll tick
    const n1 = api.listOxdnaJobs.mock.calls.length
    expect(n1).toBeGreaterThan(n0)                                     // poll fired (open + active)

    heading().click()                                                  // no collapse → poll keeps running
    await vi.advanceTimersByTimeAsync(1500)
    expect(api.listOxdnaJobs.mock.calls.length).toBeGreaterThan(n1)
  })

  it('does not poll while open when no job is active (the shared open+active gate)', async () => {
    api.listOxdnaJobs.mockResolvedValue([{ job_id: 'c1', design_source_path: 'A.nadoc', status: 'completed',
      created_at: 1, current_stage_idx: 3, stages: [{ kind: 'mc', status: 'done' }] }])
    vi.useFakeTimers()
    initOxdnaJobsPanel({ getWorkspacePath: () => 'A.nadoc' })
    heading().click()                                                  // open, but no active run
    await vi.advanceTimersByTimeAsync(0)
    const n0 = api.listOxdnaJobs.mock.calls.length
    await vi.advanceTimersByTimeAsync(4500)
    expect(api.listOxdnaJobs.mock.calls.length).toBe(n0)             // no poll scheduled (gate off)
  })
})

describe('captureStrandRunPlan', () => {
  const withCaps = (nBeads) => ({
    run_config: { surface_strands: { enabled: true, built: { n_beads: nBeads } } },
  })

  it('inherits the parent capture beads when the card asks for strands', () => {
    expect(captureStrandRunPlan(withCaps(948), { enabled: true }))
      .toEqual({ mode: 'inherit', nBeads: 948 })
  })

  it('is "none" when the card is off, whatever the parent has', () => {
    expect(captureStrandRunPlan(withCaps(948), null).mode).toBe('none')
    expect(captureStrandRunPlan(withCaps(948), { enabled: false }).mode).toBe('none')
  })

  // The run used to launch anyway, strand-free, and the echo-back then flipped the
  // card's toggle off — the user got neither the strands nor a reason.
  it('is "unbuilt" when the card asks for strands the relaxation never built', () => {
    for (const parent of [null, {}, { run_config: {} },
      { run_config: { surface_strands: null } },
      { run_config: { surface_strands: { enabled: true } } },        // spec but no build
      { run_config: { surface_strands: { enabled: true, built: { n_beads: 0 } } } }]) {
      expect(captureStrandRunPlan(parent, { enabled: true }).mode,
        JSON.stringify(parent)).toBe('unbuilt')
    }
  })
})
