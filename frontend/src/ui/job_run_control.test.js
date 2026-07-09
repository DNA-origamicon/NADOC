import { describe, it, expect } from 'vitest'
import { runControlState, RUN_ACTION } from './job_run_control.js'

const opts = {
  verb: 'Relax',
  isActive: (j) => j.status === 'running' || j.status === 'preparing',
  isResumable: (j) => j.status === 'stopped' || j.status === 'failed',
}

describe('runControlState', () => {
  it('no selection → RUN (launch a new job)', () => {
    const s = runControlState(null, opts)
    expect(s.action).toBe(RUN_ACTION.RUN)
    expect(s.label).toBe('▶ Relax')
    expect(s.disabled).toBe(false)
  })

  it('a completed job selected → still RUN (start a fresh run)', () => {
    expect(runControlState({ status: 'completed' }, opts).action).toBe(RUN_ACTION.RUN)
  })

  it('a running job selected → STOP', () => {
    const s = runControlState({ status: 'running' }, opts)
    expect(s.action).toBe(RUN_ACTION.STOP)
    expect(s.label).toBe('■ Stop Relax')
  })

  it('a preparing job selected → STOP (active covers preparing)', () => {
    expect(runControlState({ status: 'preparing' }, opts).action).toBe(RUN_ACTION.STOP)
  })

  it('a stopped job selected → RESUME', () => {
    const s = runControlState({ status: 'stopped' }, opts)
    expect(s.action).toBe(RUN_ACTION.RESUME)
    expect(s.label).toBe('↻ Resume Relax')
  })

  it('a failed job selected → RESUME', () => {
    expect(runControlState({ status: 'failed' }, opts).action).toBe(RUN_ACTION.RESUME)
  })

  it('active takes precedence over resumable (a running job is never "resume")', () => {
    // A defensive predicate pair where both would match: active wins.
    const both = { ...opts, isResumable: () => true, isActive: () => true }
    expect(runControlState({ status: 'running' }, both).action).toBe(RUN_ACTION.STOP)
  })

  it('busy → disabled, action + label unchanged', () => {
    const s = runControlState({ status: 'running' }, { ...opts, busy: true })
    expect(s.action).toBe(RUN_ACTION.STOP)
    expect(s.disabled).toBe(true)
  })

  it('interpolates the engine verb', () => {
    expect(runControlState(null, { ...opts, verb: 'Coarse' }).label).toBe('▶ Coarse')
    expect(runControlState({ status: 'running' }, { ...opts, verb: 'Coarse' }).label).toBe('■ Stop Coarse')
  })
})
