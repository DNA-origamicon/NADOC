/**
 * job_run_control.js — the shared primary-action state machine for every engine's
 * launch button (Phase C, unified Simulate panel / master Job status card).
 *
 * The rule (user-specified): the button that STARTS a job flips to STOP the instant
 * that job is running, and to RESUME when a stopped/failed job is selected. One
 * control, three meanings, driven entirely by the currently-selected job's state:
 *
 *   nothing selected / a completed job selected  →  ▶ <verb>        (launch a new run)
 *   the selected job is running/preparing        →  ■ Stop <verb>   (stop it)
 *   the selected job is stopped/failed           →  ↻ Resume <verb> (resume it)
 *
 * Pure + engine-agnostic: each engine supplies its own `isActive` / `isResumable`
 * predicates (their status vocabularies differ) and its launch verb. The panel wires
 * the returned `action` to run/stop/resume handlers and paints `label`. Unit-tested in
 * job_run_control.test.js; no DOM, no I/O.
 */

export const RUN_ACTION = Object.freeze({ RUN: 'run', STOP: 'stop', RESUME: 'resume' })

const GLYPH = Object.freeze({ run: '▶', stop: '■', resume: '↻' })

/**
 * Decide the primary control's action + label from the selected job.
 *
 * @param {object|null} selectedJob        the selected job (null = nothing selected)
 * @param {object} opts
 * @param {string}          opts.verb          launch verb, e.g. 'Relax' | 'Coarse' | 'Run'
 * @param {(job)=>boolean}  opts.isActive      engine's "running/preparing" predicate
 * @param {(job)=>boolean}  opts.isResumable   engine's "stopped/failed → resumable" predicate
 * @param {boolean}         [opts.busy=false]  a launch/stop/resume request is in flight
 * @returns {{action:string, label:string, disabled:boolean}}
 */
export function runControlState(selectedJob, { verb, isActive, isResumable, busy = false } = {}) {
  if (selectedJob && isActive?.(selectedJob)) {
    return { action: RUN_ACTION.STOP, label: `${GLYPH.stop} Stop ${verb}`, disabled: busy }
  }
  if (selectedJob && isResumable?.(selectedJob)) {
    return { action: RUN_ACTION.RESUME, label: `${GLYPH.resume} Resume ${verb}`, disabled: busy }
  }
  return { action: RUN_ACTION.RUN, label: `${GLYPH.run} ${verb}`, disabled: busy }
}
