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

  it('last resort: the segment the job says it is on', () => {
    // A production run is ONE long segment that emits its health sample at the very
    // end, so "Latest" used to read "—" for the whole run — and on an active job a
    // dash was drawn as an endless spinner. The current segment is always known.
    const job = {
      status: 'running',
      current_segment_idx: 0,
      segments: [{ name: 'p1', stage: '310K NPT conservative production 500 ns', status: 'running' }],
    }
    expect(mdLatestStageLabel(job, null, null)).toBe('500 ns production run')
  })

  it('still prefers a real health sample over the segment fallback', () => {
    const job = {
      status: 'running',
      current_segment_idx: 1,
      segments: [{ stage: 'a' }, { stage: '310K NPT ENM k=0.1' }],
    }
    expect(mdLatestStageLabel(job, { stage: '300K NPT k=0' }, null)).toBe('300K NPT k=0')
  })

  it('reports the actually-completed ns after Terminate run and download, not the submitted target', () => {
    // _decorate_terminal_segment_progress (routes_md.py) stamps completed_ns on the
    // segment once the job is done — the raw stage string alone still says "500 ns
    // production run" no matter how much of it actually ran, which used to leave the
    // "Latest" card claiming the full submitted length even for a run cut short.
    const seg = { name: 'p1', stage: '310K NPT production 500 ns unrestrained', completed_ns: 42.5 }
    const job = { status: 'completed', current_segment_idx: 0, segments: [seg] }
    expect(mdLatestStageLabel(job, null, null)).toBe('42.5 ns production complete')
    // Same via a health sample / persisted metrics record naming that segment.
    expect(mdLatestStageLabel(job, { stage: seg.stage, segment: 'p1' }, null)).toBe('42.5 ns production complete')
    expect(mdLatestStageLabel(job, null, { stage: seg.stage, segment: 'p1' })).toBe('42.5 ns production complete')
  })

  it('leaves the submitted-target label alone when the segment has no completed_ns yet', () => {
    const seg = { name: 'p1', stage: '310K NPT production 500 ns unrestrained' }
    const job = { status: 'running', current_segment_idx: 0, segments: [seg] }
    expect(mdLatestStageLabel(job, null, null)).toBe('500 ns production run')
  })
})
