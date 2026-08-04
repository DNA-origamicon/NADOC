import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { DEFAULT_PRODUCTION_TIMESTEP_FS, mdAnchorAtomNames, mdAnchorStiffness, DEFAULT_TRAJ_INTERVAL, MD_PRODUCTION_MARKER, TRAJ_FRAME_CONFIRM, effectiveProductionTimestepFs, filterJobsForPart, jobProductionTimestepFs, mdHasProductionRun, mdIsLocalTarget, mdIsRemoteJob, mdSegGlyphKind, newestCompletedForPart, normalizeWorkspacePath, productionNsFromSteps, seededBadge, stridedFrameCount } from './md_jobs_panel.js'

// Auto-mock the API client so the real panel constructs without touching the network
// (only the shared-base parity block at the bottom drives the real panel; the
// pure-helper describes above never call the client). Every export → a vi.fn().
vi.mock('../api/client.js')

describe('mdSegGlyphKind', () => {
  it('classifies a skipped chunk distinctly, even over done/advisory', () => {
    expect(mdSegGlyphKind('done', { skipped: true })).toBe('skipped')
    // skipped wins over an advisory health breach on the same chunk
    expect(mdSegGlyphKind('done', { skipped: true, advisory: true })).toBe('skipped')
  })

  it('maps ordinary segment states', () => {
    expect(mdSegGlyphKind('done')).toBe('done')
    expect(mdSegGlyphKind('done', { advisory: true })).toBe('advisory')
    expect(mdSegGlyphKind('failed')).toBe('failed')
    expect(mdSegGlyphKind('running', { jobLive: true })).toBe('running')
    expect(mdSegGlyphKind('pending')).toBe('pending')
  })

  it('renders a running chunk as pending once the job is terminal', () => {
    expect(mdSegGlyphKind('running', { jobLive: false })).toBe('pending')
  })
})

describe('productionNsFromSteps — the ETA that used to be hard-coded to 1 fs', () => {
  it('scales ns by the timestep (500k steps @ 4 fs = 2 ns, not 0.5)', () => {
    expect(productionNsFromSteps(500_000, 4)).toBeCloseTo(2.0, 9)
    expect(productionNsFromSteps(500_000, 2)).toBeCloseTo(1.0, 9)
    expect(productionNsFromSteps(500_000, 1)).toBeCloseTo(0.5, 9)
  })

  it('defaults to the 4 fs fast production timestep', () => {
    expect(DEFAULT_PRODUCTION_TIMESTEP_FS).toBe(4.0)
    expect(productionNsFromSteps(1_000_000)).toBeCloseTo(4.0, 9)
  })

  it('guards against a bad/zero timestep by falling back to the default', () => {
    expect(productionNsFromSteps(1_000_000, 0)).toBeCloseTo(4.0, 9)
    expect(productionNsFromSteps(1_000_000, NaN)).toBeCloseTo(4.0, 9)
  })
})

describe('stridedFrameCount — the "→ N frames" readout beside the interval field', () => {
  it('mirrors the backend: ceil PER SEGMENT, not over the total', () => {
    // Backend `_composite_indices` strides each written segment on its own, so a
    // 10-frame and a 7-frame segment at interval 3 keep 4 + 3.  Summing first and
    // dividing once would say 6 and the slider would be the wrong length.
    expect(stridedFrameCount([10, 7], 3)).toBe(7)
    expect(stridedFrameCount([100, 3], 50)).toBe(3)   // 2 + 1 — the short segment still counts
  })

  it('keeps every frame at interval 1', () => {
    expect(stridedFrameCount([4, 3], 1)).toBe(7)
  })

  it('is not capped by the legacy 200-frame budget', () => {
    // The whole point of the control: a long run may load far more than the old cap.
    const frames = stridedFrameCount([10_000], DEFAULT_TRAJ_INTERVAL)
    expect(frames).toBe(500)
    expect(frames).toBeGreaterThanOrEqual(TRAJ_FRAME_CONFIRM)   // …so that load asks first
  })

  it('ignores empty segments', () => {
    expect(stridedFrameCount([2, 0, 5], 4)).toBe(3)
    expect(stridedFrameCount([], 20)).toBe(0)
  })

  it('clamps a junk or sub-1 interval to 1 rather than dividing by zero', () => {
    expect(stridedFrameCount([10], 0)).toBe(10)
    expect(stridedFrameCount([10], -5)).toBe(10)
    expect(stridedFrameCount([10], NaN)).toBe(10)
    expect(stridedFrameCount([10], 2.7)).toBe(5)      // floored to 2
  })

  it('returns 0 when the raw counts are unknown', () => {
    expect(stridedFrameCount(null, 20)).toBe(0)
    expect(stridedFrameCount(undefined, 20)).toBe(0)
  })
})

describe('effectiveProductionTimestepFs — ETA and the run must agree', () => {
  const JOB_1FS = { prep_params: { production_timestep_fs: 1, fast: false } }

  it('the dropdown wins over the selected job\'s stored dt', () => {
    // The regression: the dropdown reached PREP only, so picking 2 fs before Start
    // Production changed neither the run nor the estimate — 2 fs selected, 1 fs run.
    expect(effectiveProductionTimestepFs({ selectValue: '2', job: JOB_1FS })).toBe(2)
    expect(effectiveProductionTimestepFs({ selectValue: '4', job: JOB_1FS })).toBe(4)
  })

  it('the ETA follows the dropdown, so the "x ns" readout matches the trajectory', () => {
    const ts = effectiveProductionTimestepFs({ selectValue: '2', job: JOB_1FS })
    expect(productionNsFromSteps(500_000, ts)).toBeCloseTo(1.0, 9)   // 2 fs → 1.0 ns
    // ...and NOT the 0.5 ns the old job-derived path would have shown.
    expect(productionNsFromSteps(500_000, jobProductionTimestepFs(JOB_1FS))).toBeCloseTo(0.5, 9)
  })

  it('falls back to the job\'s stored dt when the select is unset/garbage', () => {
    expect(effectiveProductionTimestepFs({ selectValue: '', job: JOB_1FS })).toBe(1)
    expect(effectiveProductionTimestepFs({ selectValue: '3', job: JOB_1FS })).toBe(1)
    expect(effectiveProductionTimestepFs({ selectValue: undefined, job: JOB_1FS })).toBe(1)
  })

  it('falls back to the default with neither a select nor a job', () => {
    expect(effectiveProductionTimestepFs({})).toBe(DEFAULT_PRODUCTION_TIMESTEP_FS)
    expect(effectiveProductionTimestepFs()).toBe(DEFAULT_PRODUCTION_TIMESTEP_FS)
  })
})

describe('jobProductionTimestepFs — what dt a prepared job will actually run', () => {
  it('uses the stored production_timestep_fs when present (1/2/4)', () => {
    expect(jobProductionTimestepFs({ prep_params: { production_timestep_fs: 2 } })).toBe(2)
    expect(jobProductionTimestepFs({ prep_params: { production_timestep_fs: 1, fast: true } })).toBe(1)
  })

  it('falls back to fast?4:1 for jobs prepared before the field existed', () => {
    expect(jobProductionTimestepFs({ prep_params: { fast: true } })).toBe(4)
    expect(jobProductionTimestepFs({ prep_params: { fast: false } })).toBe(1)
  })

  it('defaults to 4 fs when there are no prep params at all', () => {
    expect(jobProductionTimestepFs(null)).toBe(DEFAULT_PRODUCTION_TIMESTEP_FS)
    expect(jobProductionTimestepFs({})).toBe(DEFAULT_PRODUCTION_TIMESTEP_FS)
  })
})

describe('seededBadge', () => {
  it('labels oxDNA-, mrDNA-, and BLADE-seeded jobs and nothing else', () => {
    expect(seededBadge({ seed_oxdna_job_id: 'abc123' })).toBe('oxDNA seeded')
    expect(seededBadge({ seed_mrdna_job_id: 'def456' })).toBe('mrDNA seeded')
    expect(seededBadge({ seed_blade_job_id: 'bla789' })).toBe('BLADE seeded')
    expect(seededBadge({ seed_oxdna_job_id: null })).toBe('')
    expect(seededBadge({})).toBe('')
    expect(seededBadge(null)).toBe('')
  })
})

describe('normalizeWorkspacePath', () => {
  it('returns empty string for null/undefined/empty', () => {
    expect(normalizeWorkspacePath(null)).toBe('')
    expect(normalizeWorkspacePath(undefined)).toBe('')
    expect(normalizeWorkspacePath('')).toBe('')
  })

  it('converts backslashes to forward slashes', () => {
    expect(normalizeWorkspacePath('a\\b\\c.nadoc')).toBe('a/b/c.nadoc')
  })

  it('strips trailing slashes', () => {
    expect(normalizeWorkspacePath('foo/bar/')).toBe('foo/bar')
    expect(normalizeWorkspacePath('foo/bar///')).toBe('foo/bar')
  })
})

describe('filterJobsForPart', () => {
  const jobs = [
    { job_id: 'a', design_source_path: '18hb.nadoc' },
    { job_id: 'b', design_source_path: '6hb_84bp.nadoc' },
    { job_id: 'c', design_source_path: null },
    { job_id: 'd', design_source_path: '18hb.nadoc' },
  ]

  it('shows only jobs matching the active part path', () => {
    const out = filterJobsForPart(jobs, '18hb.nadoc', false)
    expect(out.map(j => j.job_id)).toEqual(['a', 'd'])
  })

  it('shows nothing when no part path is known (no leaking other designs)', () => {
    expect(filterJobsForPart(jobs, null, false)).toEqual([])
    expect(filterJobsForPart(jobs, '', false)).toEqual([])
  })

  it('never matches jobs with a null source path under a real part', () => {
    const out = filterJobsForPart(jobs, '18hb.nadoc', false)
    expect(out.some(j => j.job_id === 'c')).toBe(false)
  })

  it('normalizes both sides before comparing', () => {
    const winJobs = [{ job_id: 'x', design_source_path: 'sub\\18hb.nadoc' }]
    expect(filterJobsForPart(winJobs, 'sub/18hb.nadoc/', false).map(j => j.job_id)).toEqual(['x'])
  })

  it('showAll returns every job unfiltered', () => {
    expect(filterJobsForPart(jobs, '18hb.nadoc', true)).toEqual(jobs)
    expect(filterJobsForPart(jobs, null, true)).toEqual(jobs)
  })
})

