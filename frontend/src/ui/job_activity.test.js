import { describe, it, expect } from 'vitest'
import {
  normPath,
  formatEta,
  jobDesignName,
  activeJobForPath,
  jobActivityTooltip,
  pickBlockingJob,
  isLocalJob,
  isGpuJob,
  runningEngines,
  runningEngineForPath,
  diskWarningMessage,
  bigRunSummary,
  BIG_RUN_BYTES,
  BIG_RUN_HOURS,
  isUndersizedCellRefusal,
} from './job_activity.js'

const GiB = 1024 ** 3

describe('diskWarningMessage', () => {
  it('returns null when the forecast does not warn', () => {
    expect(diskWarningMessage(null)).toBeNull()
    expect(diskWarningMessage({ warn: false })).toBeNull()
    expect(diskWarningMessage(undefined)).toBeNull()
  })

  it('warns with sizes when finishing would leave little free space', () => {
    const msg = diskWarningMessage({
      warn: true,
      free_bytes: 12 * GiB,
      predicted_bytes: 9 * GiB,
      free_after_bytes: 3 * GiB,
    })
    expect(msg).toContain('9 GB')      // predicted
    expect(msg).toContain('12 GB')     // free now
    expect(msg).toContain('3 GB')      // free after
    expect(msg).toContain('leave only')
  })

  it('flags an outright overflow when the run needs more than is free', () => {
    const msg = diskWarningMessage({
      warn: true,
      free_bytes: 4 * GiB,
      predicted_bytes: 10 * GiB,
      free_after_bytes: -6 * GiB,
    })
    expect(msg).toContain('OUT of disk')
    expect(msg).toContain('6 GB')      // shortfall
  })

  it('names the volume it measured when the forecast reports one', () => {
    const msg = diskWarningMessage({
      warn: true,
      free_bytes: 12 * GiB,
      predicted_bytes: 9 * GiB,
      free_after_bytes: 3 * GiB,
      volume: '/media/jojo/Archive',
    })
    // A job archived to an external drive is forecast against THAT drive; without
    // naming it "you have 12 GB free" could be read as the system disk.
    expect(msg).toContain('/media/jojo/Archive')
  })
})

describe('bigRunSummary', () => {
  // The 1 us 2hb_1xT production run from the bug report: ~80 GB over ~17 days,
  // onto a 5.8 TB archive drive that raises no low-space warning at all.
  const MICROSECOND_RUN = {
    warn: false,
    predicted_bytes: 80 * GiB,
    free_bytes: 5800 * GiB,
    free_after_bytes: 5720 * GiB,
    volume: '/media/jojo/Archive',
    length_ns: 1000,
    est_hours: 407,
    est_ns_per_day: 59,
  }

  it('returns null for a run that is neither big nor long', () => {
    expect(bigRunSummary(null)).toBeNull()
    expect(bigRunSummary(undefined)).toBeNull()
    expect(bigRunSummary({ predicted_bytes: 1 * GiB, est_hours: 2 })).toBeNull()
  })

  it('fires on a huge run even when the disk has ample room', () => {
    // The whole point: warn === false, so diskWarningMessage stays silent here.
    expect(diskWarningMessage(MICROSECOND_RUN)).toBeNull()
    const s = bigRunSummary(MICROSECOND_RUN)
    expect(s).not.toBeNull()
    expect(s.message).toContain('80 GB')                 // what it will write
    expect(s.message).toContain('/media/jojo/Archive')   // onto which drive
    expect(s.message).toContain('1,000 ns')              // simulated time
    expect(s.message).toContain('days')                  // wall-clock, not "407 h"
    expect(s.message).toContain('59 ns/day')             // the rate behind it
  })

  it('fires on size alone when the run is quick', () => {
    const s = bigRunSummary({ predicted_bytes: BIG_RUN_BYTES + 1, est_hours: 1 })
    expect(s).not.toBeNull()
    expect(s.bytes).toBe(BIG_RUN_BYTES + 1)
  })

  it('fires on duration alone when the run is small', () => {
    const s = bigRunSummary({ predicted_bytes: 1024, est_hours: BIG_RUN_HOURS + 1 })
    expect(s).not.toBeNull()
    expect(s.hours).toBe(BIG_RUN_HOURS + 1)
  })

  it('does not fire exactly at the thresholds', () => {
    expect(bigRunSummary({ predicted_bytes: BIG_RUN_BYTES, est_hours: BIG_RUN_HOURS })).toBeNull()
  })

  it('still reports size when the backend could not estimate a duration', () => {
    // est_hours is null whenever the atom count is unknown — that must not
    // suppress the size half of the warning.
    const s = bigRunSummary({ predicted_bytes: 50 * GiB, est_hours: null, free_bytes: 100 * GiB })
    expect(s).not.toBeNull()
    expect(s.hours).toBeNull()
    expect(s.message).toContain('50 GB')
    expect(s.message).not.toContain('Estimated wall-clock')
  })

  it('formats short durations in hours and long ones in days', () => {
    expect(bigRunSummary({ predicted_bytes: 20 * GiB, est_hours: 30 }).message)
      .toContain('30 h')
    expect(bigRunSummary({ predicted_bytes: 20 * GiB, est_hours: 96 }).message)
      .toContain('4.0 days')
  })
})

