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

import { showConfirm, showChoice } from './primitives/confirm.js'
import { formatBytes } from './format_bytes.js'
import { listActiveJobs, gpuStatus } from '../api/client.js'

/** Pure: short engine label for a job ("oxDNA" / "MD"). */
function engLabel(job) {
  return job?.engine === 'oxdna' ? 'oxDNA' : 'MD'
}

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

/** Pure: the engine key of the currently-busy (running/preparing) job for this
 *  design path, or null when none is busy. Maps the backend NAMD engine key
 *  ('md') to the Simulate selector's key ('namd'); the other four already match
 *  ('oxdna'|'lammps'|'mrdna'|'cando'). Ties (several busy jobs on the same
 *  design) break to the most recently created job (`created_at`, epoch seconds).
 *  Used to default the Simulate engine dropdown to whatever the loaded design is
 *  already simulating. */
export function runningEngineForPath(activeJobs, path) {
  const key = normPath(path)
  if (!key) return null
  const busy = (activeJobs || []).filter(
    j => normPath(j.design_source_path) === key
      && (j.status === 'running' || j.status === 'preparing'),
  )
  if (!busy.length) return null
  busy.sort((a, b) => (b.created_at ?? 0) - (a.created_at ?? 0))
  const eng = busy[0].engine
  return eng === 'md' ? 'namd' : eng
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

/** Pure: true if a job holds the GPU (NAMD, or a CUDA-backend oxDNA run).
 *  Missing/legacy field → GPU (conservative: an untagged job blocks like before). */
export function isGpuJob(job) {
  return (job?.resource_class ?? 'gpu') === 'gpu'
}

/** Pure: a busy job (running/preparing) that should block a new launch, or null.
 *
 *  Only LOCAL jobs block — a job running on the Alpine cluster consumes no local
 *  GPU/disk, so it can't contend with a new local run (and vice versa: an Alpine
 *  submit isn't gated by a local run — its launch handler skips this guard).
 *
 *  When ``newJobUsesGpu`` is given, only jobs of the SAME resource class block: a
 *  GPU launch is blocked only by a busy GPU job (they'd fight over the card), and a
 *  CPU launch only by a busy CPU job (spare-core contention). A CPU job and a GPU
 *  job never block each other — the whole point of running them side by side.
 *  Omit ``newJobUsesGpu`` (legacy calls) to block on any busy local job.
 *
 *  ``opts`` may be the options object ``{excludeJobId, newJobUsesGpu}`` or, for
 *  back-compat, a bare ``excludeJobId`` string. */
export function pickBlockingJob(activeJobs, opts = null) {
  const isObj = opts && typeof opts === 'object'
  const excludeJobId = isObj ? (opts.excludeJobId ?? null) : (opts ?? null)
  const newJobUsesGpu = isObj ? (opts.newJobUsesGpu ?? null) : null
  return (activeJobs || []).find(
    j => j.job_id !== excludeJobId && isLocalJob(j)
      && (j.status === 'running' || j.status === 'preparing')
      && (newJobUsesGpu === null || isGpuJob(j) === newJobUsesGpu),
  ) || null
}

/** Pure: the set of engine keys ('md'|'oxdna'|'lammps'|'mrdna'|'cando') that have a
 *  currently-busy (running/preparing) job. Used to light a spinner on each engine's
 *  sidebar section header. Jobs already come pre-filtered to busy ones by the
 *  endpoint, but re-check the status so the helper is correct for any caller. */
export function runningEngines(activeJobs) {
  const set = new Set()
  for (const j of activeJobs || []) {
    if (j?.engine && (j.status === 'running' || j.status === 'preparing')) set.add(j.engine)
  }
  return set
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
 * @param {boolean} [opts.usesGpu=true] does the NEW job hold the GPU? Only a job
 *   of the same resource class blocks — a GPU launch ignores a busy CPU job and
 *   vice versa (see {@link pickBlockingJob}).
 * @returns {Promise<boolean>} true to proceed with the launch, false to abort
 */
export async function confirmNoConcurrentJob({ excludeJobId = null, usesGpu = true } = {}) {
  const blocking = pickBlockingJob(await fetchActiveJobs(), { excludeJobId, newJobUsesGpu: usesGpu })
  if (!blocking) return true
  const eng = engLabel(blocking)
  const name = jobDesignName(blocking)
  const resource = usesGpu ? 'the GPU and memory' : 'CPU cores and memory'
  return showConfirm({
    title: 'A simulation is already running',
    message:
      `An ${eng} job for "${name}" is currently ${blocking.status}.\n\n` +
      `Running two simulations at once makes them compete for ${resource}, ` +
      'which can slow both down or fail with out-of-memory. Start this job anyway?',
    confirmLabel: 'Continue',
    cancelLabel: 'Cancel',
  })
}

/**
 * Resource-aware launch guard for a job that CAN run on the GPU, offering a CPU
 * fallback when the GPU is occupied. Resolves to one of three actions:
 *
 *   'gpu'    — proceed on the GPU as requested
 *   'cpu'    — proceed, but on the CPU backend (leaves the GPU job untouched)
 *   'cancel' — abort the launch
 *
 * Behaviour:
 *  - A CPU launch (``usesGpu:false``) never contends for the GPU. It only warns if
 *    another local CPU job is busy (spare-core/RAM sharing), then returns 'cpu'.
 *  - A GPU launch checks whether the GPU is already occupied — by one of our own
 *    local GPU jobs OR an external VRAM-holding process. If free, returns 'gpu'
 *    with no prompt. If occupied and ``hasCpuAlternative``, shows the three-way
 *    popup (GPU-anyway / CPU-instead / cancel). If occupied with no CPU fallback
 *    (e.g. NAMD), shows the two-way "continue anyway / cancel" warning.
 *
 * Never blocks on its own detection errors (no nvidia-smi / fetch fail → proceeds
 * as if the GPU were free).
 *
 * @param {object}  [opts]
 * @param {boolean} [opts.usesGpu=true]           does the requested run hold the GPU?
 * @param {boolean} [opts.hasCpuAlternative=false] can this job fall back to a CPU backend?
 * @param {string}  [opts.devices='0']            CUDA device string for the external check
 * @param {?string} [opts.excludeJobId=null]      job being resumed (won't block on itself)
 * @returns {Promise<'gpu'|'cpu'|'cancel'>}
 */
export async function confirmGpuLaunch({
  usesGpu = true,
  hasCpuAlternative = false,
  devices = '0',
  excludeJobId = null,
} = {}) {
  const active = await fetchActiveJobs()

  // CPU launch: only another local CPU job shares its cores/RAM; GPU jobs don't.
  if (!usesGpu) {
    const cpuBusy = pickBlockingJob(active, { excludeJobId, newJobUsesGpu: false })
    if (!cpuBusy) return 'cpu'
    const ok = await showConfirm({
      title: 'Another CPU simulation is running',
      message:
        `A ${engLabel(cpuBusy)} job for "${jobDesignName(cpuBusy)}" is currently ` +
        `${cpuBusy.status}. Both run on the CPU, so they will share cores and memory ` +
        'and may each run slower. Start this job anyway?',
      confirmLabel: 'Continue',
      cancelLabel: 'Cancel',
    })
    return ok ? 'cpu' : 'cancel'
  }

  // GPU launch: is the card already occupied — by one of our GPU jobs, or by an
  // external process holding VRAM?
  const gpuJob = pickBlockingJob(active, { excludeJobId, newJobUsesGpu: true })
  let externalMsg = ''
  try {
    const st = await gpuStatus(devices)
    if (st?.busy) externalMsg = st.message || 'Another process is using the GPU.'
  } catch { /* detection down → treat as free, never block on our own error */ }

  if (!gpuJob && !externalMsg) return 'gpu'

  const occupant = gpuJob
    ? `A ${engLabel(gpuJob)} job for "${jobDesignName(gpuJob)}" is currently ${gpuJob.status}.`
    : externalMsg

  if (hasCpuAlternative) {
    const pick = await showChoice({
      title: 'The GPU is already busy',
      message:
        `${occupant}\n\n` +
        'Running a second GPU job makes them compete for the card and its memory, which ' +
        'can slow both to a crawl or fail with out-of-memory. You can instead run this ' +
        'job on the CPU — slower per step, but it leaves the GPU job untouched and uses ' +
        'your spare cores.',
      choices: [
        { label: 'Run on GPU anyway', value: 'gpu', variant: 'danger' },
        { label: 'Run on CPU instead', value: 'cpu', variant: 'success' },
        { label: 'Cancel', value: 'cancel' },
      ],
    })
    return pick ?? 'cancel'   // ×/Escape/backdrop → cancel
  }

  const ok = await showConfirm({
    title: 'The GPU is already busy',
    message:
      `${occupant}\n\n` +
      'Running two GPU simulations at once makes them compete for the card and memory, ' +
      'which can slow both down or fail with out-of-memory. Start this job anyway?',
    danger: true,
    confirmLabel: 'Continue',
    cancelLabel: 'Cancel',
  })
  return ok ? 'gpu' : 'cancel'
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