describe('newestCompletedForPart (cross-engine compare fallback)', () => {
  const jobs = [
    { job_id: 'old', design_source_path: '18hb.nadoc', status: 'completed', created_at: 100 },
    { job_id: 'new', design_source_path: '18hb.nadoc', status: 'completed', created_at: 300 },
    { job_id: 'running', design_source_path: '18hb.nadoc', status: 'running', created_at: 400 },
    { job_id: 'other', design_source_path: '6hb.nadoc', status: 'completed', created_at: 999 },
  ]

  it('picks the newest COMPLETED job for the active part', () => {
    expect(newestCompletedForPart(jobs, '18hb.nadoc').job_id).toBe('new')
  })

  it('ignores non-completed and other-design jobs', () => {
    // 'running' is newer but not completed; 'other' is completed+newest but wrong design.
    const out = newestCompletedForPart(jobs, '18hb.nadoc')
    expect(out.status).toBe('completed')
    expect(out.design_source_path).toBe('18hb.nadoc')
  })

  it('returns null when no completed job matches the part (or no part is known)', () => {
    expect(newestCompletedForPart(jobs, '6hb.nadoc').job_id).toBe('other')
    expect(newestCompletedForPart(jobs, null)).toBeNull()
    expect(newestCompletedForPart([], '18hb.nadoc')).toBeNull()
    expect(newestCompletedForPart(null, '18hb.nadoc')).toBeNull()
  })
})

import { mdJobIsActive, mdJobIsRunning, mdJobIsStartable, mdJobIsResumable, mdRunControl, mdRemoteAwaitingSubmit, makeSpinner, mdHasMetrics, mdListSignature, mdChildRowLabel, hasActiveRemoteJob, mdWatchdogDecision, mdRemoteReconnectPrompt, mdJobIsDraft, mdDraftRunLabel, mdJobRowSig, mdJobRowCtx, gpuFallbackFromToggle } from './md_jobs_panel.js'

describe('mdJobIsDraft / mdDraftRunLabel (deferred-prep seed)', () => {
  it('mdJobIsDraft is true only for status "draft"', () => {
    expect(mdJobIsDraft({ status: 'draft' })).toBe(true)
    for (const s of ['queued', 'preparing', 'running', 'completed', 'failed', 'stopped']) {
      expect(mdJobIsDraft({ status: s })).toBe(false)
    }
    expect(mdJobIsDraft(null)).toBe(false)
  })
  it('a draft is NOT counted as active (no spinner / not resumable)', () => {
    expect(mdJobIsActive({ status: 'draft' })).toBe(false)
  })
  it('mdDraftRunLabel names the seed engine', () => {
    expect(mdDraftRunLabel({ status: 'draft', seed_oxdna_job_id: 'ox1' })).toBe('▶ Relax from oxDNA')
    expect(mdDraftRunLabel({ status: 'draft', seed_mrdna_job_id: 'mr1' })).toBe('▶ Relax from mrDNA')
    expect(mdDraftRunLabel({ status: 'draft', seed_blade_job_id: 'bl1' })).toBe('▶ Relax from BLADE')
    expect(mdDraftRunLabel({ status: 'draft' })).toBe('▶ Relax from oxDNA')  // default
  })
})

import { isImplicitSolventProtocol, IMPLICIT_GBIS_PROTOCOL, deviceStringForCompute, computeFromDeviceString } from './md_jobs_panel.js'

describe('isImplicitSolventProtocol (GBIS grays explicit-solvent knobs)', () => {
  it('is true only for the GBIS protocol', () => {
    expect(isImplicitSolventProtocol(IMPLICIT_GBIS_PROTOCOL)).toBe(true)
    expect(isImplicitSolventProtocol('implicit_gbis_namd')).toBe(true)
    for (const p of ['equilibrium_aware_namd', 'mgh_slow_release', '', null, undefined]) {
      expect(isImplicitSolventProtocol(p)).toBe(false)
    }
  })
})

describe('deviceStringForCompute / computeFromDeviceString (Compute GPU/CPU selector)', () => {
  it('GPU compute passes the CUDA device ids through', () => {
    expect(deviceStringForCompute('gpu', '0', 'equilibrium_aware_namd')).toBe('0')
    expect(deviceStringForCompute('gpu', '0,1', 'equilibrium_aware_namd')).toBe('0,1')
    expect(deviceStringForCompute('gpu', '', 'equilibrium_aware_namd')).toBe('0')  // default
  })
  it('CPU compute → "cpu" regardless of device field', () => {
    expect(deviceStringForCompute('cpu', '0', 'equilibrium_aware_namd')).toBe('cpu')
  })
  it('GBIS forces "cpu" even when GPU is selected', () => {
    expect(deviceStringForCompute('gpu', '0', IMPLICIT_GBIS_PROTOCOL)).toBe('cpu')
  })
  it('computeFromDeviceString inverts the encoding', () => {
    expect(computeFromDeviceString('cpu')).toBe('cpu')
    expect(computeFromDeviceString('CPU')).toBe('cpu')
    expect(computeFromDeviceString('0')).toBe('gpu')
    expect(computeFromDeviceString('0,1')).toBe('gpu')
    expect(computeFromDeviceString(null)).toBe('gpu')
  })
})

describe('mdChildRowLabel', () => {
  it('labels a derived child by its global run number', () => {
    expect(mdChildRowLabel({ job_id: 'x' }, 1)).toBe('Refit 1')
    expect(mdChildRowLabel({ job_id: 'y' }, 3)).toBe('Refit 3')
  })
})

describe('mdJobIsActive', () => {
  it('is true for in-progress statuses, false otherwise', () => {
    for (const s of ['queued', 'preparing', 'running']) {
      expect(mdJobIsActive({ status: s })).toBe(true)
    }
    for (const s of ['completed', 'failed', 'stopped']) {
      expect(mdJobIsActive({ status: s })).toBe(false)
    }
    expect(mdJobIsActive(null)).toBe(false)
  })
  it('is NOT active for an Alpine OR RunPod job queued but never handed off', () => {
    // The failed-submit / never-submitted case: shows no running spinner, and (load-bearing)
    // does not hijack the Relax button — a never-launched runpod queued job is not "active".
    expect(mdJobIsActive({ status: 'queued', execution_target: 'alpine' })).toBe(false)
    expect(mdJobIsActive({ status: 'queued', execution_target: 'alpine', error: 'Cluster submission failed: x' })).toBe(false)
    expect(mdJobIsActive({ status: 'queued', execution_target: 'runpod' })).toBe(false)
  })
  it('IS active once the Alpine job has a SLURM id (on the cluster)', () => {
    expect(mdJobIsActive({ status: 'queued', execution_target: 'alpine', slurm_job_id: '123' })).toBe(true)
    expect(mdJobIsActive({ status: 'running', execution_target: 'alpine', slurm_job_id: '123' })).toBe(true)
  })
  it('local jobs are unaffected (queued = active)', () => {
    expect(mdJobIsActive({ status: 'queued', execution_target: 'local' })).toBe(true)
  })
})

describe('mdJobIsRunning / mdJobIsStartable / mdJobIsResumable (what the one control acts on)', () => {
  it('running and preparing are running', () => {
    expect(mdJobIsRunning({ status: 'running' })).toBe(true)
    expect(mdJobIsRunning({ status: 'preparing' })).toBe(true)
  })
  it('a LOCAL queued job is NOT running — it was created and is waiting for Run', () => {
    // This is the "create without starting" state. Calling it running turned the control
    // into a Stop button for a job that had never started.
    expect(mdJobIsRunning({ status: 'queued', execution_target: 'local' })).toBe(false)
    expect(mdJobIsStartable({ status: 'queued', execution_target: 'local' })).toBe(true)
  })
  it('a SUBMITTED remote job is running even while its scheduler has it queued', () => {
    expect(mdJobIsRunning({ status: 'queued', execution_target: 'alpine', slurm_job_id: '9' })).toBe(true)
    expect(mdJobIsRunning({ status: 'queued', execution_target: 'runpod', runpod_pod_id: 'p' })).toBe(true)
  })
  it('a remote job prepared but never submitted is neither running nor startable here', () => {
    const job = { status: 'queued', execution_target: 'alpine' }
    expect(mdJobIsRunning(job)).toBe(false)
    expect(mdJobIsStartable(job)).toBe(false)   // submission goes through the review card
  })
  it('stopped/failed local jobs resume; alpine resumes stay on their own gated button', () => {
    expect(mdJobIsResumable({ status: 'stopped', execution_target: 'local' })).toBe(true)
    expect(mdJobIsResumable({ status: 'failed', execution_target: 'local' })).toBe(true)
    expect(mdJobIsResumable({ status: 'stopped', execution_target: 'alpine' })).toBe(false)
    expect(mdJobIsResumable({ status: 'completed', execution_target: 'local' })).toBe(false)
  })
  it('a job paused on the GPU-resident decision is resumable', () => {
    expect(mdJobIsResumable({ status: 'paused', execution_target: 'local', decision: { gate: 'gpu_resident' } }))
      .toBe(true)
  })
})

describe('mdRunControl (ONE control for the selected job: Run / Stop / Resume)', () => {
  it('nothing selected → disabled, pointing at ＋ New job', () => {
    // Creating a run is a separate act now, so an empty selection has nothing to do
    // rather than silently launching whatever the form happens to hold.
    const rc = mdRunControl(null)
    expect(rc.disabled).toBe(true)
    expect(rc.title).toMatch(/New job/)
  })
  it('a prepared-but-unstarted job → ▶ Run', () => {
    const rc = mdRunControl({ status: 'queued', execution_target: 'local' })
    expect(rc).toMatchObject({ action: 'run', label: '▶ Run', disabled: false })
  })
  it('a running job → ■ Stop', () => {
    expect(mdRunControl({ status: 'running', execution_target: 'local' }))
      .toMatchObject({ action: 'stop', label: '■ Stop Run' })
  })
  it('a stopped job → ↻ Resume', () => {
    expect(mdRunControl({ status: 'stopped', execution_target: 'local' }))
      .toMatchObject({ action: 'resume', label: '↻ Resume Run' })
  })
  it('a PRODUCTION child gets Stop/Resume like anything else', () => {
    // It used to be excluded, so its stop/resume lived on a separate Production button
    // that knew a different subset of states.
    expect(mdRunControl({ status: 'running', run_kind: 'production', execution_target: 'local' }))
      .toMatchObject({ action: 'stop' })
    expect(mdRunControl({ status: 'stopped', run_kind: 'production', execution_target: 'local' }))
      .toMatchObject({ action: 'resume' })
  })
  it('a completed job → disabled, saying why', () => {
    const rc = mdRunControl({ status: 'completed', execution_target: 'local' })
    expect(rc.disabled).toBe(true)
    expect(rc.title).toMatch(/finished/)
  })
  it('a remote job awaiting submit → disabled, pointing at the review card', () => {
    const rc = mdRunControl({ status: 'queued', execution_target: 'alpine' }, { runTarget: 'alpine' })
    expect(rc.disabled).toBe(true)
    expect(rc.title).toMatch(/review card/)
  })
  it('a seeded draft names the engine it will start from', () => {
    expect(mdRunControl({ status: 'draft', seed_oxdna_job_id: 'x' }).label).toBe('▶ Relax from oxDNA')
    expect(mdRunControl({ status: 'draft', seed_blade_job_id: 'x' }).label).toBe('▶ Relax from BLADE')
  })
  it('busy (a request already in flight) → disabled', () => {
    expect(mdRunControl({ status: 'queued', execution_target: 'local' }, { busy: true }).disabled).toBe(true)
  })
})