describe('isUndersizedCellRefusal', () => {
  // Verbatim tail of routes_md._assert_cell_fits_a_free_run's 400 detail.
  const REFUSAL =
    "This package's cell is too small for a 1000 ns unrestrained run. It was sized " +
    'for the relaxation ladder... or resend with allow_undersized_cell=true if you ' +
    'know the solute is effectively spherical.'

  it('recognises the cell refusal so the panel can offer the override', () => {
    expect(isUndersizedCellRefusal(REFUSAL)).toBe(true)
  })

  it('does not swallow other production errors', () => {
    // These must keep propagating as real failures, not become an "override?" prompt.
    expect(isUndersizedCellRefusal(
      'Production requires a completed relaxation (or production) to seed from.')).toBe(false)
    expect(isUndersizedCellRefusal(
      'steps: Input should be less than or equal to 1000000000')).toBe(false)
    expect(isUndersizedCellRefusal('Checkpoint d_01 coordinates were not found locally.'))
      .toBe(false)
  })

  it('is safe on non-strings', () => {
    expect(isUndersizedCellRefusal(null)).toBe(false)
    expect(isUndersizedCellRefusal(undefined)).toBe(false)
    expect(isUndersizedCellRefusal({ detail: 'allow_undersized_cell' })).toBe(false)
  })

  it('still matches the shortened backend refusal', () => {
    // The detail was cut to one sentence; the override token is the load-bearing
    // part of the contract and must survive any further rewording.
    expect(isUndersizedCellRefusal(
      'A 1000 ns run drifts this structure into its own periodic image (33 Å overlap). ' +
      'Re-prep with Cell sizing set to rotation, keep the run under 20 ns, or ' +
      'resend with allow_undersized_cell=true.')).toBe(true)
  })
})

describe('normPath', () => {
  it('normalizes separators and trailing slash', () => {
    expect(normPath('a\\b\\c/')).toBe('a/b/c')
    expect(normPath('x/y//')).toBe('x/y')
    expect(normPath('')).toBe('')
    expect(normPath(null)).toBe('')
  })
})

describe('formatEta', () => {
  it('formats seconds/minutes/hours and rejects unknowns', () => {
    expect(formatEta(45)).toBe('45s')
    expect(formatEta(150)).toBe('2m 30s')
    expect(formatEta(120)).toBe('2m')
    expect(formatEta(3900)).toBe('1h 5m')
    expect(formatEta(null)).toBe('')
    expect(formatEta(-1)).toBe('')
    expect(formatEta(Infinity)).toBe('')
  })
})

describe('jobDesignName', () => {
  it('prefers the source-path stem, falls back to design_name', () => {
    expect(jobDesignName({ design_source_path: 'parts/6hb_test.nadoc' })).toBe('6hb_test')
    expect(jobDesignName({ design_source_path: 'a\\b\\foo.nass' })).toBe('foo')
    expect(jobDesignName({ design_name: 'My Design' })).toBe('My Design')
    expect(jobDesignName({})).toBe('another design')
  })
})

describe('activeJobForPath', () => {
  const jobs = [
    { job_id: '1', engine: 'md', status: 'running', design_source_path: 'parts/a.nadoc' },
    { job_id: '2', engine: 'oxdna', status: 'preparing', design_source_path: 'b.nadoc' },
  ]
  it('matches by normalized design source path', () => {
    expect(activeJobForPath(jobs, 'parts/a.nadoc').job_id).toBe('1')
    expect(activeJobForPath(jobs, 'parts\\a.nadoc/').job_id).toBe('1')
    expect(activeJobForPath(jobs, 'b.nadoc').job_id).toBe('2')
  })
  it('returns null for no match or empty path', () => {
    expect(activeJobForPath(jobs, 'parts/missing.nadoc')).toBeNull()
    expect(activeJobForPath(jobs, '')).toBeNull()
    expect(activeJobForPath(null, 'x')).toBeNull()
  })
})

