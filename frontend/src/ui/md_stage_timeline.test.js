/**
 * md_stage_timeline.test.js — the timeline's derived rows.
 *
 * The load-bearing case is a job that is RUNNING but has not started segment 1: it is
 * minimising, and before this module the UI had no way to say so.
 */
import { describe, it, expect } from 'vitest'
import { mdMinimizationRow, mdShortStage, mdLatestStageLabel } from './md_stage_timeline.js'



describe('mdMinimizationRow', () => {
  const min = { name: 'B_tube_00_min_enm_k0p5', stage: 'Minimization ENM k=0.5', steps: 9600, status: 'pending' }
  const pending = [{ name: 's1', status: 'pending' }, { name: 's2', status: 'pending' }]

  it('returns null for a job prepared before the backend recorded it', () => {
    expect(mdMinimizationRow({ status: 'running', segments: pending })).toBe(null)
    expect(mdMinimizationRow({ minimization: { stage: 'x' } })).toBe(null)   // no name → no row
    expect(mdMinimizationRow(null)).toBe(null)
  })

  it('a running job with no segment started is IN the minimisation', () => {
    const r = mdMinimizationRow({ status: 'running', minimization: min, segments: pending })
    expect(r).toEqual({ name: min.name, stage: min.stage, steps: 9600, status: 'running' })
  })

  it('echoes the stamped status once the local runner has set it', () => {
    expect(mdMinimizationRow({ status: 'running', minimization: { ...min, status: 'done' }, segments: pending }).status)
      .toBe('done')
    expect(mdMinimizationRow({ status: 'failed', minimization: { ...min, status: 'failed' }, segments: pending }).status)
      .toBe('failed')
  })

  it('a started segment proves the minimisation finished (remote runs never stamp it)', () => {
    // Alpine/RunPod: job.minimization stays "pending" because only the local runner
    // writes it — but segment 1 cannot run unless the minimisation wrote its .coor.
    for (const segStatus of ['running', 'done', 'failed']) {
      const job = { status: 'running', minimization: min, segments: [{ name: 's1', status: segStatus }] }
      expect(mdMinimizationRow(job).status, `segment ${segStatus}`).toBe('done')
    }
  })

  it('a failed job that never reached a segment failed IN the minimisation', () => {
    expect(mdMinimizationRow({ status: 'failed', minimization: min, segments: pending }).status).toBe('failed')
  })

  it('a queued job shows the step as pending, not running', () => {
    expect(mdMinimizationRow({ status: 'queued', minimization: min, segments: pending }).status).toBe('pending')
  })

  it('carries the manifest label verbatim — a replica reseeds, it does not minimise', () => {
    const replica = { status: 'running', segments: pending,
      minimization: { name: 'r0_reseed', stage: 'Velocity reseed', steps: 0, status: 'pending' } }
    expect(mdMinimizationRow(replica).stage).toBe('Velocity reseed')
  })

  it('falls back to a generic label when the manifest predates the stage key', () => {
    const job = { status: 'queued', segments: pending, minimization: { name: 'old_00_min', steps: 4800 } }
    expect(mdMinimizationRow(job).stage).toBe('Minimization')
  })
})

describe('mdShortStage / mdLatestStageLabel', () => {
  it('mdShortStage rewrites the verbose ladder + production names', () => {
    expect(mdShortStage('300K NPT MGHH-only handoff')).toBe('300K NPT k=0')
    expect(mdShortStage('310K NPT conservative production 50 ns unrestrained')).toBe('50 ns production run')
    expect(mdShortStage('310K NPT ENM k=0.1')).toBe('ENM k=0.1')
    expect(mdShortStage(null)).toBe('—')
  })

  it('prefers live health, then the persisted sample', () => {
    expect(mdLatestStageLabel({}, { stage: '300K NPT ENM k=0.1' }, { stage: 'old' })).toBe('300K NPT ENM k=0.1')
    expect(mdLatestStageLabel({}, null, { stage: '300K NPT MGHH-only handoff' })).toBe('300K NPT k=0')
  })

  it('falls back to a RUNNING minimisation, which emits no health sample', () => {
    const job = { status: 'running', segments: [{ status: 'pending' }],
                  minimization: { name: 'm', stage: 'Minimization ENM k=0.5', steps: 9600, status: 'running' } }
    expect(mdLatestStageLabel(job, null, null)).toBe('Minimization ENM k=0.5')
    // …but never once it is done: an empty dash is better than a stale "minimising".
    const done = { ...job, minimization: { ...job.minimization, status: 'done' } }
    expect(mdLatestStageLabel(done, null, null)).toBe('—')
    expect(mdLatestStageLabel({}, null, null)).toBe('—')
  })
})
