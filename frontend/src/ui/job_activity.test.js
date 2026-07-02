import { describe, it, expect } from 'vitest'
import {
  normPath,
  formatEta,
  jobDesignName,
  activeJobForPath,
  jobActivityTooltip,
  pickBlockingJob,
  diskWarningMessage,
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

describe('jobActivityTooltip', () => {
  it('includes engine, verb, and ETA when known', () => {
    expect(jobActivityTooltip({ engine: 'md', status: 'running', eta_seconds: 150 }))
      .toBe('MD simulation running · ETA 2m 30s')
    expect(jobActivityTooltip({ engine: 'oxdna', status: 'preparing', eta_seconds: null }))
      .toBe('oxDNA simulation preparing…')
    expect(jobActivityTooltip(null)).toBe('')
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
})

// ── confirmGpuNotBusy (external GPU-contention guard) ──────────────────────────
import { vi } from 'vitest'
import { confirmGpuNotBusy } from './job_activity.js'
import { gpuStatus } from '../api/client.js'
import { showConfirm } from './primitives/confirm.js'

vi.mock('../api/client.js', () => ({ gpuStatus: vi.fn(), listActiveJobs: vi.fn() }))
vi.mock('./primitives/confirm.js', () => ({ showConfirm: vi.fn() }))

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