describe('runningEngineForPath', () => {
  it('returns the selector engine key of the busy job for the path', () => {
    const jobs = [
      { engine: 'oxdna', status: 'running', design_source_path: 'a.nadoc', created_at: 1 },
      { engine: 'lammps', status: 'preparing', design_source_path: 'b.nadoc', created_at: 2 },
    ]
    expect(runningEngineForPath(jobs, 'a.nadoc')).toBe('oxdna')
    expect(runningEngineForPath(jobs, 'b.nadoc')).toBe('lammps')
  })
  it("maps the backend NAMD key 'md' to the selector key 'namd'", () => {
    const jobs = [{ engine: 'md', status: 'running', design_source_path: 'a.nadoc', created_at: 1 }]
    expect(runningEngineForPath(jobs, 'a.nadoc')).toBe('namd')
  })
  it('breaks ties on the same design by the most recent created_at', () => {
    const jobs = [
      { engine: 'oxdna', status: 'running', design_source_path: 'a.nadoc', created_at: 10 },
      { engine: 'md', status: 'running', design_source_path: 'a.nadoc', created_at: 20 },
    ]
    expect(runningEngineForPath(jobs, 'a.nadoc')).toBe('namd')
  })
  it('ignores jobs that are not busy or belong to another design', () => {
    const jobs = [
      { engine: 'oxdna', status: 'completed', design_source_path: 'a.nadoc', created_at: 5 },
      { engine: 'mrdna', status: 'running', design_source_path: 'other.nadoc', created_at: 9 },
    ]
    expect(runningEngineForPath(jobs, 'a.nadoc')).toBeNull()
  })
  it('returns null for an empty path or no jobs', () => {
    expect(runningEngineForPath([], 'a.nadoc')).toBeNull()
    expect(runningEngineForPath(null, 'a.nadoc')).toBeNull()
    expect(runningEngineForPath([{ engine: 'oxdna', status: 'running', design_source_path: 'a.nadoc' }], '')).toBeNull()
  })
})

describe('jobActivityTooltip', () => {
  it('includes engine, verb, and ETA when known', () => {
    expect(jobActivityTooltip({ engine: 'md', status: 'running', eta_seconds: 150 }))
      .toBe('MD simulation running · ETA 2m 30s')
    expect(jobActivityTooltip({ engine: 'oxdna', status: 'preparing', eta_seconds: null }))
      .toBe('oxDNA simulation preparing…')
    expect(jobActivityTooltip(null)).toBe('')
  })
})

describe('runningEngines', () => {
  it('collects the engines of running/preparing jobs', () => {
    const s = runningEngines([
      { engine: 'md', status: 'running' },
      { engine: 'oxdna', status: 'preparing' },
      { engine: 'cando', status: 'running' },
    ])
    expect([...s].sort()).toEqual(['cando', 'md', 'oxdna'])
  })
  it('de-dupes multiple busy jobs of the same engine', () => {
    const s = runningEngines([
      { engine: 'lammps', status: 'running' },
      { engine: 'lammps', status: 'preparing' },
    ])
    expect([...s]).toEqual(['lammps'])
  })
  it('ignores non-busy statuses and malformed entries', () => {
    const s = runningEngines([
      { engine: 'md', status: 'queued' },
      { engine: 'oxdna', status: 'completed' },
      { status: 'running' },   // no engine
      null,
    ])
    expect(s.size).toBe(0)
  })
  it('is safe on null/empty', () => {
    expect(runningEngines(null).size).toBe(0)
    expect(runningEngines([]).size).toBe(0)
  })
})

