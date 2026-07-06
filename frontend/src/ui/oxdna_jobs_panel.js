/**
 * oxDNA relaxation jobs panel (Dynamics tab).
 *
 * Sibling of md_jobs_panel.js: launches and monitors a managed 3-stage oxDNA
 * coarse-grained relaxation on the CURRENTLY-LOADED design, shows a scrollable
 * jobs list filtered to that design, a stage timeline, per-stage health
 * readouts, and an "OxDNA display" toggle that deforms the NADOC model to the
 * job's last relaxed positions (oxdna_display.js).
 *
 * REST-poll based (no WebSocket) — an oxDNA relaxation is short and single-frame
 * compared to a NAMD trajectory, so a light poll while the panel is open is
 * enough.  oxDNA output is display state only; topology is never touched.
 *
 * Factory: initOxdnaJobsPanel({ oxdnaDisplay, getWorkspacePath }) — pulls API
 * via dynamic import of api/client.js (mirrors md_jobs_panel usage).
 */

import { getSectionCollapsed, setSectionCollapsed } from './section_collapse_state.js'
import { resetControlsToDefaults } from './form_defaults.js'
import { showToast } from './toast.js'
import { jobOutOfDate, ensureJobCurrent } from './job_staleness.js'
import { filterJobsForPart } from './md_jobs_panel.js'
import { initFlexScale } from './flex_scale.js'
import { isUndefinedSequenceError, showSequenceWarningModal } from './sequence_warning_modal.js'
import { initOxdnaTrajectoryPlayer } from './oxdna_trajectory_player.js'
import { initOxdnaMetricsCard } from './oxdna_metrics_card.js'
import { initShapeCompareCard } from './shape_compare_card.js'
import { showConfirm } from './primitives/confirm.js'
import { createModal } from './primitives/modal.js'
import { createButton } from './primitives/button.js'
import { runExclusive } from './primitives/button_busy.js'
import { el } from './primitives/dom.js'
import { statusBadge, statusKeyFor, makeStatusLegend } from './job_status_symbol.js'
import { flattenJobTree, descendantIds } from './job_tree.js'
import { formatJobTime } from '../scene/trajectory_range.js'
import { formatBytes } from './format_bytes.js'
import { initJobArchive } from './job_archive_action.js'
import { confirmNoConcurrentJob, confirmGpuNotBusy, confirmDiskSpaceOk } from './job_activity.js'
import * as api from '../api/client.js'

const POLL_MS = 1500

const _C = {
  ok:   '#5cb85c', warn: '#e0a800', err: '#d9534f',
  accent: '#4a9eff', dim: '#8a8a8a', text: '#d8d8d8',
}

const _STATUS_COLOR = {
  queued: _C.dim, preparing: _C.accent, running: _C.warn,
  completed: _C.ok, failed: _C.err, stopped: _C.dim,
}

