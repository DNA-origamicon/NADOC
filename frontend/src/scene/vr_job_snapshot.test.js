import { describe, expect, it } from 'vitest'

import { buildVRJobSnapshot, VR_JOB_SNAPSHOT_LIMIT } from './vr_job_snapshot.js'

describe('buildVRJobSnapshot', () => {
  it('preserves canonical identity, hierarchy, status, and display flags', () => {
    const rows = buildVRJobSnapshot([
      {
        job_id: 'relax', engine: 'oxdna', status: 'completed', created_at: 1,
        design_name: 'Six helix bundle', viewable: true, out_of_date: true,
      },
      {
        job_id: 'production', parent_job_id: 'relax', engine: 'oxdna',
        status: 'running', created_at: 2, progress_fraction: 0.125,
        design_name: 'Production', archived: true,
      },
    ])

    expect(rows).toEqual([
      expect.objectContaining({
        job_id: 'relax', parent_job_id: null, engine: 'oxdna',
        status: 'completed', label: 'Six helix bundle', depth: 0,
        progress_permille: 1000, viewable: true, stale: true, archived: false,
      }),
      expect.objectContaining({
        job_id: 'production', parent_job_id: 'relax', engine: 'oxdna',
        status: 'running', depth: 1, progress_permille: 125,
        viewable: false, stale: false, archived: true,
      }),
    ])
    expect(rows[1].status_text).toBe('oxDNA - running - 12.5%')
  })

  it('uses engine-specific progress fallbacks and subtree-recency ordering', () => {
    const rows = buildVRJobSnapshot([
      { job_id: 'old', engine: 'cando', status: 'completed', created_at: 50 },
      { job_id: 'lm', engine: 'lammps', status: 'running', created_at: 1,
        current_step: 25, steps: 100 },
      { job_id: 'child', parent_job_id: 'lm', engine: 'lammps', status: 'queued',
        created_at: 100 },
    ])
    expect(rows.map(row => row.job_id)).toEqual(['lm', 'child', 'old'])
    expect(rows[0].progress_permille).toBe(250)
  })

  it('matches remote NAMD submission progress semantics', () => {
    const [waiting, uploading] = buildVRJobSnapshot([
      { job_id: 'waiting', engine: 'namd', status: 'queued', created_at: 2,
        execution_target: 'runpod', progress_fraction: 0.75 },
      { job_id: 'uploading', engine: 'namd', status: 'queued', created_at: 1,
        execution_target: 'alpine', progress_fraction: 0.05,
        remote_submit_progress: { fraction: 0.625 } },
    ])
    expect(waiting.progress_permille).toBe(0)
    expect(uploading.progress_permille).toBe(625)
  })

  it('sanitizes text, rejects malformed nodes, and caps the transport', () => {
    const jobs = Array.from({ length: VR_JOB_SNAPSHOT_LIMIT + 10 }, (_, index) => ({
      job_id: `job-${index}`,
      engine: 'namd',
      status: 'running',
      created_at: index,
      design_name: index === 0 ? 'M?del\nname' : `Run ${index}`,
    }))
    jobs.push({ job_id: '', engine: 'oxdna', status: 'running' })
    expect(buildVRJobSnapshot(jobs)).toHaveLength(VR_JOB_SNAPSHOT_LIMIT)
    expect(buildVRJobSnapshot(null)).toEqual([])
    expect(buildVRJobSnapshot(jobs, 0)).toEqual([])
    expect(buildVRJobSnapshot(jobs).every(row => !/[\r\n]/.test(row.label))).toBe(true)
  })
})