describe('pickBlockingJob', () => {
  const jobs = [
    { job_id: '1', status: 'running' },
    { job_id: '2', status: 'queued' },
    { job_id: '3', status: 'preparing' },
  ]
  it('finds the first running/preparing job', () => {
    expect(pickBlockingJob(jobs).job_id).toBe('1')
  })
  it('skips the excluded job (resuming itself never blocks)', () => {
    expect(pickBlockingJob([{ job_id: '1', status: 'running' }], '1')).toBeNull()
  })
  it('ignores queued-only and empty lists', () => {
    expect(pickBlockingJob([{ job_id: '2', status: 'queued' }])).toBeNull()
    expect(pickBlockingJob([])).toBeNull()
    expect(pickBlockingJob(null)).toBeNull()
  })
  it('ignores a job running on the remote Alpine cluster (no local contention)', () => {
    expect(pickBlockingJob([
      { job_id: 'a', status: 'running', execution_target: 'alpine' },
    ])).toBeNull()
  })
  it('still blocks on a concurrent LOCAL job when a remote one is also active', () => {
    expect(pickBlockingJob([
      { job_id: 'a', status: 'running', execution_target: 'alpine' },
      { job_id: 'b', status: 'running', execution_target: 'local' },
    ]).job_id).toBe('b')
  })
  it('treats a missing execution_target as local (legacy jobs)', () => {
    expect(pickBlockingJob([{ job_id: '1', status: 'running' }]).job_id).toBe('1')
  })
  it('accepts a bare excludeJobId string (back-compat)', () => {
    expect(pickBlockingJob([{ job_id: '1', status: 'running' }], '1')).toBeNull()
  })
  it('a GPU launch blocks only on a busy GPU job, not a CPU one', () => {
    const jobs = [
      { job_id: 'cpu', status: 'running', resource_class: 'cpu' },
      { job_id: 'gpu', status: 'running', resource_class: 'gpu' },
    ]
    expect(pickBlockingJob(jobs, { newJobUsesGpu: true }).job_id).toBe('gpu')
  })
  it('a CPU launch blocks only on a busy CPU job, not a GPU one', () => {
    const jobs = [
      { job_id: 'gpu', status: 'running', resource_class: 'gpu' },
      { job_id: 'cpu', status: 'running', resource_class: 'cpu' },
    ]
    expect(pickBlockingJob(jobs, { newJobUsesGpu: false }).job_id).toBe('cpu')
  })
  it('a CPU launch is NOT blocked by a lone GPU job (side-by-side allowed)', () => {
    expect(pickBlockingJob(
      [{ job_id: 'gpu', status: 'running', resource_class: 'gpu' }],
      { newJobUsesGpu: false },
    )).toBeNull()
  })
  it('a missing resource_class counts as GPU (legacy conservative)', () => {
    expect(pickBlockingJob(
      [{ job_id: 'x', status: 'running' }],
      { newJobUsesGpu: true },
    ).job_id).toBe('x')
  })
})

describe('isLocalJob', () => {
  it('true for local / missing target, false for alpine', () => {
    expect(isLocalJob({ execution_target: 'local' })).toBe(true)
    expect(isLocalJob({})).toBe(true)
    expect(isLocalJob(undefined)).toBe(true)
    expect(isLocalJob({ execution_target: 'alpine' })).toBe(false)
  })
})

describe('isGpuJob', () => {
  it('true for gpu / missing class, false for cpu', () => {
    expect(isGpuJob({ resource_class: 'gpu' })).toBe(true)
    expect(isGpuJob({})).toBe(true)         // legacy → GPU
    expect(isGpuJob(undefined)).toBe(true)
    expect(isGpuJob({ resource_class: 'cpu' })).toBe(false)
  })
})

// ── confirmGpuNotBusy (external GPU-contention guard) ──────────────────────────
import { vi, beforeEach } from 'vitest'
import { confirmGpuNotBusy, confirmGpuLaunch, confirmNoConcurrentJob } from './job_activity.js'
import { gpuStatus, listActiveJobs } from '../api/client.js'
import { showConfirm, showChoice } from './primitives/confirm.js'

vi.mock('../api/client.js', () => ({ gpuStatus: vi.fn(), listActiveJobs: vi.fn() }))
vi.mock('./primitives/confirm.js', () => ({ showConfirm: vi.fn(), showChoice: vi.fn() }))

describe('confirmGpuNotBusy', () => {
  it('proceeds without a prompt when the GPU is idle', async () => {
    gpuStatus.mockResolvedValue({ busy: false })
    expect(await confirmGpuNotBusy('0')).toBe(true)
    expect(showConfirm).not.toHaveBeenCalled()
  })

  it('warns and returns the user choice when the GPU is busy', async () => {
    gpuStatus.mockResolvedValue({ busy: true, message: 'namd3 (2,336 MB)' })
    showConfirm.mockResolvedValue(false)   // user cancels
    expect(await confirmGpuNotBusy('0')).toBe(false)
    expect(showConfirm).toHaveBeenCalledOnce()
  })

  it('never blocks when detection fails', async () => {
    gpuStatus.mockRejectedValue(new Error('no nvidia-smi'))
    expect(await confirmGpuNotBusy('0')).toBe(true)
  })
})