describe('gpuFallbackFromToggle (the "Prefer fastest GPU mode" launch setting)', () => {
  it('checked → ask (require resident, pause & ask); unchecked → auto_offload', () => {
    expect(gpuFallbackFromToggle(true)).toBe('ask')
    expect(gpuFallbackFromToggle(false)).toBe('auto_offload')
  })
})

describe('GPU-decision surfacing in the job list (⚠ + row signature)', () => {
  const decided = { job_id: 'j1', status: 'paused', decision: { gate: 'gpu_resident' } }
  const clean = { job_id: 'j1', status: 'paused' }

  it('the row signature changes when a decision appears/clears (so ⚠ re-renders)', () => {
    expect(mdJobRowSig(decided)).not.toBe(mdJobRowSig(clean))
  })
  it('mdJobRowCtx marks a decision job stale with the GPU hover message', () => {
    const ctx = mdJobRowCtx({})
    expect(ctx.isStale(decided)).toBe(true)
    expect(ctx.staleTitle(decided)).toMatch(/fastest GPU mode/i)
    // a plain paused job (no decision, design current) is not marked
    expect(ctx.isStale(clean)).toBe(false)
  })
})

describe('mdRemoteReconnectPrompt (reconnect nudge for in-flight Alpine runs)', () => {
  const running = { execution_target: 'alpine', slurm_job_id: '9', status: 'running' }
  it('prompts when a submitted Alpine run is in flight AND the session is down', () => {
    expect(mdRemoteReconnectPrompt([running], 'disconnected')).toMatch(/1 Alpine run in flight/)
    expect(mdRemoteReconnectPrompt([running], 'expired')).toMatch(/reconnect to monitor/)
    expect(mdRemoteReconnectPrompt([running, { ...running, slurm_job_id: '10', status: 'queued' }], 'disconnected')).toMatch(/2 Alpine runs/)
  })
  it('stays silent when connected/connecting, or nothing is in flight', () => {
    expect(mdRemoteReconnectPrompt([running], 'connected')).toBe('')
    expect(mdRemoteReconnectPrompt([running], 'connecting')).toBe('')
    expect(mdRemoteReconnectPrompt([{ ...running, status: 'completed' }], 'disconnected')).toBe('')
    expect(mdRemoteReconnectPrompt([{ execution_target: 'alpine', status: 'running' }], 'disconnected')).toBe('')  // never submitted (no slurm id)
    expect(mdRemoteReconnectPrompt([{ execution_target: 'local', status: 'running' }], 'disconnected')).toBe('')
    expect(mdRemoteReconnectPrompt([], 'disconnected')).toBe('')
    expect(mdRemoteReconnectPrompt(null, 'disconnected')).toBe('')
  })
})

describe('hasActiveRemoteJob (gates the remote-poll timer)', () => {
  it('true only when a submitted Alpine job is in flight', () => {
    expect(hasActiveRemoteJob([{ status: 'running', execution_target: 'alpine', slurm_job_id: '9' }])).toBe(true)
    expect(hasActiveRemoteJob([{ status: 'queued', execution_target: 'alpine', slurm_job_id: '9' }])).toBe(true)
  })
  it('false for local, terminal, or not-yet-submitted remote jobs', () => {
    expect(hasActiveRemoteJob([{ status: 'running', execution_target: 'local' }])).toBe(false)
    expect(hasActiveRemoteJob([{ status: 'completed', execution_target: 'alpine', slurm_job_id: '9' }])).toBe(false)
    expect(hasActiveRemoteJob([{ status: 'queued', execution_target: 'alpine' }])).toBe(false)  // awaiting submit
    expect(hasActiveRemoteJob([])).toBe(false)
    expect(hasActiveRemoteJob(null)).toBe(false)
  })
})

describe('mdWatchdogDecision (detail-WS safety net for local jobs)', () => {
  const live = { status: 'running', execution_target: 'local' }
  it('idle when a local live job has a fresh open socket', () => {
    expect(mdWatchdogDecision({ job: live, wsOpen: true, msSinceMsg: 3000 })).toBe('idle')
  })
  it('reconnect when a local live job has no socket', () => {
    expect(mdWatchdogDecision({ job: live, wsOpen: false, msSinceMsg: 0 })).toBe('reconnect')
    expect(mdWatchdogDecision({ job: { status: 'preparing', execution_target: 'local' }, wsOpen: false })).toBe('reconnect')
    expect(mdWatchdogDecision({ job: { status: 'queued', execution_target: 'local' }, wsOpen: false })).toBe('reconnect')
  })
  it('refresh when the socket is open but silent past the stale window', () => {
    expect(mdWatchdogDecision({ job: live, wsOpen: true, msSinceMsg: 99999 })).toBe('refresh')
    expect(mdWatchdogDecision({ job: live, wsOpen: true, msSinceMsg: 6000, staleMs: 5000 })).toBe('refresh')
  })
  it('disarm for no selection, terminal, or remote/Alpine jobs (no local WS to watch)', () => {
    expect(mdWatchdogDecision({ job: null, wsOpen: false })).toBe('disarm')
    expect(mdWatchdogDecision({ job: { status: 'completed', execution_target: 'local' }, wsOpen: false })).toBe('disarm')
    expect(mdWatchdogDecision({ job: { status: 'failed', execution_target: 'local' }, wsOpen: false })).toBe('disarm')
    expect(mdWatchdogDecision({ job: { status: 'stopped', execution_target: 'local' }, wsOpen: false })).toBe('disarm')
    expect(mdWatchdogDecision({ job: { status: 'running', execution_target: 'alpine', slurm_job_id: '9' }, wsOpen: false })).toBe('disarm')
    expect(mdWatchdogDecision({ job: { status: 'running', execution_target: 'local', slurm_job_id: '9' }, wsOpen: false })).toBe('disarm')
  })
})

describe('mdRemoteAwaitingSubmit', () => {
  it('is true for an Alpine OR RunPod queued job with no scheduler/pod handle', () => {
    expect(mdRemoteAwaitingSubmit({ status: 'queued', execution_target: 'alpine' })).toBe(true)
    // RunPod MUST be included — a never-launched runpod queued job carries no pod id; treating
    // it as "active" is what hijacked the Relax button into "■ Stop".
    expect(mdRemoteAwaitingSubmit({ status: 'queued', execution_target: 'runpod' })).toBe(true)
  })
  it('is false once handed off (slurm id / pod id), for local jobs, or non-queued states', () => {
    expect(mdRemoteAwaitingSubmit({ status: 'queued', execution_target: 'alpine', slurm_job_id: '9' })).toBe(false)
    expect(mdRemoteAwaitingSubmit({ status: 'queued', execution_target: 'runpod', runpod_pod_id: 'pod123' })).toBe(false)
    expect(mdRemoteAwaitingSubmit({ status: 'queued', execution_target: 'local' })).toBe(false)
    expect(mdRemoteAwaitingSubmit({ status: 'running', execution_target: 'alpine' })).toBe(false)
    expect(mdRemoteAwaitingSubmit({ status: 'running', execution_target: 'runpod', runpod_pod_id: 'pod123' })).toBe(false)
    expect(mdRemoteAwaitingSubmit(null)).toBe(false)
  })
})

import { mdDetailErrorText } from './md_jobs_panel.js'

describe('mdDetailErrorText', () => {
  it('shows nothing for a clean user-stop (no error)', () => {
    expect(mdDetailErrorText({ status: 'stopped' })).toBe(null)
    expect(mdDetailErrorText({ status: 'stopped', error: null })).toBe(null)
  })
  it('shows the error for a stopped job that carries one (raced a real failure / legacy)', () => {
    expect(mdDetailErrorText({ status: 'stopped', error: 'disk full' })).toBe('disk full')
  })
  it('shows Unknown error only for a failed job with no message', () => {
    expect(mdDetailErrorText({ status: 'failed' })).toBe('Unknown error')
    expect(mdDetailErrorText({ status: 'failed', error: 'boom' })).toBe('boom')
  })
  it('shows a failed Alpine submit and a resumable timed-out job', () => {
    expect(mdDetailErrorText({ status: 'queued', execution_target: 'alpine', error: 'rejected' })).toBe('rejected')
    expect(mdDetailErrorText({ status: 'stopped', resumable: true, error: 'click Resume' })).toBe('click Resume')
  })
  it('hides the box for live / non-terminal jobs', () => {
    expect(mdDetailErrorText({ status: 'running' })).toBe(null)
    expect(mdDetailErrorText({ status: 'preparing' })).toBe(null)
    expect(mdDetailErrorText({ status: 'completed' })).toBe(null)
  })
})

describe('makeSpinner', () => {
  it('builds a .nadoc-spinner span sized + colored', () => {
    const s = makeSpinner('#e3b341', 10)
    expect(s.className).toBe('nadoc-spinner')
    expect(s.style.width).toBe('10px')
    expect(s.style.height).toBe('10px')
    expect(s.getAttribute('aria-hidden')).toBe('true')
  })
})

describe('mdHasMetrics', () => {
  it('detects health samples, live temperature, or a persisted metric', () => {
    expect(mdHasMetrics({ health_samples: [{ stage: 'x' }] })).toBe(true)
    expect(mdHasMetrics({ live_metrics: { temperature_k: 301 } })).toBe(true)
    expect(mdHasMetrics({}, { ns_per_day: 12 })).toBe(true)
    expect(mdHasMetrics({}, null)).toBe(false)
    expect(mdHasMetrics({ live_metrics: { temperature_k: null } }, null)).toBe(false)
  })
})

import { mdEarlyStopToggleState } from './md_jobs_panel.js'

describe('mdEarlyStopToggleState', () => {
  it('settled: no override → reflects the persisted flag, not pending', () => {
    expect(mdEarlyStopToggleState({ early_stop_relax: false })).toEqual({ checked: false, pending: false })
    expect(mdEarlyStopToggleState({ early_stop_relax: true })).toEqual({ checked: true, pending: false })
  })
  it('queued override differing from persisted → shows requested value, pending', () => {
    // user toggled ON; runner has not yet consumed it, so early_stop_relax still false
    expect(mdEarlyStopToggleState({ early_stop_relax: false, early_stop_pending: true }))
      .toEqual({ checked: true, pending: true })
    // user toggled OFF a currently-on job
    expect(mdEarlyStopToggleState({ early_stop_relax: true, early_stop_pending: false }))
      .toEqual({ checked: false, pending: true })
  })
  it('override already matches persisted → settled (nothing actually queued)', () => {
    expect(mdEarlyStopToggleState({ early_stop_relax: true, early_stop_pending: true }))
      .toEqual({ checked: true, pending: false })
  })
  it('in-flight POST (busy) forces pending even before the server reports the override', () => {
    expect(mdEarlyStopToggleState({ early_stop_relax: false }, true))
      .toEqual({ checked: false, pending: true })
  })
})

