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

/**
 * Guard a run action on a possibly-stale job. Returns true to proceed, false to abort.
 * @param {object}   opts
 * @param {object}   opts.job          the selected job (carries `out_of_date`)
 * @param {Function} opts.rollFn       (jobId) => Promise<designResponse|null> — restores the job's snapshot
 * @param {Function} opts.refetch      () => Promise — refresh the job list (re-evaluates out_of_date)
 * @param {Function} opts.isStale      () => boolean — is the (re-fetched) selected job still stale?
 * @param {string}   opts.actionLabel  e.g. 'a production run' / 'a live session'
 */
export async function ensureJobCurrent({ job, rollFn, refetch, isStale, actionLabel = 'this run' }) {
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
  await refetch?.()
  if (isStale?.()) {
    showToast('Rolled, but the job is still out of date — run a new relaxation / MD prep.', 'warn')
    return false
  }
  if (r.return_loadout_id) {
    showPersistentToast(
      'Design rolled back to this job’s run state. Your later edits are saved as a “Latest” loadout.',
      { severity: 'info', action: { label: '↩ Return to latest', onClick: () => api.selectLoadout(r.return_loadout_id, { saveCurrent: false }) } })
  }
  return true
}