// ── confirmGpuLaunch (resource-aware guard + CPU-fallback popup) ───────────────
describe('confirmGpuLaunch', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    listActiveJobs.mockResolvedValue({ jobs: [] })
    gpuStatus.mockResolvedValue({ busy: false })
  })

  it('proceeds on GPU with no prompt when the GPU is free', async () => {
    expect(await confirmGpuLaunch({ usesGpu: true, hasCpuAlternative: true })).toBe('gpu')
    expect(showChoice).not.toHaveBeenCalled()
    expect(showConfirm).not.toHaveBeenCalled()
  })

  it('offers the three-way popup when a NADOC GPU job holds the card', async () => {
    listActiveJobs.mockResolvedValue({
      jobs: [{ job_id: 'g', engine: 'md', status: 'running', resource_class: 'gpu' }],
    })
    showChoice.mockResolvedValue('cpu')          // user picks the CPU fallback
    expect(await confirmGpuLaunch({ usesGpu: true, hasCpuAlternative: true })).toBe('cpu')
    expect(showChoice).toHaveBeenCalledOnce()
    const opts = showChoice.mock.calls[0][0]
    expect(opts.choices.map(c => c.value)).toEqual(['gpu', 'cpu', 'cancel'])
  })

  it('offers the three-way popup when an EXTERNAL process holds the GPU', async () => {
    gpuStatus.mockResolvedValue({ busy: true, message: 'namd3 (2,336 MB)' })
    showChoice.mockResolvedValue('gpu')          // user forces the GPU anyway
    expect(await confirmGpuLaunch({ usesGpu: true, hasCpuAlternative: true })).toBe('gpu')
    expect(showChoice).toHaveBeenCalledOnce()
  })

  it('dismissing the three-way popup (×/Escape) resolves to cancel', async () => {
    gpuStatus.mockResolvedValue({ busy: true, message: 'busy' })
    showChoice.mockResolvedValue(null)
    expect(await confirmGpuLaunch({ usesGpu: true, hasCpuAlternative: true })).toBe('cancel')
  })

  it('falls back to a two-way warning when there is NO CPU alternative (NAMD)', async () => {
    listActiveJobs.mockResolvedValue({
      jobs: [{ job_id: 'g', engine: 'md', status: 'running', resource_class: 'gpu' }],
    })
    showConfirm.mockResolvedValue(true)
    expect(await confirmGpuLaunch({ usesGpu: true, hasCpuAlternative: false })).toBe('gpu')
    expect(showChoice).not.toHaveBeenCalled()
    expect(showConfirm).toHaveBeenCalledOnce()
  })

  it('a CPU launch beside a lone GPU job proceeds with no prompt', async () => {
    listActiveJobs.mockResolvedValue({
      jobs: [{ job_id: 'g', engine: 'md', status: 'running', resource_class: 'gpu' }],
    })
    expect(await confirmGpuLaunch({ usesGpu: false })).toBe('cpu')
    expect(showConfirm).not.toHaveBeenCalled()
    expect(gpuStatus).not.toHaveBeenCalled()     // CPU launch never probes the card
  })

  it('a CPU launch warns when another CPU job is busy', async () => {
    listActiveJobs.mockResolvedValue({
      jobs: [{ job_id: 'c', engine: 'oxdna', status: 'running', resource_class: 'cpu' }],
    })
    showConfirm.mockResolvedValue(false)         // user cancels
    expect(await confirmGpuLaunch({ usesGpu: false })).toBe('cancel')
    expect(showConfirm).toHaveBeenCalledOnce()
  })
})

// ── confirmNoConcurrentJob (resource-aware two-way guard) ──────────────────────
describe('confirmNoConcurrentJob', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    listActiveJobs.mockResolvedValue({ jobs: [] })
  })

  it('a GPU launch is NOT blocked by a busy CPU job', async () => {
    listActiveJobs.mockResolvedValue({
      jobs: [{ job_id: 'c', engine: 'oxdna', status: 'running', resource_class: 'cpu' }],
    })
    expect(await confirmNoConcurrentJob({ usesGpu: true })).toBe(true)
    expect(showConfirm).not.toHaveBeenCalled()
  })

  it('a GPU launch warns about a busy GPU job', async () => {
    listActiveJobs.mockResolvedValue({
      jobs: [{ job_id: 'g', engine: 'md', status: 'running', resource_class: 'gpu' }],
    })
    showConfirm.mockResolvedValue(true)
    expect(await confirmNoConcurrentJob({ usesGpu: true })).toBe(true)
    expect(showConfirm).toHaveBeenCalledOnce()
  })
})
