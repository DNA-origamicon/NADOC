/**
 * Shared "design changed after a job was run" guard for the oxDNA + MD job panels.
 *
 * The backend tags each job `out_of_date` by comparing the current design's
 * topology/sequence/geometry fingerprint to the job's. A stale job's live/production
 * (oxDNA) or production (MD) would be inconsistent with the current structure (and,
 * for oxDNA, crash resolving current selections against the frozen topology). This
 * pops a roll-or-cancel dialog; on "Roll & run" it restores the job's EXACT saved
 * design snapshot (sequences + manual edits intact, unlike a feature-log seek) so the
 * design matches the job again — and saves the user's later edits as a "Latest"
 * loadout branch with a "Return to latest" toast.
 */

import { showConfirm } from './primitives/confirm.js'
import { showToast, showPersistentToast } from './toast.js'
import * as api from '../api/client.js'

/** Pure: did the design change since this job was run? (backend `out_of_date` flag). */
export function jobOutOfDate(job) {
  return !!job?.out_of_date
}

/** Restore from an explicit click on a job-row warning. Unlike ensureJobCurrent this
 * is not coupled to starting another run: local, Alpine, and RunPod jobs all own (or
 * inherit) the same frozen design snapshot, and restoring it never changes execution. */
export async function restoreSubmittedDesign({ job, rollFn, refetch }) {
  if (!jobOutOfDate(job)) return false
  const ok = await showConfirm({
    title: 'Restore to submitted design?',
    message: 'This design has changed since the job was submitted. Restore the exact design snapshot used to prepare this job?\n\nThe job will not be stopped or modified, whether it is running locally, on Alpine, or on RunPod. Your current design will be saved as a loadout so you can return to it later.',
    confirmLabel: 'Apply',
    cancelLabel: 'Cancel',
  })
  if (!ok) return false
  const r = await rollFn(job.job_id)
  if (!r) {
    showToast(api.lastErrorMessage?.() || 'Could not restore the submitted design (see console)', 'warn')
    return false
  }
  if (r.matches_job === false) {
    showToast('The snapshot was restored, but it still does not match this job.', 'warn')
    return false
  }
  if (refetch) setTimeout(() => { Promise.resolve(refetch()).catch(() => {}) }, 0)
  if (r.return_loadout_id) {
    showPersistentToast(
      'Submitted design restored. The job was not modified; your later edits are saved as a “Latest” loadout.',
      { severity: 'info', action: { label: '↩ Return to latest', onClick: () => api.selectLoadout(r.return_loadout_id, { saveCurrent: false }) } })
  }
  return true
}

/**
 * Guard a run action on a possibly-stale job. Returns true to proceed, false to abort.
 * @param {object}   opts
 * @param {object}   opts.job          the selected job (carries `out_of_date`)
 * @param {Function} opts.rollFn       (jobId) => Promise<designResponse|null> — restores the job's snapshot
 * @param {Function} opts.refetch      () => Promise — refresh the job list (re-evaluates out_of_date)
 * @param {string}   opts.actionLabel  e.g. 'a production run' / 'a live session'
 */
export async function ensureJobCurrent({ job, rollFn, refetch, actionLabel = 'this run' }) {
  if (!jobOutOfDate(job)) return true
  const ok = await showConfirm({
    title: 'Design has changed',
    message: `The design was edited after this job was run, so running ${actionLabel} on it would be `
      + 'inconsistent with the current structure.'
      + '\n\nRoll the design back to the exact state this job was run at and continue? Your later '
      + 'edits are saved as a "Latest" loadout — a "Return to latest" button restores them.',
    confirmLabel: 'Roll & run',
    cancelLabel: 'Cancel',
  })
  if (!ok) return false
  const r = await rollFn(job.job_id)
  if (!r) {
    showToast(api.lastErrorMessage?.() || 'Could not roll the design back (see console)', 'warn')
    return false
  }
  if (r.matches_job === false) {
    showToast('Rolled, but the job is still out of date — run a new relaxation / MD prep.', 'warn')
    return false
  }
  // Badge/list reconciliation is not on the critical path. The roll response
  // already carries the authoritative fingerprint result; refresh historical
  // jobs after returning control so the next action is not held behind disk I/O.
  if (refetch) setTimeout(() => { Promise.resolve(refetch()).catch(() => {}) }, 0)
  if (r.return_loadout_id) {
    showPersistentToast(
      'Design rolled back to this job’s run state. Your later edits are saved as a “Latest” loadout.',
      { severity: 'info', action: { label: '↩ Return to latest', onClick: () => api.selectLoadout(r.return_loadout_id, { saveCurrent: false }) } })
  }
  return true
}