describe('mdListSignature', () => {
  it('changes on status, segment, selection; stable otherwise', () => {
    const jobs = [{ job_id: 'a', status: 'running', current_segment_idx: 1 }]
    const base = mdListSignature(jobs, 'a')
    expect(mdListSignature(jobs, 'a')).toBe(base)                                   // stable
    expect(mdListSignature([{ ...jobs[0], status: 'completed' }], 'a')).not.toBe(base)
    expect(mdListSignature([{ ...jobs[0], current_segment_idx: 2 }], 'a')).not.toBe(base)
    expect(mdListSignature(jobs, 'b')).not.toBe(base)                               // selection
    expect(mdListSignature([{ ...jobs[0], ensemble_seed: 54322 }], 'a')).not.toBe(base)  // replica badge refresh
  })
})

import { mdIsEnsembleReplica, mdIsEnsembleParent, mdReplicaRowLabel, ensembleChildSummary } from './md_jobs_panel.js'

describe('ensemble helpers', () => {
  const parent = { job_id: 'P', status: 'completed' }
  const reps = [
    { job_id: 'r0', parent_job_id: 'P', ensemble_seed: 54321, ensemble_index: 0, status: 'running' },
    { job_id: 'r1', parent_job_id: 'P', ensemble_seed: 54322, ensemble_index: 1, status: 'queued' },
    { job_id: 'r2', parent_job_id: 'P', ensemble_seed: 54323, ensemble_index: 2, status: 'completed' },
  ]
  const jobs = [parent, ...reps]

  it('mdIsEnsembleReplica keys off ensemble_seed', () => {
    expect(mdIsEnsembleReplica(reps[0])).toBe(true)
    expect(mdIsEnsembleReplica({ job_id: 'x', parent_job_id: 'P' })).toBe(false)   // refit child, not a replica
    expect(mdIsEnsembleReplica(parent)).toBe(false)
  })

  it('mdIsEnsembleParent true only when a job has replica children', () => {
    expect(mdIsEnsembleParent(parent, jobs)).toBe(true)
    expect(mdIsEnsembleParent(reps[0], jobs)).toBe(false)
    expect(mdIsEnsembleParent(parent, [parent, { job_id: 'f', parent_job_id: 'P' }])).toBe(false)  // refit child only
  })

  it('mdReplicaRowLabel uses ensemble_index+1 and the seed', () => {
    expect(mdReplicaRowLabel(reps[0], 9)).toBe('Replica 1 · seed 54321')
    expect(mdReplicaRowLabel(reps[2], 9)).toBe('Replica 3 · seed 54323')
  })

  it('ensembleChildSummary aggregates replica statuses', () => {
    expect(ensembleChildSummary(parent, jobs)).toBe('⧉ 3 replicas · 1 running · 1 queued · 1 done')
    expect(ensembleChildSummary(parent, [parent])).toBe('')                        // no replicas
  })
})

import { mdIsProductionChild, mdProductionRowLabel } from './md_jobs_panel.js'

describe('production child helpers (local production fan-out under a relaxation)', () => {
  const relax = { job_id: 'P', status: 'completed' }
  const prods = [
    { job_id: 'p0', parent_job_id: 'P', ensemble_seed: 54321, ensemble_index: 0, run_kind: 'production', status: 'running' },
    { job_id: 'p1', parent_job_id: 'P', ensemble_seed: 54322, ensemble_index: 1, run_kind: 'production', status: 'completed' },
  ]
  const jobs = [relax, ...prods]

  it('mdIsProductionChild keys off run_kind', () => {
    expect(mdIsProductionChild(prods[0])).toBe(true)
    expect(mdIsProductionChild({ job_id: 'r', ensemble_seed: 1 })).toBe(false)     // ensemble replica, not production
    expect(mdIsProductionChild(relax)).toBe(false)
  })

  it('a production child still counts as a seeded (nesting) child', () => {
    expect(mdIsEnsembleReplica(prods[0])).toBe(true)                               // indents + collapses under the parent
    expect(mdIsEnsembleParent(relax, jobs)).toBe(true)
  })

  it('mdProductionRowLabel reads "Production N · seed S"', () => {
    expect(mdProductionRowLabel(prods[0], 9)).toBe('Production 1 · seed 54321')
    expect(mdProductionRowLabel(prods[1], 9)).toBe('Production 2 · seed 54322')
  })

  it('ensembleChildSummary says "production runs" for a production fan-out', () => {
    expect(ensembleChildSummary(relax, jobs)).toBe('⧉ 2 production runs · 1 running · 1 done')
  })
})

import { mdHasAppendedProduction } from './md_jobs_panel.js'

describe('mdHasAppendedProduction (legacy same-job production detection)', () => {
  const relaxSeg = { name: 'D_04_300K_NPT_MGHH_only_p100', stage: '300K NPT k=0' }
  const prodSeg = { name: 'D_05_production_0p5ns_k0_p10', stage: '0.5 ns production run' }

  it('true for a root relaxation carrying appended production segments', () => {
    expect(mdHasAppendedProduction({ job_id: 'a', segments: [relaxSeg, prodSeg] })).toBe(true)
  })
  it('false for a pure relaxation (no production segment)', () => {
    expect(mdHasAppendedProduction({ job_id: 'a', segments: [relaxSeg] })).toBe(false)
  })
  it('false for a production CHILD (run_kind) or any derived job', () => {
    expect(mdHasAppendedProduction({ job_id: 'c', run_kind: 'production', segments: [prodSeg] })).toBe(false)
    expect(mdHasAppendedProduction({ job_id: 'c', parent_job_id: 'P', segments: [prodSeg] })).toBe(false)
  })
  it('false for null / no segments', () => {
    expect(mdHasAppendedProduction(null)).toBe(false)
    expect(mdHasAppendedProduction({ job_id: 'a' })).toBe(false)
  })
})

import { mdHasLocalReadouts, mdRemoteReadoutNote, mdReplicaStateText, ensembleReplicas } from './md_jobs_panel.js'

describe('remote-job readout handling (Alpine replicas have no local metrics in flight)', () => {
  const localRunning = { job_id: 'L', execution_target: 'local', status: 'running', health_samples: [] }
  const remoteRunning = { job_id: 'R', execution_target: 'alpine', status: 'running', slurm_job_id: '2973', health_samples: [] }
  const remoteDone = { job_id: 'D', execution_target: 'alpine', status: 'completed', slurm_job_id: '2973', health_samples: [{ c1_paired_fraction: 0.98 }] }
  const awaiting = { job_id: 'A', execution_target: 'alpine', status: 'queued', health_samples: [] }  // no slurm id

  it('mdHasLocalReadouts: local always true; remote only once results fetched', () => {
    expect(mdHasLocalReadouts(localRunning)).toBe(true)
    expect(mdHasLocalReadouts(remoteRunning)).toBe(false)   // in flight, no local samples
    expect(mdHasLocalReadouts(remoteDone)).toBe(true)       // results fetched → samples present
  })

  it('mdRemoteReadoutNote: a cluster-side note for an in-flight remote job, else null', () => {
    expect(mdRemoteReadoutNote(remoteRunning)).toMatch(/Running on Alpine \(SLURM 2973\)/)
    expect(mdRemoteReadoutNote(localRunning)).toBeNull()    // local shows the real grid
    expect(mdRemoteReadoutNote(remoteDone)).toBeNull()      // has local readouts
    expect(mdRemoteReadoutNote(awaiting)).toBeNull()        // awaiting-submit has its own status line
  })

  it('mdReplicaStateText: SLURM state for remote, plain status otherwise', () => {
    expect(mdReplicaStateText({ ...remoteRunning, slurm_state: 'RUNNING' })).toBe('RUNNING · 2973')
    expect(mdReplicaStateText(remoteRunning)).toBe('running · SLURM 2973')
    expect(mdReplicaStateText(awaiting)).toBe('awaiting submit')
    expect(mdReplicaStateText(localRunning)).toBe('running')
  })

  it('ensembleReplicas: parent → its seeded children sorted by ensemble_index', () => {
    const parent = { job_id: 'P' }
    const jobs = [
      parent,
      { job_id: 'r1', parent_job_id: 'P', ensemble_seed: 2, ensemble_index: 1, status: 'running' },
      { job_id: 'r0', parent_job_id: 'P', ensemble_seed: 1, ensemble_index: 0, status: 'running' },
      { job_id: 'x', parent_job_id: 'P' },   // refit child, not a replica
    ]
    expect(ensembleReplicas(parent, jobs).map(j => j.job_id)).toEqual(['r0', 'r1'])
  })
})

import { mdShouldShowInheritedSeed } from './md_jobs_panel.js'

describe('mdShouldShowInheritedSeed', () => {
  it('true only when oxDNA-seeded AND no MD frame written yet', () => {
    // seeded + no MD trajectory → show inherited oxDNA-seed positions
    expect(mdShouldShowInheritedSeed({ seed_oxdna_job_id: 'ox1' }, { ready: false })).toBe(true)
    expect(mdShouldShowInheritedSeed({ seed_oxdna_job_id: 'ox1' }, null)).toBe(true)
    expect(mdShouldShowInheritedSeed({ seed_oxdna_job_id: 'ox1' }, {})).toBe(true)
    // seeded but MD already has a frame → MD positions take over
    expect(mdShouldShowInheritedSeed({ seed_oxdna_job_id: 'ox1' }, { ready: true })).toBe(false)
    // not seeded → never inherited
    expect(mdShouldShowInheritedSeed({ seed_oxdna_job_id: null }, { ready: false })).toBe(false)
    expect(mdShouldShowInheritedSeed({}, { ready: false })).toBe(false)
    expect(mdShouldShowInheritedSeed(null, null)).toBe(false)
  })
})

import { fastPhaseSpeedNote, FAST_PHASE_SPEEDUP } from './md_jobs_panel.js'

describe('fastPhaseSpeedNote', () => {
  const fastJob = (idx) => ({ prep_params: { fast: true }, current_segment_idx: idx })

  it('flags the slow strain-relief first segment of a fast job', () => {
    const note = fastPhaseSpeedNote(fastJob(0), 1.7)
    expect(note).not.toBeNull()
    expect(note.asterisk).toBe(true)
    expect(note.tooltip).toContain(`~${Math.round(1.7 * FAST_PHASE_SPEEDUP)} ns/day`)
    expect(note.tooltip).toMatch(/GPU-resident/)
  })

  it('returns null once past segment 0 (production speed is real)', () => {
    expect(fastPhaseSpeedNote(fastJob(1), 16)).toBeNull()
  })

  it('returns null for non-fast jobs', () => {
    expect(fastPhaseSpeedNote({ prep_params: { fast: false }, current_segment_idx: 0 }, 3.8)).toBeNull()
    expect(fastPhaseSpeedNote({ current_segment_idx: 0 }, 3.8)).toBeNull()
    expect(fastPhaseSpeedNote(null, 3.8)).toBeNull()
  })

  it('omits the estimate when speed is not yet known', () => {
    const note = fastPhaseSpeedNote(fastJob(0), null)
    expect(note.asterisk).toBe(true)
    expect(note.tooltip).not.toMatch(/ns\/day,/)   // no "~N ns/day," estimate clause
  })
})

import { mdResumeButtonState, mdResumeHistoryRows } from './md_jobs_panel.js'

