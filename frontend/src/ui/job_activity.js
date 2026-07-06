/**
 * job_activity.js — cross-engine (MD + oxDNA) job-activity helpers shared by the
 * welcome screen and the simulation panels.
 *
 *  - The welcome / library panel uses {@link fetchActiveJobs}, {@link activeJobForPath}
 *    and {@link jobActivityTooltip} to draw a spinning "this design is simulating"
 *    indicator with an ETA-on-hover.
 *  - The MD and oxDNA panels call {@link confirmNoConcurrentJob} before launching a
 *    run, so the user gets a Continue/Cancel warning if another job is already busy.
 *
 * Backed by GET /api/jobs/active (see backend/api/routes_jobs.py).  The pure helpers
 * are exported separately so they can be unit-tested without the network/DOM.
 */

import { showConfirm } from './primitives/confirm.js'
import { formatBytes } from './format_bytes.js'
import { listActiveJobs, gpuStatus } from '../api/client.js'

/** Pure: normalize a workspace path for comparison (slashes + trailing slash). */
export function normPath(p) {
  return p ? String(p).replace(/\\/g, '/').replace(/\/+$/, '') : ''
}

/** Pure: human ETA from seconds ("45s" / "2m 30s" / "1h 5m"); '' when unknown. */
export function formatEta(seconds) {
  if (seconds == null || !isFinite(seconds) || seconds < 0) return ''
  const s = Math.round(seconds)
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60), rs = s % 60
  if (m < 60) return rs ? `${m}m ${rs}s` : `${m}m`
  const h = Math.floor(m / 60), rm = m % 60
  return rm ? `${h}h ${rm}m` : `${h}h`
}

/** Pure: a readable design name for a job (file stem, falling back to design_name). */
export function jobDesignName(job) {
  const src = job?.design_source_path
  if (src) {
    const base = String(src).split(/[\\/]/).pop() || src
    const stem = base.replace(/\.[^.]+$/, '')
    if (stem) return stem
  }
  return job?.design_name || 'another design'
}

/** Pure: the active job whose design matches this workspace file path, or null. */
export function activeJobForPath(activeJobs, path) {
  const key = normPath(path)
  if (!key) return null
  return (activeJobs || []).find(j => normPath(j.design_source_path) === key) || null
}

/** Pure: hover-tooltip text for a file's activity spinner. */
export function jobActivityTooltip(job) {
  if (!job) return ''
  const eng = job.engine === 'oxdna' ? 'oxDNA' : 'MD'
  const verb = job.status === 'preparing' ? 'preparing' : 'running'
  const eta = formatEta(job.eta_seconds)
  return eta
    ? `${eng} simulation ${verb} · ETA ${eta}`
    : `${eng} simulation ${verb}…`
}

/** Pure: true if a job runs on THIS machine (vs. the remote Alpine cluster).
 *  Missing/legacy field → local (old jobs predate the remote backend). */
export function isLocalJob(job) {
  return (job?.execution_target ?? 'local') === 'local'
}

/** Pure: a busy job (running/preparing) that should block a new launch, or null.
 *  Only LOCAL jobs block — a job running on the Alpine cluster consumes no local
 *  GPU/disk, so it can't contend with a new local run (and vice versa: an Alpine
 *  submit isn't gated by a local run — its launch handler skips this guard).
 *  ``excludeJobId`` skips the job being resumed so resuming it never warns about
 *  itself. */
export function pickBlockingJob(activeJobs, excludeJobId = null) {
  return (activeJobs || []).find(
    j => j.job_id !== excludeJobId && isLocalJob(j)
      && (j.status === 'running' || j.status === 'preparing'),
  ) || null
}

/** Fetch the list of currently-busy MD/oxDNA jobs. Never throws — returns [] on error. */
export async function fetchActiveJobs() {
  try {
    const d = await listActiveJobs()
    return Array.isArray(d?.jobs) ? d.jobs : []
  } catch {
    return []
  }
}