/** Pure: overall progress % string for a job + progress payload. */
export function formatProgress(job, progress) {
  const total = job?.stages?.length ?? 0
  const done = job?.stages?.filter(s => s.status === 'done').length ?? 0
  const frac = progress?.overall ?? (total ? done / total : 0)
  return { pct: Math.round(frac * 100), done, total }
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

/** Pure: the name to show for a job — prefer the loaded file name (design_source_path
 * stem) over design_name, which a "save as" can leave stale (e.g. 6hb_OxDNA_test
 * carrying "6hb_primitive"). */
export function jobDisplayName(job) {
  const src = job?.design_source_path
  if (src) {
    const base = String(src).split(/[\\/]/).pop() || src
    const stem = base.replace(/\.[^.]+$/, '')
    if (stem) return stem
  }
  return job?.design_name || 'design'
}

/** Pure: latest health sample of a job (or null). */
export function latestHealth(job) {
  const hs = job?.health_samples
  return hs && hs.length ? hs[hs.length - 1] : null
}

/** Pure: which health snapshot the cards should show. While a stage is RUNNING,
 *  the live snapshot from /progress (`progress.live_health`) ticks every poll;
 *  otherwise fall back to the last persisted end-of-stage sample. This is what
 *  stops the cards freezing mid-stage. */
export function healthForDisplay(job, progress) {
  if (job?.status === 'running' && progress && progress.live_health) {
    return progress.live_health
  }
  return latestHealth(job)
}

/** Pure: the detail status line text for a job — the begin/monitor/finish readout. */
export function detailStatusText(job, progress) {
  const { pct, done, total } = formatProgress(job, progress)
  if (job?.status === 'running') {
    const stageName = job.stages?.[job.current_stage_idx]?.name ?? '—'
    return `Running · ${done}/${total} stages · ${stageName} · ${pct}%`
  }
  return `${job?.status ?? 'unknown'} · ${done}/${total} stages`
}

const _STAGE_GLYPH = { done: '●', failed: '✗', running: '○', pending: '·' }

/** Pure: did the job fail at the job level OR in any stage? Drives the
 *  "View error log" button's visibility. */
export function jobHasFailure(job) {
  if (!job) return false
  return job.status === 'failed' || (job.stages || []).some(s => s.status === 'failed')
}

/** Pure: build the text shown in the error-log popup from the /error-log payload.
 *  Leads with a plain-language diagnosis for the most common failure — a CUDA run
 *  against a CPU-only binary — then the job error, then the raw oxDNA log. */
export function errorLogText(payload) {
  if (!payload) return 'No error details available.'
  const d = payload.diagnostics || {}
  const out = []
  // Targeted hint for the CUDA/CPU-binary mismatch.
  if (d.requested_backend === 'CUDA' && d.oxdna_bin && d.cuda_capable === false) {
    out.push(
      'DIAGNOSIS: this run requested the GPU (CUDA) backend, but the oxDNA binary ' +
      `in use is CPU-only:\n  ${d.oxdna_bin}\n` +
      'Build a CUDA-enabled oxDNA (terminal: `just oxdna-doctor --fix`, or the MD ' +
      'Engines panel), then start the run again. To run on CPU instead, pick the ' +
      'CPU backend.\n')
  }
  if (payload.error) out.push(`Error: ${payload.error}`)
  if (payload.stage) out.push(`Failed stage: ${payload.stage}`)
  if (d.oxdna_bin !== undefined) {
    out.push(`Binary: ${d.oxdna_bin || '(none resolved)'} · backend requested: ` +
      `${d.requested_backend || '?'} · CUDA-capable: ${d.cuda_capable ? 'yes' : 'no'}`)
  }
  if (payload.log_path) out.push(`Log: ${payload.log_path}`)
  out.push('\n— oxDNA output ' + '—'.repeat(28))
  out.push(payload.log || '(no log output)')
  return out.join('\n')
}

/** Pure: per-stage timeline chips (glyph + kind + status) for a job. */
export function stageChips(job) {
  return (job?.stages || []).map((s) => ({
    kind: s.kind,
    status: s.status,
    glyph: _STAGE_GLYPH[s.status] || '·',
  }))
}

/** Pure: production-stage state — 'none' | 'running' | 'done' | 'failed'.
 *  Reflects the LATEST production run (jobs can have several). */
export function productionState(job) {
  const prods = (job?.stages || []).filter(s => s.kind === 'production')
  const prod = prods.length ? prods[prods.length - 1] : null
  if (!prod) return 'none'
  if (prod.status === 'done')   return 'done'
  if (prod.status === 'failed') return 'failed'
  if (prod.status === 'running' || prod.status === 'pending') return 'running'
  return 'none'
}

/** Pure: how many production runs a job has (done or otherwise). */
export function productionRunCount(job) {
  return (job?.stages || []).filter(s => s.kind === 'production').length
}

/** Pure: latest SAMPLING-stage state — 'none'|'running'|'done'|'failed' — over
 *  production AND electric-field stages.  The flexibility map (RMSF) pools either,
 *  so its toggle is gated on this (not productionState, which is production-only). */
export function samplingState(job) {
  const ss = (job?.stages || []).filter(s => s.kind === 'production' || s.kind === 'field')
  const last = ss.length ? ss[ss.length - 1] : null
  if (!last) return 'none'
  if (last.status === 'done')   return 'done'
  if (last.status === 'failed') return 'failed'
  if (last.status === 'running' || last.status === 'pending') return 'running'
  return 'none'
}

/** Pure: does the job have any trajectory data to scrub (≥1 stage started)? */
export function hasTrajectory(job) {
  return (job?.stages || []).some(s => s.status === 'done' || s.status === 'running')
}

/** Pure: is the job in an in-progress state (a spinner should show)? */
export function jobIsActive(job) {
  return ['queued', 'preparing', 'running'].includes(job?.status)
}

/** Pure: is the job actively running a RELAXATION stage (mc/md_relax/equil)? */
export function isRelaxRunning(job) {
  return job?.status === 'running' && !isProductionRunning(job)
}

/** Pure: is the job actively running its PRODUCTION stage? */
export function isProductionRunning(job) {
  return job?.status === 'running' && productionState(job) === 'running'
}

// Out-of-date detection + the roll-or-cancel guard are shared with the MD panel.
export { jobOutOfDate }

/** A spinning circular activity indicator (CSS class .nadoc-spinner). */
export function makeSpinner(color = 'currentColor', size = 11) {
  const s = document.createElement('span')
  s.className = 'nadoc-spinner'
  s.style.width = s.style.height = `${size}px`
  if (color) s.style.color = color
  s.setAttribute('aria-hidden', 'true')
  return s
}

/** Pure: a job whose relaxation has completed can seed a NAMD run (Phase 2).
 *  A completed status means the relaxation (and any production) finished, so a
 *  relaxed last_conf exists to hand off to NAMD. */
export function seedReady(job) {
  return job?.status === 'completed'
}

/** Pure: one-line confidence readout for a flexibility-map result.
 *  `r` = the displayRmsf return ({ nFrames, confidence:{rel_error, preliminary}, running }).
 *  Shows frames pooled + statistical RMSF error %, and a "Preliminary" warning for
 *  short or still-running runs.  Returns { text, preliminary }. */
export function flexConfidenceText(r) {
  const c = r?.confidence || {}
  const frames = c.n_frames ?? r?.nFrames ?? 0
  const errTxt = c.rel_error != null ? ` · est. RMSF error ±${Math.round(c.rel_error * 100)}%` : ''
  let warn = ''
  if (c.preliminary) {
    warn = r?.running ? ' · ⚠ Preliminary — production still running'
                      : ' · ⚠ Preliminary — short run'
  }
  return { text: `${frames} frame${frames === 1 ? '' : 's'} pooled${errTxt}${warn}`, preliminary: !!c.preliminary }
}

/** Pure: a "Resuming from checkpoint" note when the current running stage was
 *  resumed from its own checkpoint — so the progress bar resetting to 0 (the
 *  resumed run measures itself 0→100%) isn't mistaken for a restart from scratch. */
export function resumeNote(job) {
  if (job?.status !== 'running') return ''
  const cur = job?.stages?.[job.current_stage_idx]
  return cur?.resumed ? 'Resuming from checkpoint' : ''
}

/** Pure: is this an incomplete job that can be resumed (killed/failed mid-run)?
 *  A `stopped` job was interrupted (backend reconcile sets `current_stage_idx` to
 *  the unfinished stage); a `failed` job can be re-run from where it failed. */
export function isResumable(job) {
  return ['stopped', 'failed'].includes(job?.status)
}

/** Pure: label for the start/resume button. A never-run `queued` job reads
 *  "Start"; an interrupted (`stopped`/`failed`) job reads "Resume". */
export function startButtonLabel(job) {
  return isResumable(job) ? '↻ Resume' : '▶ Start'
}

/** Pure: list/detail status label + color — derives "production ready" + production states. */
export function jobListStatus(job) {
  const ps = productionState(job)
  if (job?.status === 'completed' && ps === 'none') return { label: 'production ready', color: _C.accent }
  if (ps === 'running') return { label: 'production', color: _C.warn }
  if (ps === 'done')    return { label: 'production done', color: _C.ok }
  if (ps === 'failed')  return { label: 'production failed', color: _C.err }
  return { label: job?.status ?? 'unknown', color: _STATUS_COLOR[job?.status] || _C.dim }
}

// Job-tree flatten + descendant-cascade helpers now live in the shared job_tree.js
// (both panels render the same parent→child hierarchy; imported at the top).
// Re-exported so existing importers (and tests) keep resolving them from here.
export { flattenJobTree, descendantIds }

/** Pure: the confirm-dialog copy for deleting a job.  A relaxed parent with
 *  field children warns that the children go too (cascade); a field child / a
 *  childless job gets a plain permanent-delete warning. */
export function deleteConfirmMessage(job, nChildren = 0) {
  const isChild = !!job?.parent_job_id
  if (nChildren > 0) {
    const s = nChildren === 1 ? '' : 's'
    if (isChild) {
      return { title: 'Delete field run + branches', confirmLabel: `Delete all (${nChildren + 1})`,
        message: `This field run has ${nChildren} electric-field run${s} chained off it.\n\n` +
          `Deleting it will permanently delete it AND all ${nChildren} field run${s}. This cannot be undone.` }
    }
    return { title: 'Delete relaxation + field runs', confirmLabel: `Delete all (${nChildren + 1})`,
      message: `This relaxed job has ${nChildren} electric-field run${s} branched from it.\n\n` +
        `Deleting it will permanently delete the relaxation AND all ${nChildren} field run${s}. This cannot be undone.` }
  }
  if (isChild) {
    return { title: 'Delete field run', confirmLabel: 'Delete',
      message: 'This electric-field run and its results will be permanently deleted. This cannot be undone.' }
  }
  return { title: 'Delete oxDNA job', confirmLabel: 'Delete',
    message: 'This oxDNA job and its results will be permanently deleted. This cannot be undone.' }
}

/** Pure: normalize a job's stored run conditions into the values the panel cards
 *  echo when the job is selected.  Reads `job.run_config` (surface / anchors /
 *  field / steps / bp-gate) plus the top-level backend/device/salt, falling back
 *  to the stage list for step counts and to `efield` for the field direction on
 *  jobs saved before run_config existed.  Returns:
 *    { advanced:{backend,device,salt,mcSteps,mdSteps,equilSteps,bpGate}|null,
 *      field:{field_pN,dir}|null, surface:{dir,offset_nm,stiff}|null,
 *      anchors:[…descriptors], prodSteps:number|null }
 *  `advanced` is null for an E-field/run child (it has no relaxation controls). */
export function runConfigForJob(job) {
  const rc = job?.run_config || {}
  const stages = job?.stages || []
  const stepOf = (kind) => {
    const s = stages.find(st => st.kind === kind)
    return s?.steps ?? null
  }
  const isChild = !!job?.parent_job_id
  const advanced = isChild ? null : {
    backend:    rc.backend ?? job?.backend ?? 'CUDA',
    device:     rc.device ?? job?.device ?? '0',
    salt:       rc.salt_concentration ?? job?.salt_concentration ?? null,
    mcSteps:    rc.mc_steps ?? stepOf('mc'),
    mdSteps:    rc.md_relax_steps ?? stepOf('md_relax'),
    equilSteps: rc.equil_steps ?? stepOf('equil'),
    bpGate:     rc.min_bp_retained ?? null,
  }
  // Field: prefer run_config.field; fall back to the efield record (older field
  // children stored {force_pN, dir} there before run_config existed).
  let field = rc.field ?? null
  const ef = job?.efield
  if (!field && ef && ef.force_pN != null && Array.isArray(ef.dir)) {
    field = { field_pN: ef.force_pN, dir: ef.dir }
  }
  return {
    advanced,
    field,
    surface:   rc.surface ?? null,
    anchors:   rc.anchors ?? [],
    prodSteps: rc.steps ?? stepOf('production') ?? null,
  }
}

/** Pure: hover title for an E-field child sub-item (its field params). */
export function fieldChildTitle(job) {
  const e = job?.efield || {}
  const dir = Array.isArray(e.dir) ? e.dir.map(n => (+n).toFixed(2)).join(', ') : '—'
  const pN = e.force_pN != null ? e.force_pN : '?'
  const na = e.n_anchored != null ? e.n_anchored : '?'
  return `E-field ${pN} pN/nt · dir (${dir}) · ${na} anchored`
}

/** Pure: which extra elements a consolidated run added — anchors / hard surface /
 *  electric field.  Reads `run_config` (with an `efield` fallback for older field
 *  children that predate run_config). */
export function runElements(job) {
  const cfg = runConfigForJob(job)
  const field = !!cfg.field
  const surface = !!cfg.surface
  const anchors = (Array.isArray(cfg.anchors) && cfg.anchors.length > 0) ||
                  (job?.efield?.n_anchored > 0)
  return { anchors, surface, field }
}

/** Pure: bracketed indicator tags for a run's added elements, in the order
 *  [A]nchors · [H]ard surface · [E]-field (e.g. "[A][H][E]").  Empty string for a
 *  plain production run. */
export function runIndicatorTags(job) {
  const el = runElements(job)
  return (el.anchors ? '[A]' : '') + (el.surface ? '[H]' : '') + (el.field ? '[E]' : '')
}

/** Pure: list-row label for a run child — "Run N" plus its element indicators.
 *  No lightning-bolt icon: the [E] tag denotes the electric field instead. */
export function runRowLabel(job, index) {
  const tags = runIndicatorTags(job)
  return `Run ${index}${tags ? ' ' + tags : ''}`
}

/** Pure: hover title for a run child describing its added elements. */
export function runChildTitle(job) {
  const el = runElements(job)
  if (el.field) return fieldChildTitle(job)
  const parts = []
  if (el.surface) parts.push('hard surface')
  if (el.anchors) {
    const n = job?.efield?.n_anchored || runConfigForJob(job).anchors?.length || 0
    parts.push(n ? `${n} anchored` : 'anchored')
  }
  return parts.length ? `Production run · ${parts.join(' · ')}` : 'Production run'
}

export function initOxdnaJobsPanel({ oxdnaDisplay = null, getWorkspacePath = null, getRunElements = null, applyRunConfig = null, oxdnaLive = null, getDesignLattice = null } = {}) {
  const panel   = document.getElementById('oxdna-jobs-panel')
  const heading = document.getElementById('oxdna-jobs-heading')
  const arrow   = document.getElementById('oxdna-jobs-arrow')
  const body    = document.getElementById('oxdna-jobs-body')
  if (!panel || !heading || !body) return

  const statusEl      = document.getElementById('oxdna-jobs-status')
  const runBtn        = document.getElementById('oxdna-jobs-run-btn')
  const prodBtn       = document.getElementById('oxdna-jobs-prod-btn')
  const prodStepsInput = document.getElementById('oxdna-jobs-prod-steps')
  const prodStatus    = document.getElementById('oxdna-jobs-prod-status')
  const autorefineBtn     = document.getElementById('oxdna-jobs-autorefine-btn')
  const autorefineStopBtn = document.getElementById('oxdna-jobs-autorefine-stop-btn')
  const autorefineStatus  = document.getElementById('oxdna-jobs-autorefine-status')
  const autorefineResult  = document.getElementById('oxdna-jobs-autorefine-result')
  const autorefineDevToggle = document.getElementById('oxdna-jobs-deviation-toggle')
  const autorefineDevStatus = document.getElementById('oxdna-jobs-deviation-status')
  let _autorefineRunning = false
  let _autorefineRunId = null
  let _autorefineFinalJobId = null    // the run's final oxDNA job (auto-selected on completion)
  let _autorefineLastAppliedPeriod = null  // last skip period applied live to the design
  let _autorefineCleanForDesign = false  // a run finished + design unchanged since (re-run guard)
  const _autorefineJobs = new Set()   // distinct job ids seen → live iteration count
  const _arJobIds = new Set()         // jobs created by autorefine → [AR] tag in the list (persists across runs)
  let _arSelectedJobId = null         // in-flight autorefine job auto-selected during the run
  let _arBase = '', _arColor = '#8b949e', _arSpin = 0, _arSpinTimer = null
  let _devBusy = false
  const exportBtn     = document.getElementById('oxdna-jobs-export-btn')
  const advToggle     = document.getElementById('oxdna-jobs-adv-toggle')
  const advArrow      = document.getElementById('oxdna-jobs-adv-arrow')
  const advBody       = document.getElementById('oxdna-jobs-adv-body')
  const backendSel    = document.getElementById('oxdna-jobs-backend')
  const deviceInput   = document.getElementById('oxdna-jobs-device')
  const saltInput     = document.getElementById('oxdna-jobs-salt')
  const mcStepsInput  = document.getElementById('oxdna-jobs-mc-steps')
  const mdStepsInput  = document.getElementById('oxdna-jobs-md-steps')
  const equilStepsInput = document.getElementById('oxdna-jobs-equil-steps')
  const bpGateInput   = document.getElementById('oxdna-jobs-bp-gate')
  const showAllToggle = document.getElementById('oxdna-jobs-show-all')

  const listEl     = document.getElementById('oxdna-jobs-list')
  const detailEl   = document.getElementById('oxdna-jobs-detail')
  const detailStatus = document.getElementById('oxdna-jobs-detail-status')
  const startBtn   = document.getElementById('oxdna-jobs-start-btn')
  const stopBtn    = document.getElementById('oxdna-jobs-stop-btn')
  const deleteBtn  = document.getElementById('oxdna-jobs-delete-btn')
  const archiveBtn = document.getElementById('oxdna-jobs-archive-btn')
  const archiveProgressEl = document.getElementById('oxdna-jobs-archive-progress')
  const _archive   = initJobArchive({ api, kind: 'oxdna' })
  const errorEl    = document.getElementById('oxdna-jobs-detail-error')
  const errorLogBtn = document.getElementById('oxdna-jobs-errorlog-btn')
  const progressEl = document.getElementById('oxdna-jobs-progress')
  const timelineEl = document.getElementById('oxdna-jobs-timeline')
  const healthEl   = document.getElementById('oxdna-jobs-health')
  const displayToggle = document.getElementById('oxdna-jobs-display-toggle')
  const alignToggle   = document.getElementById('oxdna-jobs-align-toggle')
  const displayStatus = document.getElementById('oxdna-jobs-display-status')
  const flexToggle    = document.getElementById('oxdna-jobs-flex-toggle')
  const flexStatus    = document.getElementById('oxdna-jobs-flex-status')
  const flexBar       = document.getElementById('oxdna-jobs-flex-bar')
  const flexLegend    = document.getElementById('oxdna-jobs-flex-legend')
  const seedBtn       = document.getElementById('oxdna-jobs-seed-btn')
  const seedStatus    = document.getElementById('oxdna-jobs-seed-status')
  const trajToggle    = document.getElementById('oxdna-jobs-traj-toggle')
  const trajStatus    = document.getElementById('oxdna-jobs-traj-status')
  const trajControls  = document.getElementById('oxdna-jobs-traj-controls')
  const trajPlay      = document.getElementById('oxdna-jobs-traj-play')
  const trajSlider    = document.getElementById('oxdna-jobs-traj-slider')
  const trajMarkers   = document.getElementById('oxdna-jobs-traj-markers')
  const trajLabel     = document.getElementById('oxdna-jobs-traj-label')
  const heavyGranSel  = document.getElementById('oxdna-jobs-heavy-granularity')
  const heavyWarn     = document.getElementById('oxdna-jobs-heavy-warn')
  const vizOffRadio   = document.getElementById('oxdna-jobs-viz-off')

  // The OxDNA display / Flexibility / Deviation / Trajectory views are mutually-
  // exclusive radios in the "Visualizations & processing" card (they share one bead
  // overlay).  Keep the "Off" radio checked whenever no view is active, so the group
  // always shows a selection — including after a programmatic turn-off (job switch,
  // lost trajectory, live-mode takeover, design edit).
  function _syncVizOffRadio() {
    if (!vizOffRadio) return
    const anyOn = [displayToggle, flexToggle, trajToggle, autorefineDevToggle].some(t => t?.checked)
    if (!anyOn) vizOffRadio.checked = true
  }

  // Atomistic/surface reconstruction detail (coarse=snap to downsampled bake /
  // fine=rebuild every frame). Applies to all three displays; only visible effect
  // when the scene is in an atomistic or surface representation.
  heavyGranSel?.addEventListener('change', () => {
    const g = heavyGranSel.value === 'fine' ? 'fine' : 'coarse'
    oxdnaDisplay?.setGranularity?.(g)
    if (heavyWarn) heavyWarn.style.display = g === 'fine' ? 'block' : 'none'
  })

  // ── State ──────────────────────────────────────────────────────────────────
  let _jobs       = []
  let _selectedId = null
  let _progress   = null
  let _pollTimer  = null
  let _listSig    = null   // last-rendered list signature (avoids spinner-restart churn)
  let _legendEl   = null   // status-symbol legend, inserted once after the list
  let _collapsed  = getSectionCollapsed('dynamics', 'oxdna-jobs-panel', true)
  let _advOpen    = false
  let _available  = false
  let _launching  = false
  let _seeding    = false
  let _flexBusy   = false
  let _trajBusy   = false
  let _lastFrameIndex = null   // last live frame the relaxed display was refreshed to
  let _displayBaseText = ''    // base display-status text (countdown appended while running)
  let _displayBaseColor = _C.ok

  // ── Autorefine skips/loops (square-lattice self-consistency tuning loop) ────────
  const _SPIN = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']
  function _renderArStatus() {
    if (!autorefineStatus) return
    const prefix = _autorefineRunning ? _SPIN[_arSpin % _SPIN.length] + ' ' : ''
    autorefineStatus.textContent = prefix + (_arBase || '')
    autorefineStatus.style.color = _arColor
  }
  function _setAutorefineStatus(msg, color, spinning = false) {
    _arBase = msg || ''; _arColor = color || '#8b949e'
    if (spinning && !_arSpinTimer) {
      _arSpinTimer = setInterval(() => { _arSpin++; _renderArStatus() }, 120)
    } else if (!spinning && _arSpinTimer) {
      clearInterval(_arSpinTimer); _arSpinTimer = null
    }
    _renderArStatus()
  }
  function _updateAutorefineButton() {
    if (!autorefineBtn) return
    const lattice = getDesignLattice?.()
    const ok = lattice === 'SQUARE' && !_autorefineRunning && _available
    autorefineBtn.disabled = !ok
    autorefineBtn.style.cursor = ok ? 'pointer' : 'not-allowed'
    autorefineBtn.style.background = ok ? '#3a2a12' : '#2a1f12'
    autorefineBtn.style.color = ok ? '#e3b341' : '#484f58'
    autorefineBtn.style.borderColor = ok ? '#bb8009' : '#30363d'
    autorefineBtn.title = (lattice && lattice !== 'SQUARE')
      ? 'Autorefine currently supports SQUARE lattice designs only (curved/twisted '
        + 'designs and other lattices are planned).'
      : 'Autorefine skips/loops: iteratively tune the design\'s skip/loop placement, '
        + 'relaxing in oxDNA each round, until the simulated time-averaged structure '
        + 'matches the geometry your design depicts. Reports a before-vs-after deviation score.'
    if (autorefineStopBtn) {
      autorefineStopBtn.style.display = _autorefineRunning ? 'block' : 'none'
      if (_autorefineRunning) autorefineStopBtn.disabled = false
    }
  }
  const _fmtTwist = v => (v == null ? '—' : `${Number(v).toFixed(1)}°`)
  const _fmtNm    = v => (v == null ? '—' : `${Number(v).toFixed(2)} nm`)
  const _SUBSTAGE = { mc: 'relaxing', md_relax: 'relaxing', equil: 'equilibrating',
                      production: 'producing' }
  function _iterRow(it) {
    const badge = it.early_reject ? '<span style="color:#f0883e">rejected (early)</span>'
      : it.status === 'met' ? '<span style="color:#3fb950">accepted ✓</span>'
      : it.status === 'unmet' ? '<span style="color:#f0883e">rejected</span>'
      : `<span style="color:#6e7681">${it.status || '—'}</span>`
    return `<div style="display:flex;justify-content:space-between;gap:8px;color:#8b949e">`
      + `<span>period ${it.period} → ${_fmtTwist(it.twist_residual_deg)}</span>${badge}</div>`
  }
  // Fine-tune summary: edits kept + the worst-local-deviation before→after they achieved.
  function _finetuneBlock(ft) {
    if (!ft) return ''
    const kept = ft.edits_kept || []
    const rows = kept.map(e =>
      `<div style="color:#c9d1d9">• ${e.op} h${e.helix_id} bp${e.bp_index} → dev ${_fmtNm(e.dev_max)}, twist ${_fmtTwist(e.twist)}</div>`).join('')
    const b = ft.before || {}, a = ft.after || {}
    return `<div style="margin-top:4px;border-top:1px solid #21262d;padding-top:3px">`
      + `<div style="color:#6e7681;margin-bottom:2px">Fine-tune — ${kept.length} of ${ft.n_candidates ?? 0} `
      + `hotspot edit${kept.length === 1 ? '' : 's'} kept</div>`
      + `<div style="color:#8b949e">Worst local deviation ${_fmtNm(b.dev_max)} → `
      + `<span style="color:#3fb950">${_fmtNm(a.dev_max)}</span></div>`
      + (rows || '<div style="color:#6e7681">no edit improved the structure — left as uniform</div>')
      + `</div>`
  }
  function _renderAutorefineResult(res) {
    if (!autorefineResult || !res) return
    const b = res.before || {}, a = res.after || {}
    const row = (label, before, after, hi) => `<tr${hi ? ' style="font-weight:600"' : ''}>`
      + `<td style="padding:1px 6px;color:#8b949e">${label}</td>`
      + `<td style="padding:1px 6px;text-align:right;color:#f0883e">${before}</td>`
      + `<td style="padding:1px 6px;text-align:right;color:#3fb950">${after}</td></tr>`
    const twist = (hi) => row('Global twist deviation', _fmtTwist(b.twist_residual_deg), _fmtTwist(a.twist_residual_deg), hi)
    const dev   = (hi) => row('Deviation from design', _fmtNm(b.rmsd_nm), _fmtNm(a.rmsd_nm), hi)
    // Plain square lattice (no bend/twist) headlines global twist; otherwise RMSD.
    const headline = res.primary_metric === 'global_twist_deg' ? twist(true) + dev(false)
                                                               : dev(true) + twist(false)
    const iters = (res.iterations || []).map(_iterRow).join('')
    autorefineResult.innerHTML = `
      <div style="font-size:var(--text-xs);border:1px solid #30363d;border-radius:3px;padding:5px;background:#0d1117">
        <div style="color:#e3b341;font-weight:600;margin-bottom:3px">Autorefine — before vs after</div>
        <table style="width:100%;border-collapse:collapse;font-size:var(--text-xs)">
          <tr style="color:#6e7681"><td></td><td style="text-align:right">Before</td><td style="text-align:right">After</td></tr>
          ${headline}
          <tr><td style="padding:1px 6px;color:#8b949e">Skip period (bp)</td>
              <td style="padding:1px 6px;text-align:right;color:#6e7681">—</td>
              <td style="padding:1px 6px;text-align:right;color:#c9d1d9">${res.converged_period ?? '—'}</td></tr>
        </table>
        ${iters ? `<div style="margin-top:4px;border-top:1px solid #21262d;padding-top:3px">`
          + `<div style="color:#6e7681;margin-bottom:2px">Iterations tried</div>${iters}</div>` : ''}
        ${_finetuneBlock(res.finetune)}
        <div style="color:#6e7681;margin-top:3px">${
          res.status === 'met' ? 'Converged: simulated structure matches the design within tolerance.'
          : res.status === 'stopped' ? 'Stopped — showing the best result reached so far.'
          : 'Best achieved (did not fully converge within the iteration budget).'}</div>
      </div>`
  }
  // Apply a period's skips to the design LIVE (deduped), so the user watches the skips
  // move each iteration and can stop early if they dislike the automated placement.
  async function _maybeApplyPeriod(runId, period) {
    if (period == null || period === _autorefineLastAppliedPeriod) return
    const applied = await api.applyAutorefineSkips(runId, period)
    if (applied) {
      api.syncDesignResponse(applied)   // editor + Feature Log update (fires design-changed)
      _autorefineLastAppliedPeriod = period
    }
  }
  function _pollAutorefine(id) {
    const tick = async () => {
      const s = await api.getAutorefine(id)
      if (!s) {
        _autorefineRunning = false
        _setAutorefineStatus('Status unavailable: ' + (api.lastErrorMessage?.() || 'error'), '#f85149')
        _updateAutorefineButton(); return
      }
      if (s.state === 'running') {
        const ev = s.last_event || {}
        // Live sub-stage from the in-flight job (relaxing / producing); iteration count
        // = distinct jobs the run has spawned so far.
        let sub = s.phase === 'before' ? 'baseline' : 'working'
        if (s.current_job_id) {
          _autorefineJobs.add(s.current_job_id)
          _arJobIds.add(s.current_job_id)         // tag it [AR] in the job list
          const job = await api.getOxdnaJob(s.current_job_id).catch(() => null)
          const run = (job?.stages || []).find(st => st.status === 'running')
          if (run) sub = _SUBSTAGE[run.kind] || run.kind
          // Select the in-flight autorefine job as soon as it appears (and follow each
          // new iteration's job) so the user watches the active run in the list.
          if (s.current_job_id !== _arSelectedJobId) {
            _arSelectedJobId = s.current_job_id
            await _fetchJobs()
            if (_jobs.some(j => j.job_id === s.current_job_id)) await _selectJob(s.current_job_id)
          }
        }
        const iter = _autorefineJobs.size
        if (s.phase === 'finetune') {
          // Fine-tune pass: report the greedy edit search (hotspots found, each add/remove
          // kept or reverted).  The exact pattern lands on the design at completion.
          let t = 'Fine-tuning'
          if (ev.ft_phase === 'candidates') t += ` · ${ev.n ?? 0} hotspot${ev.n === 1 ? '' : 's'} found`
          else if (ev.ft_phase === 'edit')
            t += ` · edit ${(ev.i ?? 0) + 1}: ${ev.op} h${ev.helix_id} bp${ev.bp_index}`
              + ` — ${ev.accepted ? '✓ kept' : '✗ reverted'} (dev ${_fmtNm(ev.dev_max)})`
          else t += ' · measuring'
          _setAutorefineStatus(`${t} · ${sub}…`, '#e3b341', true)
        } else {
          let last = ''
          if (s.phase === 'iteration')
            last = `  ·  last: period ${ev.period} → ${_fmtTwist(ev.steering?.bundle_twist_residual_deg)}`
              + (ev.early_reject ? ' (rejected early)' : '')
          _setAutorefineStatus(`Autorefine · iteration ${iter} · ${sub}…${last}`, '#e3b341', true)
          // Land THIS iteration's (uniform) skip pattern on the design so the user sees it move.
          await _maybeApplyPeriod(id, s.current_period)
        }
        setTimeout(tick, 3000)
      } else if (s.state === 'done' || s.state === 'stopped') {
        _autorefineRunning = false; _autorefineRunId = null
        const finalJob = s.current_job_id || null
        const period = s.result?.converged_period
        _setAutorefineStatus(s.state === 'stopped' ? '■ Autorefine stopped.' : '✓ Autorefine complete.',
                             s.state === 'stopped' ? '#f0883e' : '#3fb950')
        _renderAutorefineResult(s.result)
        // Ensure the final converged pattern is on the design (a revertable/seekable feature-log
        // entry).  A fine-tuned/regional run has an EXPLICIT non-uniform pattern → apply it with
        // no period (the backend lays converged_skips verbatim); a plain uniform run applies the
        // converged period (per-iteration applies usually landed it already).
        const placement = s.result?.placement
        if (placement === 'finetuned' || placement === 'regional') {
          const applied = await api.applyAutorefineSkips(id)   // no period → explicit pattern
          if (applied) {
            api.syncDesignResponse(applied)
            showToast(`Autorefine ${placement} skips applied — see the Feature Log`, 'ok')
          }
        } else if (period != null) {
          await _maybeApplyPeriod(id, period)
          showToast(`Autorefine skips applied (period ${period} bp) — see the Feature Log`, 'ok')
        }
        // Set AFTER the apply's design-changed event (which clears these) so they persist.
        _autorefineFinalJobId = finalJob
        _autorefineCleanForDesign = true
        await _fetchJobs()                     // the run's jobs are now listed…
        if (finalJob && _jobs.some(j => j.job_id === finalJob))
          await _selectJob(finalJob)           // …select the final one → deviation unlocks
        _updateAutorefineButton(); _updateButtons(_selectedJob())
      } else {
        _autorefineRunning = false; _autorefineRunId = null
        _setAutorefineStatus('✕ Autorefine error: ' + (s.error || 'unknown'), '#f85149')
        _updateAutorefineButton()
      }
    }
    tick()
  }
  autorefineBtn?.addEventListener('click', async () => {
    if (autorefineBtn.disabled || _autorefineRunning) return
    if (getDesignLattice?.() !== 'SQUARE') {
      _setAutorefineStatus('Square-lattice designs only for now.', '#f85149'); return
    }
    // If a run already finished on this exact design (nothing edited since), make the
    // user confirm a redundant re-run.
    if (_autorefineCleanForDesign) {
      if (!confirm('You already autorefined this design and nothing has changed since. '
                 + 'Running again will repeat the same simulations. Run anyway?')) return
    } else if (!confirm('Autorefine runs many oxDNA simulations (a relax + production each round) '
               + 'and can take a long time. Start now?')) return
    _autorefineRunning = true
    _autorefineJobs.clear()
    _arSelectedJobId = null
    _autorefineLastAppliedPeriod = null
    _updateAutorefineButton()
    if (autorefineResult) autorefineResult.innerHTML = ''
    _setAutorefineStatus('Starting autorefine…', '#e3b341', true)
    const r = await api.startAutorefine({
      backend: backendSel?.value || 'CUDA',
      device: deviceInput?.value || '0',
      salt_concentration: parseFloat(saltInput?.value || '0.5'),
      design_source_path: _currentPartPath(),   // so the run's jobs list with this design
      // fine-tune (gentle global + local skip edits) is the standard autorefine now —
      // always on (the route defaults finetune=True).
    })
    if (!r || !r.autorefine_id) {
      _autorefineRunning = false
      _setAutorefineStatus('Failed to start: ' + (api.lastErrorMessage?.() || 'error'), '#f85149')
      _updateAutorefineButton(); return
    }
    _autorefineRunId = r.autorefine_id
    _updateAutorefineButton()        // reveal the Stop button
    _pollAutorefine(r.autorefine_id)
  })
  autorefineStopBtn?.addEventListener('click', async () => {
    if (!_autorefineRunId) return
    autorefineStopBtn.disabled = true
    _setAutorefineStatus('Stopping autorefine…', '#f0883e', true)
    await api.stopAutorefine(_autorefineRunId)   // poll loop transitions to stopped
  })

  // ── Deviation map toggle (mean structure of the latest autorefine, coloured by
  //    per-base deviation from design) — enabled only after a run completes. ────────
  // Deviation map is a per-JOB display (like the flexibility map): the selected job's
  // production mean structure recoloured by per-base deviation from its design.  Gated
  // (in _updateButtons, mirroring the flex toggle) on the selected job having sampling.
  function _setDevStatus(text, color = '#8b949e') {
    if (autorefineDevStatus) { autorefineDevStatus.textContent = text || ''; autorefineDevStatus.style.color = color }
  }
  function _setDeviationOff() {
    if (oxdnaDisplay?.mode() === 'deviation') oxdnaDisplay.stopAndRestore()
    if (autorefineDevToggle) autorefineDevToggle.checked = false
    _setDevStatus('')
    _syncVizOffRadio()
    _updateButtons(_selectedJob())
  }
  async function _refreshDeviation() {
    if (!_selectedId) return
    _devBusy = true; _updateButtons(_selectedJob())
    _setDevStatus('Loading deviation map…')
    const resp = await api.getOxdnaDeviation(_selectedId)
    _devBusy = false; _updateButtons(_selectedJob())
    if (!resp || !resp.ready) {
      if (autorefineDevToggle) autorefineDevToggle.checked = false
      _setDevStatus('Deviation map unavailable: ' + (resp?.reason || api.lastErrorMessage?.() || 'not ready'), '#f85149')
      return
    }
    const r = oxdnaDisplay?.displayDeviation(resp)
    if (!r?.ok) {
      if (autorefineDevToggle) autorefineDevToggle.checked = false
      _setDevStatus('Could not render deviation map (' + (r?.reason || 'error') + ')', '#f85149')
      return
    }
    _setDevStatus(`Mean vs design — deviation ${_fmtNm(r.min)} (green) → ${_fmtNm(r.max)} (red), `
      + `mean ${_fmtNm(r.mean)}, ${r.nFrames ?? '?'} frames`, '#3fb950')
    _updateButtons(_selectedJob())
  }
  autorefineDevToggle?.addEventListener('change', async () => {
    if (autorefineDevToggle.checked) {
      if (!_selectedId) { autorefineDevToggle.checked = false; showToast('Select an oxDNA job first', 'warn'); _syncVizOffRadio(); return }
      oxdnaLive?.stop()                 // mutually exclusive with relaxed / flex / trajectory / live
      if (displayToggle?.checked) _setDisplayOff()
      if (flexToggle?.checked) _setFlexOff()
      if (trajToggle?.checked) _setTrajOff()
      await _refreshDeviation()
    } else {
      _setDeviationOff()
    }
  })
  // Trajectory status: base summary text, OR a "building…" / "preparing playback…"
  // overlay while a heavy reconstruction is in flight (declared here, before the player
  // init below, because the player's onBeforePlay callback reads _trajPrep).
  let _trajBaseText = '', _trajBaseColor = _C.ok, _heavyBuildKind = null, _trajPrep = null
  let _flexBaseText = '', _flexBaseColor = _C.dim

  // Trajectory player (play/pause + scrub slider); seeks drive the display frame.
  // Heavy reps (atomistic/surface) rebuild each frame slowly, so PLAY first pre-builds
  // every coarse playback frame (spinner + "building k/N"), then runs the loop smoothly.
  const trajPlayer = initOxdnaTrajectoryPlayer({
    playBtn: trajPlay, slider: trajSlider, markersEl: trajMarkers, label: trajLabel,
    onSeek: (i) => oxdnaDisplay?.showFrame(i),
    onBeforePlay: async () => {
      if (!oxdnaDisplay) return true
      oxdnaDisplay.setPlaying(true)
      const r = await oxdnaDisplay.prebuildHeavy((done, total) => {
        _trajPrep = total > 1 ? { done, total } : null   // total≤1 = CG (instant) → no notice
        _renderTrajStatus()
      })
      _trajPrep = null
      _renderTrajStatus()
      return r?.ok !== false
    },
    onPlayStateChange: (playing) => {
      if (!playing) { oxdnaDisplay?.setPlaying(false); _trajPrep = null; _renderTrajStatus() }
    },
  })

  // Workspace colour-scale widget (middle-right); editing its bounds re-colours
  // the active flexibility map live without re-fetching.
  const flexScale = initFlexScale({
    onBoundsChange: (lo, hi) => oxdnaDisplay?.recolorRmsf(lo, hi),
  })
  const _SHOW_ALL_KEY = 'nadoc:oxdna-jobs-show-all'

  if (showAllToggle) showAllToggle.checked = localStorage.getItem(_SHOW_ALL_KEY) === '1'

  // ── Collapse ───────────────────────────────────────────────────────────────
  body.style.display = _collapsed ? 'none' : ''
  arrow?.classList.toggle('is-collapsed', _collapsed)
  heading.addEventListener('click', () => {
    _collapsed = !_collapsed
    body.style.display = _collapsed ? 'none' : ''
    arrow?.classList.toggle('is-collapsed', _collapsed)
    setSectionCollapsed('dynamics', 'oxdna-jobs-panel', _collapsed)
    if (!_collapsed) _onOpen()
  })

  advToggle?.addEventListener('click', () => {
    _advOpen = !_advOpen
    if (advBody) advBody.style.display = _advOpen ? '' : 'none'
    if (advArrow) advArrow.style.transform = _advOpen ? 'rotate(90deg)' : ''
  })

  // Jobs + Visualizations + Health cards: simple collapse (start open).
  for (const [tid, bid, aid] of [
    ['oxdna-jobs-list-toggle',   'oxdna-jobs-list-body',   'oxdna-jobs-list-arrow'],
    ['oxdna-jobs-viz-toggle',    'oxdna-jobs-viz-body',    'oxdna-jobs-viz-arrow'],
    ['oxdna-jobs-health-toggle', 'oxdna-jobs-health-body', 'oxdna-jobs-health-arrow'],
  ]) {
    const t = document.getElementById(tid)
    const bd = document.getElementById(bid)
    const ar = document.getElementById(aid)
    t?.addEventListener('click', () => {
      const open = bd && bd.style.display !== 'none'
      if (bd) bd.style.display = open ? 'none' : ''
      ar?.classList.toggle('is-collapsed', open)
    })
  }

  // ── Availability ─────────────────────────────────────────────────────────
  async function _checkAvailable() {
    if (!statusEl) return
    const d = await api.oxdnaAvailable().catch(() => null)
    _available = !!d?.available
    if (_available) {
      _setStatus(`oxDNA ready · ${d.oxdna_bin}`, _C.ok)
      if (deviceInput && d.recommended_device && !deviceInput.dataset.userSet) {
        deviceInput.value = d.recommended_device
      }
    } else {
      _setStatus('oxDNA binary not found — set $OXDNA_BIN or build ~/oxDNA', _C.err)
    }
    _updateButtons(_selectedJob())
  }
  deviceInput?.addEventListener('input', () => { if (deviceInput) deviceInput.dataset.userSet = '1' })

  function _setStatus(text, color = _C.dim) {
    if (statusEl) { statusEl.textContent = text; statusEl.style.color = color }
  }
  function _setDisplayStatus(text, color = _C.dim) {
    if (displayStatus) { displayStatus.textContent = text; displayStatus.style.color = color }
  }

  // ── Job filtering (current design only, unless "show all") ────────────────
  function _currentPartPath() {
    const raw = getWorkspacePath ? getWorkspacePath() : null
    return raw || null
  }
  function _visibleJobs() {
    return filterJobsForPart(_jobs, _currentPartPath(), !!showAllToggle?.checked)
  }

  showAllToggle?.addEventListener('change', () => {
    localStorage.setItem(_SHOW_ALL_KEY, showAllToggle.checked ? '1' : '0')
    _renderList()
  })

  // ── Fetch + poll ───────────────────────────────────────────────────────────
  async function _fetchJobs() {
    const jobs = await api.listOxdnaJobs().catch(() => null)
    if (Array.isArray(jobs)) {
      _jobs = jobs
      _renderList()
      // Refresh the launch-button spinners from live job state even when nothing
      // is selected (e.g. after a page reload while a job is still running).
      _updateButtons(_selectedJob())
      if (_selectedId) {
        const sel = _jobs.find(j => j.job_id === _selectedId)
        if (sel) {
          _progress = await api.getOxdnaProgress(_selectedId).catch(() => null)
          _renderDetail(sel)
          // Relaxed display follows the run live: pull a new frame whenever the
          // sim writes one (frame_index advances) or the job finishes; between
          // frames just tick the "next frame ~Xs" countdown.  Gate on the toggle
          // (user intent) not the controller's active flag, so a job switched to
          // before it has written a frame still gets followed once it does.
          if (displayToggle?.checked && oxdnaDisplay
              && oxdnaDisplay.mode() !== 'rmsf' && oxdnaDisplay.mode() !== 'trajectory') {
            if (sel.status === 'completed') {
              _refreshDisplay()
            } else if (sel.status === 'running') {
              const fi = _progress?.frame_index
              if (fi != null && fi !== _lastFrameIndex) {
                _refreshDisplay()   // _refreshDisplay syncs _lastFrameIndex
              } else {
                _renderDisplayStatus()   // tick the countdown only
              }
            }
          }
        }
      }
    }
    _scheduleNextPoll()
  }

  function _hasActiveJob() {
    return _visibleJobs().some(j => ['queued', 'preparing', 'running'].includes(j.status))
  }
  function _scheduleNextPoll() {
    if (_pollTimer) { clearTimeout(_pollTimer); _pollTimer = null }
    if (_collapsed) return
    if (_hasActiveJob() || (_selectedId && _jobs.find(j => j.job_id === _selectedId && j.status === 'running'))) {
      _pollTimer = setTimeout(_fetchJobs, POLL_MS)
    }
  }

  function _onOpen() {
    _checkAvailable()
    _fetchJobs()
  }

  // ── Launch ─────────────────────────────────────────────────────────────────
  runBtn?.addEventListener('click', async () => {
    if (_launching || !_available) return
    if (!(await confirmNoConcurrentJob())) return
    if (!(await confirmGpuNotBusy(deviceInput?.value || '0'))) return
    oxdnaLive?.stop()   // a relaxation supersedes any live session (shared overlay)
    _launching = true
    runBtn.disabled = true
    _setStatus('Preparing relaxation job…', _C.accent)
    _updateButtons(_selectedJob())   // show the relax spinner immediately
    const body = {
      backend:            backendSel?.value || 'CUDA',
      device:             deviceInput?.value || '0',
      salt_concentration: parseFloat(saltInput?.value || '0.5'),
      mc_steps:           parseInt(mcStepsInput?.value || '1000', 10),
      md_relax_steps:     parseInt(mdStepsInput?.value || '1000000', 10),
      equil_steps:        parseInt(equilStepsInput?.value || '100000', 10),
      min_bp_retained:    parseFloat(bpGateInput?.value || '0.5'),
      autostart:          true,
      design_source_path: _currentPartPath(),
    }
    // Relax-on-a-surface: a structure relaxed free settles differently than one
    // bound to a surface, so relaxation carries the hard surface + anchors too —
    // but NOT the electric field (a field-relaxed structure isn't how it'd settle).
    const el = getRunElements?.() || {}
    if (el.surface?.enabled) {
      body.surface = { dir: el.surface.dir, offset_nm: el.surface.offsetNm, stiff: el.surface.stiff }
    }
    if (el.anchors?.length) body.anchors = el.anchors
    try {
      const fc = await api.estimateOxdnaDisk(body)
      if (!(await confirmDiskSpaceOk(fc))) {
        _launching = false
        runBtn.disabled = false
        _setStatus('', _C.muted)
        _updateButtons(_selectedJob())
        return
      }
    } catch { /* forecast is best-effort — never block a launch on it */ }
    const job = await api.createOxdnaJob(body).catch(() => null)
    _launching = false
    _updateButtons(_selectedJob())
    if (job?.job_id) {
      _selectedId = job.job_id
      showToast('oxDNA relaxation started', 'ok')
      _setStatus('Relaxation running…', _C.warn)
      await _fetchJobs()
    } else {
      const detail = api.lastErrorMessage?.()
      if (isUndefinedSequenceError(detail)) {
        // Design has undefined bases — block with a clear warning popup rather
        // than a quiet inline status line.
        showSequenceWarningModal({ message: detail })
        _setStatus('Relaxation blocked — finish assigning sequences', _C.err)
      } else {
        _setStatus(detail || 'Failed to start relaxation (see console)', _C.err)
      }
    }
  })

  // ── List ─────────────────────────────────────────────────────────────────
  // Signature of what the list actually renders (id + status + production state +
  // selection) — a running job's health/progress changing must NOT re-render the
  // list, or the row spinners restart their animation every poll.
  function _listSignature(jobs) {
    return jobs.map(j => `${j.job_id}:${j.status}:${productionState(j)}:${j.out_of_date ? 1 : 0}:${j.archived ? 1 : 0}:${j.size_bytes ?? ''}`).join(',') +
           `|sel=${_selectedId}`
  }

  function _renderList() {
    if (!listEl) return
    const jobs = _visibleJobs().slice().sort((a, b) => b.created_at - a.created_at)
    const sig = _listSignature(jobs)
    if (sig === _listSig && listEl.childElementCount > 0) return
    _listSig = sig
    if (!jobs.length) {
      listEl.innerHTML = `<div style="color:${_C.dim};padding:6px 4px;font-size:11px">No oxDNA jobs for this design yet.</div>`
      return
    }
    listEl.innerHTML = ''
    let rootNo = 0
    for (const { job, depth, index } of flattenJobTree(jobs)) {
      if (depth === 0) rootNo += 1
      listEl.appendChild(_jobRow(job, { isChild: depth > 0, index, depth, listIndex: rootNo }))
    }
    if (!_legendEl) { _legendEl = makeStatusLegend(); listEl.after(_legendEl) }
  }

  // One job row: [N] name · timestamp · status-symbol (parent relaxation, or a
  // depth-indented numbered E-field child).
  function _jobRow(job, { isChild = false, index = 0, depth = 0, listIndex = 0 }) {
    const row = document.createElement('div')
    row.dataset.jobId = job.job_id
    row.style.cssText =
      `display:flex;align-items:center;gap:6px;padding:4px 6px;cursor:pointer;border-radius:4px;` +
      `font-size:11px;${depth ? `padding-left:${6 + depth * 14}px;` : ''}` +
      `${job.job_id === _selectedId ? 'background:#2a3a4a;' : ''}`
    const badge = statusBadge(statusKeyFor('oxdna', job.status, productionState(job)))

    // Leading list index (root jobs only; children show their run number).
    const idx = document.createElement('span')
    idx.textContent = isChild ? '' : `[${listIndex}]`
    idx.style.cssText = `flex-shrink:0;color:${_C.dim};font-family:var(--font-mono)`

    const label = document.createElement('span')
    label.style.cssText = 'flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap'
    if (isChild) {
      label.textContent = runRowLabel(job, index)
      row.title = runChildTitle(job)
    } else {
      label.textContent = jobDisplayName(job)
    }

    const ts = document.createElement('span')
    ts.textContent = formatJobTime(job.created_at)
    ts.style.cssText = `flex-shrink:0;color:${_C.dim};font-size:10px;font-family:var(--font-mono)`

    // On-disk size of this job's folder (resolves to the archive location when archived).
    const size = document.createElement('span')
    size.textContent = job.size_bytes ? formatBytes(job.size_bytes) : ''
    size.style.cssText = `flex-shrink:0;color:${job.archived ? _C.warn : _C.dim};font-size:10px;font-family:var(--font-mono)`
    if (job.archived) size.title = `Archived → ${job.archive_path || ''}`

    // Status symbol: animated spinner while active, else the badge shape.
    const sym = jobIsActive(job)
      ? makeSpinner(badge.color, 10)
      : Object.assign(document.createElement('span'), { textContent: badge.symbol })
    sym.style.flexShrink = '0'
    sym.title = badge.label
    if (!jobIsActive(job)) sym.style.color = badge.color

    row.append(idx)
    // [AR] designation for jobs created by an Autorefine run.
    if (_arJobIds.has(job.job_id)) {
      const ar = Object.assign(document.createElement('span'), { textContent: '[AR]' })
      ar.style.cssText = `flex-shrink:0;color:#e3b341;font-family:var(--font-mono);font-weight:600`
      ar.title = 'Created by Autorefine skips/loops'
      row.append(ar)
    }
    row.append(label, ts, size)
    if (job.archived) {
      const box = Object.assign(document.createElement('span'), { textContent: '📦' })
      box.style.cssText = 'flex-shrink:0;font-size:10px'
      box.title = `Archived → ${job.archive_path || ''}`
      row.append(box)
    }
    // Out-of-date marker: the design changed since this job was relaxed, so
    // live/production would be inconsistent (only Relax stays available).
    // Suppressed WHILE an autorefine run is active: the loop deliberately edits the
    // design (it lands each iteration's skip pattern live), which would otherwise flag
    // every job stale mid-run — don't surface design-difference warnings until the run
    // completes.
    if (jobOutOfDate(job) && !_autorefineRunning) {
      const warn = Object.assign(document.createElement('span'), { textContent: '⚠' })
      warn.className = 'oxdna-job-stale-warn'   // stable hook for the AF-26 staleness e2e
      warn.style.cssText = `flex-shrink:0;color:${_C.warn};font-size:11px`
      warn.title = 'Design changed since this job was relaxed — run a new Relax, or roll the feature log back, before live/production.'
      row.append(warn)
    }
    row.append(sym)
    row.dataset.jobId = job.job_id   // stable per-row selector (rows are otherwise id-less)
    row.addEventListener('click', () => { _selectJob(job.job_id) })
    return row
  }

  // Select a job by id: pull its progress, render list + detail, echo its run
  // conditions into every card (field arrow / surface / anchors), and follow the
  // OxDNA display to it.  Used by row clicks AND by auto-selecting a freshly
  // started run so the new list item is selected.
  async function _selectJob(jobId) {
    const job = _jobs.find(j => j.job_id === jobId)
    if (!job) return
    _selectedId = jobId
    _progress = await api.getOxdnaProgress(jobId).catch(() => null)
    _renderList()
    _renderDetail(job)
    _applyRunControls(job)   // echo this run's conditions into every card
    // If the "OxDNA display" toggle is on, follow it to the newly-selected job
    // (re-deform the model to THIS job's relaxed positions, not the old one's).
    if (displayToggle?.checked && oxdnaDisplay?.mode() !== 'rmsf' && oxdnaDisplay?.mode() !== 'trajectory') {
      _lastFrameIndex = null
      await _refreshDisplay()
    }
    _scheduleNextPoll()
  }

  // Repopulate the panel's own relaxation/production inputs AND the external
  // Hard-surface / Anchors / E-field cards with the conditions this job ran with,
  // so clicking a job shows exactly what it used.  Fired only on an explicit row
  // click (never on a status poll, which would clobber the user mid-edit).
  function _applyRunControls(job) {
    const cfg = runConfigForJob(job)
    if (cfg.advanced) {
      const a = cfg.advanced
      if (backendSel && a.backend) backendSel.value = a.backend
      if (deviceInput && a.device != null) { deviceInput.value = a.device; deviceInput.dataset.userSet = '1' }
      if (saltInput && a.salt != null) saltInput.value = String(a.salt)
      if (mcStepsInput && a.mcSteps != null) mcStepsInput.value = String(a.mcSteps)
      if (mdStepsInput && a.mdSteps != null) mdStepsInput.value = String(a.mdSteps)
      if (equilStepsInput && a.equilSteps != null) equilStepsInput.value = String(a.equilSteps)
      if (bpGateInput && a.bpGate != null) bpGateInput.value = String(a.bpGate)
    }
    if (prodStepsInput && cfg.prodSteps != null) prodStepsInput.value = String(cfg.prodSteps)
    applyRunConfig?.(cfg, job)
  }

  // No job selected → clear the run cards so the E-field arrow (and surface /
  // anchor glow) don't linger from a previously-selected field run.  The arrow is
  // only shown when a field has been applied to the *current* job.
  function _clearRunCards() {
    applyRunConfig?.({ advanced: null, field: null, surface: null, anchors: [] }, null)
  }

  // Reset every relaxation/production INPUT back to its index.html default — used
  // when a design is closed or a different one is opened, so the panel doesn't
  // carry the previous design's (or last-selected job's) settings.  Also clears
  // the run cards (field/surface/anchors) and drops the device "user set" flag so
  // the recommended device re-applies.
  function _resetControlsToDefaults() {
    resetControlsToDefaults([
      backendSel, deviceInput, saltInput, mcStepsInput, mdStepsInput,
      equilStepsInput, bpGateInput, prodStepsInput,
    ])
    if (deviceInput) delete deviceInput.dataset.userSet
    _clearRunCards()
    _checkAvailable()   // re-apply the recommended device into the now-default field
  }

  // ── Detail ─────────────────────────────────────────────────────────────────
  // Hide the detail block AND clear the now-relocated loading bar + health card
  // (they live outside #oxdna-jobs-detail, so detail's display:none can't hide them).
  function _hideDetail() {
    if (detailEl) detailEl.style.display = 'none'
    if (progressEl) progressEl.innerHTML = ''
    if (healthEl) healthEl.innerHTML = ''
  }

  function _renderDetail(job) {
    if (!detailEl) return
    detailEl.style.display = ''

    if (detailStatus) {
      const ls = jobListStatus(job)
      detailStatus.textContent = job.status === 'running'
        ? detailStatusText(job, _progress)
        : ls.label
      detailStatus.style.color = ls.color
    }

    if (startBtn) {
      startBtn.style.display = ['queued', 'stopped', 'failed'].includes(job.status) ? '' : 'none'
      startBtn.textContent = startButtonLabel(job)
    }
    if (stopBtn)  stopBtn.style.display  = job.status === 'running' ? '' : 'none'
    if (deleteBtn) deleteBtn.style.display = job.status === 'running' ? 'none' : ''
    if (archiveBtn) {
      // Archive/unarchive only for non-running jobs; label tracks archived state.
      archiveBtn.style.display = job.status === 'running' ? 'none' : ''
      archiveBtn.textContent = job.archived ? 'Unarchive' : 'Archive'
    }

    _updateButtons(job)

    if (errorEl) {
      errorEl.style.display = job.error ? '' : 'none'
      errorEl.textContent = job.error || ''
    }
    // "View error log" appears whenever the job (or any stage) failed — even if
    // job.error is blank — so the user can always reach the raw oxDNA output.
    if (errorLogBtn) errorLogBtn.style.display = jobHasFailure(job) ? '' : 'none'

    _renderProgress(job)
    _renderTimeline(job)
    _renderHealth(job)
    _emitJobSelected()   // let the E-field section re-evaluate its Run button
  }

  // Notify the E-field setup section that the selected job (or its status)
  // changed, so its "Run field" button enables the moment a completed relaxed
  // job is selected — without the user having to hover the button.
  function _emitJobSelected() {
    window.dispatchEvent(new CustomEvent('nadoc:oxdna-job-selected'))
  }

  // Fetch the detailed failure log and show it in a scrollable popup with a copy
  // button. Used by the "View error log" button on a failed job.
  async function _showErrorLog(jobId) {
    if (!jobId) return
    let text
    try {
      text = errorLogText(await api.getOxdnaErrorLog(jobId))
    } catch (e) {
      text = `Could not load the error log.\n${e?.message || e}`
    }
    const pre = el('pre', {
      text,
      attrs: { style:
        'white-space:pre-wrap;word-break:break-word;font-family:monospace;' +
        'font-size:12px;line-height:1.45;margin:0;max-height:55vh;overflow:auto;' +
        'background:#0d1117;color:#c9d1d9;padding:10px;border-radius:4px' },
    })
    const modal = createModal({
      title: 'oxDNA error log',
      size: 'lg',
      body: pre,
      actions: [
        createButton({
          label: 'Copy', size: 'sm', onClick: async () => {
            try { await navigator.clipboard.writeText(text); showToast('Error log copied') }
            catch { showToast('Copy failed', { severity: 'error' }) }
          },
        }),
        createButton({ label: 'Close', size: 'sm', variant: 'primary', onClick: () => modal.close() }),
      ],
    })
    modal.open()
  }

  function _renderProgress(job) {
    if (!progressEl) return
    const idx = job.current_stage_idx
    const cur = job.stages?.[idx]
    let barPct = formatProgress(job, _progress).pct
    let label = ''
    // During a production OR electric-field run, show steps completed out of total.
    if (job.status === 'running' && (cur?.kind === 'production' || cur?.kind === 'field')) {
      const frac = _progress?.stage_fraction ?? 0
      barPct = Math.round(frac * 100)
      const done = Math.round(frac * (cur.steps || 0))
      const noun = cur.kind === 'field' ? 'Field' : 'Production'
      label = `${noun}: ${done.toLocaleString()} / ${(cur.steps || 0).toLocaleString()} steps`
    }
    // Flag a resumed run so the reset bar reads as "continuing", not "restarted".
    const note = resumeNote(job)
    if (note) label = label ? `${note} · ${label}` : note
    // Estimated time to completion (current run — relax or production).
    const eta = job.status === 'running' ? formatEta(_progress?.eta_seconds) : ''
    if (eta) label = label ? `${label} · ETA ~${eta}` : `ETA ~${eta}`
    const color = job.status === 'failed' ? _C.err : job.status === 'completed' ? _C.ok : _C.accent
    progressEl.innerHTML =
      `<div style="height:7px;background:#222;border-radius:4px;overflow:hidden">` +
      `<div style="height:100%;width:${barPct}%;background:${color};transition:width .3s"></div></div>` +
      (label ? `<div style="font-size:10px;color:${_C.dim};margin-top:2px">${label}</div>` : '')
  }

  function _renderTimeline(job) {
    if (!timelineEl) return
    const color = { done: _C.ok, failed: _C.err, running: _C.warn, pending: _C.dim }
    timelineEl.innerHTML = ''
    for (const c of stageChips(job)) {
      const chip = document.createElement('span')
      chip.style.cssText = `display:inline-flex;align-items:center;gap:3px;margin-right:10px;font-size:11px;color:${color[c.status] || _C.dim}`
      chip.innerHTML = `<span>${c.glyph}</span><span>${c.kind}</span>`
      timelineEl.appendChild(chip)
    }
  }

  function _renderHealth(job) {
    if (!healthEl) return
    const h = healthForDisplay(job, _progress)
    const cards = [
      ['Base pairs', h?.bp_retained_fraction != null ? `${Math.round(h.bp_retained_fraction * 100)}%` : '—',
        h && h.bp_retained_fraction != null && h.bp_retained_fraction < 0.8 ? _C.warn : _C.ok],
      ['Pot. energy', h?.potential_energy != null ? h.potential_energy.toFixed(3) : '—', _C.text],
      ['Max clash', h?.max_backbone_clash != null ? `${h.max_backbone_clash.toFixed(2)} nm` : '—',
        h && h.max_backbone_clash != null && h.max_backbone_clash > 1.5 ? _C.warn : _C.text],
      ['Speed', h?.steps_per_s != null ? `${Math.round(h.steps_per_s)} st/s` : '—', _C.dim],
    ]
    healthEl.innerHTML = ''
    healthEl.style.cssText = 'display:grid;grid-template-columns:1fr 1fr;gap:4px;margin-top:6px'
    for (const [label, val, col] of cards) {
      const c = document.createElement('div')
      c.style.cssText = 'background:#1c1c1c;border-radius:4px;padding:4px 6px'
      c.innerHTML = `<div style="font-size:9px;color:${_C.dim}">${label}</div>` +
                    `<div style="font-size:13px;color:${col}">${val}</div>`
      healthEl.appendChild(c)
    }
  }

  // ── Production (enabled only after a relaxation completes — mirrors MD) ─────
  // Central button-state: Relax + Production grey out while a production run is
  // active; Show RMSD unlocks only after a production stage completes.
  // Toggle a leading spinner on a launch button without restarting its animation
  // every poll (rebuild only on a state change, tracked via dataset.spinning).
  function _setBtnSpinner(btn, active, idleLabel, busyLabel = idleLabel) {
    if (active) {
      if (btn.dataset.spinning !== '1') {
        btn.textContent = ''
        btn.append(makeSpinner(_C.warn, 10), document.createTextNode(' ' + busyLabel))
        btn.dataset.spinning = '1'
      }
    } else if (btn.dataset.spinning !== '0') {
      btn.textContent = idleLabel
      btn.dataset.spinning = '0'
    }
  }

  function _updateButtons(job) {
    const ps = productionState(job)
    const prodRunning = job?.status === 'running' && ps === 'running'
    // Production is allowed whenever the job is completed — the first run starts
    // from the relaxed structure, later runs CONTINUE from the previous run's
    // last frame (each is its own stage).
    const prodReady = job?.status === 'completed'
    const hasRun = productionRunCount(job) > 0
    // A live session owns the one bead overlay — lock the relaxed-display / flex /
    // trajectory toggles while it runs so a click can't fight it (the user must
    // Stop Live first).  Cleared the moment Live stops (the live-change events
    // re-run _updateButtons).
    const liveOn = !!oxdnaLive?.isOn?.()

    // Relax — disabled while unavailable, launching, or a production run is active.
    if (runBtn) runBtn.disabled = !_available || _launching || prodRunning

    // Activity spinners — derived from live job state (across this design's jobs),
    // so they re-appear correctly after a page reload while a job is still running.
    const relaxActive = _launching || _visibleJobs().some(isRelaxRunning)
    const prodActive  = _visibleJobs().some(isProductionRunning)
    if (runBtn)  _setBtnSpinner(runBtn,  relaxActive, '▶ Relax', 'Relaxing…')
    if (prodBtn) _setBtnSpinner(prodBtn, prodActive,  'Full Sim', 'Running…')
    _updateAutorefineButton()   // gate by lattice + availability + in-flight autorefine

    if (prodBtn) {
      prodBtn.disabled = !prodReady
      prodBtn.style.cursor = prodReady ? 'pointer' : 'not-allowed'
      prodBtn.style.background = prodReady ? '#1a4a1a' : '#122117'
      prodBtn.style.borderColor = prodReady ? '#3fb950' : '#30363d'
      prodBtn.style.color = prodReady ? '#3fb950' : '#484f58'
    }
    if (prodRunning) _setProdStatus('Production running…', _C.warn)
    else if (ps === 'failed') _setProdStatus('Production failed.', _C.err)
    else if (prodReady && hasRun)
      _setProdStatus(`Production complete (${productionRunCount(job)} run${productionRunCount(job) > 1 ? 's' : ''}). Start again to continue from the last frame.`, _C.ok)
    else _setProdStatus(prodReady ? 'Ready to run production from the relaxed structure.'
                                  : 'Production unlocks after relaxation completes.', _C.dim)

    // Flexibility map (RMSF) — unlocks as soon as a production run has STARTED
    // (done OR running).  A mid-run map is preliminary; the confidence readout
    // warns the user not to trust a short run.
    if (flexToggle && !_flexBusy) {
      // Flex map pools production OR field trajectories → gate on samplingState.
      // Locked while a live session is running (shared overlay).
      const ok = !liveOn && (samplingState(job) === 'done' || samplingState(job) === 'running')
      flexToggle.disabled = !ok
      const lab = flexToggle.closest('label')
      if (lab) {
        lab.style.opacity = ok ? '1' : '0.5'
        lab.style.cursor = ok ? 'pointer' : 'not-allowed'
        lab.title = liveOn ? 'Stop Live to use the flexibility map' : ''
      }
      if (!ok && !liveOn && flexStatus && oxdnaDisplay?.mode() !== 'rmsf') {
        _setFlexStatus('Waiting for a production or field run', _C.dim)
      }
    }

    // Deviation map — same gate as the flexibility map (any job with sampling).
    if (autorefineDevToggle && !_devBusy) {
      const ok = !liveOn && (samplingState(job) === 'done' || samplingState(job) === 'running')
      autorefineDevToggle.disabled = !ok
      const lab = autorefineDevToggle.closest('label')
      if (lab) {
        lab.style.opacity = ok ? '1' : '0.5'
        lab.style.cursor = ok ? 'pointer' : 'not-allowed'
        lab.title = ok ? 'Mean structure of this job, recoloured green→red by per-base deviation from design.'
          : (liveOn ? 'Stop Live to use the deviation map' : 'Select a job with a production run.')
      }
    }

    // Use as NAMD seed — only once the relaxation has completed.
    if (seedBtn && !_seeding) {
      const ok = seedReady(job)
      seedBtn.disabled = !ok
      seedBtn.style.cursor = ok ? 'pointer' : 'not-allowed'
      seedBtn.style.background = ok ? '#21262d' : '#122117'
      seedBtn.style.color = ok ? '#c9d1d9' : '#484f58'
    }

    // View trajectory — unlocks once the job has any trajectory data (≥1 stage
    // started); shows the composite relaxation + all production runs.  Locked while
    // a live session is running (shared overlay).
    if (trajToggle && !_trajBusy) {
      const ok = !liveOn && hasTrajectory(job)
      trajToggle.disabled = !ok
      const lab = trajToggle.closest('label')
      if (lab) {
        lab.style.opacity = ok ? '1' : '0.5'
        lab.style.cursor = ok ? 'pointer' : 'not-allowed'
        lab.title = liveOn ? 'Stop Live to view a trajectory' : ''
      }
    }

    // OxDNA display (relaxed positions) — available once a job is selected, EXCEPT
    // while a live session owns the overlay, when it is locked too.  With no job
    // selected only "Off" is selectable (the card is always visible now).
    if (displayToggle) {
      const ok = !liveOn && !!job
      displayToggle.disabled = !ok
      const lab = displayToggle.closest('label')
      if (lab) {
        lab.style.opacity = ok ? '1' : '0.5'
        lab.style.cursor = ok ? 'pointer' : 'not-allowed'
        lab.title = liveOn ? 'Stop Live to use the OxDNA display'
          : (!job ? 'Select an oxDNA job first' : '')
      }
    }
    // Nothing selectable but "Off"? keep "Off" checked so the group shows a selection.
    _syncVizOffRadio()
  }
  function _setProdStatus(text, color = _C.dim) {
    if (prodStatus) { prodStatus.textContent = text; prodStatus.style.color = color }
  }
  function _selectedJob() { return _jobs.find(j => j.job_id === _selectedId) || null }

  // Stale-design guard: if the selected job's design changed since it was relaxed,
  // running live/production would resolve current selections against the job's frozen
  // topology and crash.  Offer to non-destructively ROLL the feature log back to the
  // relaxation stage (later edits kept — a persistent toast lets the user return), or
  // cancel.  Returns true to proceed, false to abort.  Shared by production + Live.
  function _ensureJobCurrent(actionLabel) {
    return ensureJobCurrent({
      job: _selectedJob(),
      rollFn: api.rollOxdnaJobDesign,
      refetch: _fetchJobs,
      isStale: () => jobOutOfDate(_selectedJob()),
      actionLabel,
    })
  }

  prodBtn?.addEventListener('click', async () => {
    if (!_selectedId || prodBtn.disabled) return
    if (!(await _ensureJobCurrent('a production run'))) return
    if (!(await confirmNoConcurrentJob({ excludeJobId: _selectedId }))) return
    oxdnaLive?.stop()   // a production run supersedes any live session (shared overlay)
    const steps = parseInt(prodStepsInput?.value || '5000000', 10)

    // Compose the run from the independently-enabled elements (field / surface /
    // anchors).  Each is optional — with none enabled this is a plain production.
    const el = getRunElements?.() || {}
    const body = { steps }
    if (el.field?.enabled && el.field.field_pN > 0) {
      body.field = { field_pN: el.field.field_pN, dir: el.field.dir }
    }
    if (el.surface?.enabled) {
      body.surface = { dir: el.surface.dir, offset_nm: el.surface.offsetNm, stiff: el.surface.stiff }
    }
    if (el.anchors?.length) body.anchors = el.anchors
    // A field with no anchors drifts the whole structure — block before the POST.
    if (body.field && !body.anchors) {
      _setProdStatus('Field needs ≥1 anchor — add a fixed strand in the Anchors card, or disable the field.', _C.err)
      return
    }

    try {
      const fc = await api.estimateOxdnaRunDisk(_selectedId, { steps })
      if (!(await confirmDiskSpaceOk(fc))) return
    } catch { /* forecast is best-effort — never block a launch on it */ }

    prodBtn.disabled = true
    if (runBtn) runBtn.disabled = true     // grey out both immediately on press
    const what = [body.field && 'field', body.surface && 'surface', body.anchors && 'anchors'].filter(Boolean).join(' + ') || 'production'
    _setProdStatus(`Starting run (${what})…`, _C.accent)
    // The consolidated run branches a CHILD job from the relaxed parent (success =
    // the child dict carries a job_id; it starts queued/running in the background).
    const r = await api.appendOxdnaRun(_selectedId, body)
    if (r && (r.job_id || r.ok)) {
      showToast('oxDNA run started', 'ok')
      _setProdStatus(`Run started (${what}) — see the new sub-item.`, _C.warn)
      await _fetchJobs()
      // Select the new run so its list item is highlighted and every card (incl.
      // the E-field arrow) reflects the run that was just started.
      if (r.job_id) await _selectJob(r.job_id)
    } else {
      _setProdStatus(api.lastErrorMessage?.() || 'Failed to start run (see console)', _C.err)
      prodBtn.disabled = false
    }
  })

  exportBtn?.addEventListener('click', async () => {
    exportBtn.disabled = true
    const prev = exportBtn.textContent
    exportBtn.textContent = 'Preparing ZIP…'
    const ok = await api.exportOxdna()
    exportBtn.textContent = ok ? 'ZIP downloaded' : 'Export failed — see console'
    setTimeout(() => { exportBtn.textContent = prev; exportBtn.disabled = false }, 2000)
  })

  // ── Flexibility map (production avg structure recoloured by per-base RMSF) ───
  // Like the trajectory status, the flex line shows its base summary OR a "building…"
  // notice while a heavy (atomistic/surface) reconstruction of the AVERAGE structure is
  // in flight (those take several seconds each — without this the panel looks frozen).
  function _setFlexStatus(text, color = _C.dim) {
    _flexBaseText = text; _flexBaseColor = color; _renderFlexStatus()
  }
  function _renderFlexStatus() {
    if (!flexStatus) return
    if (_heavyBuildKind && oxdnaDisplay?.mode() === 'rmsf') {
      const what = _heavyBuildKind === 'surface' ? 'surface' : 'atomistic'
      flexStatus.textContent = `⏳ Building ${what} average structure… (heavy — a few seconds)`
      flexStatus.style.color = _C.accent
    } else {
      flexStatus.textContent = _flexBaseText
      flexStatus.style.color = _flexBaseColor
    }
  }
  function _setFlexBar(state) {
    // state: 'computing' (indeterminate stripe) | 'done' | 'off'
    if (!flexBar) return
    if (state === 'computing') {
      flexBar.style.display = ''
      flexBar.innerHTML =
        `<div style="position:relative;height:6px;border-radius:4px;overflow:hidden;background:#222">` +
        `<div style="position:absolute;top:0;height:100%;width:35%;background:${_C.accent};` +
        `animation:gromacs-indeterminate 1.1s linear infinite"></div></div>`
    } else if (state === 'done') {
      flexBar.style.display = ''
      flexBar.innerHTML = `<span style="color:${_C.ok};font-size:11px">✓ Flexibility map ready</span>`
    } else {
      flexBar.style.display = 'none'
      flexBar.innerHTML = ''
    }
  }
  function _setFlexLegend(min, max) {
    if (!flexLegend) return
    if (min == null || max == null) { flexLegend.style.display = 'none'; flexLegend.innerHTML = ''; return }
    flexLegend.style.display = ''
    // viridis ramp: dark-purple (rigid) → yellow (flexible)
    flexLegend.innerHTML =
      `<div style="display:flex;align-items:center;gap:5px;font-size:9px;color:${_C.dim};margin-top:3px">` +
      `<span>${min.toFixed(2)} nm</span>` +
      `<span style="flex:1;height:7px;border-radius:3px;background:linear-gradient(90deg,#440154,#3b528b,#21918c,#5dc863,#fde725)"></span>` +
      `<span>${max.toFixed(2)} nm</span></div>` +
      `<div style="font-size:9px;color:${_C.dim}">rigid → flexible (RMSF)</div>`
  }
  function _setFlexOff() {
    if (oxdnaDisplay?.mode() === 'rmsf') oxdnaDisplay.stopAndRestore()
    if (flexToggle) flexToggle.checked = false
    flexScale.hide()
    _setFlexBar('off')
    _setFlexLegend(null, null)
    _setFlexStatus('Off', _C.dim)
    _syncVizOffRadio()
  }
  async function _refreshFlex() {
    if (!_selectedId || !oxdnaDisplay) return
    _flexBusy = true
    _setFlexStatus('Computing average structure + RMSF…', _C.accent)
    _setFlexBar('computing')
    const r = await oxdnaDisplay.displayRmsf(_selectedId)
    _flexBusy = false
    if (r.ok) {
      _setFlexBar('done')
      _setFlexLegend(r.min, r.max)
      flexScale.show(r.min, r.max)
      const conf = flexConfidenceText(r)
      _setFlexStatus(`Avg structure · ${r.n} bases · ${conf.text}`,
                     conf.preliminary ? _C.warn : _C.ok)
    } else {
      _setFlexBar('off')
      _setFlexLegend(null, null)
      _setFlexStatus(r.reason === 'waiting for production' ? 'Waiting for production'
                                                          : (r.reason || 'no data'), _C.warn)
      if (flexToggle) flexToggle.checked = false
    }
    _updateButtons(_selectedJob())
  }
  flexToggle?.addEventListener('change', async () => {
    if (flexToggle.checked) {
      if (!_selectedId) { flexToggle.checked = false; showToast('Select an oxDNA job first', 'warn'); _syncVizOffRadio(); return }
      const ss = samplingState(_selectedJob())
      if (ss !== 'done' && ss !== 'running') {
        flexToggle.checked = false; _setFlexStatus('Waiting for a production or field run', _C.warn); _syncVizOffRadio(); return
      }
      oxdnaLive?.stop()   // mutually exclusive with the live overlay
      if (displayToggle?.checked) _setDisplayOff()   // mutually exclusive with OxDNA display
      if (trajToggle?.checked) _setTrajOff()
      if (autorefineDevToggle?.checked) _setDeviationOff()
      await _refreshFlex()
    } else {
      _setFlexOff()
    }
  })

  // ── View trajectory (scrub composite relaxation + all production runs) ──────
  function _setTrajStatusEl(text, color = _C.dim) {
    if (trajStatus) { trajStatus.textContent = text; trajStatus.style.color = color }
  }
  // Status line shows the trajectory summary, OR a "building…" notice while a heavy
  // (atomistic/surface) frame reconstruction is in flight (those take several seconds
  // each — without this the panel looks frozen). _heavyBuildKind is set by the
  // oxdna-heavy-status event the display controller fires around each rebuild.
  function _setTrajStatus(text, color = _C.ok) { _trajBaseText = text; _trajBaseColor = color; _renderTrajStatus() }
  function _renderTrajStatus() {
    if (_trajPrep) {
      _setTrajStatusEl(
        `⏳ Preparing playback… building frame ${_trajPrep.done}/${_trajPrep.total} ` +
        `(heavy reps build once, then play smoothly)`, _C.accent)
    } else if (_heavyBuildKind && oxdnaDisplay?.mode() === 'trajectory') {
      const what = _heavyBuildKind === 'surface' ? 'surface' : 'atomistic'
      _setTrajStatusEl(`⏳ Building ${what} frame… (heavy — a few seconds; coarse caches as you scrub)`, _C.accent)
    } else {
      _setTrajStatusEl(_trajBaseText, _trajBaseColor)
    }
  }
  function _setTrajOff() {
    trajPlayer.stop()
    if (oxdnaDisplay?.mode() === 'trajectory') oxdnaDisplay.stopAndRestore()
    if (trajToggle) trajToggle.checked = false
    if (trajControls) trajControls.style.display = 'none'
    _heavyBuildKind = null
    _trajPrep = null
    _setTrajStatus('', _C.dim)
    _syncVizOffRadio()
  }
  // Heavy reconstruction in/out → flip the building notice. The display controller
  // fires this around every atomistic/surface rebuild in ANY mode; _renderTraj/Flex
  // each gate on their own mode so only the active overlay's status line reacts.
  window.addEventListener('nadoc:oxdna-heavy-status', (e) => {
    const d = e.detail || {}
    _heavyBuildKind = d.building ? d.kind : null
    _renderTrajStatus()
    _renderFlexStatus()
  })
  async function _refreshTraj() {
    if (!_selectedId || !oxdnaDisplay) return
    _trajBusy = true
    _setTrajStatus('Loading trajectory…', _C.accent)
    const r = await oxdnaDisplay.loadTrajectory(_selectedId)
    _trajBusy = false
    if (r.ok) {
      if (trajControls) trajControls.style.display = ''
      trajPlayer.setTrajectory(r.n_frames, r.markers)
      const nProd = (r.stages || []).filter(s => s.kind === 'production').length
      _setTrajStatus(`${r.n_frames} frames · relaxation + ${nProd} production run${nProd === 1 ? '' : 's'}`, _C.ok)
    } else {
      if (trajToggle) trajToggle.checked = false
      if (trajControls) trajControls.style.display = 'none'
      _setTrajStatus(r.reason || 'no trajectory', _C.warn)
    }
    _updateButtons(_selectedJob())
  }
  trajToggle?.addEventListener('change', async () => {
    if (trajToggle.checked) {
      if (!_selectedId) { trajToggle.checked = false; showToast('Select an oxDNA job first', 'warn'); _syncVizOffRadio(); return }
      if (!hasTrajectory(_selectedJob())) {
        trajToggle.checked = false; _setTrajStatus('No trajectory yet', _C.warn); _syncVizOffRadio(); return
      }
      oxdnaLive?.stop()   // mutually exclusive with the live overlay
      if (displayToggle?.checked) _setDisplayOff()   // mutually exclusive overlays
      if (flexToggle?.checked) _setFlexOff()
      if (autorefineDevToggle?.checked) _setDeviationOff()
      await _refreshTraj()
    } else {
      _setTrajOff()
    }
  })

  // ── Use as NAMD seed (Phase 2 — feed relaxed coords into a NAMD MD run) ─────
  function _setSeedStatus(text, color = _C.dim) {
    if (seedStatus) { seedStatus.textContent = text; seedStatus.style.color = color }
  }
  seedBtn?.addEventListener('click', async () => {
    if (!_selectedId || seedBtn.disabled || _seeding) return
    if (!(await confirmNoConcurrentJob())) return
    const src = _selectedJob()
    _seeding = true
    seedBtn.disabled = true
    _setSeedStatus('Building NAMD seed + solvating (this can take 1–2 min)…', _C.accent)
    const job = await api.createMdJob({
      oxdna_job_id: _selectedId,
      design_source_path: src?.design_source_path || _currentPartPath(),
      autostart: false,
    })
    _seeding = false
    if (job?.job_id && job.status !== 'failed') {
      _setSeedStatus('NAMD seed job created — see Molecular Dynamics below.', _C.ok)
      showToast('NAMD seed job created from relaxed oxDNA structure', 'ok')
      _revealMdPanel()
      // Refresh the MD panel even if it was already open (reveal only refreshes
      // on a collapse→expand), so the new preparing job appears + is selected.
      window.dispatchEvent(new CustomEvent('nadoc:md-job-created', { detail: { jobId: job.job_id } }))
    } else {
      const detail = job?.error || api.lastErrorMessage?.()
      _setSeedStatus(detail || 'Failed to create NAMD seed (see console)', _C.err)
    }
    _updateButtons(_selectedJob())
  })

  // Collapse this oxDNA panel and open the Molecular Dynamics panel so the new
  // seeded job is visible right away.  Expanding MD via its own heading click
  // keeps its collapse state consistent and refreshes its job list.
  function _revealMdPanel() {
    if (!_collapsed) {
      _collapsed = true
      body.style.display = 'none'
      arrow?.classList.toggle('is-collapsed', true)
      setSectionCollapsed('dynamics', 'oxdna-jobs-panel', true)
    }
    if (getSectionCollapsed('dynamics', 'md-jobs-panel', true)) {
      document.getElementById('md-jobs-panel-heading')?.click()
    }
  }

  // ── Detail actions ───────────────────────────────────────────────────────
  // Start/Stop take a beat to register on the backend — busy-guard them so a
  // spam of clicks fires the request once, with an immediate spinner + gray-out.
  startBtn?.addEventListener('click', () => runExclusive(startBtn, async () => {
    if (!_selectedId) return
    if (!(await confirmNoConcurrentJob({ excludeJobId: _selectedId }))) return
    await api.startOxdnaJob(_selectedId)
    await _fetchJobs()
  }, { label: 'Starting…' }))
  stopBtn?.addEventListener('click', () => runExclusive(stopBtn, async () => {
    if (!_selectedId) return
    await api.stopOxdnaJob(_selectedId)
    await _fetchJobs()
  }, { label: 'Stopping…' }))
  errorLogBtn?.addEventListener('click', () => { _showErrorLog(_selectedId) })
  deleteBtn?.addEventListener('click', async () => {
    if (!_selectedId) return
    const job = _selectedJob()
    // Deleting a job cascades to its full descendant subtree (chained runs) — warn
    // with the count.
    const nChildren = job ? descendantIds(_jobs, _selectedId).size : 0
    const { title, message, confirmLabel } = deleteConfirmMessage(job, nChildren)
    const ok = await showConfirm({ title, message, danger: true, confirmLabel })
    if (!ok) return
    const r = await api.deleteOxdnaJob(_selectedId)
    const deletedIds = Array.isArray(r?.deleted) ? r.deleted : [_selectedId]
    const active = oxdnaDisplay?.activeJobId()
    if (active && deletedIds.includes(active)) _allDisplaysOff()
    _selectedId = null
    _hideDetail()
    _updateButtons(null)
    _clearRunCards()   // drop the E-field arrow / anchor glow of the deleted job
    _emitJobSelected()
    _fetchJobs()
  })

  function _setArchiveProgress(st) {
    if (!archiveProgressEl) return
    if (!st) { archiveProgressEl.style.display = 'none'; archiveProgressEl.textContent = ''; return }
    const pct = st.total_bytes ? Math.round((st.moved_bytes / st.total_bytes) * 100) : 0
    archiveProgressEl.style.display = ''
    archiveProgressEl.textContent =
      `${formatBytes(st.moved_bytes || 0)} / ${formatBytes(st.total_bytes || 0)} (${pct}%)`
  }

  archiveBtn?.addEventListener('click', async () => {
    if (!_selectedId) return
    const job = _selectedJob()
    if (!job) return
    archiveBtn.disabled = true; deleteBtn && (deleteBtn.disabled = true)
    const action = job.archived ? _archive.unarchive : _archive.archive
    try {
      await action(job, { onProgress: _setArchiveProgress })
    } finally {
      archiveBtn.disabled = false; deleteBtn && (deleteBtn.disabled = false)
      _setArchiveProgress(null)
      await _fetchJobs()
    }
  })

  // ── OxDNA display toggle ───────────────────────────────────────────────────
  async function _refreshDisplay() {
    if (!_selectedId || !oxdnaDisplay) return
    const align = alignToggle ? alignToggle.checked : true
    const r = await oxdnaDisplay.displayJob(_selectedId, align)
    const frame = align ? '' : ', own frame'
    _displayBaseText = r.ok ? `Showing relaxed positions (${r.stage || ''}, ${r.n} nt${frame})` : (r.reason || 'no data')
    _displayBaseColor = r.ok ? _C.ok : _C.warn
    // Mark the frame we're now showing so the live-follow poll only re-fetches
    // when the sim writes a newer one.
    _lastFrameIndex = _progress?.frame_index ?? null
    _renderDisplayStatus()
  }

  // Render the display-status line: the base "Showing relaxed positions …" text,
  // plus a "next frame ~Xs" countdown while the selected job is still running (the
  // relaxed display follows the run, refreshing each time the sim writes a frame).
  function _renderDisplayStatus() {
    let text = _displayBaseText
    let color = _displayBaseColor
    if (displayToggle?.checked && oxdnaDisplay?.mode() === 'relaxed'
        && _selectedJob()?.status === 'running') {
      const eta = formatEta(_progress?.next_frame_eta_seconds)
      text = `${text || 'Following live'} · next frame ${eta ? `~${eta}` : '…'}`
      color = _C.accent
    }
    _setDisplayStatus(text, color)
  }
  // Re-fetch with the new alignment whenever the Align toggle flips (only while the
  // relaxed display is on).
  alignToggle?.addEventListener('change', () => {
    if (displayToggle?.checked && oxdnaDisplay?.mode() === 'relaxed') _refreshDisplay()
  })
  function _setDisplayOff() {
    // Always restore (and bump the controller's epoch) so an in-flight relaxed
    // fetch from the live-follow poll / a job switch can't re-apply positions
    // after we've turned the display off.  Only ever called for the relaxed
    // overlay (flex/traj are mutually exclusive), so this never kills those.
    oxdnaDisplay?.stopAndRestore()
    if (displayToggle) displayToggle.checked = false
    _lastFrameIndex = null
    _displayBaseText = ''
    _setDisplayStatus('Display off', _C.dim)
    _syncVizOffRadio()
  }
  // Turn off whichever overlay is active (relaxed display / flexibility map /
  // trajectory player) — they share the one bead overlay.
  function _allDisplaysOff() {
    if (oxdnaDisplay?.mode() === 'rmsf') _setFlexOff()
    else if (oxdnaDisplay?.mode() === 'trajectory') _setTrajOff()
    else if (oxdnaDisplay?.mode() === 'deviation') _setDeviationOff()
    else _setDisplayOff()
    // Defensive: ensure every checkbox is cleared and the renderer restored.
    trajPlayer.stop()
    if (oxdnaDisplay?.isActive()) oxdnaDisplay.stopAndRestore()
    if (displayToggle) displayToggle.checked = false
    if (flexToggle) flexToggle.checked = false
    if (trajToggle) trajToggle.checked = false
    if (autorefineDevToggle) autorefineDevToggle.checked = false
    if (trajControls) trajControls.style.display = 'none'
  }
  displayToggle?.addEventListener('change', async () => {
    if (displayToggle.checked) {
      if (!_selectedId) { displayToggle.checked = false; showToast('Select an oxDNA job first', 'warn'); _syncVizOffRadio(); return }
      oxdnaLive?.stop()   // mutually exclusive with the live overlay
      if (flexToggle?.checked) _setFlexOff()   // mutually exclusive with the flexibility map
      if (trajToggle?.checked) _setTrajOff()
      if (autorefineDevToggle?.checked) _setDeviationOff()
      await _refreshDisplay()
    } else {
      _setDisplayOff()
    }
  })

  // "Off" radio: turn off whichever overlay is active (native positions).  The
  // browser already unchecked the active view; _allDisplaysOff tears every overlay
  // down and restores the renderer (idempotent).
  vizOffRadio?.addEventListener('change', () => {
    if (!vizOffRadio.checked) return
    _allDisplaysOff()
    vizOffRadio.checked = true   // _allDisplaysOff's teardowns leave this set; keep it explicit
  })

  // ── Live mode took over the bead overlay → drop our relaxed/flex/traj overlay ─
  // The live controller dispatches this before applying its first frame, so the
  // shared bead overlay isn't fought over (Live and the job-display overlays are
  // mutually exclusive).  We also clear + LOCK the three display toggles for the
  // duration of the live session so a click can't create a conflict.
  window.addEventListener('nadoc:oxdna-live-start', () => {
    if (oxdnaDisplay?.isActive()) _allDisplaysOff()
    _updateButtons(_selectedJob())   // disable display / flex / traj toggles
  })
  // Live stopped → re-enable the toggles (subject to their normal job-state gating).
  window.addEventListener('nadoc:oxdna-live-stop', () => {
    _updateButtons(_selectedJob())
  })

  // ── Pause display when leaving the Dynamics tab ───────────────────────────
  window.addEventListener('nadoc:left-tab-change', (e) => {
    if (e.detail?.activeTab !== 'dynamics') {
      if (oxdnaDisplay?.isActive()) _allDisplaysOff()
      if (_pollTimer) { clearTimeout(_pollTimer); _pollTimer = null }
    } else if (!_collapsed) {
      _onOpen()
    }
  })

  // ── Design changed (edit OR feature-log seek) → re-evaluate out-of-date ────
  // The client emits this on every design sync; refetch so the ⚠ markers update
  // even off the Dynamics tab (where the 1.5 s poll is paused) — e.g. when the user
  // seeks the Feature Log back to a job's run position, clearing its stale flag.
  window.addEventListener('nadoc:design-changed', () => {
    // A design edit makes a re-run no longer redundant; drop any live deviation overlay
    // (it no longer matches the edited design).  The deviation DATA stays available for
    // the run's final job (a historical result) — its toggle re-enables on re-selection.
    _autorefineCleanForDesign = false
    if (oxdnaDisplay?.mode() === 'deviation') _setDeviationOff()
    _metricsCard?.refresh()      // cached twist/curve/bp graphs no longer match the edited design
    _compareCard?.refresh()      // cached cross-engine comparison no longer matches the edited design
    _fetchJobs()
  })

  // ── Design switched/opened → re-filter the list to the new design ─────────
  // Without this the list keeps showing the previous design's jobs (and the
  // selection/display belong to the old design).  Mirrors md_jobs_panel.
  window.addEventListener('nadoc:workspace-path-change', () => {
    if (oxdnaDisplay?.isActive()) _allDisplaysOff()
    _selectedId = null
    _hideDetail()
    _resetControlsToDefaults()   // drop the previous design's relaxation/run settings
    _updateButtons(null)
    _emitJobSelected()
    if (_collapsed) _renderList()   // re-filter cached jobs to the new path
    else _fetchJobs()               // fresh fetch + re-filter
  })

  // Graphs & Metrics card — a child module reading the panel's job selection.
  const _metricsCard = initOxdnaMetricsCard({
    getSelectedJob: _selectedJob,
    getJobs: () => _jobs,
  })

  // Cross-engine Shape comparison card (S5) — engine-agnostic, hosted here.  `getSources`
  // returns the per-engine {engine, descriptors, rmsf, shape_frame, field} bundles for the
  // current design; the per-engine emission tasks (O1/C5/M5/N4) populate it, so for now it
  // is empty and the card reports that no predictions are ready (live data = an MV row).
  const _compareCard = initShapeCompareCard({
    api: { start: api.startShapeCompare, poll: api.getShapeCompareRun },
    getSources: () => [],
  })

  // initial availability probe (cheap) so the status line is populated.
  _checkAvailable()
  if (!_collapsed) _onOpen()

  return { refresh: _fetchJobs, getSelectedJob: _selectedJob, ensureJobCurrent: _ensureJobCurrent }
}