describe('mdResumeButtonState (one-click Resume for a timed-out remote job)', () => {
  it('hidden for a non-resumable or non-alpine job', () => {
    expect(mdResumeButtonState({ execution_target: 'alpine', resumable: false }, 'connected').show).toBe(false)
    expect(mdResumeButtonState({ execution_target: 'local', resumable: true }, 'connected').show).toBe(false)
  })
  it('shown+enabled only when connected', () => {
    const j = { execution_target: 'alpine', resumable: true }
    expect(mdResumeButtonState(j, 'connected')).toMatchObject({ show: true, disabled: false })
    const off = mdResumeButtonState(j, 'disconnected')
    expect(off.show).toBe(true)
    expect(off.disabled).toBe(true)
    expect(off.reason).toMatch(/Duo/)
  })
})

describe('mdResumeHistoryRows (expand-chevron content)', () => {
  it('formats newest-first with numbering', () => {
    const job = { resume_history: [
      { slurm_job_id: '100', state: 'TIMEOUT', segment_reached: 2, segments_total: 12, walltime: '1:00:00' },
      { slurm_job_id: '200', state: 'TIMEOUT', segment_reached: 5, segments_total: 12, walltime: '1:00:00' },
    ] }
    const rows = mdResumeHistoryRows(job)
    expect(rows).toHaveLength(2)
    expect(rows[0]).toContain('#2')            // newest first
    expect(rows[0]).toContain('SLURM 200')
    expect(rows[0]).toContain('seg 5/12')
    expect(rows[1]).toContain('#1')
  })
  it('empty for no history', () => {
    expect(mdResumeHistoryRows({})).toEqual([])
    expect(mdResumeHistoryRows(null)).toEqual([])
  })
})

import { mdIsRemoteQueued, mdQueueWaitLabel, fmtDurationShort } from './md_jobs_panel.js'

describe('mdIsRemoteQueued (SLURM PENDING, not running / not awaiting-submit)', () => {
  it('true for a submitted alpine job that is queued and not yet running', () => {
    expect(mdIsRemoteQueued({ execution_target: 'alpine', status: 'queued', slurm_job_id: '9', slurm_state: 'PENDING' })).toBe(true)
    expect(mdIsRemoteQueued({ execution_target: 'alpine', status: 'queued', slurm_job_id: '9' })).toBe(true)
  })
  it('false for awaiting-submit (no slurm id), running, or local', () => {
    expect(mdIsRemoteQueued({ execution_target: 'alpine', status: 'queued' })).toBe(false)          // no slurm id
    expect(mdIsRemoteQueued({ execution_target: 'alpine', status: 'queued', slurm_job_id: '9', slurm_state: 'RUNNING' })).toBe(false)
    expect(mdIsRemoteQueued({ execution_target: 'alpine', status: 'running', slurm_job_id: '9' })).toBe(false)
    expect(mdIsRemoteQueued({ execution_target: 'local', status: 'queued', slurm_job_id: '9' })).toBe(false)
  })
})

describe('fmtDurationShort', () => {
  it('formats seconds/minutes/hours compactly', () => {
    expect(fmtDurationShort(45)).toBe('45s')
    expect(fmtDurationShort(6 * 60)).toBe('6m')
    expect(fmtDurationShort(3 * 3600 + 4 * 60)).toBe('3h 4m')
    expect(fmtDurationShort(-5)).toBe('0s')
  })
})

describe('mdQueueWaitLabel', () => {
  it('reports elapsed time since queued_at', () => {
    const now = 1000000
    const job = { queued_at: now - 300 }        // 5 min ago
    expect(mdQueueWaitLabel(job, now * 1000)).toMatch(/Queued 5m ago/)
  })
  it('falls back when queued_at is missing', () => {
    expect(mdQueueWaitLabel({})).toMatch(/waiting for the cluster scheduler/)
  })
})

// ── U3 slice 2b — NAMD converges onto the canonical jobs-panel model+renderer ──
// The bright line: the unified card must emit the SAME payload the bespoke `_jobRow`
// produced. These pin the payload of mdJobRowCtx (the extracted, pure ctx factory) +
// its rendered DOM for every NAMD-specific row variant: the tree chevron, the
// collapsed-ensemble summary, the CG-seed / Alpine post-label badges, the ⧗
// remote-queued symbol override (with the live-refresh dataset), the "Fix" VRAM-OOM
// row action, and the out-of-date ⚠.
import { mdJobRowCtx } from './md_jobs_panel.js'
import { buildJobListModel, buildJobRowModel } from './jobs_panel_model.js'
import { renderJobList } from './jobs_panel_render.js'

describe('U3 slice 2b — NAMD canonical convergence (payload parity)', () => {
  // A relaxation parent with 2 Alpine ensemble replicas, plus a seeded root, a
  // remote-queued root, and a VRAM-failed + out-of-date root.
  const JOBS = [
    { job_id: 'p', status: 'completed', created_at: 100, design_name: 'origami' },
    { job_id: 'r1', status: 'running', created_at: 90, parent_job_id: 'p', design_name: 'origami',
      ensemble_seed: 7001, ensemble_index: 0, execution_target: 'alpine', slurm_job_id: '555', resources: { partition: 'amilan' } },
    { job_id: 'r2', status: 'queued', created_at: 89, parent_job_id: 'p', design_name: 'origami',
      ensemble_seed: 7002, ensemble_index: 1, execution_target: 'alpine' },
    { job_id: 'seed', status: 'completed', created_at: 80, design_name: 'from-cg', seed_oxdna_job_id: 'ox42' },
    { job_id: 'q', status: 'queued', created_at: 70, design_name: 'waiting', execution_target: 'alpine',
      slurm_job_id: '999', queued_at: 1000 },
    { job_id: 'boom', status: 'failed', created_at: 60, design_name: 'toobig',
      failure_kind: 'cuda_oom', out_of_date: true },
  ]
  const fmt = () => 't'
  const ctx = (over = {}) => mdJobRowCtx({
    jobs: JOBS, dimColor: '#8b949e', warnColor: '#e0a800', formatTime: fmt, ...over,
  })

  it('models the parent/child TREE with a chevron on the parent (collapsed → summary marker)', () => {
    const model = buildJobListModel(JOBS, ctx({ collapsedIds: new Set(['p']) }))
    const p = model.rows.find(r => r.jobId === 'p')
    expect(p.chevron).toEqual({ childCount: 2, collapsed: true, title: 'Expand 2 child jobs' })
    // Collapsed → the ensemble summary rides the leading post-label marker; children hidden.
    expect(p.postLabelMarkers[0].text).toMatch(/⧉ 2 replicas/)
    expect(model.rows.map(r => r.jobId)).not.toContain('r1')   // subtree hidden while collapsed
  })

  it('expands the parent and labels replica children (no summary when open)', () => {
    const model = buildJobListModel(JOBS, ctx())   // nothing collapsed
    const p = model.rows.find(r => r.jobId === 'p')
    expect(p.chevron).toEqual({ childCount: 2, collapsed: false, title: 'Collapse' })
    expect(p.postLabelMarkers).toEqual([])          // open → no aggregate summary
    const r1 = model.rows.find(r => r.jobId === 'r1')
    expect(r1.depth).toBe(1)
    expect(r1.indexLabel).toBe('')                  // children carry no list number
    expect(r1.label).toBe('Replica 1 · seed 7001')
    expect(r1.title).toBe('Ensemble production replica (independent seed)')
  })

  it('emits the CG-seed + Alpine post-label badges the bespoke row showed', () => {
    const model = buildJobListModel(JOBS, ctx())
    const seed = model.rows.find(r => r.jobId === 'seed')
    expect(seed.postLabelMarkers).toEqual([
      expect.objectContaining({ text: 'oxDNA seeded', title: 'Seeded from oxDNA job ox42' }),
    ])
    const r1 = model.rows.find(r => r.jobId === 'r1')
    expect(r1.postLabelMarkers).toEqual([
      expect.objectContaining({ text: 'SLURM 555 · amilan', title: 'Running on Alpine (SLURM 555)' }),
    ])
  })

  it('overrides the status symbol for a remote-queued job (⧗ + live-refresh dataset)', () => {
    const model = buildJobListModel(JOBS, ctx())
    const q = model.rows.find(r => r.jobId === 'q')
    expect(q.symbolOverride).toMatchObject({ glyph: '⧗', color: '#e0a800', dataset: { mdQueued: 'q' } })
    expect(q.symbolOverride.title).toMatch(/Queued/)
    // a non-queued job gets no override (falls through to spinner/badge)
    expect(model.rows.find(r => r.jobId === 'seed').symbolOverride).toBe(null)
  })

  it('offers the "Fix" row action only for a VRAM-OOM failure, and marks it out-of-date', () => {
    const model = buildJobListModel(JOBS, ctx())
    const boom = model.rows.find(r => r.jobId === 'boom')
    expect(boom.action).toMatchObject({ text: 'Fix' })
    expect(boom.stale).toBe(true)
    expect(model.rows.find(r => r.jobId === 'seed').action).toBe(null)
  })

  it('renders a wired "Fix" button whose click fires onAction (NOT row select)', () => {
    const el = document.createElement('div')
    const clicks = []
    const actions = []
    renderJobList(el, buildJobListModel(JOBS, ctx()), {
      onClick: (id) => clicks.push(id), onAction: (id) => actions.push(id),
      emptyText: 'none', dimColor: '#8b949e',
    })
    const boomRow = [...el.querySelectorAll('[data-job-id]')].find(r => r.dataset.jobId === 'boom')
    const fixBtn = boomRow.querySelector('button')
    expect(fixBtn.textContent).toBe('Fix')
    fixBtn.click()
    expect(actions).toEqual(['boom'])   // Fix action fired — guards the onAction wiring
    expect(clicks).toEqual([])          // stopPropagation → row select did NOT fire
  })

  it('renders the queued ⧗ symbol with the [data-md-queued] hook the poll-refresh selector needs', () => {
    const el = document.createElement('div')
    renderJobList(el, buildJobListModel(JOBS, ctx()), { onClick: () => {}, emptyText: 'none', dimColor: '#8b949e' })
    const hook = el.querySelector('[data-md-queued]')
    expect(hook).toBeTruthy()
    expect(hook.dataset.mdQueued).toBe('q')
    expect(hook.textContent).toBe('⧗')
  })

  it('renders a chevron whose click fires onChevron (tree toggle), NOT the row onClick', () => {
    const el = document.createElement('div')
    const clicks = []
    const chevrons = []
    renderJobList(el, buildJobListModel(JOBS, ctx()), {
      onClick: (id) => clicks.push(id), onChevron: (id) => chevrons.push(id),
      emptyText: 'none', dimColor: '#8b949e',
    })
    const pRow = [...el.querySelectorAll('[data-job-id]')].find(r => r.dataset.jobId === 'p')
    const chev = pRow.querySelector('span')   // leading-most span is the chevron
    expect(chev.textContent).toBe('▾')
    chev.click()
    expect(chevrons).toEqual(['p'])            // chevron toggled the tree
    expect(clicks).toEqual([])                 // stopPropagation → row select did NOT fire
  })

  it('a leaf row still gets an (empty) chevron span so indentation lines up', () => {
    const m = buildJobRowModel(JOBS[3], ctx(), { depth: 0, listIndex: 1, childCount: 0 })
    expect(m.chevron).toEqual({ childCount: 0, collapsed: false, title: '' })
  })
})

