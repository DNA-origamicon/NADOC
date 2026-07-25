import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { normalizeWorkspacePath, filterJobsForPart, newestCompletedForPart, seededBadge, mdSegGlyphKind,
  mdIsLocalTarget,
  mdIsRemoteJob,
  productionNsFromSteps,
  jobProductionTimestepFs,
  DEFAULT_PRODUCTION_TIMESTEP_FS,
} from './md_jobs_panel.js'

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

import { mdJobIsActive, mdRunControl, mdSelectedJobControl, mdRemoteAwaitingSubmit, makeSpinner, mdHasMetrics, mdListSignature, mdChildRowLabel, hasActiveRemoteJob, mdWatchdogDecision, mdProductionAction, mdRemoteReconnectPrompt, mdJobIsDraft, mdDraftRunLabel, mdJobRowSig, mdJobRowCtx, gpuFallbackFromToggle } from './md_jobs_panel.js'

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

describe('mdRunControl (primary ▶ Relax — DECOUPLED: always a fresh launch, never Stop/Resume/disabled)', () => {
  it('nothing selected → ▶ Relax (launch)', () => {
    const rc = mdRunControl(null)
    expect(rc.action).toBe('run')
    expect(rc.label).toBe('▶ Relax')
  })
  it('ALWAYS ▶ Relax regardless of the selected job — the decouple (an auto-selected past job can no longer change/disable it)', () => {
    for (const job of [
      { status: 'completed', execution_target: 'local' },
      { status: 'running', execution_target: 'local' },
      { status: 'stopped', execution_target: 'local' },
      { status: 'failed', execution_target: 'local' },
      { status: 'completed', run_kind: 'production', execution_target: 'local' },   // ← 6hbx100_90deg case: used to be DISABLED
      { status: 'running', run_kind: 'production', execution_target: 'local' },
      { status: 'queued', execution_target: 'runpod' },                              // ← runpod hijack: used to be ■ Stop
      { status: 'running', execution_target: 'alpine', slurm_job_id: '9' },
    ]) {
      const rc = mdRunControl(job)
      expect(rc.action, JSON.stringify(job)).toBe('run')
      expect(rc.label, JSON.stringify(job)).toBe('▶ Relax')
      expect(rc.disabled, JSON.stringify(job)).toBeFalsy()
    }
  })
  it('busy (a launch already in flight) → disabled', () => {
    expect(mdRunControl(null, { busy: true }).disabled).toBe(true)
  })
  it('run-target Alpine relabels the fresh launch → "▶ Prepare for Alpine" (it only preps+queues)', () => {
    expect(mdRunControl(null, { runTarget: 'alpine' }).label).toBe('▶ Prepare for Alpine')
    expect(mdRunControl({ status: 'completed' }, { runTarget: 'alpine' }).label).toBe('▶ Prepare for Alpine')
    expect(mdRunControl(null, { runTarget: 'local' }).label).toBe('▶ Relax')
  })
})

describe('mdSelectedJobControl (contextual Stop/Resume for the SELECTED job — where Stop/Resume moved)', () => {
  it('nothing selected → hidden', () => {
    expect(mdSelectedJobControl(null).show).toBe(false)
  })
  it('a running/preparing local job → ■ Stop', () => {
    expect(mdSelectedJobControl({ status: 'running', execution_target: 'local' })).toMatchObject({ show: true, action: 'stop' })
    expect(mdSelectedJobControl({ status: 'preparing', execution_target: 'local' })).toMatchObject({ show: true, action: 'stop' })
  })
  it('a stopped/failed LOCAL job → ↻ Resume', () => {
    expect(mdSelectedJobControl({ status: 'stopped', execution_target: 'local' })).toMatchObject({ show: true, action: 'resume' })
    expect(mdSelectedJobControl({ status: 'failed', execution_target: 'local' })).toMatchObject({ show: true, action: 'resume' })
  })
  it('a completed job → hidden (use the always-fresh Relax for a new run)', () => {
    expect(mdSelectedJobControl({ status: 'completed', execution_target: 'local' }).show).toBe(false)
  })
  it('a PRODUCTION child → hidden here (the Production button drives its lifecycle)', () => {
    expect(mdSelectedJobControl({ status: 'running', run_kind: 'production' }).show).toBe(false)
    expect(mdSelectedJobControl({ status: 'stopped', run_kind: 'production' }).show).toBe(false)
  })
  it('a stopped ALPINE job → hidden here (its resume is the cluster-gated button)', () => {
    expect(mdSelectedJobControl({ status: 'stopped', execution_target: 'alpine' }).show).toBe(false)
  })
  it('a job PAUSED on a GPU-resident decision → ↻ Resume (re-opens the gate)', () => {
    const job = { status: 'paused', execution_target: 'local', decision: { gate: 'gpu_resident' } }
    expect(mdSelectedJobControl(job)).toMatchObject({ show: true, action: 'resume' })
    expect(mdSelectedJobControl(job).title).toMatch(/fastest GPU mode/i)
    // a plain paused job with no decision stays hidden here
    expect(mdSelectedJobControl({ status: 'paused', execution_target: 'local' }).show).toBe(false)
  })
  it('an in-flight Alpine job (SLURM id) → ■ Stop (scancel)', () => {
    expect(mdSelectedJobControl({ status: 'running', execution_target: 'alpine', slurm_job_id: '9' })).toMatchObject({ show: true, action: 'stop' })
  })
  it('a never-launched RunPod queued job → hidden (awaiting submit, not active)', () => {
    expect(mdSelectedJobControl({ status: 'queued', execution_target: 'runpod' }).show).toBe(false)
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

describe('mdProductionAction (what the Production button does)', () => {
  it('running/preparing production child → stop', () => {
    expect(mdProductionAction({ status: 'running', run_kind: 'production', execution_target: 'local' })).toBe('stop')
    expect(mdProductionAction({ status: 'preparing', run_kind: 'production', execution_target: 'local' })).toBe('stop')
  })
  it('stopped/failed production child → resume', () => {
    expect(mdProductionAction({ status: 'stopped', run_kind: 'production' })).toBe('resume')
    expect(mdProductionAction({ status: 'failed', run_kind: 'production' })).toBe('resume')
  })
  it('a relaxation root, or a completed production child → start (spawn/chain a new production)', () => {
    expect(mdProductionAction({ status: 'completed' })).toBe('start')                       // relaxation
    expect(mdProductionAction({ status: 'running', execution_target: 'local' })).toBe('start')  // relaxation running
    expect(mdProductionAction({ status: 'completed', run_kind: 'production' })).toBe('start')  // chain off a finished production
    expect(mdProductionAction(null)).toBe('start')
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
    'md-jobs-adv-toggle', 'md-jobs-adv-arrow', 'md-jobs-adv-body',
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
    // markup default: advanced drawer body hidden, arrow un-rotated.
    $('md-jobs-adv-body').style.display = 'none'
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

  it('the advanced drawer toggles its body + a `rotate(90deg)` arrow (first click opens)', async () => {
    mdApi.listMdJobs.mockResolvedValue([])
    initMdJobsPanel()
    await flushMicro()
    const advBody = $('md-jobs-adv-body'), advArrow = $('md-jobs-adv-arrow')
    expect(advBody.style.display).toBe('none')                         // starts hidden

    $('md-jobs-adv-toggle').click()                                    // first click → open
    expect(advBody.style.display).not.toBe('none')
    expect(advArrow.style.transform).toBe('rotate(90deg)')

    $('md-jobs-adv-toggle').click()                                    // close
    expect(advBody.style.display).toBe('none')
    expect(advArrow.style.transform).toBe('')
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