/**
 * Guard against running two simulations at once.  If another MD/oxDNA job is
 * already running or preparing, show a Continue/Cancel warning and resolve to the
 * user's choice; otherwise resolve true immediately.
 *
 * @param {object}  [opts]
 * @param {?string} [opts.excludeJobId] job being resumed (won't block on itself)
 * @returns {Promise<boolean>} true to proceed with the launch, false to abort
 */
export async function confirmNoConcurrentJob({ excludeJobId = null } = {}) {
  const blocking = pickBlockingJob(await fetchActiveJobs(), excludeJobId)
  if (!blocking) return true
  const eng = blocking.engine === 'oxdna' ? 'oxDNA' : 'MD'
  const name = jobDesignName(blocking)
  return showConfirm({
    title: 'A simulation is already running',
    message:
      `An ${eng} job for "${name}" is currently ${blocking.status}.\n\n` +
      'Running two simulations at once makes them compete for the GPU and memory, ' +
      'which can slow both down or fail with out-of-memory. Start this job anyway?',
    confirmLabel: 'Continue',
    cancelLabel: 'Cancel',
  })
}

/**
 * Guard against an EXTERNAL GPU hog (a non-NADOC process — e.g. an experiment's
 * NAMD run, a manual GROMACS job — holding the card). Complements
 * {@link confirmNoConcurrentJob}, which only knows about NADOC's own jobs. Shows
 * a Continue/Cancel warning if the GPU is busy; resolves true to proceed. Never
 * blocks on its own errors (no nvidia-smi, fetch fail → proceed).
 *
 * @param {string} [devices] CUDA device string for the run (default '0')
 * @returns {Promise<boolean>} true to proceed with the launch, false to abort
 */
/**
 * Pure: build the disk-space warning message from a forecast, or null when no
 * warning is warranted. Split out so the threshold/wording is unit-testable
 * without the network or a modal.
 *
 * @param {object} forecast  {free_bytes, predicted_bytes, free_after_bytes, warn, ...}
 * @returns {?string} popup body text, or null if the run is fine to launch
 */
export function diskWarningMessage(forecast) {
  if (!forecast || forecast.warn !== true) return null
  const free = formatBytes(forecast.free_bytes)
  const predicted = formatBytes(forecast.predicted_bytes)
  const after = forecast.free_after_bytes
  const afterStr = after < 0
    ? `run OUT of disk (short by ${formatBytes(-after)})`
    : `leave only ${formatBytes(after)} free`
  return (
    `This run is estimated to write about ${predicted} of trajectory and restart ` +
    `data. You currently have ${free} free, so finishing it would ${afterStr}.\n\n` +
    'Simulations that fill the disk can corrupt their output and wedge the machine. ' +
    'Free up space (delete or archive old jobs) first, or start anyway if you know ' +
    'the run will be stopped early.'
  )
}

/**
 * Guard against launching a run that would leave too little free disk. Given a
 * disk-space forecast from the backend (see estimateMdDisk / estimateOxdnaDisk),
 * show a Continue/Cancel warning when finishing the run would drop free space
 * below the 10 GB floor; otherwise resolve true immediately. Never blocks on a
 * missing/failed forecast — a forecast must never prevent a launch.
 *
 * @param {?object} forecast  the backend forecast dict (or null/undefined)
 * @returns {Promise<boolean>} true to proceed with the launch, false to abort
 */
export async function confirmDiskSpaceOk(forecast) {
  const message = diskWarningMessage(forecast)
  if (!message) return true
  return showConfirm({
    title: 'Low disk space for this run',
    message,
    danger: true,
    confirmLabel: 'Start anyway',
    cancelLabel: 'Cancel',
  })
}

export async function confirmGpuNotBusy(devices = '0') {
  let status
  try {
    status = await gpuStatus(devices)
  } catch {
    return true   // detection unavailable → don't block
  }
  if (!status?.busy) return true
  return showConfirm({
    title: 'The GPU is busy with another process',
    message:
      `${status.message}\n\n` +
      'This is not a NADOC job — likely a background experiment or a manual run. ' +
      'Start this job anyway?',
    confirmLabel: 'Continue',
    cancelLabel: 'Cancel',
  })
}