// ── U3 slice 2c-3b — shared jobs-panel base parity (section collapse + adv drawer) ──
// The 5th and final panel converges onto initJobsPanelBase. md accommodations:
// the SECTION arrow is the `is-collapsed` class idiom (arrowStyle:'class'); the
// ADVANCED drawer arrow is the CSS-transform idiom (advArrowStyle:'rotate'). Unlike
// oxDNA's slice, md's advanced drawer ALSO converges (its markup is a clean
// `display:none`, so the base's display-reading toggle opens on the first click
// exactly as md's old `_advOpen` boolean did — no flip hazard). md does NOT use the
// base's primary poll: live updates ride a WebSocket + `_remotePollTimer`
// (setInterval), torn down by the onClose hook. These PARITY assertions drive the
// REAL initMdJobsPanel and were run GREEN against the pre-rewire bespoke code first
// (git-stash rerun) → behaviour-preserving adapted-code pin, not green-by-construction.
import * as mdApi from '../api/client.js'
import { initMdJobsPanel } from './md_jobs_panel.js'
import { mountIds, clearDom } from '../test-helpers/factory_dom.js'

describe('initMdJobsPanel — shared jobs-panel base parity (U3 slice 2c-3b)', () => {
  const IDS = [
    'md-jobs-panel', 'md-jobs-panel-heading', 'md-jobs-panel-arrow', 'md-jobs-panel-body',
    'md-jobs-new-btn', 'md-jobs-run-btn',
  ]
  const $ = (id) => document.getElementById(id)
  const heading = () => $('md-jobs-panel-heading')
  const flushMicro = async (n = 12) => { for (let i = 0; i < n; i++) await Promise.resolve() }

  beforeEach(() => {
    clearDom(); mountIds(IDS); localStorage.clear()
    vi.clearAllMocks()
    // markup default: section body collapsed, arrow shows the is-collapsed class.
    $('md-jobs-panel-body').style.display = 'none'
    $('md-jobs-panel-arrow').classList.add('is-collapsed')
  })
  afterEach(() => { clearDom(); vi.useRealTimers() })

  it('starts OPEN regardless of markup/persisted collapse; the heading click is a no-op', async () => {
    // Seed a stale "collapsed" preference + collapsed markup — a non-collapsible
    // section must ignore both and force itself open.
    localStorage.setItem('nadoc.leftSidebar.sections.v1',
      JSON.stringify({ dynamics: { 'md-jobs-panel': true } }))
    mdApi.listMdJobs.mockResolvedValue([])
    initMdJobsPanel()
    await flushMicro()
    expect($('md-jobs-panel-body').style.display).not.toBe('none')     // forced open
    expect($('md-jobs-panel-arrow').classList.contains('is-collapsed')).toBe(false)

    heading().click(); await flushMicro()                              // no-op now
    expect($('md-jobs-panel-body').style.display).not.toBe('none')     // still open
  })

  it('wires NO advanced drawer — every job parameter moved into the Job Wizard', () => {
    // The drawer was a flat grid of ~17 controls that reflected none of the four layers
    // deciding a job's real settings, so the value on screen was frequently not the one
    // that ran. Pinned as an absence so it cannot quietly come back.
    mdApi.listMdJobs.mockResolvedValue([])
    initMdJobsPanel()
    expect($('md-jobs-adv-toggle')).toBeNull()
    expect($('md-jobs-adv-body')).toBeNull()
    expect($('md-jobs-new-btn')).not.toBeNull()
  })

  it('_onOpen fires on init (fetches the job list) and the remote SLURM poll runs while open', async () => {
    // A running Alpine job keeps the remote-poll setInterval firing _fetchJobs. The
    // section is always open now, so _onOpen fires on init and the poll keeps running
    // (the heading click no longer collapses / stops it).
    mdApi.listMdJobs.mockResolvedValue([{
      job_id: 'a1', execution_target: 'alpine', status: 'running',
      slurm_job_id: '999', created_at: 1,
    }])
    vi.useFakeTimers()
    initMdJobsPanel()                                                  // opens → _onOpen fetch + start remote poll
    await vi.advanceTimersByTimeAsync(0)
    const nOpen = mdApi.listMdJobs.mock.calls.length
    expect(nOpen).toBeGreaterThan(0)                                   // onOpen fetched on init

    await vi.advanceTimersByTimeAsync(20000)                           // one remote-poll tick
    const nPolled = mdApi.listMdJobs.mock.calls.length
    expect(nPolled).toBeGreaterThan(nOpen)                             // remote poll fired while open

    heading().click()                                                  // no-op → poll keeps running
    await vi.advanceTimersByTimeAsync(20000)
    expect(mdApi.listMdJobs.mock.calls.length).toBeGreaterThan(nPolled)
  })
})

// ── Three run targets: local | alpine | runpod ────────────────────────────────
// Most of this panel was written when there were only TWO targets, so `!== 'alpine'`
// was a safe synonym for "local". It is not any more: a RunPod job that tests
// `!== 'alpine'` gets classified as LOCAL and autostarted on the user's own desktop
// GPU. These pins exist so that regression is impossible to reintroduce silently.
describe('mdIsLocalTarget / mdIsRemoteJob', () => {
  it('treats only "local" (and missing) as local', () => {
    expect(mdIsLocalTarget('local')).toBe(true)
    expect(mdIsLocalTarget(undefined)).toBe(true)
    expect(mdIsLocalTarget(null)).toBe(true)
    expect(mdIsLocalTarget('alpine')).toBe(false)
    expect(mdIsLocalTarget('runpod')).toBe(false)
  })

  it('classifies a RunPod job as REMOTE, not local', () => {
    expect(mdIsRemoteJob({ execution_target: 'runpod' })).toBe(true)
    expect(mdIsRemoteJob({ execution_target: 'alpine' })).toBe(true)
    expect(mdIsRemoteJob({ execution_target: 'local' })).toBe(false)
    expect(mdIsRemoteJob({})).toBe(false)
  })

  it('a running RunPod job has no local readouts until results are fetched', () => {
    // Its metrics live on the pod; the health grid would spin forever otherwise.
    expect(mdHasLocalReadouts({ execution_target: 'runpod', health_samples: [] })).toBe(false)
    expect(mdHasLocalReadouts({ execution_target: 'runpod', health_samples: [{}] })).toBe(true)
    expect(mdHasLocalReadouts({ execution_target: 'local', health_samples: [] })).toBe(true)
  })
})

// ── "View trajectory" frame interval (DOM → handler → controller) ──────────────
// The pure arithmetic is pinned above; this drives the REAL panel to prove the three
// links that arithmetic alone can't: the readout is painted from the job's raw DCD
// counts, typing re-prices it without a fetch, and the number the user typed actually
// reaches loadTrajectory. (Controller → adapter → /md/ URL is pinned separately in
// md_viz_adapter.test.js and client_viz_opts.test.js.)
describe('initMdJobsPanel — trajectory frame interval', () => {
  const $ = (id) => document.getElementById(id)
  const flushMicro = async (n = 20) => { for (let i = 0; i < n; i++) await Promise.resolve() }
  const JOB = { job_id: 'J9', design_name: 'D', status: 'completed', created_at: 1, segments: [] }

  let viz
  const mountTrajDom = () => {
    mountIds({
      'md-jobs-panel': 'div', 'md-jobs-panel-heading': 'div', 'md-jobs-panel-arrow': 'div',
      'md-jobs-panel-body': 'div', 'md-jobs-list': 'div', 'md-jobs-detail': 'div',
      'md-jobs-traj-opts': 'div', 'md-jobs-traj-status': 'div', 'md-jobs-traj-controls': 'div',
      'md-jobs-traj-frames-hint': 'div', 'md-jobs-traj-slider': 'input',
      'md-jobs-traj-toggle': 'input', 'md-jobs-traj-interval': 'input',
    })
    $('md-jobs-traj-toggle').type = 'radio'
    const iv = $('md-jobs-traj-interval')
    iv.type = 'number'
    iv.value = '20'                       // index.html's `value=` attribute
  }

  beforeEach(async () => {
    clearDom(); mountTrajDom(); localStorage.clear(); vi.clearAllMocks()
    viz = {
      loadTrajectory: vi.fn(async () => ({ ok: true, n_frames: 50, markers: [], stages: [{}] })),
      mode: () => 'off', stopAndRestore: vi.fn(), showFrame: vi.fn(),
      trajectoryInfo: () => null,          // CG by default → nothing to prebuild
      prebuildHeavy: vi.fn(async () => ({ ok: true, n: 0 })),
    }
    mdApi.getSystemResources.mockResolvedValue({ ram_available_mb: 16_000, ram_total_mb: 32_000 })
    mdApi.listMdJobs.mockResolvedValue([JOB])
    mdApi.getMdJob.mockResolvedValue(JOB)
    // 3 segments, 100 raw frames each — interval 20 keeps 5 per segment.
    mdApi.getMdTrajectoryMeta.mockResolvedValue({
      ready: true, n_frames: 15, total_raw: 300,
      stages: [{ n_raw: 100 }, { n_raw: 100 }, { n_raw: 100 }],
    })
  })
  afterEach(() => { clearDom(); vi.useRealTimers() })

  const openWithJob = async () => {
    const panel = initMdJobsPanel({ getMdViz: () => viz })
    await flushMicro()
    await panel.selectJob('J9')
    await flushMicro()
    return panel
  }

  it('prices the readout from the RAW on-disk counts, not the downsampled ones', async () => {
    await openWithJob()
    // 3 x ceil(100/20) = 15 of the 300 frames actually written.
    expect($('md-jobs-traj-frames-hint').textContent).toMatch(/15 frames of 300 written/)
  })

  it('re-prices as the user types, without another network read', async () => {
    await openWithJob()
    const metaCalls = mdApi.getMdTrajectoryMeta.mock.calls.length
    const iv = $('md-jobs-traj-interval')
    iv.value = '5'
    iv.dispatchEvent(new Event('input'))
    expect($('md-jobs-traj-frames-hint').textContent).toMatch(/60 frames of 300 written/)
    expect(mdApi.getMdTrajectoryMeta.mock.calls.length).toBe(metaCalls)   // hint is pure arithmetic
  })

  it('sends the typed interval to loadTrajectory when the view is switched on', async () => {
    await openWithJob()
    const iv = $('md-jobs-traj-interval')
    iv.value = '7'
    iv.dispatchEvent(new Event('input'))
    const t = $('md-jobs-traj-toggle')
    t.checked = true
    t.dispatchEvent(new Event('change'))
    await flushMicro()
    expect(viz.loadTrajectory).toHaveBeenCalledWith('J9', true, 'lineage', 7)
  })

  it('falls back to the default interval when the field is emptied', async () => {
    await openWithJob()
    const iv = $('md-jobs-traj-interval')
    iv.value = ''
    const t = $('md-jobs-traj-toggle')
    t.checked = true
    t.dispatchEvent(new Event('change'))
    await flushMicro()
    expect(viz.loadTrajectory).toHaveBeenCalledWith('J9', true, 'lineage', DEFAULT_TRAJ_INTERVAL)
  })

  it('reloads at the new density when the interval is committed while displaying', async () => {
    await openWithJob()
    const t = $('md-jobs-traj-toggle')
    t.checked = true
    t.dispatchEvent(new Event('change'))
    await flushMicro()
    viz.loadTrajectory.mockClear()

    const iv = $('md-jobs-traj-interval')
    iv.value = '4'
    iv.dispatchEvent(new Event('change'))
    await flushMicro()
    expect(viz.loadTrajectory).toHaveBeenCalledWith('J9', true, 'lineage', 4)
  })

  it('does NOT reload on a committed interval while the view is off', async () => {
    await openWithJob()
    viz.loadTrajectory.mockClear()
    const iv = $('md-jobs-traj-interval')
    iv.value = '4'
    iv.dispatchEvent(new Event('change'))
    await flushMicro()
    expect(viz.loadTrajectory).not.toHaveBeenCalled()
  })

  it('warns when the all-atom prebuild would not fit this machine\'s free RAM', async () => {
    // The whole point of reading host memory: a big origami's atomistic trajectory can
    // exceed what is actually free, and finding that out by exhausting it is not a plan.
    mdApi.getSystemResources.mockResolvedValue({ ram_available_mb: 512, ram_total_mb: 8192 })
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    viz.trajectoryInfo = () => ({ frame: 1, total: 991, atomSerials: 469_350, nNucleotides: 14_774 })
    viz.prebuildHeavy = vi.fn(async () => ({ ok: true, n: 1, frames: 1, trajFrames: 991 }))
    await openWithJob()
    const t = $('md-jobs-traj-toggle')
    t.checked = true
    t.dispatchEvent(new Event('change'))
    await flushMicro(40)
    expect(confirm).toHaveBeenCalled()
    const msg = confirm.mock.calls.at(-1)[0]
    // Must be the MEMORY warning, not the frame-count one — they are different gates and
    // this test would pass on the wrong one if it only checked that *a* confirm fired.
    expect(msg).toMatch(/free on this machine/i)
    expect(msg, 'quotes what it needs and what is free').toMatch(/GB|MB/)
    expect(viz.prebuildHeavy, 'declining must not start the build').not.toHaveBeenCalled()
    confirm.mockRestore()
  })

  it('does not warn about memory when the prebuild comfortably fits', async () => {
    mdApi.getSystemResources.mockResolvedValue({ ram_available_mb: 32_000, ram_total_mb: 64_000 })
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    viz.trajectoryInfo = () => ({ frame: 1, total: 20, atomSerials: 20_000, nNucleotides: 600 })
    viz.prebuildHeavy = vi.fn(async () => ({ ok: true, n: 20, frames: 20, trajFrames: 20 }))
    await openWithJob()
    const t = $('md-jobs-traj-toggle')
    t.checked = true
    t.dispatchEvent(new Event('change'))
    await flushMicro(40)
    expect(confirm).not.toHaveBeenCalled()
    expect(viz.prebuildHeavy).toHaveBeenCalled()
    confirm.mockRestore()
  })

  it('asks before a load big enough to hurt, and abandons it on cancel', async () => {
    // 300 raw frames at interval 1 = 300 frames… still under the threshold, so push the
    // job's size up instead of weakening the guard.
    mdApi.getMdTrajectoryMeta.mockResolvedValue({
      ready: true, n_frames: 200, total_raw: 20_000, stages: [{ n_raw: 20_000 }],
    })
    await openWithJob()
    const iv = $('md-jobs-traj-interval')
    iv.value = '1'
    iv.dispatchEvent(new Event('input'))
    expect(stridedFrameCount([20_000], 1)).toBeGreaterThanOrEqual(TRAJ_FRAME_CONFIRM)

    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    const t = $('md-jobs-traj-toggle')
    t.checked = true
    t.dispatchEvent(new Event('change'))
    await flushMicro()
    expect(confirm).toHaveBeenCalled()
    expect(viz.loadTrajectory).not.toHaveBeenCalled()
    expect(t.checked, 'a cancelled load must leave the radio off').toBe(false)

    confirm.mockReturnValue(true)                     // …and proceeds when accepted
    t.checked = true
    t.dispatchEvent(new Event('change'))
    await flushMicro()
    expect(viz.loadTrajectory).toHaveBeenCalledWith('J9', true, 'lineage', 1)
    confirm.mockRestore()
  })

  it('does not ask for an ordinary load', async () => {
    await openWithJob()
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    const t = $('md-jobs-traj-toggle')
    t.checked = true
    t.dispatchEvent(new Event('change'))
    await flushMicro()
    expect(confirm).not.toHaveBeenCalled()
    confirm.mockRestore()
  })

  // ── Click-the-selected-row-to-deselect ────────────────────────────────────
  // Deselecting is not a job switch: the loaded trajectory (and the live display) stay
  // exactly as they are. It also has to STICK — `_selectBestJob` runs on every poll and
  // would otherwise re-select the job a beat later.
  // The shared `openWithJob` selects programmatically; a row CLICK needs the job to
  // survive the per-part list filter, so give it a design path and a matching workspace.
  const PART = '/w/D.nadoc'
  const openWithRow = async () => {
    const job = { ...JOB, design_source_path: PART }
    mdApi.listMdJobs.mockResolvedValue([job])
    mdApi.getMdJob.mockResolvedValue(job)
    // `_selectBestJob` auto-selects the only job on the first fetch — no click needed.
    const panel = initMdJobsPanel({ getMdViz: () => viz, getWorkspacePath: () => PART })
    await flushMicro()
    return panel
  }
  const clickRow = () => $('md-jobs-list').querySelector('[data-job-id="J9"]').click()

  it('clicking the selected row deselects it WITHOUT unloading the trajectory', async () => {
    const panel = await openWithRow()
    expect(panel.getSelectedJob()?.job_id).toBe('J9')
    const t = $('md-jobs-traj-toggle')
    t.checked = true
    t.dispatchEvent(new Event('change'))
    await flushMicro()
    expect(viz.loadTrajectory).toHaveBeenCalled()
    viz.mode = () => 'trajectory'
    viz.stopAndRestore.mockClear()

    clickRow()                                                   // second click, same row
    await flushMicro()
    expect(panel.getSelectedJob()).toBe(null)                    // deselected
    expect($('md-jobs-detail').style.display).toBe('none')       // detail cleared
    expect(viz.stopAndRestore).not.toHaveBeenCalled()            // …frames kept
    expect(t.checked).toBe(true)
  })

  it('the poll does not re-select after a deliberate deselect (until the user picks again)', async () => {
    const panel = await openWithRow()
    clickRow()
    await flushMicro()
    expect(panel.getSelectedJob()).toBe(null)

    await panel.refresh()      // a poll tick → _selectBestJob
    await flushMicro()
    expect(panel.getSelectedJob()).toBe(null)   // still deselected (the sticky flag)

    clickRow()
    await flushMicro()
    expect(panel.getSelectedJob()?.job_id).toBe('J9')            // an explicit pick wins again
  })
})

// ── Stage timeline: the minimisation row (DOM → real panel) ────────────────────
// The pure derivation is pinned in md_stage_timeline.test.js; this drives the REAL
// panel to prove the row is actually painted, leads the ladder, and carries the same
// spinner/✓ glyphs a segment does — the "is it running / did it finish" signal the
// timeline previously had no way to show for the step before segment 1.
describe('initMdJobsPanel — minimisation timeline row', () => {
  const $ = (id) => document.getElementById(id)
  const flushMicro = async (n = 20) => { for (let i = 0; i < n; i++) await Promise.resolve() }

  const MIN = { name: 'D_00_min_enm_k0p5', stage: 'Minimization ENM k=0.5', percent: 100,
                steps: 9600, status: 'running', skipped: false }
  const LADDER = [
    { name: 'D_0S_settle', stage: '300K NPT settle (DNA fixed)', percent: 100, steps: 100, status: 'pending' },
    { name: 'D_01_k0p5_p10', stage: '300K NPT ENM k=0.5', percent: 10, steps: 100, status: 'pending' },
  ]
  const jobWith = (over) => ({ job_id: 'J1', design_name: 'D', created_at: 1, status: 'running',
                               segments: LADDER, health_samples: [], ...over })

  beforeEach(async () => {
    clearDom()
    mountIds({
      'md-jobs-panel': 'div', 'md-jobs-panel-heading': 'div', 'md-jobs-panel-arrow': 'div',
      'md-jobs-panel-body': 'div', 'md-jobs-list': 'div', 'md-jobs-detail': 'div',
      'md-jobs-timeline': 'div',
    })
    localStorage.clear(); vi.clearAllMocks()
    mdApi.getSystemResources.mockResolvedValue({ ram_available_mb: 16_000, ram_total_mb: 32_000 })
  })
  afterEach(() => { clearDom() })

  const openWith = async (job) => {
    mdApi.listMdJobs.mockResolvedValue([job])
    mdApi.getMdJob.mockResolvedValue(job)
    const panel = initMdJobsPanel({ getMdViz: () => null })
    await flushMicro()
    await panel.selectJob('J1')
    await flushMicro()
    return $('md-jobs-timeline')
  }

  it('leads the timeline, ahead of the settle stage', async () => {
    const el = await openWith(jobWith({ minimization: MIN }))
    const labels = [...el.children].map(r => r.firstChild.textContent)
    expect(labels[0]).toBe('Minimization ENM k=0.5')
    expect(labels[1]).toBe('300K NPT settle (DNA fixed)')
  })

  it('spins while it runs and shows ✓ once done', async () => {
    const running = await openWith(jobWith({ minimization: MIN }))
    // A running stage gets a spinner instead of the ✓/✗ glyph span.
    expect(running.children[0].textContent).not.toMatch(/[✓✗]/)

    const done = await openWith(jobWith({
      minimization: { ...MIN, status: 'done' },
      segments: [{ ...LADDER[0], status: 'running' }, LADDER[1]],
    }))
    expect(done.children[0].textContent).toMatch(/✓/)
  })

  it('is omitted for a job prepared before the backend recorded it', async () => {
    const el = await openWith(jobWith({}))
    expect([...el.children].map(r => r.firstChild.textContent))
      .toEqual(['300K NPT settle (DNA fixed)', '300K NPT ENM k=0.5'])
  })
})

// ── The Health card must never spin on data that is not coming ────────────────
// The reported bug, end to end: on a local production run Temp/Pressure/Speed filled
// in (the WebSocket parses the NAMD log itself) while Base pairs / WC health / Latest /
// Broken bp / Shell charge spun forever — the runner's health probe was disabled by an
// orphaning dev-server reload and nothing on screen could say so. The renderer turned
// ANY missing value on an active job into a spinner, so "not coming" looked identical
// to "arriving shortly". These drive the REAL panel and count actual spinner nodes.
describe('initMdJobsPanel — Health card tile states', () => {
  const $ = (id) => document.getElementById(id)
  const flushMicro = async (n = 20) => { for (let i = 0; i < n; i++) await Promise.resolve() }
  const spinners = () => $('md-jobs-metrics').querySelectorAll('.nadoc-spinner').length
  const tiles = () => [...$('md-jobs-metrics').children]
      .map(c => [c.children[0]?.textContent, c.children[1]?.textContent])

  const PRODUCTION = {
    job_id: 'P1', design_name: 'D', created_at: 1, status: 'running',
    execution_target: 'local', run_kind: 'production', current_segment_idx: 0,
    segments: [{ name: 'p_01_prod', stage: '310K NPT conservative production 500 ns',
                 percent: 100, steps: 1000, status: 'running', skipped: false }],
    health_samples: [],
    // Exactly what the WS pushes while the runner samples nothing.
    live_metrics: { temperature_k: 310.4, pressure_avg_bar: 1.2, ns_per_day: 44.1 },
  }

  beforeEach(async () => {
    clearDom()
    mountIds({
      'md-jobs-panel': 'div', 'md-jobs-panel-heading': 'div', 'md-jobs-panel-arrow': 'div',
      'md-jobs-panel-body': 'div', 'md-jobs-list': 'div', 'md-jobs-detail': 'div',
      'md-jobs-timeline': 'div', 'md-jobs-metrics': 'div',
    })
    localStorage.clear(); vi.clearAllMocks()
    mdApi.getSystemResources.mockResolvedValue({ ram_available_mb: 16_000, ram_total_mb: 32_000 })
    mdApi.getMdJobMetrics.mockResolvedValue([])
  })
  afterEach(() => { clearDom() })

  const openWith = async (job) => {
    mdApi.listMdJobs.mockResolvedValue([job])
    mdApi.getMdJob.mockResolvedValue(job)
    const panel = initMdJobsPanel({ getMdViz: () => null })
    await flushMicro()
    await panel.selectJob(job.job_id)
    await flushMicro()
    return $('md-jobs-metrics')
  }

  it('THE BUG: a probe that will never run paints dashes, not endless spinners', async () => {
    await openWith({
      ...PRODUCTION,
      health_probe: { enabled: false, reason: 'adopted after an orchestrator restart',
                      interval_s: 300, last_at: null, last_error: null },
    })
    expect(spinners()).toBe(0)
    const byLabel = Object.fromEntries(tiles())
    expect(byLabel['Temp']).toMatch(/310/)          // log-derived tiles still populate
    expect(byLabel['Speed']).toMatch(/44/)
    expect(byLabel['Base pairs']).toBe('—')         // and the rest say "no", not "wait"
    expect(byLabel['WC health']).toBe('—')
    expect(byLabel['Broken bp']).toBe('—')
    expect(byLabel['Shell charge']).toBe('—')
    // "Latest" is derived from the running segment, so it is never unknown mid-run.
    expect(byLabel['Latest']).toBe('500 ns production run')
  })

  it('an absent tile carries a tooltip explaining WHY it is absent', async () => {
    const el = await openWith({
      ...PRODUCTION,
      health_probe: { enabled: false, reason: 'adopted after an orchestrator restart',
                      interval_s: 300, last_at: null, last_error: null },
    })
    const bp = [...el.children].find(c => c.children[0].textContent === 'Base pairs')
    expect(bp.title).toMatch(/adopted after an orchestrator restart/)
  })

  it('an OLD sample missing the per-frame fields does not spin them', async () => {
    // Samples written before `diagnostics` existed reload as diagnostics: null. Those
    // two tiles were the ones that spun for entire production runs.
    await openWith({
      ...PRODUCTION,
      health_probe: { enabled: true, interval_s: 300, last_at: Date.now() / 1000,
                      last_error: null, reason: null },
      health_samples: [{
        wall_time: 1, stage: '310K NPT conservative production 500 ns', segment: 'p_01_prod',
        c1_paired_fraction: 0.95, wc_ref_relative_fraction: 0.88, passed: true,
        broken_bp_count: null, charge_within_shell_e: null, diagnostics: null,
      }],
    })
    expect(spinners()).toBe(0)
    const byLabel = Object.fromEntries(tiles())
    expect(byLabel['Base pairs']).toMatch(/95/)
    expect(byLabel['Broken bp']).toBe('—')
    expect(byLabel['Shell charge']).toBe('—')
  })

  it('a fresh run with a live probe DOES spin the tiles that are genuinely coming', async () => {
    // The spinner is not banned — it is restricted to values actually in flight.
    await openWith({
      ...PRODUCTION,
      created_at: Date.now() / 1000 - 5,
      health_probe: { enabled: true, interval_s: 300, last_at: null, last_error: null,
                      reason: 'waiting for the first trajectory frames' },
    })
    expect(spinners()).toBeGreaterThan(0)
  })

  it('a terminal job never spins, whatever is missing', async () => {
    await openWith({ ...PRODUCTION, status: 'completed', live_metrics: null })
    expect(spinners()).toBe(0)
  })

  it('a full sample renders every tile with no spinner', async () => {
    await openWith({
      ...PRODUCTION,
      health_probe: { enabled: true, interval_s: 300, last_at: Date.now() / 1000,
                      last_error: null, reason: null },
      health_samples: [{
        wall_time: 1, stage: '310K NPT conservative production 500 ns', segment: 'p_01_prod',
        c1_paired_fraction: 0.96, wc_ref_relative_fraction: 0.91, passed: true,
        broken_bp_count: 0, charge_within_shell_e: -244, diagnostics: 'ok',
      }],
    })
    expect(spinners()).toBe(0)
    const byLabel = Object.fromEntries(tiles())
    expect(byLabel['Broken bp']).toBe('0')      // zero is a reading, not an absence
    expect(byLabel['Shell charge']).toMatch(/-244/)
  })
})

describe('mdHasProductionRun — occupancy is only offered for production dynamics', () => {
  const seg = (stage, status = 'done') => ({ stage, status, name: stage })

  it('rejects the terminal unrestrained equilibration stage', () => {
    // "300K NPT k=0" ends the ENM ladder. It is unrestrained, but it is still
    // equilibration — not a production run.
    expect(mdHasProductionRun({ segments: [seg('300K NPT ENM k=0.5'), seg('300K NPT k=0')] }))
      .toBe(false)
  })

  it('rejects a restraint ramp that encodes k in the label', () => {
    // The real killer: these carry no enm/fixed/minim keyword at all, so a
    // keyword-EXCLUSION filter admitted every one of them.
    for (const l of ['50K NVT k=5.0', '310K NPT k=5.0', '310K NPT k=0.01',
                     'Vacuum ENRG-MD shape relaxation',
                     'solvent equilibration (DNA position-restrained, NVT)',
                     '310K NPT unrestrained qualification']) {
      expect(mdHasProductionRun({ segments: [seg(l)] }), l).toBe(false)
    }
  })

  it('rejects a job that never left the ENM restraint ramp', () => {
    expect(mdHasProductionRun({
      segments: [seg('300K NPT ENM k=0.5'), seg('300K NPT ENM k=0.1'), seg('300K NPT ENM k=0.01')],
    })).toBe(false)
  })

  it('rejects the DNA-fixed settle stage and minimisation', () => {
    expect(mdHasProductionRun({ segments: [seg('300K NPT settle (DNA fixed)')] })).toBe(false)
    expect(mdHasProductionRun({ segments: [seg('Minimization ENM k=0.5')] })).toBe(false)
  })

  it('requires the production stage to have actually written frames', () => {
    // Queued is not sampling — offering occupancy there would fetch nothing.
    expect(mdHasProductionRun({ segments: [seg('5 ns production run', 'pending')] })).toBe(false)
    expect(mdHasProductionRun({ segments: [seg('5 ns production run', 'running')] })).toBe(true)
  })

  it('is false for a job with no segments at all', () => {
    expect(mdHasProductionRun({ segments: [] })).toBe(false)
    expect(mdHasProductionRun(null)).toBe(false)
  })

  it('falls back to the segment name when no stage label is present', () => {
    expect(mdHasProductionRun({ segments: [{ name: 'x_seq02_production_k0_p10', status: 'done' }] }))
      .toBe(true)
    expect(mdHasProductionRun({ segments: [{ name: 'x_01_300K_NPT_ENM_k0p5_p10', status: 'done' }] }))
      .toBe(false)
  })

  it('accepts every label a production builder emits', () => {
    for (const l of ['50 ns fast production run',
                     '2 ns production replica (seed 54321)',
                     '310K NPT conservative production 0.5 ns unrestrained',
                     'shell NVT production (COM-restrained, HMR 4 fs)']) {
      expect(mdHasProductionRun({ segments: [seg(l)] }), l).toBe(true)
    }
    expect(mdHasProductionRun({
      segments: [seg('300K NPT ENM k=0.5'), seg('120 ns conservative production run')],
    })).toBe(true)
  })

  it('uses the same marker as the backend, so the UI and the analysis agree', () => {
    expect(MD_PRODUCTION_MARKER).toBe('production')
  })
})

// ── anchor granularity + stiffness (the Hold-atoms / Stiffness selects) ────────
// These feed BOTH launch paths. Production previously read neither — the anchors card
// was wired only to the relax create payload, so picking anchors and clicking Production
// silently discarded them.
describe('mdAnchorAtomNames', () => {
  it('maps the All-heavy-atoms option to null, not an empty list', () => {
    // [] would ask the backend to anchor NOTHING; null is its "no filter" sentinel.
    expect(mdAnchorAtomNames('')).toBeNull()
    expect(mdAnchorAtomNames(null)).toBeNull()
    expect(mdAnchorAtomNames(undefined)).toBeNull()
  })

  it('splits a comma-separated atom-name list and trims it', () => {
    expect(mdAnchorAtomNames("C1'")).toEqual(["C1'"])
    expect(mdAnchorAtomNames("P,C1'")).toEqual(['P', "C1'"])
    expect(mdAnchorAtomNames(" P , C1' ")).toEqual(['P', "C1'"])
  })

  it('ignores empty entries rather than emitting a blank atom name', () => {
    expect(mdAnchorAtomNames('P,,')).toEqual(['P'])
    expect(mdAnchorAtomNames(',')).toBeNull()
  })
})

describe('mdAnchorStiffness', () => {
  it('maps the Hard-pin option to null (NAMD fixedAtoms)', () => {
    expect(mdAnchorStiffness('')).toBeNull()
    expect(mdAnchorStiffness(null)).toBeNull()
  })

  it('passes a positive force constant through as a number', () => {
    expect(mdAnchorStiffness('0.02')).toBe(0.02)
    expect(mdAnchorStiffness('1')).toBe(1)
  })

  it('treats zero and nonsense as a hard pin, never a zero-strength restraint', () => {
    // k=0 would emit a conskfile that restrains nothing while the run reports itself
    // anchored — the exact silent-no-op class of bug this whole change removes.
    expect(mdAnchorStiffness('0')).toBeNull()
    expect(mdAnchorStiffness('-1')).toBeNull()
    expect(mdAnchorStiffness('abc')).toBeNull()
  })
})
