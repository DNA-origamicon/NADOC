/**
 * ui/md_jobs_panel.js — MD relaxation / production panel (Milestone 2).
 *
 * Provides:
 *   - Preset selector + Relax / Production buttons
 *   - Advanced parameter drawer
 *   - Job list with status chips
 *   - Live job detail: stage timeline, health dots, metric cards, stop button
 *
 * Connects to /ws/md-jobs/{job_id} for live updates while a job is running.
 * Falls back to REST polling for completed jobs.
 */

import { initOccupancyControls } from './occupancy_controls.js'
import { initJobsPanelBase } from './jobs_panel_base.js'
import { showOpProgress, hideOpProgress, setOpProgressLabel } from './op_progress.js'
import { showToast } from './toast.js'
import {
  applyMdVisualizationJobSwitch,
  mdVisualizationJobSwitchAction,
  selectionUpdatesVisualization,
} from './visualization_selection_policy.js'
import { jobOutOfDate, ensureJobCurrent } from './job_staleness.js'
import { rollMdJobDesign, estimateMdDisk, estimateMdProductionDisk, preflightMdVram } from '../api/client.js'
import { getRunDir, recommendArchive, archiveRecommendation } from './run_location.js'
import { docKey } from '../shared/doc_id.js'
import { resetControlsToDefaults } from './form_defaults.js'
import { buildJobListModel, jobListSignature } from './jobs_panel_model.js'
import { renderJobList } from './jobs_panel_render.js'
import { shouldForceDisplayReload, mdReadinessIndicator, mdDisplayReadinessFromMeta } from './md_display_state.js'
import { initMdSolventControls } from './md_solvent_controls.js'
import { initMdWeldControls } from './md_weld_controls.js'
import { initOxdnaAnchorsSetup } from './oxdna_anchors_setup.js'
import { atomNamesFromValue } from '../scene/efield_math.js'
import { initForcesCard } from './forces_card.js'
import { initOxdnaTrajectoryPlayer } from './oxdna_trajectory_player.js'
import { repKind } from './oxdna_display.js'
import { initTrajPrebuildPlan } from './traj_prebuild_plan.js'
import { shouldShowFixButton, openVramFixModal } from './md_vram_fix.js'
import { openGpuDecisionModal, hasPendingGpuDecision } from './md_gate_b.js'
import { gateAMessage, openGateAModal } from './md_gate_a.js'
import { store } from '../state/store.js'
import { formatBytes } from './format_bytes.js'
import { initJobArchive } from './job_archive_action.js'
import { initMdMetricsCard } from './md_metrics_card.js'
import {
  confirmNoConcurrentJob, confirmGpuNotBusy, confirmDiskSpaceOk, confirmBigRunOk,
  isUndersizedCellRefusal, confirmUndersizedCell,
} from './job_activity.js'
import { initMdSubmitReview, remoteJobBadge, alpineTargetDisabledReason } from './md_submit_review.js'
import { runExclusive } from './primitives/button_busy.js'
import { RUN_ACTION, runControlState } from './job_run_control.js'
import { initAdvancedOptimize, residentModeFromRecommendation } from './md_advanced_optimize.js'
import * as api from '../api/client.js'
import {
  initRunpodStatus, runpodBlockReason, runpodCanLaunch, runpodConnected,
} from './runpod_status.js'
import { initRunpodSetup } from './runpod_setup.js'
import { initRunpodGpuPicker } from './runpod_gpu_picker.js'
import { initClusterAvailability } from './cluster_availability.js'
import { shouldStopLiveSession, shouldResumeDisplays, displayTabIds } from './display_tab_policy.js'
import { initJobWizard } from './md_job_wizard.js'
import { isProductionParent, jobSettingsState } from './md_job_wizard_model.js'
import { createContextMenu } from './primitives/context_menu.js'
import { mdMinimizationRow, mdLatestStageLabel } from './md_stage_timeline.js'
import { mdHealthTileStates, TILE_STATE } from './md_health_tiles.js'

// ── Colour palette (matches NADOC dark theme) ─────────────────────────────────
const _C = {
  bg:     '#161b22', bg2:  '#0d1117',
  border: '#30363d', dim:  '#484f58',
  muted:  '#8b949e', text: '#c9d1d9',
  accent: '#58a6ff', ok:   '#3fb950',
  warn:   '#d29922', err:  '#f85149',
  purple: '#bc8cff',
}

const _TERMINAL_STATUSES = new Set(['completed', 'failed', 'stopped'])
// Production runs at the timestep chosen in the Advanced card: 4 fs fast (default),
// 2 fs medium, or 1 fs conservative.  (This was hard-coded to 1 fs, which under-reported
// every fast production run's simulated time by 4x.)
export const DEFAULT_PRODUCTION_TIMESTEP_FS = 4.0
/** Pure: simulated ns for a raw NAMD step count at a given production timestep (fs). */
export function productionNsFromSteps(steps, timestepFs = DEFAULT_PRODUCTION_TIMESTEP_FS) {
  const ts = Number(timestepFs) > 0 ? Number(timestepFs) : DEFAULT_PRODUCTION_TIMESTEP_FS
  return (Number(steps) || 0) * ts / 1_000_000
}
// "View trajectory" frame interval: load every Nth frame of each written segment, the
// same idea as the stride field when a DCD is imported into VMD.  The DEFAULT lives in
// index.html's `value=` attribute (form_defaults reads el.defaultValue) — this constant is
// only the fallback for an unreadable/empty field.
/** A segment is PRODUCTION dynamics iff its stage label says so — the same rule as the
 *  backend's `md_production_segments`, so the panel cannot offer a view the analysis
 *  refuses. Every builder that emits a production segment puts the word in its label
 *  ("… production run", "… production replica (seed n)", "… conservative production N ns
 *  unrestrained", "shell NVT production (…)"). */
export const MD_PRODUCTION_MARKER = 'production'

/**
 * Does this job have PRODUCTION frames? Pure.
 *
 * Occupancy clustering is only meaningful over free dynamics. A POSITIVE test, because
 * restraint is encoded in the label as `k=<value>` — `50K NVT k=5.0`,
 * `310K NPT k=5.0 → … → 0.01`, `Vacuum ENRG-MD shape relaxation` — and no reasonable list
 * of "restrained" keywords catches them all. Excluding by keyword admitted every one of
 * those on the real job set; matching "production" admits exactly the runs the
 * Run-production button (and the ensemble/replica builders) create.
 *
 * A segment counts only once it has written frames (done/running): a queued production
 * run is not sampling yet.
 */
export function mdHasProductionRun(job) {
  return (job?.segments || []).some((seg) => {
    if (seg?.status !== 'done' && seg?.status !== 'running') return false
    return String(seg.stage ?? seg.name ?? '').toLowerCase().includes(MD_PRODUCTION_MARKER)
  })
}

export const DEFAULT_TRAJ_INTERVAL = 20
// Past this many frames a load is slow and memory-hungry enough to be worth confirming
// rather than silently starting.  Warn, don't cap — the user asked for the frames.
export const TRAJ_FRAME_CONFIRM = 500
/** Pure: how many frames a given interval will actually load, given each written
 *  segment's raw DCD frame count.  Mirrors the backend's `_composite_indices` stride
 *  branch exactly — every segment is strided on its own (so a non-empty segment always
 *  keeps at least its own frame 0), hence ceil per segment rather than over the total. */
export function stridedFrameCount(rawCountsPerSegment, interval) {
  const s = Math.max(1, Math.floor(Number(interval)) || 1)
  if (!Array.isArray(rawCountsPerSegment)) return 0
  return rawCountsPerSegment.reduce((n, c) => {
    const raw = Math.floor(Number(c)) || 0
    return n + (raw > 0 ? Math.ceil(raw / s) : 0)
  }, 0)
}
/** Pure: the production timestep a prepared job will actually use — its stored
 *  `production_timestep_fs` (Advanced card), or the legacy fast?4:1 derivation for
 *  jobs prepared before that field existed. */
export function jobProductionTimestepFs(job) {
  const pp = job?.prep_params
  const ts = Number(pp?.production_timestep_fs)
  if (ts === 1 || ts === 2 || ts === 4) return ts
  if (pp) return pp.fast ? 4.0 : 1.0
  return DEFAULT_PRODUCTION_TIMESTEP_FS
}
/** Pure: the production timestep the ETA, the "x ns" readout and the Start-Production
 *  POST must ALL use.
 *
 *  The DROPDOWN wins. It is the control the user operates, and it is now sent with the
 *  production request, so the estimate is computed from the same number the run uses.
 *  This used to return the selected JOB's stored dt while the dropdown reached prep only
 *  — so changing it before starting production moved neither the run nor the estimate,
 *  and a 2 fs selection produced a 1 fs trajectory under a 1 fs ETA (seen on 2hb_1xT).
 *
 *  Falls back to the selected job's stored dt (which also seeds the dropdown on
 *  selection), then the global default — so the value shown for a prepared job that the
 *  user has not touched is unchanged. */
export function effectiveProductionTimestepFs({ selectValue, job } = {}) {
  const sel = Number(selectValue)
  if (sel === 1 || sel === 2 || sel === 4) return sel
  if (job) return jobProductionTimestepFs(job)
  return DEFAULT_PRODUCTION_TIMESTEP_FS
}

const _SHOW_ALL_KEY = 'nadoc:md-jobs-show-all'

/** Pure: the launch policy value from the "Prefer fastest GPU mode" toggle. */
export function gpuFallbackFromToggle(checked) {
  return checked ? 'ask' : 'auto_offload'
}
const _WORKSPACE_PATH_KEY = 'nadoc:workspace-path'
const _MD_PREWARM_INTERVAL_MS = 30000
// Remote (Alpine) jobs have no live WebSocket push — the backend supervisor polls
// SLURM, but the panel otherwise only re-fetches on user actions.  So while a
// submitted remote job is in flight we poll the list ourselves on this cadence.
const _MD_REMOTE_POLL_MS = 20000
const _WS_WATCHDOG_MS = 5000     // safety-net tick: reconnect a dropped detail WS / probe a wedged one
const _WS_STALE_MS    = 12000    // no WS state push for this long ⇒ treat the socket as wedged (pushes are 1–3 s)
const _MD_WARMING_TIMEOUT_MS = 30000   // a Display-MD load stuck 'warming…' this long ⇒ flip the dot to 'error'

// Debug timestamp — kept to <12 chars so console entries don't collapse
const _ts = () => new Date().toISOString().slice(11, 23)


// ── Pure job-filtering helpers (exported for testing) ─────────────────────────

/** Normalise a workspace path for comparison: forward slashes, no trailing `/`. */
export function normalizeWorkspacePath(path) {
  return path ? String(path).replace(/\\/g, '/').replace(/\/+$/, '') : ''
}

/**
 * Jobs to show for the active part. With `showAll`, every job passes. Otherwise
 * only jobs whose `design_source_path` matches the active part's path; if no part
 * path is known we show nothing (rather than leaking other designs' jobs).
 */
export function filterJobsForPart(jobs, partPath, showAll) {
  if (showAll) return jobs
  const current = normalizeWorkspacePath(partPath)
  if (!current) return []
  return jobs.filter(j => normalizeWorkspacePath(j.design_source_path) === current)
}

/**
 * The newest `completed` job for the active part — the cross-engine comparison card's
 * fallback when the user hasn't explicitly clicked a job in that engine's panel, so a
 * design where every engine ran compares all of them without hunting for a row to select.
 * Pure: filters to the active part (never leaks another design's jobs) → completed →
 * most recent by `created_at`.  Returns `null` when nothing qualifies.
 */
export function newestCompletedForPart(jobs, partPath) {
  const forPart = filterJobsForPart(jobs || [], partPath, false)
  const done = forPart.filter(j => j?.status === 'completed')
  done.sort((a, b) => (b?.created_at ?? 0) - (a?.created_at ?? 0))
  return done[0] ?? null
}

/** Preserve an explicit historical selection while another job runs in the background.
 * Active is only the initial default; it never outranks a still-valid user choice. */
export function preferredMdSelection(jobs, selectedId, userDeselected = false) {
  if (!jobs?.length || userDeselected) return null
  if (selectedId && jobs.some(j => j.job_id === selectedId)) return selectedId
  return (jobs.find(j => ['running', 'preparing'].includes(j.status)) ?? jobs[0]).job_id
}

/** Pure: list badge for a job seeded from another engine's relaxation, else ''.
 *  oxDNA/mrDNA seed from a coarse-grained frame; BLADE seeds from an exact all-atom relax. */
export function seededBadge(job) {
  if (job?.seed_oxdna_job_id) return 'oxDNA seeded'
  if (job?.seed_mrdna_job_id) return 'mrDNA seeded'
  if (job?.seed_blade_job_id) return 'BLADE seeded'
  return ''
}

/** Pure: a REMOTE job (Alpine OR RunPod) that finished local prep but was never handed
 *  to its scheduler/pod — "prepared, awaiting remote submit".  NOT actually running, even
 *  though its status is `queued`; a failed submit leaves it here (with an error).  RunPod
 *  MUST be included: a never-launched RunPod job carries no slurm id AND no pod id, and
 *  treating its `queued` status as "active" made it hijack the Relax button into "■ Stop". */
export function mdRemoteAwaitingSubmit(job) {
  const remote = job?.execution_target === 'alpine' || job?.execution_target === 'runpod'
  return remote && !job?.remote_submit_progress
    && !job?.slurm_job_id && !job?.runpod_pod_id && job?.status === 'queued'
}

/** Pure: text for the detail error box, or null to hide it.  A user-`stopped` job is
 *  NOT an error — it only shows the box when it actually carries an error message (an
 *  older job saved before the clean-stop fix, or a stop that raced a real failure).  A
 *  clean stop returns null so the sidebar never shows the "Unknown error" fallback. */
export function mdDetailErrorText(job) {
  const showErr = job?.status === 'failed'
    || (job?.status === 'stopped' && !!job?.error)
    || (mdRemoteAwaitingSubmit(job) && job?.error)
    || (job?.resumable && job?.error)   // timed-out: show the "click Resume" message
  return showErr ? (job?.error ?? 'Unknown error') : null
}

/** Diagnostic text for the native failure <details> disclosure. The primary error stays
 * first; structured runner evidence follows so an NAMD return code cannot be buried in a
 * sentence or omitted merely because this was a preparation failure. */
export function mdFailureDetailsText(job) {
  const error = mdDetailErrorText(job)
  if (!error) return null
  const d = job?.failure_details || {}
  const rows = [error, '', `Kind: ${d.failure_kind || job?.failure_kind || 'other'}`]
  if (d.phase) rows.push(`Phase: ${d.phase}`)
  if (d.stage) rows.push(`Stage: ${d.stage}`)
  if (d.segment) rows.push(`Segment: ${d.segment}`)
  if (d.exit_code != null) rows.push(`NAMD exit code: ${d.exit_code}`)
  if (d.log_file) rows.push(`Log: ${d.log_file}`)
  if (d.log_excerpt) rows.push('', 'Last log lines:', d.log_excerpt)
  return rows.join('\n')
}

/** Pure: is the job in an in-progress state (a spinner should show)?  A remote job
 *  that hasn't been submitted to SLURM yet is prepared-but-idle, not running — so a
 *  failed/never-attempted Alpine submit doesn't masquerade as a live job. */
export function mdJobIsActive(job) {
  if (job?.remote_submit_progress) return true
  if (!['queued', 'preparing', 'running'].includes(job?.status)) return false
  if (mdRemoteAwaitingSubmit(job)) return false
  return true
}

/** Pure: is this job actually executing?  A remote job sitting at `queued` with no
 *  scheduler id has been prepared but never handed to its cluster — it is idle, not
 *  running, and treating it as running turned the control into a Stop button for a job
 *  that had not started. */
export function mdJobIsRunning(job) {
  if (!job) return false
  if (['preparing', 'running'].includes(job.status)) return true
  // A submitted remote job is genuinely in flight even while SLURM has it queued.
  return job.status === 'queued' && !!(job.slurm_job_id || job.runpod_pod_id)
}

/** Pure: which RunPod card a launch should ask for.
 *
 *  `requested` is what the Job Wizard's step 1 put in the payload — the card the user
 *  actually picked from the ranked table, and the one every cost / ns-day / $-per-ns
 *  number they were shown was computed from. The Clusters-card picker is deliberately
 *  absent: that card browses availability and must not control a launch.
 *
 *  Both launch paths used to assign the panel's value UNCONDITIONALLY, after spreading
 *  the wizard's payload — so the wizard's card was overwritten, invariably with `null`
 *  (nothing but the Clusters-card picker ever sets it), and the backend rented whatever
 *  headed its own ranked list. Cleared for every other target for the same reason the
 *  backend clears it: a leftover card on a run re-pointed at the local GPU must not
 *  resurface at launch. */
export function mdRunpodGpuKeyFor({ runTarget = 'local', requested = null } = {}) {
  if (runTarget !== 'runpod') return null
  return requested ?? null
}

/** Pure: is this job holding THIS computer's GPU/cores/disk right now?
 *
 *  Strictly narrower than `mdJobIsRunning`, and the question the run queue asks: a run
 *  on Alpine or a rented RunPod pod IS in flight, but it consumes nothing here.  Counting
 *  it as busy turned ▶ Run into ＋ Queue on every local job — behind a server-side queue
 *  that then never drained — for the whole duration of every remote run, with the local
 *  GPU idle.  Mirrors `md_queue.job_occupies_local_machine`, and applies the same rule
 *  `pickBlockingJob` (job_activity.js) already uses for the launch guard. */
export function mdJobOccupiesLocalMachine(job) {
  return mdIsLocalTarget(job?.execution_target) && mdJobIsRunning(job)
}

/** Pure: has this job been prepared and left waiting for the user to press Run?
 *  This is what "create a job without starting it" produces — `autostart:false` leaves a
 *  fully solvated package at `queued`, so every value the wizard had to call deferred is
 *  now real and starting it is instant.  Remote jobs are excluded: theirs is a SUBMIT,
 *  which goes through the review card. */
export function mdJobIsStartable(job) {
  return !!job && job.status === 'queued' && !job.slurm_job_id && !job.runpod_pod_id
    && !mdRemoteAwaitingSubmit(job)
}

/** Pure: is this a prepared RunPod job that the Run button should launch?
 *
 *  Kept separate from `mdJobIsStartable` on purpose. That predicate means "startable by the
 *  plain local path", and `mdQueueable` leans on it to keep remote jobs out of the local run
 *  queue — widening it would silently park a rented-GPU run behind a desktop one.
 *
 *  Renting is a real start, not a submit: `POST /md/jobs/{id}/start` dispatches straight to
 *  `_start_runpod_job`, which pre-flights and then provisions. Alpine needs its review card
 *  because an sbatch spends a shared allocation; a pod is rented, run and destroyed by NADOC
 *  in one act, and the wizard already collected the card, the cap and the volume. */
export function mdRunpodStartable(job) {
  return job?.execution_target === 'runpod' && mdRemoteAwaitingSubmit(job)
}

/** Pure: which unattended phase of a RunPod launch is this job in, or `null` when it is not
 *  in one? Nothing here is clickable — the control spins and waits.
 *
 *    'preparing' — solvating and packaging ON THIS COMPUTER. Nothing is rented yet.
 *    'renting'   — asking RunPod for a pod. Billing starts the moment one exists.
 *    'uploading' — staging the package over SFTP. The GPU is idle and BILLING; on the
 *                  1.9M-atom run this was ~15 min and ~$0.20 before NAMD ran a step.
 *
 *  The signals are already on the job: `runpod_pod_id` lands when the pod is created and
 *  `runpod_pid` when the chain script actually launches, so "pod but no pid" is exactly the
 *  staging window. */
export function mdRunpodPhase(job) {
  if (job?.execution_target !== 'runpod') return null
  if (job.status === 'preparing') return 'preparing'
  if (job.status !== 'running' || job.runpod_pid) return null
  return job.runpod_pod_id ? 'uploading' : 'renting'
}

/** Pure: can this job be picked up from its last checkpoint?  A job paused on a
 *  GPU-resident decision counts — resuming re-opens the decision, so the modal is not the
 *  only way back in.  Alpine resumes are cluster-gated and stay on their own button. */
export function mdJobIsResumable(job) {
  if (!job || job.execution_target === 'alpine') return false
  return ['paused', 'stopped', 'failed'].includes(job.status) || hasPendingGpuDecision(job)
}

/** Pure: how a queued run reads in the queue list.
 *
 *  Named by the PART it simulates plus when the run was created — this UI shows no job
 *  ids, so that pair is what tells two runs of the same design apart.  A production child
 *  says so, because "same part, same day" otherwise reads as a duplicate.  Falls back to
 *  what the server recorded when the job itself is no longer in the list. */
export function mdQueueRowLabel(job, entry = null, formatTime = null) {
  const name = job?.design_name || entry?.design_name || 'Unknown run'
  const when = job?.created_at != null && formatTime ? formatTime(job.created_at) : ''
  const kind = mdIsProductionChild(job) ? ' · production'
    : job?.status === 'stopped' || job?.status === 'failed' ? ' · resume' : ''
  return `${name}${kind}${when ? ` · ${when}` : ''}`
}

/** Pure: can this job be parked behind the run that's going?
 *
 *  Mirror of `md_queue.job_is_queueable` on the backend — keep the two in lockstep, or
 *  the button offers a queue the server then refuses.  Prepared-but-unstarted and
 *  stopped/failed both qualify (POST …/start handles them identically).
 *
 *  The queue is LOCAL-only.  A `draft` needs the wizard, a GPU-decision pause needs an
 *  answer, and an Alpine submit / RunPod rental is a decision made at the review card —
 *  none of those should fire unattended hours later. */
export function mdQueueable(job) {
  if (!job) return false
  if (job.execution_target && job.execution_target !== 'local') return false
  if (job.awaiting_sequence) return false
  if (mdJobIsDraft(job) || hasPendingGpuDecision(job)) return false
  return mdJobIsStartable(job) || ['stopped', 'failed'].includes(job.status)
}

/** Pure: the primary control's state — ONE button, four meanings, all about the SELECTED
 *  job (2026-08-03, with the Job Wizard).
 *
 *  Creating a run and running one are now separate acts: "＋ New job" opens the wizard,
 *  and this button starts / stops / resumes whatever is selected.  That removes the old
 *  split where a fresh Relax, a contextual Stop/Resume and a Production button competed
 *  for the same row and each knew about a different subset of job states.
 *
 *    nothing selected            → disabled, with a hint pointing at ＋ New job
 *    a seeded DRAFT              → solvate-from-seed and start it
 *    an Alpine job still prepping→ ⟳ Preparing…  (disabled, spinner)
 *    an Alpine job ready to go   → ☁ Submit to Alpine
 *    running / preparing         → ■ Stop
 *    already in the run queue    → ✕ Queued #N (click to take it back out)
 *    startable while busy        → ＋ Queue  (the server starts it when the machine frees)
 *    stopped / failed / gated    → ↻ Resume
 *    prepared but never started  → ▶ Run
 *    anything else (completed)   → disabled, with a reason
 *
 *  The two Alpine rows used to be a separate ☁ button buried in the Cluster card, which
 *  split the "what do I press to run this?" question across two places — and left the
 *  primary control saying "■ Stop Run" during a prep whose only outcome is a submit.
 *
 *  `machineBusy` is "a NAMD job is in flight right now" and `queuedIds` is the server's
 *  queue order — both come from GET /md/queue, so what the button offers and what the
 *  server would actually do can't drift apart.  `clusterState` gates the submit: there is
 *  no point offering an upload with no session behind it. */
const RUNPOD_PHASE_LABEL = Object.freeze({
  preparing: 'Preparing…', renting: 'Renting a GPU…', uploading: 'Uploading…',
})

const RUNPOD_PHASE_TITLE = Object.freeze({
  preparing: 'Solvating and building the package on this computer. Nothing is rented yet — '
    + 'attach anchors or an electric field meanwhile.',
  renting: 'Asking RunPod for the GPU you chose. Billing starts the moment a pod exists.',
  uploading: 'Uploading the package to the pod. The GPU is rented and billing while this '
    + 'runs, and NAMD starts by itself when it finishes. To abandon it, terminate the pod '
    + 'from the Clusters card.',
})

/**
 * @param {object|null} selectedJob
 * @param {object} opts
 * @param {boolean} [opts.runpodReady]    RunPod pre-flight passes (gates ▶ Rent & Run)
 * @param {string}  [opts.runpodBlocked]  why it does not, for the tooltip
 */
export function mdRunControl(selectedJob, {
  busy = false, runTarget = 'local', machineBusy = false, queuedIds = [],
  clusterState = 'disconnected', submitting = false,
  runpodReady = false, runpodBlocked = '',
} = {}) {
  if (!selectedJob) {
    return {
      action: RUN_ACTION.RUN, label: '▶ Run', disabled: true,
      title: 'Select a run in the list, or create one with ＋ New job.',
    }
  }
  if (selectedJob.awaiting_sequence) {
    return {
      action: RUN_ACTION.RUN, label: '▶ Run', disabled: busy,
      title: 'Sequence assignment is checked when you run. The job itself may be created first.',
    }
  }
  if (mdJobIsDraft(selectedJob)) {
    return {
      action: RUN_ACTION.RUN, label: mdDraftRunLabel(selectedJob), disabled: busy,
      title: 'Solvate this seeded job and start it.',
    }
  }
  // An Alpine job's whole local phase exists to produce a package to upload, so the
  // primary control tracks that: it spins while the package builds, then becomes the
  // submit. (Only Alpine — a RunPod job's rental flow is still its own thing.)
  if (selectedJob.execution_target === 'alpine') {
    if (selectedJob.status === 'preparing') {
      return {
        action: RUN_ACTION.PREPARING, label: 'Preparing…', disabled: true, spinner: true,
        title: 'Solvating and building the package on this computer. Submit unlocks when '
             + 'it is done — attach anchors or an electric field meanwhile.',
      }
    }
    // The upload itself is minutes of SFTP for an 800 MB package, and a second click on
    // an enabled-looking button during it is exactly how a job gets submitted twice.
    if (submitting) {
      return {
        action: RUN_ACTION.PREPARING, label: 'Submitting…', disabled: true, spinner: true,
        title: 'Uploading the package to Alpine, then sbatch.',
      }
    }
    if (selectedJob.resumable) {
      const blocked = alpineTargetDisabledReason(clusterState)
      return {
        action: RUN_ACTION.RESUME, label: '↻ Continue', disabled: busy || !!blocked,
        title: blocked || 'Review or adjust SLURM resources, then continue this same run from its checkpoint.',
      }
    }
    if (mdRemoteAwaitingSubmit(selectedJob)) {
      const blocked = alpineTargetDisabledReason(clusterState)
      return {
        action: RUN_ACTION.SUBMIT, label: '☁ Submit to Alpine', disabled: busy || !!blocked,
        title: blocked
          || 'Upload this package and queue it on the cluster with the resources you chose '
           + 'in the wizard.',
      }
    }
  }
  // A RunPod job has THREE unattended waits before NAMD starts, and the control used to
  // misread all of them: it said "■ Stop Run" through the local package build (offering to
  // stop a run that had not begun), and a prepared job's button was disabled entirely,
  // pointing at a review card the Job Wizard replaced. Now it mirrors Alpine — spin while
  // the machine works, then be the button that actually starts it.
  if (selectedJob.execution_target === 'runpod') {
    const phase = mdRunpodPhase(selectedJob)
    if (phase) {
      return {
        action: RUN_ACTION.PREPARING, disabled: true, spinner: true,
        label: RUNPOD_PHASE_LABEL[phase],
        title: RUNPOD_PHASE_TITLE[phase],
      }
    }
    if (mdRunpodStartable(selectedJob)) {
      return {
        action: RUN_ACTION.RUN, label: '▶ Rent & Run',
        disabled: busy || !runpodReady,
        title: runpodReady
          ? 'Rent the GPU you chose, upload this package, run the whole ladder, fetch the '
            + 'results, then destroy the pod.'
          : `Cannot run on RunPod yet:\n${runpodBlocked || 'pre-flight has not passed.'}`,
      }
    }
  }
  const base = runControlState(selectedJob, {
    verb: 'Run', isActive: mdJobIsRunning, isResumable: mdJobIsResumable, busy,
  })
  if (base.action === RUN_ACTION.STOP) {
    return { ...base, title: 'Stop this run. It can be resumed from its last checkpoint.' }
  }
  // Already waiting its turn → the button takes it back out of the queue.
  const place = queuedIds.indexOf(selectedJob.job_id)
  if (place >= 0) {
    return {
      action: RUN_ACTION.DEQUEUE, label: `✕ Queued #${place + 1}`, disabled: busy,
      title: 'Waiting for the machine. Click to take it back out of the queue.',
    }
  }
  // Something else is running → queue instead of refusing. The server starts it.
  if (machineBusy && mdQueueable(selectedJob)) {
    return {
      action: RUN_ACTION.QUEUE, label: '＋ Queue', disabled: busy,
      title: 'A run is already going. This one starts on its own when the machine frees up '
           + '— you can close the browser.',
    }
  }
  if (base.action === RUN_ACTION.RESUME) {
    // Resuming on RunPod rents a pod, so it needs the SAME gate as starting one. It did
    // not have it, and that is the whole reason a stopped run "could not be resumed": the
    // session can be disconnected (no stored key, a revoked one, RunPod unreachable) while
    // the button stays lit, offering a resume that could only ever come back as a 400.
    if (selectedJob.execution_target === 'runpod' && !runpodReady) {
      return {
        ...base, disabled: true,
        title: `Cannot resume on RunPod yet:\n${runpodBlocked || 'pre-flight has not passed.'}`,
      }
    }
    return {
      ...base,
      title: hasPendingGpuDecision(selectedJob)
        ? "The fastest GPU mode couldn't start — resume to choose how to proceed."
        : 'Resume from the last checkpoint.',
    }
  }
  if (mdJobIsStartable(selectedJob)) {
    return { ...base, label: '▶ Run', title: 'Start this prepared job.' }
  }
  // (There used to be an `mdRemoteAwaitingSubmit` catch-all here, disabling the button and
  // sending the user to "the review card". It is unreachable now and its advice was stale:
  // an awaiting-submit job is either Alpine — handled above, ☁ Submit to Alpine — or RunPod,
  // handled above as ▶ Rent & Run. The wizard replaced the review card for both.)
  return {
    ...base, disabled: true,
    title: selectedJob.status === 'completed'
      ? 'This run has finished. Use ＋ New job to set up another.'
      : `Nothing to run: this job is ${selectedJob.status}.`,
  }
}

/** Pure: what should the detail-WebSocket watchdog do for the selected job?
 *  The status WS only drives a LOCAL, non-terminal job — so:
 *    'disarm'    → nothing to watch (no selection / terminal / remote-SLURM/Alpine job)
 *    'reconnect' → local live job but the socket is gone (dropped/never opened)
 *    'refresh'   → socket open but silent past `staleMs` (wedged) → probe + reopen
 *    'idle'      → socket open and pushing recently, do nothing
 *  Keeps the local job live behind a dropped/wedged socket, where there is otherwise
 *  no poll fallback (the old `_pollTimer` was never armed). */
export function mdWatchdogDecision({ job = null, wsOpen = false, msSinceMsg = 0, staleMs = _WS_STALE_MS } = {}) {
  if (!job) return 'disarm'
  if (_TERMINAL_STATUSES.has(job.status)) return 'disarm'
  // Any remote target, not just Alpine: a RunPod run is NAMD on a rented box, so there is no
  // local status socket to reconnect to and the watchdog would retry one forever.
  if (job.slurm_job_id || mdIsRemoteJob(job)) return 'disarm'
  if (!wsOpen) return 'reconnect'
  if (msSinceMsg > staleMs) return 'refresh'
  return 'idle'
}

/** Pure: a nudge to reconnect when remote runs are in flight but the session isn't.
 *  Such jobs can't be monitored and — critically — a run that FINISHES while disconnected
 *  can't have its results fetched until the user reconnects (poll_remote_jobs no-ops when
 *  down).  Returns a message, or '' when connected/connecting or nothing is in flight.
 *  In-flight = a job handed to its scheduler (slurm_job_id / runpod_pod_id) and still
 *  queued/running/preparing.
 *
 *  BOTH targets, not just Alpine.  RunPod is the one that matters most and was the one
 *  missing: the API key is held in MEMORY ONLY (routes_runpod.connect), so a backend
 *  restart silently drops the session, the poll loop dies with it, and the job record
 *  freezes at `running` — while the pod goes on billing by the second with nothing
 *  watching it.  Reconnecting is what reaps orphans and re-attaches the supervisor, so
 *  the whole safety net depends on the user knowing to do it.  Hence the sharper wording:
 *  an idle Alpine allocation wastes SU, an unwatched pod spends money. */
export function mdRemoteReconnectPrompt(jobs, clusterState, runpodState = 'connected') {
  const down = (s) => s !== 'connected' && s !== 'connecting'
  const inFlight = (target, idKey, state) => down(state)
    ? (jobs ?? []).filter(j => j?.execution_target === target && j?.[idKey] &&
        ['queued', 'running', 'preparing'].includes(j?.status)).length
    : 0
  const nAlpine = inFlight('alpine', 'slurm_job_id', clusterState)
  const nPod = inFlight('runpod', 'runpod_pod_id', runpodState)
  const parts = []
  if (nPod) {
    parts.push(`${nPod} RunPod pod${nPod === 1 ? '' : 's'} still billing with no session `
      + 'watching — reconnect to monitor, fetch results and be able to terminate.')
  }
  if (nAlpine) {
    parts.push(`${nAlpine} Alpine run${nAlpine === 1 ? '' : 's'} in flight — reconnect to `
      + 'monitor and fetch results.')
  }
  return parts.length ? `⚠ ${parts.join(' ')}` : ''
}

/** Pure: is this a deferred-prep DRAFT job — created by "Use as NAMD seed" but not
 *  yet solvated?  Its run control reads "Relax from oxDNA/mrDNA" and clicking it runs
 *  the standard prep+relax (POST /md/jobs/{id}/prepare) from the seed's coordinates. */
export function mdJobIsDraft(job) {
  return job?.status === 'draft' && !job?.awaiting_sequence
}

/** Settings may change only before a process, scheduler, or pod owns the job. */
export function mdJobEditable(job) {
  return ['draft', 'queued'].includes(job?.status)
    && !job?.slurm_job_id && !job?.runpod_pod_id
}

/** Resolve where a newly-created job runs.
 *
 * The Job Wizard owns this choice. Legacy/non-wizard callers default to local; the
 * Clusters information card is intentionally not an input.
 */
export function mdRequestedRunTarget(request) {
  const requested = String(request?.execution_target || '').toLowerCase()
  if (['local', 'alpine', 'runpod'].includes(requested)) return requested
  return 'local'
}

/** Pure: the run-button label for a selected draft — names the seed engine so the
 *  user knows the run starts from those relaxed coordinates. */
export function mdDraftRunLabel(job) {
  if (job?.seed_blade_job_id) return '▶ Relax from BLADE'
  if (job?.seed_mrdna_job_id) return '▶ Relax from mrDNA'
  return '▶ Relax from oxDNA'
}

/** Pure: is any Alpine job submitted-and-in-flight (so the panel should keep polling
 *  SLURM status)?  Gates the remote-poll timer — false when nothing remote is active,
 *  so idle panels don't hit the network. */
export function hasActiveRemoteJob(jobs) {
  // Alpine AND RunPod. It was Alpine-only, which meant the 20 s remote poll never armed for
  // a rented run — so a pod could be provisioning, uploading, or finished, and the panel
  // would sit on whatever it last saw until the user clicked something.
  return (jobs ?? []).some(j => mdIsRemoteJob(j) && mdJobIsActive(j))
}

/** Pure: list-row label for a derived (refit/retry) child job — "Refit N", where N
 *  is its global run number among all non-root jobs (from flattenJobTree). */
export function mdChildRowLabel(job, index) {
  return `Refit ${index}`
}

/** Pure: is this job a SEEDED child (fanned out from a parent with a distinct NAMD
 *  velocity seed)?  Covers both an Alpine ensemble replica and a local production child;
 *  both indent + collapse under the parent, so the tree logic keys off this. */
export function mdIsEnsembleReplica(job) {
  return job?.ensemble_seed != null
}

/** Pure: is this job a local production run branched off a completed parent (its own
 *  seed + coords, nested under the relaxation)?  Distinguishes it from an Alpine
 *  ensemble replica so the row reads "Production N" rather than "Replica N". */
export function mdIsProductionChild(job) {
  return job?.run_kind === 'production'
}

/** Pure: is this a LEGACY job whose production was appended onto the relaxation (the
 *  old same-job layout, before production became a child job)?  True for a root
 *  relaxation (no parent, not itself a production child) that carries a production
 *  segment — such a job can be reverted to a clean relaxation via /revert-production. */
export function mdHasAppendedProduction(job) {
  if (!job || job.parent_job_id || job.run_kind === 'production') return false
  return (job.segments ?? []).some(s =>
    /production/i.test(s?.name ?? '') || /production/i.test(s?.stage ?? ''))
}

/** Pure: list-row label for a production child — "Production N · seed S" (N is 1-based
 *  from ensemble_index; falls back to the global run index). */
export function mdProductionRowLabel(job, index) {
  const n = (job?.ensemble_index != null ? job.ensemble_index + 1 : index)
  return `Production ${n} · seed ${job?.ensemble_seed}`
}

/** Pure: does this job have ensemble replica children (so its row is the one
 *  collapsible ensemble item)? */
export function mdIsEnsembleParent(job, jobs) {
  return (jobs ?? []).some(j => j?.parent_job_id === job?.job_id && mdIsEnsembleReplica(j))
}

/** Pure: list-row label for an ensemble replica — "Replica N · seed S" (N is 1-based
 *  from ensemble_index; falls back to the global run index). */
export function mdReplicaRowLabel(job, index) {
  const n = (job?.ensemble_index != null ? job.ensemble_index + 1 : index)
  return `Replica ${n} · seed ${job?.ensemble_seed}`
}

/** Pure: THE list-row label for any NAMD child job — production run, ensemble
 *  replica, or a refit/retry.  Lifted out of `mdJobRowCtx` so every list that shows
 *  NAMD children (the NAMD tab, the unified Simulate list, the animation panel's
 *  trajectory dropdown) names them identically instead of re-deriving the dispatch. */
export function mdChildLabelFor(job, index) {
  if (mdIsProductionChild(job)) return mdProductionRowLabel(job, index)
  if (mdIsEnsembleReplica(job)) return mdReplicaRowLabel(job, index)
  return mdChildRowLabel(job, index)
}

/** Pure: what the Anchors card is showing, in words — forces the selected job HOLDS, a
 *  selection that resolved to nothing, or an empty card that will apply on Run.
 *
 *  This distinction is the whole point of the read side. The same chips once meant
 *  "this job is anchored" and "someone typed this and never submitted it", and a real
 *  debugging session was misled by exactly that ambiguity.
 *  @returns {{text: string, tone: 'ok'|'warn'|'dim'}}
 */
export function mdForcesProvenance(d) {
  const a = d?.anchors
  const n = a?.n_atoms_fixed ?? a?.n_atoms_anchored ?? 0
  if (!d?.prepared) {
    return { text: 'No package yet — forces apply when this job is prepared.', tone: 'dim' }
  }
  if (a && a.applied === false) {
    return {
      text: 'Selection recorded but resolved to no residue — this run is NOT anchored.',
      tone: 'warn',
    }
  }
  if (n) {
    const k = a.k_kcal_mol_a2
    return {
      text: `Holding ${n} atom${n === 1 ? '' : 's'}`
        + (k ? ` at k=${k} kcal/mol/Å²` : ' (fixed)')
        + (d.editable ? ' — editable until this job starts.' : ' — this run owns these.'),
      tone: 'ok',
    }
  }
  return d.editable
    ? { text: 'Not anchored. Pick anchors here and they apply when you press Run.', tone: 'dim' }
    : { text: 'This run is unanchored.', tone: 'dim' }
}

/** The Hold-atoms select value → the `anchor_atoms` request field.  Now that each anchor
 *  can carry its OWN atom list, this same parse has to run on both sides of the card, so
 *  it lives with the rest of the descriptor algebra in scene/efield_math.js; this stays
 *  as the panel's name for it (3 senders + its tests import it from here). */
export const mdAnchorAtomNames = atomNamesFromValue

/** Pure: the Stiffness select's value → the `anchor_k` request field (kcal/mol/Å²).
 *  '' (Hard pin) → null, which selects NAMD fixedAtoms. A number selects harmonic
 *  restraints. 0 is NOT a hard pin — it is a restraint of zero strength — so it maps to
 *  null too rather than emitting a conskfile that restrains nothing. */
export function mdAnchorStiffness(value) {
  if (value === '' || value == null) return null
  const k = Number(value)
  return Number.isFinite(k) && k > 0 ? k : null
}

/** Pure: one-line summary of a parent's seeded children for the collapsed parent row,
 *  e.g. "⧉ 8 replicas · 2 running · 5 queued · 1 done" (Alpine ensemble) or
 *  "⧉ 3 production runs · 1 running · 2 done" (local production fan-out).  Returns ''
 *  when the job has no seeded children. */
export function ensembleChildSummary(job, jobs) {
  const reps = (jobs ?? []).filter(j => j?.parent_job_id === job?.job_id && mdIsEnsembleReplica(j))
  if (!reps.length) return ''
  let running = 0, queued = 0, done = 0, failed = 0
  for (const r of reps) {
    if (r.status === 'running') running++
    else if (r.status === 'completed') done++
    else if (r.status === 'failed' || r.status === 'stopped') failed++
    else queued++   // queued / preparing / paused (awaiting or in the SLURM queue)
  }
  const noun = reps.every(mdIsProductionChild) ? 'production run' : 'replica'
  const parts = [`⧉ ${reps.length} ${noun}${reps.length === 1 ? '' : 's'}`]
  if (running) parts.push(`${running} running`)
  if (queued) parts.push(`${queued} queued`)
  if (done) parts.push(`${done} done`)
  if (failed) parts.push(`${failed} failed`)
  return parts.join(' · ')
}

/** Pure: the seeded children (ensemble replicas / production fan-out) of a parent,
 *  sorted by ensemble_index then creation, for the detail roll-up. */
export function ensembleReplicas(job, jobs) {
  return (jobs ?? [])
    .filter(j => j?.parent_job_id === job?.job_id && mdIsEnsembleReplica(j))
    .sort((a, b) =>
      (a.ensemble_index ?? 0) - (b.ensemble_index ?? 0) ||
      (a.created_at ?? 0) - (b.created_at ?? 0))
}

/** Pure: compact per-replica state text for the ensemble roll-up — the SLURM state for
 *  a remote replica (with its id), else the plain status. */
export function mdReplicaStateText(job) {
  if (job?.execution_target === 'alpine') {
    if (mdRemoteAwaitingSubmit(job)) return 'awaiting submit'
    if (job?.slurm_state) return `${job.slurm_state}${job?.slurm_job_id ? ` · ${job.slurm_job_id}` : ''}`
    if (job?.slurm_job_id) return `${job.status} · SLURM ${job.slurm_job_id}`
  }
  return job?.status ?? ''
}

/** Pure: does this job's health/metrics come from LOCAL files the panel can read?
 *  A remote (Alpine) run streams nothing locally while in flight — its health/metrics
 *  land only after it finishes and results are fetched (health_samples populated).  So a
 *  remote job has local readouts only once it carries samples; before that the metric
 *  grid + health spinner would spin forever on data that lives on the cluster. */
/** Pure: does this run target execute on THIS machine?
 *
 *  There are now THREE targets (local / alpine / runpod), and most of this panel was
 *  written when there were two — so "not alpine" was a safe synonym for "local".  It is
 *  no longer: a RunPod job that tests `!== 'alpine'` gets treated as LOCAL and launched
 *  on the user's desktop GPU.  Ask this question, never `!== 'alpine'`. */
export function mdIsLocalTarget(target) {
  return !target || target === 'local'
}

/** Pure: does this job execute on a remote machine — an Alpine cluster OR a rented
 *  RunPod GPU?  Anything not local streams no local WebSocket and has no local
 *  readouts until its results are fetched. */
export function mdIsRemoteJob(job) {
  return !mdIsLocalTarget(job?.execution_target)
}

export function mdHasLocalReadouts(job) {
  if (!mdIsRemoteJob(job)) return true
  // Live metrics now DO arrive for a cluster run: nadoc_live_metrics.py computes them
  // on the node and the poll retrieves them, so `live_metrics` counts as a readout
  // even before any health sample exists.
  if (job?.live_metrics && Object.keys(job.live_metrics).length) return true
  return (job?.health_samples?.length ?? 0) > 0
}

/** Pure: one-line note for a remote job whose live metrics aren't available locally
 *  (in flight on the cluster), or null when local readouts apply / the awaiting-submit
 *  status line already covers it. */
export function mdRemoteReadoutNote(job) {
  if (mdHasLocalReadouts(job) || mdRemoteAwaitingSubmit(job)) return null
  const slurm = job?.slurm_job_id ? ` (SLURM ${job.slurm_job_id})` : ''
  if (job?.status === 'running' || (job?.execution_target === 'alpine' && job?.status === 'queued')) {
    return `Running on Alpine${slurm}. Speed and temperature arrive from the node each ` +
           `poll; health needs the trajectory, so use Fetch results to pull it mid-run.`
  }
  return `On Alpine${slurm} — no local readouts yet. Use Fetch results to pull them.`
}

/** Pure: classify a segment's timeline glyph.  Separated from colour/symbol mapping
 *  so the decision is unit-testable.  `skipped` (the early-stop accelerator marked a
 *  redundant chunk done without running it) takes precedence over everything — it is
 *  always a completed-but-not-run state, drawn distinctly from a chunk that ran. */
export function mdSegGlyphKind(status, { skipped = false, advisory = false, jobLive = true } = {}) {
  if (skipped) return 'skipped'
  if (status === 'done' && advisory) return 'advisory'
  // A "running" segment on a terminal job was interrupted mid-flight — pending, not active.
  if (status === 'running' && !jobLive) return 'pending'
  if (status === 'done') return 'done'
  if (status === 'failed') return 'failed'
  if (status === 'running') return 'running'
  return 'pending'
}

/** Pure: should the one-click Resume button show, and can it be clicked?  A timed-out
 *  Alpine job (`resumable`) can resume from its last checkpoint, but only with a live
 *  cluster session (Duo).  Returns {show, disabled, reason}. */
export function mdResumeButtonState(job, clusterState) {
  if (job?.execution_target !== 'alpine' || !job?.resumable) return { show: false, disabled: true, reason: '' }
  const connected = clusterState === 'connected'
  return {
    show: true,
    disabled: !connected,
    reason: connected ? 'Resume from the last checkpoint (new SLURM submission)'
                      : 'Connect to the cluster (Duo) to resume',
  }
}

/** Pure: is this remote job sitting in the SLURM queue (submitted, PENDING — waiting
 *  for the scheduler)?  Distinct from "awaiting submit" (no slurm id) and from RUNNING.
 *  Drives the queued icon + wait tooltip. */
export function mdIsRemoteQueued(job) {
  return job?.execution_target === 'alpine'
    && job?.status === 'queued'
    && !!job?.slurm_job_id
    && (job?.slurm_state == null || String(job.slurm_state).toUpperCase() !== 'RUNNING')
}

/** Pure: is this job actually executing on a cluster node right now?
 *  Queued-but-not-started has no `.restart.coor` to fetch, so it must not qualify. */
export function mdIsRemoteRunning(job) {
  return job?.execution_target === 'alpine'
    && !!job?.slurm_job_id
    && (job?.status === 'running' || String(job?.slurm_state ?? '').toUpperCase() === 'RUNNING')
}

/** Pure: is this job actually executing on a rented pod right now?
 *  The RunPod twin of `mdIsRemoteRunning`. A job with no pod id has nothing to reach,
 *  and a queued one has written no `.restart.coor` to fetch. */
export function mdIsPodRunning(job) {
  return job?.execution_target === 'runpod'
    && !!job?.runpod_pod_id
    && (job?.status === 'running' || job?.status === 'preparing')
}

/** Pure: should we pull a single display frame off the remote machine for this job?
 *
 *  Only when there is nothing local to show (`ready` false) — once a real
 *  trajectory has been fetched it outranks any snapshot.
 *
 *  The two targets gate on different things, and that asymmetry is the feature:
 *  Alpine auth is Duo-gated, so a live human session is a hard precondition. A pod is
 *  key-based, so the backend can reach it whenever the RunPod session is up — which is
 *  what lets the panel fetch snapshots on a timer instead of telling the user to. */
export function shouldFetchLiveFrame(
  job, { clusterState, displayReady, runpodConnected = false } = {},
) {
  if (displayReady) return false
  if (job?.execution_target === 'runpod') return runpodConnected && mdIsPodRunning(job)
  return clusterState === 'connected' && mdIsRemoteRunning(job)
}

/** How often a RunPod job re-pulls its display snapshot, unprompted.
 *
 *  Matched to what the pod actually produces: NAMD rewrites `output/<seg>.restart.coor`
 *  every `restartfreq` (5,000 steps — a few minutes on a big system), so polling faster
 *  just moves identical bytes. The backend enforces its own 60 s floor
 *  (`remote_live_frame.MIN_REFETCH_INTERVAL_S`); this is the UI's cadence on top. */
export const LIVE_FRAME_REFRESH_MS = 120_000

/** Pure: the countdown to the next automatic snapshot.
 *
 *  `due` is what the caller acts on; `label` is what the user reads. Returns due=true
 *  with an empty label when nothing has been fetched yet, so the first pull happens
 *  immediately rather than after a full interval of silence.
 *
 *  @param {object} p
 *  @param {number|null} p.lastFetchAt  ms epoch of the last completed fetch
 *  @param {number} p.nowMs
 *  @param {number} p.intervalMs
 */
export function liveFrameCountdown({
  lastFetchAt = null, nowMs = Date.now(), intervalMs = LIVE_FRAME_REFRESH_MS,
} = {}) {
  if (!lastFetchAt) return { due: true, msRemaining: 0, label: '' }
  const msRemaining = Math.max(0, lastFetchAt + intervalMs - nowMs)
  if (msRemaining <= 0) return { due: true, msRemaining: 0, label: '' }
  const mins = Math.ceil(msRemaining / 60_000)
  return {
    due: false,
    msRemaining,
    // "in 0 minutes" would be a lie for anything under a minute, and the exact seconds
    // are noise at this cadence.
    label: msRemaining < 60_000
      ? 'next update in under a minute'
      : `next update in ${mins} min`,
  }
}

/** Pure: the one line under the Display MD toggle for a RunPod run with no local
 *  trajectory yet. Every branch has to say something — a blank line here is what the
 *  old "fetch a live frame yourself" wording was replacing. */
export function runpodSnapshotStatus({
  fetching = false, liveFrame = null, countdownLabel = '', connected = true,
} = {}) {
  if (!connected) {
    return { text: 'Not connected to RunPod — cannot reach the pod for a snapshot.', busy: false }
  }
  if (fetching) return { text: 'Retrieving the latest frame from the pod…', busy: true }
  const base = liveFrame ? liveFrameLabel(liveFrame, 'runpod') : 'No snapshot from the pod yet'
  return { text: countdownLabel ? `${base} · ${countdownLabel}` : base, busy: false }
}

/** Pure: how to describe a fetched snapshot. It is ONE frame from a run still going
 *  on the cluster — it does not advance on its own, and saying "trajectory" would
 *  imply results that do not exist locally. */
export function liveFrameLabel(liveFrame, executionTarget = 'alpine') {
  if (!liveFrame) return ''
  // Name the machine it is still running on. Hardcoding "Alpine" mislabelled every
  // snapshot from a rented RunPod GPU.
  const where = executionTarget === 'runpod' ? 'the pod' : 'Alpine'
  const step = Number(liveFrame.step)
  return Number.isFinite(step) && step > 0
    ? `Snapshot at step ${step.toLocaleString()} — still running on ${where}`
    : `Snapshot from the running ${where === 'the pod' ? 'pod' : 'Alpine'} job`
}

/** Pure: compact duration label from a number of seconds (e.g. "45s", "6m", "1h 3m"). */
export function fmtDurationShort(secs) {
  const s = Math.max(0, Math.floor(secs))
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m`
  const h = Math.floor(m / 60)
  return `${h}h ${m % 60}m`
}

/** Pure: tooltip text for a queued remote job — how long it has waited in the queue.
 *  ``nowMs`` defaults to Date.now() (injectable for tests). */
export function mdQueueWaitLabel(job, nowMs = Date.now()) {
  const t = job?.queued_at
  if (!t) return 'Queued — waiting for the cluster scheduler'
  return `Queued ${fmtDurationShort(nowMs / 1000 - t)} ago — waiting in the cluster queue`
}

/** Pure: display rows for a job's remote resumption history (original + each resume),
 *  newest first — feeds the detail's expand chevron. */
export function mdResumeHistoryRows(job) {
  const hist = job?.resume_history ?? []
  return hist.slice().reverse().map((h, i) => {
    const n = hist.length - i
    const seg = h.segments_total ? `seg ${h.segment_reached}/${h.segments_total}` : ''
    const wt = h.walltime ? ` · ${h.walltime}` : ''
    return `#${n} · SLURM ${h.slurm_job_id ?? '—'} · ${h.state ?? '—'}${seg ? ' · ' + seg : ''}${wt}`
  })
}

// The implicit-solvent (GBIS) protocol has no explicit water box, so the salt /
// padding / water-shell / fast-mode knobs don't apply — GBIS is DNA-only, NVT,
// standard CUDA.  Pure predicate so the UI (and a test) can gray those fields.
export const IMPLICIT_GBIS_PROTOCOL = 'implicit_gbis_namd'
export function isImplicitSolventProtocol(protocol) {
  return protocol === IMPLICIT_GBIS_PROTOCOL
}

// The backend `devices` string encodes the Compute choice: "cpu" → the multicore
// build (no VRAM limit); otherwise the CUDA device ids for the GPU build.  GBIS
// implicit solvent can ONLY run on CPU, so it always resolves to "cpu".
export function deviceStringForCompute(compute, cudaDevices, protocol) {
  if (isImplicitSolventProtocol(protocol) || compute === 'cpu') return 'cpu'
  return (cudaDevices && String(cudaDevices).trim()) || '0'
}
// Inverse: which Compute option a stored `devices` string represents.
export function computeFromDeviceString(devices) {
  return String(devices ?? '').trim().toLowerCase() === 'cpu' ? 'cpu' : 'gpu'
}

// Production segments of a fast job (HMR + GPU-resident, 4 fs) run ~9x the speed
// of its strain-relief first segment (1 fs, standard CUDA): 4x from the larger
// timestep and ~2.4x per step from GPU-resident acceleration (benchmarked
// 1.7 -> 16 ns/day NPT on an RTX 3080 Ti).
export const FAST_PHASE_SPEEDUP = 9

/** Pure: when a fast-relaxation job is still in its slow strain-relief FIRST
 *  segment (1 fs, standard CUDA — the only non-fast segment in a fast ladder),
 *  return `{asterisk, tooltip}` explaining production will be ~FAST_PHASE_SPEEDUP
 *  faster, with an estimated production rate from the current speed.  Returns null
 *  when not applicable (job isn't fast mode, or it has moved past segment 0). */
export function fastPhaseSpeedNote(job, nsPerDay) {
  if (job?.prep_params?.fast !== true) return null
  if ((job?.current_segment_idx ?? 0) !== 0) return null
  const est = (typeof nsPerDay === 'number' && isFinite(nsPerDay) && nsPerDay > 0)
    ? Math.round(nsPerDay * FAST_PHASE_SPEEDUP) : null
  const tooltip =
    'Strain-relief first segment (1 fs, standard CUDA) — the slowest stage by design. '
    + 'The production segments use hydrogen-mass repartitioning + GPU-resident acceleration '
    + 'at a 4 fs timestep'
    + (est ? `, expected to reach ~${est} ns/day` : '')
    + ` (≈${FAST_PHASE_SPEEDUP}× this rate). The Speed jumps at the next segment.`
  return { asterisk: true, tooltip }
}

/** A spinning circular activity indicator (shared CSS class .nadoc-spinner). */
export function makeSpinner(color = 'currentColor', size = 11) {
  const s = document.createElement('span')
  s.className = 'nadoc-spinner'
  s.style.width = s.style.height = `${size}px`
  if (color) s.style.color = color
  s.setAttribute('aria-hidden', 'true')
  return s
}

/** Pure: does a job have at least one measurable health/metric sample yet?  Used to
 *  decide between a "Calculating…" spinner and the metric cards in the Health card. */
export function mdHasMetrics(job, persisted = null) {
  if (job?.health_samples?.length) return true
  if (job?.live_metrics && job.live_metrics.temperature_k != null) return true
  return persisted != null && (persisted.temperature_k != null || persisted.ns_per_day != null)
}

/** Pure: the per-row render signature — everything a NAMD row's appearance depends on.
 *  Shared by mdListSignature and the canonical jobs-panel ctx (rowSig) so the poll
 *  short-circuit and the unified renderer key off the exact same fields. */
export function mdJobRowSig(j) {
  return `${j.job_id}:${j.status}:${j.current_segment_idx ?? ''}:${j.failure_kind ?? ''}`
    + `:${j.out_of_date ? 1 : 0}:${j.archived ? 1 : 0}:${j.size_bytes ?? ''}:${j.dcd_size_bytes ?? ''}`
    + `:${j.execution_target ?? ''}:${j.slurm_job_id ?? ''}:${j.ensemble_seed ?? ''}`
    + `:${j.decision ? 1 : 0}`   // GPU-decision pending → ⚠ appears/clears with it
}

/** Pure: a stable signature of the job list so _renderList can skip a rebuild when
 *  nothing visible changed — otherwise the row spinners' CSS animation restarts on
 *  every poll (visible stutter).  Mirrors the oxDNA panel. */
export function mdListSignature(jobs, selectedId) {
  return (jobs ?? []).map(mdJobRowSig).join('|') + `#${selectedId ?? ''}`
}

/** Compact NAMD list caption: run kind, its visible number, and execution site. */
export function mdCompactJobLabel(job, number) {
  const kind = mdIsProductionChild(job) || mdIsEnsembleReplica(job) ? 'P' : 'R'
  const runNumber = Number.isInteger(job?.ensemble_index) ? job.ensemble_index + 1 : number
  const target = job?.execution_target === 'alpine' ? 'Alpine'
    : job?.execution_target === 'runpod' ? 'runpod' : 'local'
  return `${kind}${runNumber} ${target}`
}

/** Pure: the canonical jobs-panel ctx for NAMD (U3 unified panel).  NAMD is the
 *  richest panel, so it drives every optional slot the shared model exposes: the
 *  parent/child TREE + expand/collapse chevron, post-label markers (collapsed-ensemble
 *  summary + oxDNA/mrDNA-seed + Alpine badges), a ⧗ remote-queued symbol override (with
 *  a live-refresh dataset the panel re-titles without a rebuild), and the "Fix" VRAM-OOM
 *  row action.  Extracted from the panel closure so the payload it emits — the exact
 *  data the bespoke `_jobRow` rendered — is unit-testable in isolation. */
export function mdJobRowCtx({ selectedId = null, collapsedIds = null, jobs = [], dimColor = '#8b949e', warnColor = '#e0a800', formatTime = null } = {}) {
  return {
    engine: 'namd',
    selectedId,
    hierarchical: true,
    showIndex: false,
    compactColumns: true,
    collapsedIds,
    displayName: (job, { listIndex = 1 } = {}) => mdCompactJobLabel(job, listIndex),
    childLabel: (job, index) => mdCompactJobLabel(job, index + 1),
    childTitle: (job) => mdIsProductionChild(job)
      ? 'Production run branched from the relaxed parent (independent seed)'
      : mdIsEnsembleReplica(job) ? 'Ensemble production replica (independent seed)'
      : 'Refit / retry derived from the parent run',
    isActive: mdJobIsActive,
    // ⚠ marks a job that needs attention: the design changed since it was prepared,
    // OR it's paused on a GPU-resident fallback decision. Same glyph, message per job.
    isStale: (job) => jobOutOfDate(job) || hasPendingGpuDecision(job),
    staleTitle: (job) => hasPendingGpuDecision(job)
      ? "The fastest GPU mode couldn't start — open this job to choose how to proceed."
      : 'Design changed since this MD job was prepared — roll the design back, or prepare a new run.',
    formatTime,
    formatSize: formatBytes,
    sizeLabel: (job, total) => job.dcd_size_bytes != null && total != null
      ? `${formatBytes(job.dcd_size_bytes)} DCD / ${formatBytes(total)} total`
      : (total ? formatBytes(total) : ''),
    chevron: true,
    postLabelMarkers: () => [],
    symbolOverride: (job) => mdIsRemoteQueued(job)
      ? { glyph: '⧗', color: warnColor, title: mdQueueWaitLabel(job), dataset: { mdQueued: job.job_id } }
      : null,
    rowAction: (job) => shouldShowFixButton(job)
      ? {
          text: 'Fix', title: 'Ran out of GPU memory — adjust settings to fit this card',
          styleText: `flex-shrink:0;font-size:10px;color:#fff;background:${warnColor};`
            + 'border:none;border-radius:3px;padding:1px 7px;cursor:pointer;font-weight:600',
        }
      : null,
    rowSig: mdJobRowSig,
    colors: { dim: dimColor, warn: warnColor },
  }
}

/** Pure: should the Display-MD toggle fall back to the inherited oxDNA-seed
 *  positions?  True when the run was oxDNA-seeded AND no MD trajectory frame has
 *  been written yet (the display meta isn't ready) — so the toggle shows the
 *  structure the MD started from instead of nothing. */
export function mdShouldShowInheritedSeed(job, displayMeta) {
  return !!job?.seed_oxdna_job_id && !displayMeta?.ready
}


/** Pure: resolve the live early-stop toggle's display state from a job dict + the
 *  "a POST is in flight" flag.  A running job stashes a mid-run override the runner
 *  only consumes at the next chunk boundary, so `early_stop_relax` (the persisted
 *  flag) lags behind the user's intent for as long as a chunk takes.  While the
 *  override differs from persisted — or a POST is still in flight — the toggle is
 *  `pending`: shown in the REQUESTED position, `checked` reflecting intent, and
 *  `disabled` so it can't be spam-toggled before the change lands.
 *  Returns {checked, pending}. */
export function mdEarlyStopToggleState(job, busy = false) {
  const persisted = !!job?.early_stop_relax
  const ov = job?.early_stop_pending
  const serverPending = (ov === true || ov === false) && ov !== persisted
  const checked = serverPending ? ov : persisted
  return { checked, pending: serverPending || !!busy }
}


// ── Public entry point ────────────────────────────────────────────────────────

export function initMdJobsPanel({ mdDisplayController = null, getOccupancyOverlay = null, getAnchorSelection = null, getWorkspacePath = null, getOxdnaDisplay = null, getMdViz = null, getFlexScale = null, getClusterState = null, getSelection = null, getSolventOverlay = null, getBoxOverlay = null, getCurrentRepr = null, getWeldOverlay = null } = {}) {
  const panel   = document.getElementById('md-jobs-panel')
  const heading = document.getElementById('md-jobs-panel-heading')
  const arrow   = document.getElementById('md-jobs-panel-arrow')
  const body    = document.getElementById('md-jobs-panel-body')
  if (!panel || !body) return   // heading optional (removed; tab names the engine)

  // Form elements
  const namdStatusEl  = document.getElementById('md-jobs-namd-status')
  const newBtn        = document.getElementById('md-jobs-new-btn')      // opens the Job Wizard
  const runBtn        = document.getElementById('md-jobs-run-btn')
  const queueWrap     = document.getElementById('md-queue-wrap')
  const queueList     = document.getElementById('md-queue-list')
  const runTargetLocal  = document.getElementById('md-run-target-local')
  const runTargetAlpine = document.getElementById('md-run-target-alpine')
  const runTargetRunpod = document.getElementById('md-run-target-runpod')
  const runpodStatusEl  = document.getElementById('md-jobs-runpod-status')
  const runpodSetupEl   = document.getElementById('md-runpod-setup-mount')
  const runpodPickerEl  = document.getElementById('md-jobs-runpod-picker')
  const alpineAvailEl   = document.getElementById('md-jobs-alpine-availability')
  const runTargetAlpineLabel = document.getElementById('md-run-target-alpine-label')
  const runTargetHint   = document.getElementById('md-run-target-hint')
  const targetPanes = {
    local: document.getElementById('md-jobs-local-pane'),
    alpine: document.getElementById('md-jobs-alpine-pane'),
    runpod: document.getElementById('md-jobs-runpod-pane'),
  }
  const resumeBtn     = document.getElementById('md-jobs-resume-btn')
  const resumeHistWrap   = document.getElementById('md-jobs-resume-history-wrap')
  const resumeHistToggle = document.getElementById('md-jobs-resume-history-toggle')
  const resumeHistArrow  = document.getElementById('md-jobs-resume-history-arrow')
  const resumeHistCount  = document.getElementById('md-jobs-resume-history-count')
  const resumeHistEl     = document.getElementById('md-jobs-resume-history')
  // Live mid-relax control.  Its LAUNCH-time counterpart moved into the Job Wizard; this
  // one applies to a relaxation that is ALREADY running, at its next stage checkpoint.
  const liveControlsCard = document.getElementById('md-jobs-live-controls')
  // Anchor granularity + stiffness. Their card survives the Job Wizard move; these feed
  // BOTH launch paths (relax bakes the marker PDB, production re-resolves the selection).
  const forcesProvenanceEl = document.getElementById('md-anchors-provenance')
  const anchorAtomsSel     = document.getElementById('md-anchors-atoms')
  const anchorStiffnessSel = document.getElementById('md-anchors-stiffness')
  const earlyStopChk  = document.getElementById('md-jobs-early-stop')
  const displayToggle = document.getElementById('md-jobs-display-toggle')
  const displayStatus = document.getElementById('md-jobs-display-status')
  const liveFrameRefreshBtn = document.getElementById('md-jobs-live-frame-refresh')
  const displayIndicator      = document.getElementById('md-jobs-display-indicator')
  const displayIndicatorDot   = document.getElementById('md-jobs-display-indicator-dot')
  const displayIndicatorLabel = document.getElementById('md-jobs-display-indicator-label')
  const vizOffRadio   = document.getElementById('md-jobs-viz-off')
  const showAllToggle = document.getElementById('md-jobs-show-all')

  // The Display / Flexibility / Trajectory views are mutually-exclusive radios in
  // the "Visualizations & processing" card (each deforms the same design model).
  // Selecting a view's radio runs its "on" path (which tears the others down);
  // this keeps the "Off" radio checked whenever no view is active, so the group
  // always shows a selection — including after a programmatic turn-off (job switch,
  // lost trajectory, failed load).
  function _syncVizOffRadio() {
    if (!vizOffRadio) return
    const anyOn = [displayToggle, flexToggle, trajToggle, occupancyToggle].some(t => t?.checked)
    if (!anyOn) vizOffRadio.checked = true
  }

  // List + detail
  const listEl      = document.getElementById('md-jobs-list')
  const detailEl    = document.getElementById('md-jobs-detail')
  // Relax start/stop/resume is owned by the master run control (the retired detail
  // Start/Stop were removed); Archive/Delete are consolidated into #simulate-job-actions.
  // The single early-stop toggle (#md-jobs-early-stop) is the live mid-relax control; its
  // card sits at section level, directly under the unified Jobs card
  // (#namd-live-controls-host), not inside this panel. Pending badge: #md-jobs-early-stop-pending.
  const earlyStopPending = document.getElementById('md-jobs-early-stop-pending')
  const errorEl     = document.getElementById('md-jobs-detail-error')
  const errorBodyEl = document.getElementById('md-jobs-detail-error-body')
  const timelineEl  = document.getElementById('md-jobs-timeline')
  const metricsEl   = document.getElementById('md-jobs-metrics')
  const healthToggle  = document.getElementById('md-jobs-health-toggle')
  const healthBody    = document.getElementById('md-jobs-health-body')
  const healthArrow   = document.getElementById('md-jobs-health-arrow')
  const healthSpinner = document.getElementById('md-jobs-health-spinner')
  // Alpine-only status within the run-location card.
  const clusterStatusEl  = document.getElementById('md-jobs-cluster-status')
  const clusterReconnectEl = document.getElementById('md-jobs-cluster-reconnect-note')
  const _archive      = initJobArchive({ api, kind: 'md' })
  // The run-location "📁 Directory" button is shared across all engines and mounted once by
  // simulate_jobs.js above the jobs list; here we just READ the chosen dir (getRunDir) into the
  // create payload as run_dir so a run writes there (archive-from-birth).
  const prodBox       = document.getElementById('md-jobs-production')
  const prodStatus    = document.getElementById('md-jobs-prod-status')
  const revertProdBtn = document.getElementById('md-jobs-revert-prod-btn')

  // Visualization tools (flexibility map + trajectory scrub) — mirror the oxDNA panel.
  const flexToggle   = document.getElementById('md-jobs-flex-toggle')
  const flexStatus   = document.getElementById('md-jobs-flex-status')
  const flexBar      = document.getElementById('md-jobs-flex-bar')
  const flexLegend   = document.getElementById('md-jobs-flex-legend')
  const trajToggle   = document.getElementById('md-jobs-traj-toggle')
  // With its peers, not beside the occupancy card below: _syncVizOffRadio reads this in
  // its `anyOn` array and runs during init, so a later `const` is a TDZ that kills boot.
  const occupancyToggle = document.getElementById('md-jobs-occupancy-toggle')
  // Declared HERE, with the elements, not beside the controls factory ~1100 lines below:
  // _updateVizToggles reads it during init, and a `let` declared later is a TDZ.
  let _occupancyReady = false
  const trajStatus   = document.getElementById('md-jobs-traj-status')
  const trajLoadProgress = document.getElementById('md-jobs-traj-load-progress')
  const trajControls = document.getElementById('md-jobs-traj-controls')
  const trajPlay     = document.getElementById('md-jobs-traj-play')
  const trajPrev     = document.getElementById('md-jobs-traj-prev')
  const trajNext     = document.getElementById('md-jobs-traj-next')
  const trajSlider   = document.getElementById('md-jobs-traj-slider')
  const trajMarkers  = document.getElementById('md-jobs-traj-markers')
  const trajLabel    = document.getElementById('md-jobs-traj-label')
  const trajOpts       = document.getElementById('md-jobs-traj-opts')
  const trajInterval   = document.getElementById('md-jobs-traj-interval')
  const trajFramesHint = document.getElementById('md-jobs-traj-frames-hint')

  // ── State ──────────────────────────────────────────────────────────────────
  let _jobs         = []     // cached list from API
  let _selectedId   = null   // currently displayed job_id
  // The user clicked the selected row to DESELECT it. `_selectBestJob` runs on every poll
  // and would otherwise re-select a job a beat later, so the deselection has to be sticky
  // until something explicit happens (a row click, a launch, an empty list, a design switch).
  let _userDeselected = false
  let _ws           = null   // active WebSocket
  let _wsWatchdog   = null   // safety-net interval: reconnect a dropped detail WS / unwedge a silent one
  let _lastWsMsgAt  = 0      // ms timestamp of the last WS push (staleness detector)
  let _wsProbing    = false  // a watchdog REST probe is in flight (avoid overlap)
  let _launching    = false
  let _enginesOk    = false  // both NAMD + GROMACS found
  // The SERVER's run queue (GET /md/queue), refreshed with every job fetch. The panel is a
  // view onto it and never its owner — the queue outlives this tab.
  let _queue        = []     // [{job_id, position, design_name, status}] in run order
  let _queueBusy    = false  // a NAMD job is in flight right now → ▶ Run becomes ＋ Queue
  let _queueTimer   = null   // 5 s queue poll, armed ONLY while something is queued/running
  let _displayTimer = null
  let _prewarmTimer = null
  let _remotePollTimer = null   // periodic SLURM-status poll for in-flight Alpine jobs
  let _hadActiveRemote = false  // did the last remote poll see an active Alpine job? (edge-trigger a final refresh)
  let _displayJobId = null
  let _displayKey   = null
  let _displayMeta  = null
  let _prewarmKey   = null
  let _listSig      = null   // last-rendered list signature (avoids spinner-restart churn)
  const _legend     = { el: null }   // status-symbol legend, inserted once after the list (renderJobList memo)
  // job_id → per-segment RAW DCD frame counts, from the header-only /trajectory-meta read.
  // Prices the "→ N frames" readout for any interval without a round trip per keystroke.
  const _trajRawCounts = new Map()
  // Host MemAvailable + the prebuild memory plan. One instance per panel, so this
  // panel's two consumers (DNA prebuild + solvent) price against ONE reading.
  const _memPlan = initTrajPrebuildPlan({ api })
  const _collapsedParents = new Set()   // parent job_ids whose child rows are hidden (chevron)
  const _autoCollapsed    = new Set()   // ensemble parents we've already default-collapsed once
  let _fetchFails   = 0      // consecutive failed job-list polls (backend-down detector)
  let _inheritedSeedShown = null  // oxDNA job id whose seed positions are currently displayed
  let _mdFrameShown = false       // has a real MD frame been displayed for the current display job?
  let _earlyStopBusy = false      // a live early-stop POST is in flight (locks the toggle until the server confirms)
  const _metricsByJob = new Map()
  let _pendingAlpineReview = null   // jobId to announce as ready once its prep finishes

  // Alpine submit-review card (Phase 4): fetches the auto-recommended SLURM
  // resources for a prepared job, lets the user review/override, then submits.
  // Set while a package is uploading to the cluster, so the job row and the cluster
  // status line can say so.  A remote submit stages hundreds of MB over SFTP before
  // SLURM ever sees the job; without this the UI showed a plain "queued" the whole
  // time and looked like nothing was happening.
  let _remoteSubmitting = null      // { jobId, label } | null

  const _submitReview = initMdSubmitReview({
    api,
    toast: showToast,
    onSubmitted: async (jobId) => { await _fetchJobs(); _selectJob(jobId) },
    onSubmitStart: ({ jobId, parentId, label }) => {
      _remoteSubmitting = { jobId: jobId || parentId, label }
      window.dispatchEvent(new CustomEvent('nadoc:md-submit-progress', {
        detail: { jobId: jobId || parentId, active: true, label },
      }))
      // Indeterminate: SFTP gives no byte-level progress through this path, and a fake
      // percentage that stalls is worse than an honest spinner.
      showOpProgress(label, 'Uploading the prepared package to Alpine…', { indeterminate: true })
      _paintRemoteSubmitting()
      _paintRunControl()   // ☁ Submit → ⟳ Submitting… for the duration of the upload
    },
    onSubmitEnd: async ({ ok, message }) => {
      const submittedJobId = _remoteSubmitting?.jobId
      _remoteSubmitting = null
      window.dispatchEvent(new CustomEvent('nadoc:md-submit-progress', {
        detail: { jobId: submittedJobId, active: false },
      }))
      hideOpProgress()
      if (!ok && message && clusterStatusEl) {
        clusterStatusEl.style.display = ''
        clusterStatusEl.style.color = _C.err
        clusterStatusEl.textContent = message
      }
      _paintRemoteSubmitting()
      _paintRunControl()
      // The backend persists submit/pre-flight failures on the queued job. Refetch now;
      // otherwise only the transient toast changes and the persistent Details card does
      // not receive the error until the next polling interval (or can be missed entirely
      // if this panel is not currently polling).
      if (!ok && _selectedId) {
        await _fetchJobs()
        _selectJob(_selectedId)
      }
    },
  })

  /** Show the upload/prepare phase on the cluster status line while it is happening. */
  function _paintRemoteSubmitting() {
    if (!clusterStatusEl) return
    if (!_remoteSubmitting) return          // normal painting resumes on the next render
    clusterStatusEl.style.display = ''
    clusterStatusEl.style.color = _C.accent
    clusterStatusEl.textContent =
      `${_remoteSubmitting.label} — uploading package to Alpine, then sbatch…`
  }

  // ── Run target (Local subprocess vs. Alpine cluster) ────────────────────────
  function _currentRunTarget() {
    if (runTargetAlpine?.checked) return 'alpine'
    if (runTargetRunpod?.checked) return 'runpod'
    return 'local'
  }

  // Show/hide the "reconnect to monitor & fetch results" nudge from the live cluster state
  // + the current job set.  Called on cluster-state changes and after every list refresh.
  function _renderReconnectPrompt() {
    if (!clusterReconnectEl) return
    // RunPod has its OWN session, independent of the Alpine one — a pod outliving its
    // supervisor is invisible unless we ask the RunPod chip, not the cluster state.
    const msg = mdRemoteReconnectPrompt(
      _jobs,
      getClusterState?.() ?? 'disconnected',
      _runpod?.chip?.()?.state ?? 'unknown',
    )
    clusterReconnectEl.textContent = msg
    clusterReconnectEl.style.display = msg ? '' : 'none'
  }

  // Alpine must remain selectable while signed out: its connection chip lives inside
  // the Alpine pane, so disabling this radio creates a circular lockout (the user cannot
  // open the pane in order to sign in). Authentication still gates Submit/Resume through
  // alpineTargetDisabledReason; this control only chooses which target details to show.
  function _updateRunTargetGate(state = getClusterState?.() ?? 'disconnected') {
    const reason = alpineTargetDisabledReason(state)
    if (runTargetAlpine) runTargetAlpine.disabled = false
    if (runTargetAlpineLabel) {
      runTargetAlpineLabel.style.opacity = '1'
      runTargetAlpineLabel.style.cursor = 'pointer'
      runTargetAlpineLabel.title = reason
        ? `${reason} Select Alpine to sign in.`
        : 'Submit this relaxation to the CU Alpine cluster'
    }
    if (runTargetHint) runTargetHint.textContent = reason && runTargetAlpine?.checked
      ? '(sign in below)'
      : ''
  }

  // ── RunPod: pre-flight gate ────────────────────────────────────────────────
  // A pod bills from the moment it is created. Every pre-flight row maps to a failure
  // that ALREADY cost a real, billing pod: a wrong-architecture GPU that boots and dies
  // at step 0; a missing SSH key on a pod that refuses every connection; no network
  // volume, so the pod has neither NAMD nor any packages. So the Run button stays
  // DISABLED until every check is green — we refuse to rent a GPU we already know
  // cannot run the job.
  const _runpod = initRunpodStatus({
    mount: runpodStatusEl,
    onChange: () => _paintRunpodGate(),
  })

  // First-time setup wizard (API key → SSH key → volume → pre-flight). A successful setup
  // re-runs the pre-flight so the gate above turns green without the user hunting for it.
  initRunpodSetup({
    mount: runpodSetupEl,
    onConnected: () => _runpod.refresh(),
  })

  // GPU picker: "Check RunPod GPUs" → scrollable list of available cards with live price,
  // estimated relax wall-clock, and estimated cost; the chosen card is remembered for launch.
  let _selectedRunpodGpu = null
  const _runpodPicker = initRunpodGpuPicker({
    mount: runpodPickerEl,
    onSelect: (row) => { _selectedRunpodGpu = row },
  })

  // Alpine GPU availability: free GPUs, queue depth and estimated wait per partition.
  // Passes the selected job so the estimate is sized for the real run, not a generic one.
  initClusterAvailability({
    mount: alpineAvailEl,
    getJobId: () => _selectedId,
  })

  /**
   * Show or hide the Clusters-card RunPod boxes for the run-target radio.
   *
   * It used to paint the primary Run button too — and that was a second painter fighting
   * `_paintRunControl` over the same element, keyed on the wrong thing: the RADIO says where
   * the NEXT job will run, while the button is about the job that is SELECTED. Selecting a
   * finished local run with the radio on RunPod left the button lit and titled "Rent a GPU".
   * The pre-flight gate did not disappear — it moved into `mdRunControl`, where it is pure,
   * tested, and applied to the job the button will actually act on.
   */
  function _paintRunpodGate() {
    _paintRunControl()
  }

  /** Keep the card mutually exclusive: Local has no details, while Alpine and RunPod
   * each own a pane. Clear transient results when leaving a target so returning cannot
   * reveal information fetched for an earlier choice. */
  function _syncTargetPane(previousTarget = null) {
    const target = _currentRunTarget()
    Object.entries(targetPanes).forEach(([name, pane]) => {
      if (pane) pane.hidden = name !== target
    })
    if (previousTarget === 'runpod' && target !== 'runpod') {
      _selectedRunpodGpu = null
      _runpodPicker.clear()
    }
    if (target !== 'alpine') {
      if (clusterStatusEl) { clusterStatusEl.style.display = 'none'; clusterStatusEl.textContent = '' }
      if (clusterReconnectEl) { clusterReconnectEl.style.display = 'none'; clusterReconnectEl.textContent = '' }
      if (resumeBtn) resumeBtn.style.display = 'none'
      if (resumeHistWrap) resumeHistWrap.style.display = 'none'
    } else {
      _renderReconnectPrompt()
      const job = _selectedJob()
      if (job?.execution_target === 'alpine') _applyJobState(job)
    }
    _paintRunpodGate()
  }

  let _visibleTarget = _currentRunTarget()
  for (const _el of [runTargetLocal, runTargetAlpine, runTargetRunpod]) {
    _el?.addEventListener('change', () => {
      const next = _currentRunTarget()
      _syncTargetPane(_visibleTarget)
      _visibleTarget = next
      if (next === 'runpod') _runpod.refresh()
    })
  }
  _syncTargetPane()

  let _lastClusterState = null
  window.addEventListener('nadoc:cluster-state-change', (e) => {
    const state = e.detail?.state
    _updateRunTargetGate(state)
    _renderReconnectPrompt()
    // ☁ Submit to Alpine is gated on a live session, so signing in has to unlock it
    // without the user having to reselect the job.
    _paintRunControl()
    // Edge-detect: the chip re-broadcasts on every 15 s poll, not just transitions.
    const became = state === 'connected' && _lastClusterState !== 'connected'
    _lastClusterState = state
    // Signing in is the ONE moment a running cluster job can be looked at (Duo), so
    // that is when we go get a frame — for the job already selected, or for whichever
    // one gets selected next (_selectJob's tail runs the same refresh).
    if (became) {
      _liveFrameTried.clear()          // a new session deserves a fresh attempt
      _refreshMdDisplay()
    }
  })
  _updateRunTargetGate()
  // Health card: simple collapse (starts open).
  healthToggle?.addEventListener('click', () => {
    const open = healthBody && healthBody.style.display !== 'none'
    if (healthBody) healthBody.style.display = open ? 'none' : ''
    healthArrow?.classList.toggle('is-collapsed', open)
  })

  if (showAllToggle) showAllToggle.checked = localStorage.getItem(_SHOW_ALL_KEY) === '1'

  // ── Section collapse + advanced drawer — shared jobs-panel base (U3 slice 2c-3b) ──
  // md accommodations: the section arrow is the `is-collapsed` class idiom
  // (arrowStyle:'class'), the advanced-drawer arrow is the CSS-transform idiom
  // (advArrowStyle:'rotate'). The advanced drawer CONVERGES too (unlike oxDNA's): its
  // markup is a clean `display:none`, so the base's display-reading toggle opens on
  // the first click exactly as md's old `_advOpen` boolean did — no flip hazard.
  // md does NOT use the base's primary poll: live updates ride a WebSocket and the
  // Alpine SLURM state rides `_remotePollTimer` (setInterval), both bespoke and torn
  // down by the onClose hook. `initCollapsed` runs at the end (with the other mount
  // probes) to preserve the original apply-then-onOpen ordering.
  const _base = initJobsPanelBase({
    section: 'md-jobs-panel',
    els: { heading, body, arrow },
    arrowStyle: 'class',
    advArrowStyle: 'rotate',
    collapsible: false,   // engine header is a static label; Simulate owns the collapse
    onOpen: () => _onOpen(),
    onClose: () => { _stopMdPrewarm(); _stopRemotePoll(); _stopWsWatchdog() },   // retained for teardown symmetry (no per-panel collapse fires it now)
  })

  // ── Advanced: ⚡ Optimize + the derived run-path readout (md_advanced_optimize.js) ──
  // The module owns the policy UX (diff → caveat gate → apply); the panel only maps
  // its Advanced inputs to/from the module's field names.
  /** ⚡ moved INTO the wizard with the settings it edits — it exists to write recommended
   *  values into controls, and those controls are no longer in this panel. Wired the first
   *  time the wizard builds its modal, since that is when its button exists. */
  function _wireOptimize({ button, progressEl }) {
    initAdvancedOptimize({
      button,
      progressEl,
      getCurrent: () => _wizard.currentValues(),
      fetchHardware: () => api.optimizeMdHardware(_wizardDevices()),
      fetchRecommendation: async () => {
        const cur = _wizard.currentValues()
        // The optimiser's `facts.chosen_atoms`/`full_atoms` (the real solvated count) used
        // to be cached here for the panel's GPU-resident warning; that warning moved into
        // the wizard, which reads the package PSF directly. No panel-side cache needed.
        return await api.optimizeMdAdvanced({
          devices: _wizardDevices(),
          padding_nm: cur.padding_nm || 1.2,
          minimize_steps: cur.minimize_steps || 10000,
        })
      },
      apply: rec => _wizard.applyRecommendation({
        ...rec,
        gpu_resident: rec.gpu_resident == null
          ? null
          : residentModeFromRecommendation(rec.gpu_resident) === 'on',
      }),
      notify: (msg, kind) => showToast(msg, kind === 'error' ? 'error' : 'info'),
    })
  }

  /** The device string the hardware probe should look at, from the wizard's own state. */
  function _wizardDevices() {
    const cur = _wizard.currentValues()
    return cur.compute === 'cpu' ? 'cpu' : '0'
  }

  // ── Jobs + Visualizations cards: simple collapse (start open), mirror oxDNA ──
  for (const [tid, bid, aid] of [
    ['md-jobs-list-toggle', 'md-jobs-list-body', 'md-jobs-list-arrow'],
    ['md-jobs-viz-toggle',  'md-jobs-viz-body',  'md-jobs-viz-arrow'],
    ['md-jobs-cluster-toggle', 'md-jobs-cluster-body', 'md-jobs-cluster-arrow'],
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
  // Water / ions / periodic box — layers over whichever view is active. Owns its own
  // DOM, cache and network; the panel only tells it which job and which frame.
  // Built BEFORE the first _updateVizToggles() below, which gates it: a `const`
  // declared further down would be in its temporal dead zone there, and `?.` does
  // not save you from that.
  const solvent = initMdSolventControls({
    api, getSolventOverlay, getBoxOverlay, getCurrentRepr,
    getLiveDisplay: () => mdDisplayController,
    // Synchronous read of the same MemAvailable cache the DNA prebuild uses, so
    // both price against ONE budget. Null until it has been read once, which is
    // the honest answer (an unknown machine is not assumed to be a large one).
    getAvailableBytes: () => _memPlan.lastFreeRamBytes(),
  })
  // CPD weld pair — markers on the designed extra-base UV weld. Owns its own DOM +
  // readout ticker; the panel only tells it which job is selected. Most designs have no
  // weld pair, which the control reports as information rather than an error.
  const weld = initMdWeldControls({ api, getWeldOverlay })

  _updateVizToggles(null)   // no job selected yet → only "Off" is selectable


  // ── Engine availability check ─────────────────────────────────────────────
  async function _checkEngines() {
    if (!namdStatusEl) return
    console.log(`[${_ts()}] md-jobs: checking engines`)
    try {
      const d = await api.namdAvailable()
      if (!d) throw new Error(api.lastErrorMessage() ?? 'namd-available failed')
      console.log(`[${_ts()}] md-jobs: engines response`, d)

      _enginesOk = d.available

      // The threads default now comes from the server's own request-model default
      // (half the logical CPUs), which the wizard shows as `default` provenance — so
      // there is nothing to seed on this side.

      const missing = []
      if (!d.namd_available) missing.push('NAMD3 (install to ~/Applications/NAMD_3.0.2/)')
      if (!d.gmx_available)  missing.push('GROMACS (install + add gmx to PATH)')
      // Broadcast to the NAMD engine tab (the ⚠ not-installed marker lives there now).
      window.dispatchEvent(new CustomEvent('nadoc:engine-availability', { detail: {
        engine: 'namd', ok: !!(d.namd_available && d.gmx_available),
        reason: missing.length ? `Missing: ${missing.join(', ')}.` : '' } }))
      if (d.namd_available && d.gmx_available) {
        namdStatusEl.textContent = `NAMD3 + GROMACS found`
        namdStatusEl.style.color = _C.ok
      } else {
        namdStatusEl.textContent = `Missing: ${missing.join(', ')}`
        namdStatusEl.style.color = _C.err
      }
      _paintRunControl()   // reflect engine availability on the primary control
    } catch (err) {
      console.warn(`[${_ts()}] md-jobs: engine check failed`, err)
      namdStatusEl.textContent = 'Could not check engine status'
      namdStatusEl.style.color = _C.warn
    }
  }

  /** Surface (or clear) the "backend not responding" banner.  `#md-jobs-namd-status`
   *  is `display:none` by default (engine-availability moved to the tab ⚠), so an
   *  active job would otherwise keep looking "ongoing" with the backend dead and no
   *  visible hint — un-hide the element only while the warning is live. */
  function _setBackendStale(stale) {
    if (!namdStatusEl) return
    if (stale) {
      namdStatusEl.textContent = '⚠ Backend not responding — job status may be stale (is the server running?)'
      namdStatusEl.style.color = _C.err
      namdStatusEl.style.display = ''
    } else {
      namdStatusEl.style.display = 'none'
    }
  }

  // ── Job list fetch ─────────────────────────────────────────────────────────
  async function _fetchJobs() {
    try {
      const jobs = await api.listMdJobs()
      if (!jobs) throw new Error(api.lastErrorMessage() ?? 'HTTP error')
      _jobs = jobs
      _jobs.sort((a, b) => b.created_at - a.created_at)
      console.log(`[${_ts()}] md-jobs: fetched ${_jobs.length} jobs`)
      if (_fetchFails > 0) { _fetchFails = 0; _setBackendStale(false); _checkEngines() }  // reconnected → restore status line
      _renderList()
      _selectBestJob()
      _notifyIfJobsChanged()
      _renderReconnectPrompt()   // in-flight Alpine runs + a down session → nudge to reconnect
      void _fetchQueue()         // who's waiting, and is the machine busy (▶ Run vs ＋ Queue)
      if (displayToggle?.checked) _refreshMdDisplay()
      else _refreshMdPrewarm()
    } catch (err) {
      _fetchFails++
      console.warn(`[${_ts()}] md-jobs: _fetchJobs failed (${_fetchFails})`, err)
      // Surface a non-responding backend so an active job doesn't silently keep
      // looking "ongoing" — the poll can't confirm it's still alive.  Two strikes
      // avoids flapping on a single dropped request.
      if (_fetchFails >= 2) _setBackendStale(true)
    }
  }

  // Wake the master job list + progress bar (simulate_jobs.js, the VISIBLE list) whenever
  // THIS panel's job set/statuses change — a relax/production launch, resume, stop, Alpine
  // submit, or completion. The master self-polls only while it already holds an active
  // node, so a run launched while it's idle would otherwise not surface until a manual
  // page refresh.
  let _prevJobsSig = null
  function _notifyIfJobsChanged() {
    const sig = _jobs.map(j => `${j.job_id}:${j.status}`).sort().join('|')
    if (_prevJobsSig !== null && sig !== _prevJobsSig) {
      window.dispatchEvent(new CustomEvent('nadoc:sim-jobs-changed'))
    }
    _prevJobsSig = sig
  }

  function _selectBestJob() {
    const jobs = _visibleJobs()
    if (!jobs.length) {
      _clearSelectedJob()
      _userDeselected = false   // nothing to hold a deselection against
      return
    }
    if (_userDeselected) return   // the user deliberately cleared the selection — respect it
    const preferred = preferredMdSelection(jobs, _selectedId)
    if (preferred && preferred !== _selectedId) _selectJob(preferred)
  }

  function _onOpen() {
    _checkEngines()
    _fetchJobs()
    _startMdPrewarm()
    _startRemotePoll()
  }

  function _isDynamicsTabVisible() {
    const pane = document.getElementById('tab-content-dynamics')
    return !!pane && !pane.hidden
  }

  // Dynamics OR any view-only tab (Photo): the tabs on which an MD display —
  // a live frame, a scrubbed trajectory frame, an RMSD/RMSF colouring — is
  // allowed to stay on screen. See display_tab_policy.js.
  function _isDisplayTabVisible() {
    return displayTabIds().some(id => {
      const pane = document.getElementById(`tab-content-${id}`)
      return !!pane && !pane.hidden
    })
  }

  // Readiness dot next to the Display-MD toggle: 'warming' | 'ready' | 'error' | 'off'.
  // Reflects the background prewarm (socket load) as well as the live display, so the
  // user can see when toggling will paint instantly vs pay the ~5 s load.
  let _displayIndicatorState = 'off'
  let _warmTimer = null
  // `jobId` names the job the dot is ABOUT, which is what words the 'remote' case. It
  // defaults to the selection; callers resolving an async answer pass the job they asked
  // about, so the wording can never come from a different run than the state did.
  function _setDisplayIndicator(state, title = '', jobId = _selectedId) {
    _displayIndicatorState = state
    // A background load that hangs (huge PSF, wedged WS) fires no follow-up event, so a
    // 'warming' dot could sit amber forever.  Time it out to 'error' so it stops implying
    // progress; the next prewarm cycle re-warms and flips it back to 'ready' on success.
    if (_warmTimer) { clearTimeout(_warmTimer); _warmTimer = null }
    if (state === 'warming') {
      _warmTimer = setTimeout(() => {
        _warmTimer = null
        if (_displayIndicatorState === 'warming') _setDisplayIndicator('error')
      }, _MD_WARMING_TIMEOUT_MS)
    }
    if (!displayIndicator) return
    // Worded for the job it is about, not for whatever ran last: 'remote' reads
    // "on the pod" for RunPod and "on the cluster" for Alpine.
    const target = (_jobs.find(j => j.job_id === jobId) ?? _selectedJob())?.execution_target
    const spec = mdReadinessIndicator(state, target)
    displayIndicator.style.display = spec.show ? 'inline-flex' : 'none'
    displayIndicator.querySelector('.nadoc-spinner')?.remove()
    // The dot is small and its label is two words; the WHY lives in the tooltip, which is
    // the only place a "no frames yet" can explain that the data is on a rented GPU.
    displayIndicator.title = title || ''
    if (spec.show) {
      if (displayIndicatorDot) {
        displayIndicatorDot.style.display = state === 'warming' ? 'none' : ''
        displayIndicatorDot.style.background = _C[spec.color] ?? _C.dim
      }
      if (state === 'warming') displayIndicator.prepend(makeSpinner(_C.accent, 10))
      if (displayIndicatorLabel) displayIndicatorLabel.textContent = spec.text
    }
  }

  /** Blank the dot the instant the selection moves.
   *
   *  The dot and its tooltip describe ONE job, and the meta that fills them is a round
   *  trip away. Leaving the old job's answer up meanwhile is not a stale render, it is a
   *  wrong statement: selecting an Alpine run right after a RunPod one showed
   *  "on the pod — Nothing fetched from the pod yet" about the Alpine run, and kept
   *  showing it until the new fetch resolved (or failed, leaving 'error' behind).
   *  `_displayMeta` was already cleared here; the dot was not. */
  function _resetDisplayIndicator() {
    if (_warmTimer) { clearTimeout(_warmTimer); _warmTimer = null }
    _displayIndicatorState = 'off'
    if (displayIndicator) {
      displayIndicator.style.display = 'none'
      displayIndicator.title = ''
    }
    // The LABEL too, not just the tooltip and the visibility. `_setDisplayIndicator` only
    // writes the label when the dot is shown, so hiding alone leaves the previous job's
    // words sitting in the DOM — invisible today, but one `display:''` away from being the
    // wrong caption, and enough to make "the dot never carries another job's words" a
    // claim that only happens to be true rather than one that is enforced.
    if (displayIndicatorLabel) displayIndicatorLabel.textContent = ''
  }

  /** Is a just-resolved async answer still about the job on screen?
   *
   *  Every display fetch is `await`ed while the user can keep clicking, and neither
   *  `_refreshMdPrewarm` nor `_fetchDisplayMeta` re-checked the selection afterwards — so
   *  a slow answer for the job you just left painted itself over the one you just picked. */
  const _stillSelected = (jobId) => !!jobId && jobId === _selectedId

  function _setDisplayStatus(text, color = _C.dim, loading = false) {
    if (!displayStatus) return
    displayStatus.innerHTML = ''
    if (loading) {
      const sp = makeSpinner(color, 9)
      sp.style.cssText += ';margin-right:5px;vertical-align:middle'
      displayStatus.appendChild(sp)
    }
    displayStatus.appendChild(document.createTextNode(text))
    displayStatus.style.color = color
  }

  function _setProductionStatus(text, color = _C.dim) {
    if (!prodStatus) return
    prodStatus.textContent = text
    prodStatus.style.color = color
  }

  function _clearSelectedJob() {
    _stopLiveFrameTimer()   // no selection ⇒ no pod to snapshot
    _selectedId = null
    _userDeselected = false   // a forced clear (design switch / empty list), not a user deselect
    _displayMeta = null
    _closeWs()
    if (detailEl) detailEl.style.display = 'none'
    // Nothing selected ⇒ nothing to early-stop.
    if (liveControlsCard) liveControlsCard.style.display = 'none'
    // Clear selected-job Alpine details; connection and availability remain target-level.
    if (clusterStatusEl) { clusterStatusEl.style.display = 'none'; clusterStatusEl.textContent = '' }
    if (resumeBtn) resumeBtn.style.display = 'none'
    if (resumeHistWrap) resumeHistWrap.style.display = 'none'
    if (errorEl) {
      errorEl.style.display = 'none'
      errorEl.open = false
      if (errorBodyEl) errorBodyEl.textContent = ''
    }
    if (timelineEl) timelineEl.textContent = ''
    if (metricsEl) metricsEl.textContent = ''
    _setHealthSpinner(false)
    _renderProductionControls(null)
    _updateVizToggles(null)   // no job selected → only "Off" is selectable
    _paintRunControl()        // nothing selected → the control reverts to "▶ Relax"
  }

  // Reset the panel's own inputs back to their index.html defaults when a design is
  // closed or a different one is opened, so it doesn't carry the previous design's
  // settings.  Job PARAMETERS are no longer here — the wizard starts from the protocol's
  // defaults on every open, which is the same guarantee without a reset to remember.
  function _resetControlsToDefaults() {
    resetControlsToDefaults([trajInterval])
    _checkEngines()
    _renderTrajFramesHint()
  }

  function _currentPartPath() {
    // Authoritative source is main.js's live `_workspacePath`. The doc-scoped
    // localStorage key is the fallback — NOT the bare key, which is only correct
    // on the legacy default doc and otherwise leaks/drops the active part.
    const raw = getWorkspacePath
      ? getWorkspacePath()
      : localStorage.getItem(docKey(_WORKSPACE_PATH_KEY))
    return normalizeWorkspacePath(raw)
  }

  function _showAllJobs() {
    return !!showAllToggle?.checked
  }

  function _visibleJobs() {
    return filterJobsForPart(_jobs, _currentPartPath(), _showAllJobs())
  }

  /**
   * The production card is now INFORMATIONAL.
   *
   * Setting a production run up moved into the Job Wizard, which is the only place the
   * run can be shown side-by-side with the relaxation stage that seeds it — the
   * difference between the two was the thing nobody could see. What stays here is the
   * readiness verdict (so a selected relaxation says whether it can seed one yet) and the
   * legacy-migration button for a job whose production was appended onto the relaxation
   * under the old same-job layout.
   */
  function _renderProductionControls(job, meta = _displayMeta) {
    if (revertProdBtn) {
      revertProdBtn.style.display = mdHasAppendedProduction(job) ? '' : 'none'
    }
    if (prodBox) prodBox.style.display = ''
    if (!job) {
      _setProductionStatus('Select a completed relaxation, or open ＋ New job → Production.', _C.dim)
      return
    }
    if (mdIsProductionChild(job)) {
      _setProductionStatus('This is a production run — Run / Stop above controls it.', _C.muted)
      return
    }
    const ready = job.status === 'completed'
      && (!!meta?.production_ready || !!meta?.production_continue_available)
    if (!ready) {
      _setProductionStatus(
        meta?.production_ready_reason
          || 'Production unlocks once minimization and restraint release complete.',
        _C.dim)
      return
    }
    const chained = !meta?.production_ready && !!meta?.production_continue_available
    const checkpoint = chained ? meta.production_continue_checkpoint : meta.production_checkpoint
    const text = `Ready to seed production from ${checkpoint} — open ＋ New job → Production.`
    _setProductionStatus(
      !chained && meta.production_warning ? `${text} Warning: ${meta.production_warning}` : text,
      !chained && meta.production_warning ? _C.warn : _C.ok)
  }

  // ── Live snapshot from a running remote job ──────────────────────────────────
  // ALPINE is one-shot per session: Duo means we can only pull while the user is signed
  // in, so a failed pull (no checkpoint written yet) must not retry on every 15 s display
  // tick for the rest of the run. RUNPOD is key-based and therefore on a timer, so it
  // deliberately does NOT consult this set — see `_liveFrameTick`.
  const _liveFrameTried = new Set()
  let _liveFrameFetching = false        // a pull is in flight (drives the spinner)
  let _liveFrameAt = null               // ms epoch of the last COMPLETED pull
  let _liveFrameJobId = null            // which job `_liveFrameAt` is about
  let _liveFrameTimer = null

  /** Pull one display frame off the remote machine.  Returns true if something landed. */
  async function _fetchLiveFrame(jobId, { force = false } = {}) {
    const job = _jobs.find(j => j.job_id === jobId)
    const isPod = job?.execution_target === 'runpod'
    if (!isPod && !force && _liveFrameTried.has(jobId)) return false
    if (_liveFrameFetching) return false     // never stack pulls; ~32 MB each
    if (!isPod) _liveFrameTried.add(jobId)
    _liveFrameFetching = true
    if (isPod) _paintPodSnapshotStatus(job)
    else _setDisplayStatus('Fetching a snapshot from Alpine…', _C.warn, true)
    try {
      const res = await api.fetchMdLiveFrame(jobId, force)
      if (res?.ok) return true
      console.info(`[${_ts()}] md-jobs: no live frame yet — ${res?.reason ?? 'unavailable'}`)
      return false
    } catch (err) {
      console.warn(`[${_ts()}] md-jobs: live frame fetch failed`, err)
      return false
    } finally {
      _liveFrameFetching = false
      // Stamp on FAILURE too. A pod with no checkpoint written yet answers "not ok"
      // every time, and without a stamp the countdown would sit at "due" and re-pull on
      // every tick — the 32 MB stampede this pacing exists to prevent.
      _liveFrameAt = Date.now()
      _liveFrameJobId = jobId
    }
  }

  /** The one status line for a RunPod job whose trajectory is still on the pod. */
  function _paintPodSnapshotStatus(job) {
    const connected = runpodConnected(_runpod.preflight)
    const { label } = liveFrameCountdown({
      lastFetchAt: _liveFrameJobId === job?.job_id ? _liveFrameAt : null,
    })
    const { text, busy } = runpodSnapshotStatus({
      fetching: _liveFrameFetching,
      liveFrame: _displayMeta?.live_frame ?? null,
      countdownLabel: label,
      connected,
    })
    _setDisplayStatus(text, busy ? _C.accent : _C.warn, busy)
  }

  /** Show the manual ⟳ only where it means something: a RunPod job we can actually
   *  reach. On Alpine the equivalent action is "sign in", which this button cannot do. */
  function _updateLiveFrameControls(job) {
    if (!liveFrameRefreshBtn) return
    const show = mdIsPodRunning(job) && !!displayToggle?.checked
    liveFrameRefreshBtn.style.display = show ? '' : 'none'
    liveFrameRefreshBtn.disabled = _liveFrameFetching
    liveFrameRefreshBtn.style.opacity = _liveFrameFetching ? '0.5' : '1'
    liveFrameRefreshBtn.style.cursor = _liveFrameFetching ? 'default' : 'pointer'
  }

  /** Countdown tick for a displayed RunPod job: repaint the "next update in…" line and
   *  pull a fresh frame when it comes due. Runs only while such a job is on screen. */
  async function _liveFrameTick() {
    const job = _jobs.find(j => j.job_id === _selectedId)
    if (!job || !mdIsPodRunning(job) || !displayToggle?.checked) {
      _stopLiveFrameTimer()
      return
    }
    if (_liveFrameFetching) return
    if (!runpodConnected(_runpod.preflight)) { _paintPodSnapshotStatus(job); return }
    const { due } = liveFrameCountdown({
      lastFetchAt: _liveFrameJobId === job.job_id ? _liveFrameAt : null,
    })
    if (!due) { _paintPodSnapshotStatus(job); _updateLiveFrameControls(job); return }
    const got = await _fetchLiveFrame(job.job_id, { force: true })
    _updateLiveFrameControls(job)
    if (got) _refreshMdDisplay()
    else _paintPodSnapshotStatus(job)
  }

  function _startLiveFrameTimer() {
    if (_liveFrameTimer) return
    // 5 s: the countdown label has to move, but the FETCH cadence is the one that costs
    // anything and that is gated by `liveFrameCountdown`, not by this interval.
    _liveFrameTimer = setInterval(_liveFrameTick, 5000)
  }

  function _stopLiveFrameTimer() {
    clearInterval(_liveFrameTimer)
    _liveFrameTimer = null
    if (liveFrameRefreshBtn) liveFrameRefreshBtn.style.display = 'none'
  }

  liveFrameRefreshBtn?.addEventListener('click', async () => {
    const job = _jobs.find(j => j.job_id === _selectedId)
    if (!job || _liveFrameFetching) return
    // `force` bypasses the backend's 60 s re-fetch floor: the user asked, explicitly.
    const got = await _fetchLiveFrame(job.job_id, { force: true })
    _updateLiveFrameControls(job)
    if (got) _refreshMdDisplay()
    else _paintPodSnapshotStatus(job)
  })

  async function _fetchDisplayMeta(jobId = _selectedId) {
    if (!jobId) return null
    try {
      const d = await api.getMdDisplayMeta(jobId)
      if (!d) throw new Error(api.lastErrorMessage() ?? 'Server error')
      // Only adopt this as THE meta if it is still about the selected job — otherwise it
      // is an answer about a job the user has already left, and `_renderProductionControls`
      // would draw that job's production controls under the current one. The value is still
      // returned, so a caller that asked about a specific job explicitly gets its answer.
      if (_stillSelected(jobId)) {
        _displayMeta = d
        const job = _jobs.find(j => j.job_id === jobId)
        if (job) _renderProductionControls(job, d)
      }
      return d
    } catch (err) {
      console.warn(`[${_ts()}] md-jobs: display metadata failed`, err)
      return null
    }
  }

  async function _fetchJobMetrics(jobId = _selectedId) {
    if (!jobId) return []
    try {
      const d = await api.getMdJobMetrics(jobId)
      if (!d) throw new Error(api.lastErrorMessage() ?? 'Server error')
      const records = Array.isArray(d) ? d : []
      _metricsByJob.set(jobId, records)
      if (jobId === _selectedId) {
        const job = _jobs.find(j => j.job_id === jobId)
        if (job) _applyJobState(job)
      }
      return records
    } catch (err) {
      console.warn(`[${_ts()}] md-jobs: metrics fetch failed`, err)
      return _metricsByJob.get(jobId) ?? []
    }
  }

  function _selectDisplayJob() {
    const jobs = _visibleJobs()
    return (
      jobs.find(j => j.job_id === _selectedId) ??
      // Nothing selected (the user deselected the row): stay on whatever the display is
      // already streaming rather than jumping to another job — deselecting must not move
      // the picture, only clear the highlight.
      jobs.find(j => j.job_id === _displayJobId) ??
      jobs.find(j => j.status === 'running') ??
      jobs[0] ??
      null
    )
  }

  function _jobNeedsLiveDisplay(job) {
    return job?.status === 'queued' || job?.status === 'preparing' || job?.status === 'running'
  }

  // Show the oxDNA-seed positions a seeded MD run inherited (reuses the oxDNA display
  // controller — both deform the same model via applyFemPositions).  Returns true if
  // it showed (or is already showing) them.  Idempotent: re-applies only on first show.
  async function _showInheritedSeed(job) {
    const oxd = getOxdnaDisplay?.()
    const seedId = job?.seed_oxdna_job_id
    if (!seedId || !oxd?.displayJob) { _clearInheritedSeed(); return false }
    if (_inheritedSeedShown === seedId) {
      _setDisplayStatus(`Inherited oxDNA-seed positions — no MD frame yet (${job.status})`, _C.accent)
      return true
    }
    _clearInheritedSeed()   // switching seeds → drop the previous overlay first
    _setDisplayStatus('Loading inherited oxDNA-seed positions…', _C.muted, true)
    const r = await oxd.displayJob(seedId, true).catch(() => null)
    if (r?.ok) {
      _inheritedSeedShown = seedId
      _setDisplayStatus(
        `Inherited oxDNA-seed positions (${r.stage || ''}${r.n ? `, ${r.n} nt` : ''}) — no MD frame yet`,
        _C.accent)
      return true
    }
    return false   // seed has no relaxed frame either → fall through to "waiting"
  }

  // restore=true → also clear the model back to native (used on stop / job switch).
  // restore=false → just drop the flag: a real MD frame has already overwritten the
  // seed overlay, so restoring would wrongly flash the model back to native.
  function _clearInheritedSeed(restore = true) {
    if (!_inheritedSeedShown) return
    if (restore) getOxdnaDisplay?.()?.stopAndRestore?.()
    _inheritedSeedShown = null
  }

  async function _refreshMdDisplay() {
    if (!displayToggle?.checked) return
    if (!_isDynamicsTabVisible()) {
      _stopMdDisplay('Native positions restored')
      return
    }
    if (!mdDisplayController) {
      _setDisplayStatus('MD display unavailable', _C.warn)
      return
    }

    const job = _selectDisplayJob()
    if (!job) {
      _setDisplayStatus('No MD job found', _C.dim)
      return
    }

    // The live trajectory is mapped onto whatever design is currently OPEN.  If the chosen
    // display job belongs to a DIFFERENT design (possible in "show all job types" mode, or
    // briefly while switching designs), streaming would paint one structure's coordinates
    // onto another — refuse rather than render wrong data.
    const curPath = _currentPartPath()
    if (job.design_source_path && curPath &&
        normalizeWorkspacePath(job.design_source_path) !== curPath) {
      _stopMdDisplay('This MD job is from a different design — open it to view its trajectory')
      return
    }

    // Display job changed → reset frame tracking + drop any stale seed overlay.
    if (job.job_id !== _displayJobId) {
      _mdFrameShown = false
      _clearInheritedSeed()
    }

    // Seeded run that hasn't shown a real MD frame yet → show the INHERITED oxDNA-seed
    // positions (the structure MD started from) as a placeholder.  NAMD creates its DCD
    // file immediately (so `ready` flips true with zero frames), so we gate on "no MD
    // frame displayed yet", NOT on `ready` — otherwise the seed never shows.  The first
    // streamed MD frame clears this overlay (see the md-display-state listener).
    if (job.seed_oxdna_job_id && !_mdFrameShown) {
      await _showInheritedSeed(job)
    }

    try {
      const d = await _fetchDisplayMeta(job.job_id)
      if (!d) throw new Error('Could not load MD display metadata')
      // A quick second row click can finish while the first metadata request is in
      // flight. Never let that older response repaint the newly-selected job.
      if (_selectedId && _selectedId !== job.job_id) return
      // The user may have toggled Display MD OFF (or left the tab) while the metadata
      // fetch was in flight — bail rather than re-activating the stream behind their back.
      if (!displayToggle?.checked || !_isDynamicsTabVisible()) return
      _renderProductionControls(job, d)
      if (!d.ready || !d.config_path) {
        // A remote job's trajectory stays on the remote machine for the WHOLE run, so
        // `ready` is false throughout and this used to spin forever. Pull one frame
        // instead — cheap (one `.restart.coor`), and for a POD we can do it unprompted.
        if (shouldFetchLiveFrame(job, {
          clusterState: getClusterState?.(),
          displayReady: d.ready,
          runpodConnected: runpodConnected(_runpod.preflight),
        })) {
          const got = await _fetchLiveFrame(job.job_id)
          if (got) { _refreshMdDisplay(); return }
        }
        _displayJobId = job.job_id
        _displayKey = null
        // Seed placeholder already on screen (if seeded) → leave it; else say waiting.
        if (!_inheritedSeedShown) {
          // A RunPod job owns its own line: it is not waiting on the user for anything,
          // it is on a snapshot timer, and the status has to show that rather than the
          // backend's static "the trajectory is elsewhere" note.
          if (mdIsPodRunning(job)) {
            _paintPodSnapshotStatus(job)
          } else {
            // The backend already worked out WHY (`not_ready_reason`) and it is
            // per-target. The spinner is reserved for waits that end on their own; a
            // trajectory sitting on the Duo-gated cluster is not one of them.
            const remote = d.not_ready_code === 'remote'
            _setDisplayStatus(
              d.not_ready_reason
                || (mdIsRemoteRunning(job)
                  ? 'Running on Alpine — sign in to the cluster to pull a snapshot'
                  : `Waiting for trajectory output (${job.status})`),
              _C.warn, !remote)
          }
        }
        _updateLiveFrameControls(job)
        if (mdIsPodRunning(job)) _startLiveFrameTimer()
        return
      }

      // The DCD exists.  Stream MD frames — the first real frame overwrites the seed
      // placeholder and clears the overlay flag (md-display-state 'frame').  Until then
      // the inherited positions stay visible (an empty DCD yields no 'frame' event).
      const key = `${d.config_path}|${d.trajectory_path ?? ''}|${d.segment_name ?? ''}`
      // The background prewarm (running while the toggle was off) already loaded
      // this exact job/segment into the shared MD-display socket and cached its
      // latest frame.  Reuse that warm socket so toggle-on paints instantly instead
      // of waiting through a fresh PSF parse — same instant-display feel as oxDNA.
      const forceReload = shouldForceDisplayReload({
        key, displayKey: _displayKey, displayJobId: _displayJobId,
        jobId: job.job_id, prewarmKey: _prewarmKey,
      })
      const live = _jobNeedsLiveDisplay(job)
      _displayJobId = job.job_id
      _displayKey = key
      if (!_inheritedSeedShown) {
        _setDisplayStatus(forceReload ? `Loading ${d.segment_name ?? 'latest MD segment'}...` : `Refreshing ${d.segment_name ?? 'latest frame'}...`, _C.muted, forceReload)
      }
      mdDisplayController.displayLatest(d.config_path, { forceReload, live, jobId: job.job_id })
      // A fetched snapshot is ONE frame and does not advance — say so, or it reads as
      // a live trajectory that has silently frozen. On a pod the same line carries the
      // countdown, because there the answer to "so when does it move?" is "on its own,
      // shortly" rather than "when you fetch it".
      if (d.live_frame) {
        if (mdIsPodRunning(job)) _paintPodSnapshotStatus(job)
        else _setDisplayStatus(liveFrameLabel(d.live_frame, job.execution_target), _C.warn, false)
      }
      _updateLiveFrameControls(job)
      if (mdIsPodRunning(job)) _startLiveFrameTimer()
      if (!live) {
        clearInterval(_displayTimer)
        _displayTimer = null
      }
    } catch (err) {
      console.warn(`[${_ts()}] md-jobs: display refresh failed`, err)
      if (!_stillSelected(job.job_id)) return
      _setDisplayStatus(`Display failed: ${err.message}`, _C.err)
    }
  }

  async function _refreshMdPrewarm(force = false) {
    if (displayToggle?.checked) return
    // NB: intentionally NOT gated on the Dynamics tab being visible.  Prewarm now
    // warms the display socket (parse PSF + build model, ~5 s) in the background as
    // soon as a design with a loadable MD job is open, so toggling Display MD later
    // paints the latest frame instantly instead of paying that load inline.  It is
    // still self-gating: no ready job → no socket opened (returns below).
    if (!mdDisplayController?.prewarmLatest) return

    const job = _selectDisplayJob()
    if (!job) {
      // No job to warm — release any previously-warmed socket (free its Universe)
      // but keep the re-check timer running so a job that starts later gets warmed.
      mdDisplayController.stopPrewarm?.()
      _prewarmKey = null
      _setDisplayIndicator('off')
      return
    }

    try {
      const d = await _fetchDisplayMeta(job.job_id)
      // Display may have been toggled ON during the await (e.g. a quick off→on).
      // Bail so this stale prewarm can't clobber the controller's _displayVisible
      // back to false and suppress the just-started live stream.
      if (displayToggle?.checked) return
      // …and bail if the SELECTION moved during the await. Same class of race, and the
      // one the user hits: click a RunPod job then an Alpine one and this answer, about
      // the RunPod job, used to set the dot for the Alpine one.
      if (!_stillSelected(job.job_id)) return
      if (!d?.ready || !d.config_path) {
        // NOT always 'off'. A job running on a pod, or one still writing its first frame,
        // has a real reason the display is empty — and hiding the dot made that look
        // identical to having no job at all.
        const v = mdDisplayReadinessFromMeta(d)
        _setDisplayIndicator(v.state, v.title, job.job_id)
        return
      }
      const key = `${d.config_path}|${d.trajectory_path ?? ''}|${d.segment_name ?? ''}`
      const forceReload = force || key !== _prewarmKey
      // A fresh load will emit 'loading'→'ready'; show 'warming' up front. A reuse of
      // an already-warm socket stays 'ready' (the controller re-emits ready on reuse).
      if (forceReload && _displayIndicatorState !== 'ready') _setDisplayIndicator('warming')
      _prewarmKey = key
      mdDisplayController.prewarmLatest(d.config_path, { forceReload, jobId: job.job_id })
    } catch (err) {
      console.warn(`[${_ts()}] md-jobs: MD display prewarm failed`, err)
      if (!_stillSelected(job.job_id)) return
      _setDisplayIndicator('error')
    }
  }

  function _startMdPrewarm(force = true) {
    if (_prewarmTimer) return
    // force=false lets the first refresh REUSE an already-warm socket (e.g. right
    // after toggling display off — see _stopMdDisplay) instead of re-parsing the PSF.
    _refreshMdPrewarm(force)
    _prewarmTimer = setInterval(_refreshMdPrewarm, _MD_PREWARM_INTERVAL_MS)
  }

  function _stopMdPrewarm() {
    clearInterval(_prewarmTimer)
    _prewarmTimer = null
    _prewarmKey = null
    mdDisplayController?.stopPrewarm?.()
  }

  function _startRemotePoll() {
    if (_remotePollTimer) return
    _remotePollTimer = setInterval(_maybePollRemote, _MD_REMOTE_POLL_MS)
  }

  function _stopRemotePoll() {
    clearInterval(_remotePollTimer)
    _remotePollTimer = null
  }

  /** Refresh in-flight Alpine jobs (no live WS push for remote jobs). Cheap no-op
   *  when nothing is submitted-and-active; mdListSignature keeps the list from
   *  needlessly rebuilding when the SLURM state hasn't changed. */
  async function _maybePollRemote() {
    if (!hasActiveRemoteJob(_jobs)) {
      // Active→idle edge: the poll that saw the last replica finish may have run before
      // the backend fetched its cluster health_samples, so the ensemble grid/metrics can
      // stay on the "remote — appears after the run" note forever.  Do ONE more refresh
      // on the transition to pull the now-arrived samples before going quiet.
      if (_hadActiveRemote) {
        _hadActiveRemote = false
        await _fetchJobs()
        const sel = _jobs.find(j => j.job_id === _selectedId)
        if (sel) { _applyJobState(sel); _fetchJobMetrics(sel.job_id) }
      }
      return
    }
    _hadActiveRemote = true
    await _fetchJobs()
    // _selectJob early-returns for an unchanged selection, so the selected remote
    // job's DETAIL (status / cleared error / SLURM state) wouldn't refresh on its
    // own — re-apply it explicitly.
    const sel = _jobs.find(j => j.job_id === _selectedId)
    if (sel && mdIsRemoteJob(sel)) _applyJobState(sel)
    // The primary control reads the phase off runpod_pod_id / runpod_pid, which only move
    // on this poll — without a repaint it would stay on "Renting a GPU…" through the whole
    // upload and on into the run.
    _paintRunControl()
    _refreshQueuedWaits()
  }

  /** Keep queued jobs' "waiting Nm" tooltips fresh without rebuilding the list (which
   *  would restart other rows' spinners) — mdListSignature is stable while PENDING. */
  function _refreshQueuedWaits() {
    if (!listEl) return
    for (const el of listEl.querySelectorAll('[data-md-queued]')) {
      const job = _jobs.find(j => j.job_id === el.dataset.mdQueued)
      if (job && mdIsRemoteQueued(job)) el.title = mdQueueWaitLabel(job)
    }
  }

  function _startMdDisplay() {
    if (!displayToggle) return
    if (_occupancyIsActive()) _setOccupancyOff()
    _setFlexOff()                     // live display + flex/traj are mutually exclusive
    _setTrajOff()
    displayToggle.checked = true
    clearInterval(_prewarmTimer)
    _prewarmTimer = null
    clearInterval(_displayTimer)
    _setDisplayStatus('Searching for current MD output...', _C.muted, true)
    _fetchJobs()
    _refreshMdDisplay()
    _displayTimer = setInterval(_refreshMdDisplay, 15000)
    // Solvent rides the live stream in this view; the request is replayed by the
    // socket on (re)connect, so ordering against the WS handshake doesn't matter.
    solvent?.setEnabled(true, 'live')
    solvent?.setJob(_selectedId)
    weld?.setJob(_selectedId)
  }

  function _stopMdDisplay(status = 'Off') {
    clearInterval(_displayTimer)
    _displayTimer = null
    // The snapshot timer is the display's, not the job's: nothing should keep pulling
    // ~32 MB off a pod for a view that is no longer on screen.
    _stopLiveFrameTimer()
    solvent?.setEnabled(false)
    solvent?.clear()
    // Kill any in-flight backend trajectory/RMSF/surface analysis for this job so a
    // heavy MDAnalysis read of the live DCD can't keep running after the user
    // toggles the view off (the run-away that used to wedge the server).
    if (_displayJobId) api.cancelMdAnalysis(_displayJobId)
    _displayJobId = null
    const displayKeyBefore = _displayKey
    _displayKey = null
    if (displayToggle) displayToggle.checked = false
    _mdFrameShown = false
    _clearInheritedSeed()             // drop any inherited oxDNA-seed overlay too (restore native)
    // Revert the scene to native but KEEP the display socket + cached frame warm, so
    // the indicator stays 'ready' and a re-toggle is instant (no PSF re-parse).  Only
    // fall back to a fresh warm-up when there was no warm socket to keep.
    const keptWarm = mdDisplayController?.stopDisplayKeepWarm?.()
    _setDisplayStatus(status, _C.dim)
    if (keptWarm) {
      _prewarmKey = displayKeyBefore  // so the next (non-forced) refresh reuses the socket
      _setDisplayIndicator('ready')
      _startMdPrewarm(false)          // non-forced → decideReload 'reuse-open', no re-warm
    } else {
      _startMdPrewarm()               // no warm socket → fresh background warm-up
    }
    _syncVizOffRadio()
  }

  displayToggle?.addEventListener('change', () => {
    if (displayToggle.checked) _startMdDisplay()
    else _stopMdDisplay('Native positions restored')
  })

  // "Off" radio: turn every view off (native positions).  The browser already
  // unchecked whichever view was active; run each teardown (all idempotent) so
  // the model is restored and any in-flight analysis is cancelled.
  // Off is an idempotent action, not merely a radio transition. A stale already-checked
  // Off control must still clear shared occupancy scene ownership when clicked.
  vizOffRadio?.addEventListener('click', () => {
    if (_occupancyReady && _occupancyIsActive()) _setOccupancyOff()
    _setFlexOff()
    _setTrajOff()
    _stopMdDisplay('Native positions restored')
  })

  showAllToggle?.addEventListener('change', () => {
    localStorage.setItem(_SHOW_ALL_KEY, showAllToggle.checked ? '1' : '0')
    _renderList()
    _selectBestJob()
    if (displayToggle?.checked) _refreshMdDisplay()
    else _refreshMdPrewarm(true)
  })

  window.addEventListener('nadoc:workspace-path-change', () => {
    _clearSelectedJob()
    _resetControlsToDefaults()   // drop the previous design's MD settings
    _renderList()
    if (displayToggle?.checked) _refreshMdDisplay()
    else _refreshMdPrewarm(true)
  })

  // ── Visualization tools: flexibility map (RMSF) + trajectory scrub ────────────
  // A second display controller (getMdViz) drives these — same machinery as the
  // oxDNA panel, pointed at the MD job endpoints.  Live display / flex / trajectory
  // are mutually exclusive (each deforms the same design model).
  function _selectedJob() { return _jobs.find(j => j.job_id === _selectedId) || null }

  // A job has a scrub-able trajectory / flex map once any segment has written frames.
  function _mdHasTrajectory(job) {
    if (!job) return false
    if (['running', 'completed', 'stopped', 'failed'].includes(job.status)) return true
    return (job.segments || []).some(s => s.status === 'done' || s.status === 'running')
  }

  // Trajectory player (play/pause + scrub slider); seeks drive the display frame.
  const trajPlayer = initOxdnaTrajectoryPlayer({
    playBtn: trajPlay, slider: trajSlider, markersEl: trajMarkers, label: trajLabel,
    loadProgressEl: trajLoadProgress,
    prevBtn: trajPrev, nextBtn: trajNext,
    onSeek: (i) => { getMdViz?.()?.showFrame(i); solvent?.showFrame(i) },
    onBeforePlay: async () => {
      const v = getMdViz?.()
      if (!v) return true
      v.setPlaying(true)
      // CG plays instantly (prebuildHeavy is a no-op for the bead model). A heavy rep has
      // to have every played frame in hand first, and on a long trajectory that is tens of
      // seconds — REPORT IT. Discarding the progress callback (`() => {}`) left the play
      // button sitting on a bare ⏳ with nothing moving anywhere, which reads as "play is
      // broken", not "play is waiting". Same status line the toggle's own prebuild uses.
      const base = (trajStatus?.textContent || '').split(' · preparing')[0].split(' · atoms')[0]
      const r = await v.prebuildHeavy((done, total) => {
        if (total) _setTrajStatus(`${base} · preparing atoms ${done}/${total}…`, _C.accent)
      })
      if (r?.n) _setTrajStatus(`${base} · atoms ready (${r.frames ?? r.n} frames)`, _C.ok)
      return r?.ok !== false
    },
    onPlayStateChange: (playing) => { if (!playing) getMdViz?.()?.setPlaying(false) },
  })

  function _setFlexStatus(text, color = _C.dim) {
    if (flexStatus) { flexStatus.textContent = text; flexStatus.style.color = color }
  }
  function _setFlexBar(state) {
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
    flexLegend.innerHTML =
      `<div style="display:flex;align-items:center;gap:5px;font-size:9px;color:${_C.dim};margin-top:3px">` +
      `<span>${min.toFixed(2)} nm</span>` +
      `<span style="flex:1;height:7px;border-radius:3px;background:linear-gradient(90deg,#440154,#3b528b,#21918c,#5dc863,#fde725)"></span>` +
      `<span>${max.toFixed(2)} nm</span></div>` +
      `<div style="font-size:9px;color:${_C.dim}">rigid → flexible (RMSF)</div>`
  }
  // The SAME card the oxDNA panel uses, on the md- id prefix with its own fetch.
  // Only production (unrestrained) dynamics is ever clustered — see mdHasFreeSampling.
  const _occupancy = initOccupancyControls({
    api,
    engine: 'md',
    getOverlay: () => getOccupancyOverlay?.() ?? null,
    getDisplay: () => getMdViz?.() ?? null,
    getSelectedJobId: () => _selectedId,
    getAnchorSelection,
    fetchOccupancy: ({ jobId, params, selection, refetch, signal }) => {
      const opts = { ...params, refetch }
      return selection
        ? api.postMdOccupancy(jobId, signal, { ...opts, selection })
        : api.getMdOccupancy(jobId, signal, opts)
    },
  })

  _occupancyReady = true

  function _setOccupancyOff() {
    _occupancy?.off()
    // Occupancy setup is asynchronous; teardown must also invalidate the interval before
    // the display has published mode='occupancy', or a late completion leaves states up.
    getMdViz?.()?.stopAndRestore()
    if (occupancyToggle) occupancyToggle.checked = false
    _syncVizOffRadio()
  }
  function _occupancyIsActive() {
    return !!_occupancy?.isActive() || getMdViz?.()?.mode?.() === 'occupancy'
  }
  occupancyToggle?.addEventListener('change', async () => {
    if (!occupancyToggle.checked) { _setOccupancyOff(); return }
    if (!_selectedId) {
      occupancyToggle.checked = false
      showToast('Select an MD job first', 'warn')
      _syncVizOffRadio()
      return
    }
    if (displayToggle?.checked) _stopMdDisplay('Native positions restored')
    _setFlexOff()
    _setTrajOff()
    await _occupancy?.refresh()
  })

  function _setFlexOff() {
    if (getMdViz?.()?.mode?.() === 'rmsf') getMdViz().stopAndRestore()
    if (flexToggle) flexToggle.checked = false
    getFlexScale?.()?.hide?.()
    _setFlexBar('off')
    _setFlexLegend(null, null)
    _setFlexStatus('', _C.dim)
    _syncVizOffRadio()
  }
  async function _refreshFlex() {
    const v = getMdViz?.()
    if (!_selectedId || !v) return
    const jobId = _selectedId
    _setFlexStatus('Computing average structure + RMSF…', _C.accent)
    _setFlexBar('computing')
    const r = await v.displayRmsf(jobId)
    if (jobId !== _selectedId) return
    if (r.ok) {
      _setFlexBar('done')
      _setFlexLegend(r.min, r.max)
      getFlexScale?.()?.show?.({ title: 'RMSF (nm)', min: r.min, max: r.max, mapType: 'flex',
        onRecolor: (lo, hi, cmap) => getMdViz?.()?.recolorRmsf?.(lo, hi, cmap) })
      const conf = r.confidence || {}
      const note = conf.preliminary ? ' · preliminary (short run)' : ''
      _setFlexStatus(`Avg structure · ${r.n} bases · ${r.nFrames ?? '?'} frames${note}`,
                     conf.preliminary ? _C.warn : _C.ok)
    } else {
      _setFlexBar('off')
      _setFlexLegend(null, null)
      _setFlexStatus(r.reason || 'no data', _C.warn)
      if (flexToggle) flexToggle.checked = false
    }
  }
  flexToggle?.addEventListener('change', async () => {
    if (flexToggle.checked) {
      if (!_selectedId) { flexToggle.checked = false; showToast('Select an MD job first', 'warn'); _syncVizOffRadio(); return }
      if (!_mdHasTrajectory(_selectedJob())) {
        flexToggle.checked = false; _setFlexStatus('No trajectory frames yet', _C.warn); _syncVizOffRadio(); return
      }
      if (displayToggle?.checked) _stopMdDisplay('Native positions restored')
      if (_occupancyIsActive()) _setOccupancyOff()
      _setTrajOff()
      await _refreshFlex()
    } else {
      _setFlexOff()
    }
  })

  function _setTrajStatus(text, color = _C.ok) {
    if (trajStatus) { trajStatus.textContent = text; trajStatus.style.color = color }
  }
  function _setTrajOff() {
    trajPlayer.stop()
    if (getMdViz?.()?.mode?.() === 'trajectory') getMdViz().stopAndRestore()
    if (trajToggle) trajToggle.checked = false
    if (trajControls) trajControls.style.display = 'none'
    _setTrajStatus('', _C.dim)
    solvent?.setEnabled(false)
    solvent?.clear()
    _syncVizOffRadio()
  }
  // Frame interval, clamped in JS — the min/max attributes are a hint to the browser,
  // not a guarantee.
  function _trajInterval() {
    const n = parseInt(trajInterval?.value ?? '', 10)
    return Number.isFinite(n) && n >= 1 ? n : DEFAULT_TRAJ_INTERVAL
  }
  /** Raw per-segment DCD frame counts for the selected job, cached per job id.  Comes
   *  from the header-only /trajectory-meta read, so the "→ N frames" readout can be
   *  recomputed as the user types without touching the network. */
  async function _loadTrajRawCounts(jobId, { refetch = false } = {}) {
    if (!jobId) return null
    if (!refetch && _trajRawCounts.has(jobId)) return _trajRawCounts.get(jobId)
    const meta = await api.getMdTrajectoryMeta(jobId).catch(() => null)
    if (!meta?.ready) return null
    const counts = (meta.stages || []).map(s => Number(s.n_raw) || 0)
    _trajRawCounts.set(jobId, counts)
    if (jobId === _selectedId) _renderTrajFramesHint()
    return counts
  }
  function _renderTrajFramesHint() {
    if (!trajFramesHint) return
    const counts = _selectedId ? _trajRawCounts.get(_selectedId) : null
    if (!counts || !counts.length) { trajFramesHint.textContent = ''; return }
    const frames = stridedFrameCount(counts, _trajInterval())
    const raw = counts.reduce((n, c) => n + c, 0)
    trajFramesHint.textContent =
      `→ ${frames.toLocaleString()} frame${frames === 1 ? '' : 's'} of ${raw.toLocaleString()} written`
    trajFramesHint.style.color = frames >= TRAJ_FRAME_CONFIRM ? _C.warn : _C.dim
  }
  /** Gate a heavy load behind a confirm once the interval asks for a lot of frames.
   *  Warn, never cap — the frames were explicitly requested. */
  function _confirmTrajLoad() {
    const counts = _selectedId ? _trajRawCounts.get(_selectedId) : null
    if (!counts || !counts.length) return true
    const frames = stridedFrameCount(counts, _trajInterval())
    if (frames < TRAJ_FRAME_CONFIRM) return true
    return window.confirm(
      `Frame interval ${_trajInterval()} loads ${frames.toLocaleString()} frames.\n\n`
      + 'That can take several minutes and a lot of memory. Continue?')
  }
  /** Build every atomistic/surface frame the trajectory will need, UP FRONT.
   *
   *  Reconstructing them lazily as the user scrubs is what made an all-atom trajectory
   *  feel broken: each first visit to a frame is a fresh backend analysis (the MD
   *  context — PSF parse + model — is rebuilt per request, ~32 s on a 300 k-atom system
   *  against ~2.8 s per extra frame in the same call), so scrubbing stalled repeatedly.
   *  One batched prebuild pays that context cost once.
   *
   *  No-op for the CG bead rep, which is instant and needs nothing baked. */
  const _freeRamBytes  = () => _memPlan.freeRamBytes()
  /** What an all-atom prebuild for the loaded trajectory would cost on THIS machine. */
  const _trajMemoryPlan = (v) => _memPlan.planFor(v)

  const _LIMIT_WHY = {
    ram: 'free RAM', heap: 'browser memory limit', budget: 'memory budget',
  }

  async function _prebuildTrajHeavy(v, baseStatus) {
    if (typeof v?.prebuildHeavy !== 'function') return
    // CG plays instantly — there is nothing to prepare, so don't flash a spinner over a
    // button that is genuinely ready.
    const heavy = repKind(getCurrentRepr?.()) !== 'cg'
    if (!heavy) return _prebuildTrajHeavyInner(v, baseStatus)
    // Mark the player busy for the WHOLE prepare, including the memory plan + confirm
    // above the fetch loop. Playback needs every coarse cell in memory, so until this
    // finishes the play button must not offer a ▶ it cannot honour. `finally` is what
    // guarantees it clears on every exit — cancel, cap-declined, or throw.
    trajPlayer.setPreparing({ done: 0, total: _trajTotalFrames(v) || 1 })
    try {
      return await _prebuildTrajHeavyInner(v, baseStatus)
    } finally {
      trajPlayer.setPreparing(null)
    }
  }

  async function _prebuildTrajHeavyInner(v, baseStatus) {
    const plan = await _trajMemoryPlan(v)
    // Warn BEFORE spending minutes rebuilding frames that won't fit. The estimate uses
    // the exact serial span once the topology is known and a per-nucleotide estimate
    // before that, so the first load is priced too rather than silently attempted.
    if (plan?.capped && plan.limitedBy === 'ram') {
      const free = await _freeRamBytes()
      const ok = window.confirm(
        `The full atomistic trajectory needs about ${formatBytes(plan.wantBytes)}, but only `
        + `${formatBytes(free ?? 0)} of memory is free on this machine.\n\n`
        + `Loading all ${_trajTotalFrames(v)} frames could exhaust it. `
        + `Prepare ${plan.frames} evenly-spaced frames instead?`)
      if (!ok) { _setTrajStatus(`${baseStatus} · atoms not prepared`, _C.warn); return }
    }
    const r = await v.prebuildHeavy((done, total) => {
      _setTrajStatus(`${baseStatus} · preparing atoms ${done}/${total}…`, _C.accent)
      trajPlayer.setPreparing({ done, total })   // same count, on the button's tooltip
    }, { budgetBytes: plan?.budgetBytes ?? null }).catch(() => null)
    if (!r || !r.n) { _setTrajStatus(baseStatus, _C.ok); return }   // CG, or cancelled
    // Say plainly when memory forced a coarser set than the slider has — and WHICH limit
    // bound — otherwise the atomistic view silently snaps to neighbours and looks laggy.
    const why = _LIMIT_WHY[plan?.limitedBy] || 'memory limit'
    _setTrajStatus(
      r.capped
        ? `${baseStatus} · atoms: ${r.frames} of ${r.trajFrames} frames (${why})`
        : `${baseStatus} · atoms ready (${r.frames} frames)`,
      r.capped ? _C.warn : _C.ok)
  }

  function _trajTotalFrames(v) { return Number(v?.trajectoryInfo?.()?.total) || 0 }

  async function _refreshTraj() {
    const v = getMdViz?.()
    if (!_selectedId || !v) return
    const interval = _trajInterval()
    _setTrajStatus('Loading trajectory…', _C.accent)
    const jobId = _selectedId
    trajPlayer.setLoading({ done: 0, total: 0 })
    const poll = setInterval(async () => {
      const p = await api.getMdTrajectoryProgress(jobId).catch(() => null)
      if (_selectedId === jobId && p?.active) trajPlayer.setLoading(p)
    }, 250)
    let r
    try {
      r = await v.loadTrajectory(jobId, true, 'lineage', interval)
    } finally {
      clearInterval(poll)
      trajPlayer.setLoading(null)
    }
    if (r.ok) {
      if (trajControls) trajControls.style.display = ''
      trajPlayer.setTrajectory(r.n_frames, r.markers)
      const nStages = (r.stages || []).length
      const base =
        `${r.n_frames} frames · ${nStages} segment${nStages === 1 ? '' : 's'} · every ${interval}`
      _setTrajStatus(base, _C.ok)
      // A running job keeps writing — re-price the hint against what's on disk now.
      _loadTrajRawCounts(_selectedId, { refetch: true })
      // loadTrajectory applies frame 0 through its own showFrame(0), which bypasses
      // the player's onSeek — so the solvent for frame 0 has to be asked for here.
      solvent?.setEnabled(true, 'traj')
      await solvent?.setJob(_selectedId, { stride: interval, nFrames: r.n_frames })
      weld?.setJob(_selectedId)
      solvent?.showFrame(0)
      await _prebuildTrajHeavy(v, base)
    } else {
      if (trajToggle) trajToggle.checked = false
      if (trajControls) trajControls.style.display = 'none'
      _setTrajStatus(r.reason || 'no trajectory', _C.warn)
    }
  }
  trajToggle?.addEventListener('change', async () => {
    if (trajToggle.checked) {
      if (!_selectedId) { trajToggle.checked = false; showToast('Select an MD job first', 'warn'); _syncVizOffRadio(); return }
      if (!_mdHasTrajectory(_selectedJob())) {
        trajToggle.checked = false; _setTrajStatus('No trajectory yet', _C.warn); _syncVizOffRadio(); return
      }
      if (!_confirmTrajLoad()) { trajToggle.checked = false; _syncVizOffRadio(); return }
      if (displayToggle?.checked) _stopMdDisplay('Native positions restored')
      if (_occupancyIsActive()) _setOccupancyOff()
      _setFlexOff()
      await _refreshTraj()
    } else {
      _setTrajOff()
    }
  })
  // Typing re-prices the readout (free); committing the field reloads at the new density
  // ('change', not 'input' — one fetch per edit, not one per keystroke).
  trajInterval?.addEventListener('input', _renderTrajFramesHint)
  trajInterval?.addEventListener('change', async () => {
    _renderTrajFramesHint()
    if (!trajToggle?.checked) return
    if (!_confirmTrajLoad()) return
    await _refreshTraj()
  })
  _renderTrajFramesHint()
  // Switching CG → atomistic/surface mid-scrub needs the same up-front build as loading
  // the trajectory did; without it the first switch drops back to reconstructing frames
  // one stall at a time. The controller re-applies the current frame on this event
  // (main.js → reapplyForRepr); this fills the cache behind it.
  window.addEventListener('nadoc:representation-change', () => {
    if (!trajToggle?.checked || !_selectedId) return
    const v = getMdViz?.()
    if (v?.mode?.() !== 'trajectory') return
    const base = (trajStatus?.textContent || '').split(' · preparing')[0].split(' · atoms')[0]
    _prebuildTrajHeavy(v, base)
  })

  // Enable/disable one view radio + dim its label.
  function _setRadioEnabled(t, ok) {
    if (!t) return
    t.disabled = !ok
    const lab = t.closest('label')
    if (lab) { lab.style.opacity = ok ? '1' : '0.5'; lab.style.cursor = ok ? 'pointer' : 'not-allowed' }
  }

  // Enable/disable the viz view radios for the current selection.  With NO job
  // selected only "Off" is selectable (Display needs a job; Flexibility/Trajectory
  // additionally need a written trajectory).  Turns an active view off if the job
  // switched away or lost its trajectory, and keeps "Off" checked when nothing is on.
  function _updateVizToggles(job = _selectedJob()) {
    const hasJob  = !!job
    const hasTraj = _mdHasTrajectory(job)
    _setRadioEnabled(displayToggle, hasJob)
    _setRadioEnabled(flexToggle, hasTraj)
    _setRadioEnabled(trajToggle, hasTraj)
    // Occupancy needs PRODUCTION dynamics, not merely frames: clustering the relaxation
    // ladder describes the schedule. Gated tighter than the flexibility map on purpose.
    const hasFree = mdHasProductionRun(job)
    _setRadioEnabled(occupancyToggle, hasFree)
    // `_ready` guards the `const _occupancy` this tears down: _updateVizToggles runs
    // during init, before that const exists, and touching it there is a TDZ that aborts
    // the whole panel's boot (it did once — see the occupancyToggle note above).
    if (!hasFree && occupancyToggle?.checked && _occupancyReady) _setOccupancyOff()
    if (!hasJob && displayToggle?.checked) _stopMdDisplay('Native positions restored')
    if (!hasTraj) { if (flexToggle?.checked) _setFlexOff(); if (trajToggle?.checked) _setTrajOff() }
    // Solvent layers over any view that shows ONE FRAME — the live stream or the
    // trajectory scrub, which deliver frames by different transports. The flex map
    // is deliberately excluded: an RMSF map is a time-mean structure, so there is
    // no single frame's solvent to draw.
    solvent?.setEnabled(
      !!trajToggle?.checked || !!displayToggle?.checked,
      displayToggle?.checked ? 'live' : 'traj')
    if (hasJob) _freeRamBytes()      // prime the shared budget for the readout
    // Interval row only means anything for a job with frames on disk; its readout needs
    // that job's raw per-segment counts (header-only fetch, fire-and-forget).
    if (trajOpts) trajOpts.style.display = hasTraj ? 'flex' : 'none'
    if (hasTraj && _selectedId) _loadTrajRawCounts(_selectedId)
    _renderTrajFramesHint()
    _syncVizOffRadio()
  }

  // Delete the selected NAMD job + its files. Invoked by the consolidated
  // #simulate-job-actions Delete button (dispatched by the master card on the selected
  // node). Returns true if the delete went through.
  async function deleteSelected() {
    if (!_selectedId) return false
    const job = _jobs.find(j => j.job_id === _selectedId)
    const label = job ? `${job.design_name} (${job.job_id})` : _selectedId
    if (!window.confirm(`Delete MD job ${label} and all generated files?`)) return false
    try {
      const d = await api.deleteMdJob(_selectedId)
      if (!d) throw new Error(api.lastErrorMessage() ?? 'Server error')
      if (_displayJobId === _selectedId) _stopMdDisplay('Native positions restored')
      showToast('MD job deleted', 'ok')
      _selectedId = null
      await _fetchJobs()
      if (!_jobs.length && detailEl) detailEl.style.display = 'none'
      return true
    } catch (err) {
      showToast(`Delete failed: ${err.message}`, 'error')
      return false
    }
  }

  revertProdBtn?.addEventListener('click', async () => {
    if (!_selectedId) return
    if (!window.confirm(
      'Separate this job\'s appended production into its own run?\n\n' +
      'The relaxation becomes a clean completed job you can spawn fresh production ' +
      'children from. The existing (partial) production trajectory is MOVED to a ' +
      '_superseded_production/ backup folder in the job — not deleted.')) return
    revertProdBtn.disabled = true
    try {
      const d = await api.revertMdProduction(_selectedId)
      if (!d) throw new Error(api.lastErrorMessage() ?? 'Server error')
      showToast(`Production separated (${d.moved_files} files backed up)`, 'ok')
      await _fetchJobs()
      _selectJob(_selectedId)   // now a clean relaxation
    } catch (err) {
      showToast(`Separate failed: ${err.message}`, 'error')
    } finally {
      revertProdBtn.disabled = false
    }
  })

  // Archive / unarchive the selected job. `onProgress` receives the byte-move progress
  // (the master card renders it); dispatched from #simulate-job-actions.
  async function archiveSelected({ onProgress = () => {} } = {}) {
    if (!_selectedId) return
    const job = _jobs.find(j => j.job_id === _selectedId)
    if (!job) return
    try {
      await _archive.changeDirectory(job, { onProgress })
    } finally {
      await _fetchJobs()
    }
  }

  // Leaving the Dynamics tab stops the live DISPLAY (it deforms the model, which
  // shouldn't persist off-tab) but KEEPS the background prewarm socket warm, so
  // returning + re-toggling is instant.  Prewarm now spans tabs (Option 1); it is
  // torn down only on Display-MD handoff (_startMdDisplay) or app teardown.
  // The Photo tab is EXEMPT: it renders what's on screen, so the MD frame the user
  // picked has to still be there when the photo renderer draws it.
  document.querySelectorAll('#left-tab-strip .left-tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      setTimeout(() => {
        if (displayToggle?.checked && !_isDisplayTabVisible()) {
          _stopMdDisplay('Native positions restored')  // also resumes prewarm
        } else if (!displayToggle?.checked) {
          _startMdPrewarm()
        }
      }, 0)
    })
  })

  window.addEventListener('nadoc:left-tab-change', evt => {
    const tab = evt.detail?.activeTab
    // The LIVE "Display MD" socket, not the painted trajectory scrub — so this uses the
    // stricter predicate and still stops on the Animations tab, where a stream would
    // fight animation playback for the same beads.
    if (shouldStopLiveSession(tab)) {
      if (displayToggle?.checked) _stopMdDisplay('Native positions restored')  // resumes prewarm
    } else if (shouldResumeDisplays(tab) && !displayToggle?.checked) {
      _startMdPrewarm()
    }
  })

  // Editing the design after a prep invalidates every MD job — refetch so the
  // out-of-date ⚠ markers appear immediately (main.js dispatches this on each design
  // change), not only on the next poll.  Then, if the design has a loadable MD job,
  // start warming the display socket in the BACKGROUND regardless of which tab is
  // active — so opening a design that has a running MD job makes Display MD instant
  // to toggle (Option 1).  Both are cheap no-ops when nothing applies: _startMdPrewarm
  // is idempotent, and _refreshMdPrewarm opens no socket unless a ready job exists.
  let _designChangeRefreshTimer = null
  window.addEventListener('nadoc:design-changed', () => {
    _metricsCard?.refresh()   // cached twist/curve/bp graphs no longer match the edited design
    clearTimeout(_designChangeRefreshTimer)
    _designChangeRefreshTimer = setTimeout(async () => {
      await _fetchJobs()
      // Sequence assignment changes the exact CHARMM atom count by base identity.  As
      // soon as a previously-unsequenced job becomes buildable, prepare it in place
      // (without running) so disk/VRAM/throughput/resource projections consume the
      // sequenced PSF count before the user presses Run.
      for (const job of _jobs.filter(j => j?.awaiting_sequence)) {
        const prepared = await api.prepareMdSequenceJob(job.job_id)
        if (prepared) {
          showToast('Sequences assigned — refreshing atom counts and preparing the job', 'ok')
          await _fetchJobs()
        }
      }
      if (!displayToggle?.checked) _startMdPrewarm()
    }, 150)
  })

  window.addEventListener('nadoc:md-display-state', evt => {
    const state = evt.detail?.state
    const eventJobId = evt.detail?.jobId
    // Closing/replacing a socket can still drain already-queued browser events. They
    // belong to the old job and must never flash an error over the newly selected one.
    if (eventJobId && eventJobId !== _selectedId) return
    // Drive the readiness dot for BOTH prewarm (toggle off) and live display.
    // 'loading' → warming; 'ready'/'frame' → ready; 'error' → error.
    if (state === 'error') _setDisplayIndicator('error')
    else if (state === 'frame') _setDisplayIndicator('ready')
    else if (state === 'ready') _setDisplayIndicator(displayToggle?.checked ? 'warming' : 'ready')
    else if (state === 'loading') _setDisplayIndicator('warming')

    if (!displayToggle?.checked) return
    const message = evt.detail?.message
    if (!message) return
    // A real MD frame just landed → it overwrote any inherited-seed placeholder, so
    // drop that overlay (flag only — the frame is already on screen; restoring would
    // flash to native) and remember we've shown a frame so we stop re-showing the seed.
    if (state === 'frame') {
      _clearInheritedSeed(false)
      _mdFrameShown = true
    }
    // A frame/ready state means data is on screen → drop the loading spinner; the
    // 'loading' state (trajectory still being fetched/streamed) keeps it spinning.
    if (state === 'error') _setDisplayStatus(`Display failed: ${message}`, _C.err, false)
    else if (state === 'frame') _setDisplayStatus(message, _C.accent, false)
    else if (state === 'ready') _setDisplayStatus(`${message} — loading first frame…`, _C.muted, true)
    else _setDisplayStatus(message, _C.muted, true)   // 'loading'
  })

  // A job created elsewhere (the oxDNA panel's "Use as NAMD seed") must show up
  // here even when this panel is already open — `_revealMdPanel` only refreshes
  // on a collapse→expand, so without this the new preparing job never appears.
  window.addEventListener('nadoc:md-job-created', async (evt) => {
    const jobId = evt.detail?.jobId
    await _fetchJobs()
    if (jobId) _selectJob(jobId)
  })

  // ── Relax button ──────────────────────────────────────────────────────────
  // ── Primary run control: ▶ Relax ⇄ ■ Stop ⇄ ↻ Resume (Phase C) ─────────────
  // One button, three meanings driven by the SELECTED job (job_run_control). A LOCAL
  // stopped/failed job resumes here; an Alpine job's cluster-gated resume stays on the
  // dedicated resume button.
  function _runControl() {
    // Creating a job has begun but the backend has not returned its id yet, so there is
    // no selected record from which mdRunControl can derive this transient state.
    if (_launching) {
      return { action: RUN_ACTION.PREPARING, label: 'Preparing…', disabled: true, spinner: true }
    }
    // A selected DRAFT (deferred-prep seed) relabels the launcher "Relax from oxDNA"
    // and, when clicked, solvates-from-seed + starts THIS job (POST …/prepare).
    const sel = _selectedJob()
    if (mdJobIsDraft(sel)) {
      return { action: RUN_ACTION.RUN, label: mdDraftRunLabel(sel), disabled: _launching }
    }
    return mdRunControl(sel, {
      busy: _launching,
      runTarget: _currentRunTarget(),
      // The machine runs one job at a time: while something is going, ▶ Run becomes
      // ＋ Queue and the server starts this job when the current one finishes.
      // Two sources, because neither alone is complete: this panel's own list is the
      // freshest signal for THIS design, and the server's flag covers a run belonging to
      // a design that isn't open (the queue is workspace-wide, the list is not).
      // LOCAL jobs only — see mdJobOccupiesLocalMachine for why a remote run must not
      // count, and md_queue.job_occupies_local_machine for the server side of the same rule.
      machineBusy: _queueBusy || _jobs.some(mdJobOccupiesLocalMachine),
      queuedIds: _queue.map((e) => e.job_id),
      // Gates ☁ Submit to Alpine — an upload with no Duo session behind it only 409s.
      clusterState: getClusterState?.() ?? 'disconnected',
      submitting: !!_remoteSubmitting && _remoteSubmitting.jobId === sel?.job_id,
      // Gates ▶ Rent & Run the way clusterState gates ☁ Submit: renting a pod that cannot
      // run the job still bills. Until a pre-flight has come back we do NOT block — the
      // backend runs the same check and answers with the same reason, and a button that is
      // dead on arrival because a probe has not finished is worse than one 400.
      runpodReady: !_runpod.preflight || runpodCanLaunch(_runpod.preflight),
      runpodBlocked: runpodBlockReason(_runpod.preflight),
    })
  }
  function _paintRunControl() {
    if (!runBtn) return
    const rc = _runControl()
    runBtn.textContent = rc.label
    runBtn.dataset.runAction = rc.action
    runBtn.title = rc.title || ''
    // Chain mode only queues a plan → always enabled (engines are checked at Launch).
    runBtn.disabled = rc.disabled || _launching || !_enginesOk
    // A greyed-out button with no motion reads as "broken", not "working" — so the one
    // state the user is expected to WAIT through carries a spinner beside its label.
    if (rc.spinner) {
      runBtn.prepend(makeSpinner(_C.dim, 10))
      runBtn.style.display = 'inline-flex'
      runBtn.style.alignItems = 'center'
      runBtn.style.justifyContent = 'center'
      runBtn.style.gap = '5px'
    } else {
      runBtn.style.display = ''
      runBtn.style.gap = ''
    }
    // Three readings, three colours. GREEN = this starts a run now (including sending it
    // to the cluster — a submit spends SU and starts a real run). AMBER = this stops or
    // resumes a real run (the green Run styling on a Stop button is the kind of thing that
    // gets a live run killed by accident). BLUE = scheduling only, nothing happens to the
    // machine yet — the same blue as ＋ New job, which is also a "set it up" action.
    const queueing = rc.action === RUN_ACTION.QUEUE || rc.action === RUN_ACTION.DEQUEUE
    const starting = rc.action === RUN_ACTION.RUN || rc.action === RUN_ACTION.SUBMIT
      || rc.action === RUN_ACTION.PREPARING
    const stopping = !queueing && !starting
    runBtn.style.background = runBtn.disabled ? '#122117'
      : queueing ? '#1c2333' : (stopping ? '#2d2119' : '#1a4a1a')
    runBtn.style.borderColor = runBtn.disabled ? _C.border
      : queueing ? '#30456d' : (stopping ? '#d29922' : _C.ok)
    runBtn.style.color = runBtn.disabled ? _C.dim
      : queueing ? '#8fb3ff' : (stopping ? '#e3b341' : _C.ok)
    runBtn.style.cursor = runBtn.disabled ? 'not-allowed' : 'pointer'
  }
  // ── The run queue ─────────────────────────────────────────────────────────
  // One machine, one NAMD job at a time.  While something is running, ▶ Run becomes
  // ＋ Queue: the job is parked on the SERVER (POST /md/queue), which starts it when the
  // machine frees up — so closing the browser doesn't cancel what's waiting.
  function _applyQueue(res, { detectStart = false } = {}) {
    if (!res) return
    // The queue shrank with no click of ours → the server started something.
    const started = detectStart && _queue.length > (res.queue?.length ?? 0)
    _queue = Array.isArray(res.queue) ? res.queue : []
    _queueBusy = !!res.busy
    _renderQueue()
    _paintRunControl()
    _armQueuePoll()
    // Pull the job list so the newly-running job appears without the user clicking.
    if (started) void _fetchJobs()
  }
  async function _fetchQueue(opts = {}) {
    try {
      _applyQueue(await api.getMdQueue(), opts)
    } catch (err) {
      console.warn(`[${_ts()}] md-jobs: queue fetch failed`, err)
    }
  }
  /** Watch the queue only while there IS something to watch.  This panel has no general
   *  status poll (live updates ride the detail WebSocket), so without this the auto-start
   *  would land on the server and the UI would keep showing the old state until the user
   *  clicked something.  Stops itself the moment the machine is idle and nothing waits. */
  function _armQueuePoll() {
    const want = _queueBusy || _queue.length > 0 || _jobs.some(mdJobIsRunning)
    if (want && !_queueTimer) {
      _queueTimer = setInterval(() => _fetchQueue({ detectStart: true }), 5000)
    } else if (!want && _queueTimer) {
      clearInterval(_queueTimer)
      _queueTimer = null
    }
  }
  function _renderQueue() {
    if (!queueWrap || !queueList) return
    if (!_queue.length) { queueWrap.style.display = 'none'; queueList.replaceChildren(); return }
    queueWrap.style.display = ''
    queueList.replaceChildren(..._queue.map((entry) => {
      const job = _jobs.find((j) => j.job_id === entry.job_id) || null
      const row = document.createElement('div')
      row.style.cssText = 'display:flex;align-items:center;gap:5px;padding:2px 3px;font-size:10px;color:' + _C.muted
      const pos = document.createElement('span')
      pos.textContent = `${entry.position}.`
      pos.style.cssText = `color:${_C.dim};min-width:12px`
      const label = document.createElement('span')
      label.textContent = mdQueueRowLabel(job, entry, _fmtJobTime)
      label.style.cssText = 'flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;cursor:pointer'
      label.title = 'Show this run in the list'
      label.addEventListener('click', () => _selectJob(entry.job_id))
      const drop = document.createElement('button')
      drop.textContent = '✕'
      drop.title = 'Take this run out of the queue'
      drop.style.cssText = `background:none;border:none;color:${_C.dim};cursor:pointer;font-size:10px;padding:0 2px`
      drop.addEventListener('click', async () => {
        drop.disabled = true
        _applyQueue(await api.dequeueMdJob(entry.job_id))
      })
      row.append(pos, label, drop)
      return row
    }))
  }
  function _queueSelected(btn = runBtn) {
    return runExclusive(btn, async () => {
      if (!_selectedId) return
      const res = await api.enqueueMdJob(_selectedId)
      if (!res) { showToast(`Could not queue: ${api.lastErrorMessage() ?? 'Server error'}`, 'error'); return }
      _applyQueue(res)
      showToast('Queued — it starts when the machine is free', 'ok')
    }, { label: 'Queueing…' })
  }
  function _dequeueSelected(btn = runBtn) {
    return runExclusive(btn, async () => {
      if (!_selectedId) return
      const res = await api.dequeueMdJob(_selectedId)
      if (!res) { showToast(`Could not dequeue: ${api.lastErrorMessage() ?? 'Server error'}`, 'error'); return }
      _applyQueue(res)
      showToast('Taken out of the queue', 'warn')
    }, { label: 'Removing…' })
  }

  function _stopSelected(btn = runBtn) {
    return runExclusive(btn, async () => {
      if (!_selectedId) return
      try {
        const d = await api.stopMdJob(_selectedId)
        // Surface the deferred-scancel case (stopped locally while the cluster session is
        // down → SLURM cancel happens on reconnect) so the user knows it's not orphaned.
        showToast(d?.pending_scancel ? (d.message || 'Stopped — will cancel on reconnect')
                                     : 'Stop requested', 'warn')
      } catch (err) {
        console.warn(`[${_ts()}] md-jobs: stop failed`, err)
      }
    }, { label: 'Stopping…' })
  }
  /** Start a job that was CREATED but not run — the "＋ New job → Create job" outcome.
   *  The package is already solvated, so this is just the launch; the only gate that
   *  still applies is not stepping on another local run. */
  /** Push the anchors + E-field cards onto the SELECTED prepared job, returning a short
   *  human summary (or '' when there is nothing to say). Production children carry their
   *  own forces through the spawn payload, so this only applies to a relaxation. */
  async function _applyForcesToSelected() {
    const sel = _selectedJob()
    if (!sel || mdIsProductionChild(sel) || mdIsEnsembleReplica(sel)) return ''
    const anchors = _anchorsCard?.getAnchors?.() ?? []
    const spec = _efieldCard?.getFieldSpec?.()
    const on = !!_efieldCard?.isEnabled?.() && (spec?.field_pN ?? 0) > 0
    const field = on ? { field_pN: spec.field_pN, dir: spec.dir } : null
    if (!anchors.length && !field) return ''
    const d = await api.setMdJobForces(_selectedId, {
      anchors, anchor_atoms: mdAnchorAtomNames(anchorAtomsSel?.value), field,
    })
    if (!d) { showToast(api.lastErrorMessage() ?? 'Could not attach forces', 'error'); return '' }
    const n = d.anchors?.n_atoms_fixed ?? 0
    return [n ? `${n} anchored atom${n === 1 ? '' : 's'}` : '', field ? 'E-field' : '']
      .filter(Boolean).join(' + ')
  }

  function _startSelected(btn = runBtn) {
    const runpod = mdRunpodStartable(_selectedJob())
    return runExclusive(btn, async () => {
      if (!_selectedId) return
      const awaitingSequence = !!_selectedJob()?.awaiting_sequence
      // The concurrency confirm is about THIS machine's single GPU. A rented pod is a
      // different computer, so asking "another job is already running here, continue?"
      // before renting one is a question about nothing.
      if (!runpod && !(await confirmNoConcurrentJob({ excludeJobId: _selectedId }))) return
      try {
        // Forces are chosen AFTER the job exists now (Create no longer runs), so the
        // anchors/field cards describe THIS job and are applied to its prepared package
        // before it starts. Reported in the toast rather than applied silently — a force
        // the user cannot see landing is the bug this whole flow replaced.
        // A sequence-deferred job has no package yet.  Let /start perform the sequence
        // gate first; forces can only be attached after preparation has produced confs.
        const forced = awaitingSequence ? '' : await _applyForcesToSelected()
        const d = await api.startMdJob(_selectedId)
        if (!d) throw new Error(api.lastErrorMessage() ?? 'Server error')
        showToast(
          (awaitingSequence
            ? (d.message || 'Refreshing atom counts and preparing the run')
            : runpod ? 'Renting a GPU — the pod is destroyed when the run finishes' : 'Run started')
          + (forced ? ` — ${forced}` : ''), 'ok')
        await _fetchJobs()
        _reselectJob(_selectedId)
      } catch (err) {
        showToast(`Could not start: ${err.message}`, 'error')
      }
    }, { label: 'Starting…' })
  }

  function _resumeSelected(btn = runBtn) {
    return runExclusive(btn, async () => {
      if (!_selectedId) return
      // Resuming a GPU-decision job: reassess if the design changed (roll back / rebuild
      // via the shared stale-guard), and clear the dismiss so the gate re-appears. If
      // nothing changed, the resume re-hits the cached probe → the same gate pops.
      if (hasPendingGpuDecision(_selectedJob())) {
        const proceed = await ensureJobCurrent({
          job: _selectedJob(), rollFn: rollMdJobDesign, refetch: _fetchJobs,
          isStale: () => jobOutOfDate(_selectedJob()), actionLabel: 'this run',
        })
        if (!proceed) return
        _gateBDismissed = null
      }
      if (!(await confirmNoConcurrentJob({ excludeJobId: _selectedId }))) return
      try {
        const d = await api.startMdJob(_selectedId)
        if (!d) throw new Error(api.lastErrorMessage() ?? 'Server error')
        showToast('Resume requested', 'ok')
        await _fetchJobs()
        _reselectJob(_selectedId)
      } catch (err) {
        showToast(`Resume failed: ${err.message}`, 'error')
      }
    }, { label: 'Resuming…' })
  }
  // ONE control for the SELECTED job: start it, stop it, or resume it.  Creating a run is
  // a separate act now (＋ New job → the wizard), which is what let these three collapse
  // into a single button — they used to be a fresh-Relax button, a contextual Stop/Resume
  // button and a Production button, each aware of a different subset of job states.
  runBtn?.addEventListener('click', () => {
    const sel = _selectedJob()
    if (!sel) return
    const act = runBtn.dataset.runAction
    if (act === RUN_ACTION.STOP) return _stopSelected(runBtn)
    if (act === RUN_ACTION.RESUME) {
      if (sel.execution_target === 'alpine' && sel.resumable) {
        if (_remoteSubmitting) return
        return _submitReview.open(sel.job_id, { mode: 'resume' })
      }
      return _resumeSelected(runBtn)
    }
    if (act === RUN_ACTION.QUEUE) return _queueSelected(runBtn)
    if (act === RUN_ACTION.DEQUEUE) return _dequeueSelected(runBtn)
    // The cluster hand-off: same review card the ☁ button in the Cluster card used to
    // open, now reached from the one control that answers "how do I run this?".
    if (act === RUN_ACTION.SUBMIT) {
      if (_remoteSubmitting) return       // a package is already uploading
      return _submitReview.open(sel.job_id)
    }
    // A seeded draft solvates from its source job's coordinates. Send it through the
    // wizard too, prefilled with what the draft recorded — solvating from a seed is
    // still a whole protocol's worth of choices, and it used to reveal a drawer of
    // controls that no longer exists.
    if (mdJobIsDraft(sel)) {
      return _wizard.open('relaxation', { draftId: sel.job_id, prefill: _draftPrefill(sel) })
    }
    // Renting is a start, not a submit — POST /md/jobs/{id}/start dispatches to
    // _start_runpod_job, which pre-flights and provisions. This line is what makes the
    // button at the top actually launch a RunPod run; before it, the click fell through
    // and nothing happened at all.
    if (sel?.awaiting_sequence || mdJobIsStartable(sel) || mdRunpodStartable(sel)) {
      return _startSelected(runBtn)
    }
  })
  // "New job" opens the Job Wizard, which supplies a protocol payload to the same
  // _launchRelax gate sequence the Advanced form uses.
  //
  // With ANY completed run selected — a relaxation or a production — it opens on
  // Production, seeded from that run. Selecting a finished run and pressing New job is
  // the gesture for "carry on from this": off a relaxation that means an independent
  // sample, off a production it means extending that trajectory (the backend has always
  // chained, via `_production_seed_checkpoint`; only the UI had no way to ask). It used
  // to land on a blank relaxation form, so continuing a specific run meant switching mode
  // by hand and then finding it again in a picker that had silently defaulted to the
  // newest one instead.
  newBtn?.addEventListener('click', () => {
    const sel = _selectedJob()
    if (isProductionParent(sel)) {
      return void _wizard.open('production', { parentJobId: sel.job_id })
    }
    void _wizard.open('relaxation')
  })
  /**
   * Spawn a production child from the wizard — the only production launch path.
   *
   * Carries every gate the old Production button had, because they are all about the
   * ENVIRONMENT rather than the protocol and none of them belongs in the wizard: the
   * stale-design guard, the local-concurrency confirm, the disk forecast with its two
   * independent warnings, and the documented override when the inherited cell is too
   * small for the requested length. That last refusal is advisory — the run is
   * physically startable, it just risks the structure meeting its own periodic image —
   * so it asks rather than making the user hand-craft a request.
   */
  async function _spawnProductionFromWizard(parentId, body) {
    if (!parentId) return null
    const parent = _jobs.find(j => j.job_id === parentId)

    // If the design changed since the parent was prepared, offer to roll back to the
    // job's run-state (or cancel) before seeding a run off coordinates it no longer
    // matches.
    const proceed = await ensureJobCurrent({
      job: parent, rollFn: rollMdJobDesign, refetch: _fetchJobs,
      isStale: () => jobOutOfDate(_jobs.find(j => j.job_id === parentId)),
      actionLabel: 'a production run',
    })
    if (!proceed) return null

    // The wizard decides where THIS production runs, independent of both its parent and
    // whichever informational pane happens to be selected in the Clusters card.
    const runTarget = mdRequestedRunTarget(body)
    const isLocalRun = mdIsLocalTarget(runTarget)
    if (isLocalRun && !(await confirmNoConcurrentJob({ excludeJobId: parentId }))) return null

    const full = {
      ...body,
      autostart: isLocalRun && body.autostart,
      execution_target: runTarget,
      cluster_name: runTarget === 'alpine' ? 'alpine' : null,
      // RunPod hardware is part of the wizard request. The Clusters-card picker is an
      // information probe and must not alter the workflow being created.
      runpod_gpu_key: mdRunpodGpuKeyFor({
        runTarget, requested: body?.runpod_gpu_key }),
      // Anchors on the PRODUCTION request. This card used to be read only by the relax
      // launch, so picking anchors and clicking Production silently discarded them — and
      // even an anchored parent lost them, because the replica builder never passed them
      // through. Sending [] (an empty card) means "explicitly unanchored".
      anchors:      _anchorsCard?.getAnchors?.() ?? [],
      anchor_atoms: mdAnchorAtomNames(anchorAtomsSel?.value),
      anchor_k:     mdAnchorStiffness(anchorStiffnessSel?.value),
    }

    if (isLocalRun) {
      try {
        // Forecast with the SAME dt and DCD interval the run will use — trajectory bytes
        // scale as 1/dcd_freq, so forecasting the defaults while the panel sends
        // something else silently mis-states the size by that ratio.
        const fc = await estimateMdProductionDisk(parentId, {
          length_ns: full.length_ns,
          autostart: true,
          dcd_freq: full.dcd_freq,
          production_timestep_fs: full.production_timestep_fs,
        })
        // Two independent gates: "the disk will run short" (only fires on a full volume)
        // and "this run is simply big/long" (fires on a roomy archive drive too).
        if (!(await confirmDiskSpaceOk(fc))) return null
        if (!(await confirmBigRunOk(fc))) return null
      } catch { /* forecast is best-effort — never block a launch on it */ }
    }

    try {
      let d = await api.spawnMdProduction(parentId, full)
      if (!d) {
        const why = api.lastErrorMessage() ?? 'Server error'
        if (!isUndersizedCellRefusal(why)) throw new Error(why)
        if (!(await confirmUndersizedCell({ lengthNs: full.length_ns }))) return null
        d = await api.spawnMdProduction(parentId, { ...full, allow_undersized_cell: true })
        if (!d) throw new Error(api.lastErrorMessage() ?? 'Server error')
      }
      const childId = d.job?.job_id
      await _fetchJobs()
      if (childId) _selectJob(childId)
      if (isLocalRun) {
        showToast(full.autostart ? 'Production started' : 'Production job created', 'ok')
      } else {
        // Same rule as a relaxation: the wizard's first step already sized the request,
        // so the child waits for a deliberate Submit rather than opening a card over the
        // panel the moment it is staged.
        showToast('Alpine production staged — Submit to Alpine when ready', 'ok')
      }
      return d.job ?? { job_id: childId }
    } catch (err) {
      showToast(`Production failed: ${err.message}`, { severity: 'error', duration: 8000 })
      return null
    }
  }

  const _wizard = initJobWizard({
    api: {
      getRelaxPresets: () => api.getRelaxPresets(),
      fetchProtocolPlan: body => api.fetchProtocolPlan(body),
      // The client returns null on a non-OK response, so the wizard needs this to say
      // WHY a plan came back empty instead of showing a blank table.
      lastErrorMessage: () => api.lastErrorMessage?.(),
      // Step 1 ("Where it runs") probes: this machine's hardware, and — once a cluster
      // session exists — live Alpine availability.  Same endpoints the Optimize button
      // and the Clusters card already use; no new backend surface.
      fetchHardware: () => api.optimizeMdHardware(_wizardDevices()),
      fetchAvailability: opts => api.getClusterAvailability(opts),
      // Sizes the sbatch request for the plan step, so the whole SLURM story is
      // inspectable before the job exists.
      getSlurmPreview: body => api.getSlurmPreview(body),
      // The RunPod half of step 1: what this whole plan would cost on each currently-available
      // card, what it writes, and whether it fits the network volume.  One round trip carries
      // the cards, storage, balance, live pods AND the pre-flight.
      getRunpodJobPreview: body => api.getRunpodJobPreview(body),
      getRunpodVolumes: () => api.getRunpodVolumes(),
      setRunpodVolume: id => api.setRunpodVolume(id),
      // The folder picker browses the server's filesystem through the same client.
      fsApi: api,
    },
    launch: (payload, opts) => _launchRelax(payload, opts),
    spawnProduction: _spawnProductionFromWizard,
    updateJob: async (jobId, payload) => {
      const job = await api.updateMdJobSettings(jobId, payload)
      if (!job) {
        showToast(api.lastErrorMessage?.() || 'Could not save job settings', 'error')
        return null
      }
      await _fetchJobs()
      _reselectJob(jobId)
      showToast('Job settings saved', 'ok')
      return job
    },
    getJobs: () => _jobs,
    getPartPath: () => _currentPartPath(),
    onJobCreated: jobId => { _reselectJob(jobId) },
    onOptimizeMount: mount => _wireOptimize(mount),
  })

  /**
   * Launch a relaxation from a protocol payload, running every gate on the way.
   *
   * `protocolPayload` carries only the protocol settings — from the Advanced form or from
   * the Job Wizard. Everything environmental (run target, anchors, electric field, run
   * directory, GPU device string) is merged in HERE, so both callers inherit the same
   * concurrency confirms, VRAM pre-flight, disk forecast and big-run confirmation rather
   * than each growing its own copy.
   */
  async function _launchRelax(protocolPayload, { draftId = null } = {}) {
    if (_launching) {
      console.log(`[${_ts()}] md-jobs: Relax clicked but already launching`)
      return
    }
    // Alpine runs on the remote cluster — it can't contend for the local GPU/disk,
    // so the local-resource guards (concurrent NADOC job, external GPU hog, local
    // disk space) don't apply and would wrongly block a submit while a local job runs.
    const runTarget = mdRequestedRunTarget(protocolPayload)
    const isLocalRun = mdIsLocalTarget(runTarget)

    // The device string comes from whichever surface supplied the protocol settings, so
    // the multi-GPU and busy-GPU checks below judge the run that will actually happen —
    // not whatever the (possibly hidden) Advanced form happens to hold.
    const proto = protocolPayload ?? {}
    const deviceStr = String(proto.devices ?? '0').trim()

    const anchors = _anchorsCard?.getAnchors?.() ?? []
    const fieldSpec = _efieldCard?.getFieldSpec?.()
    const fieldOn = !!_efieldCard?.isEnabled?.() && (fieldSpec?.field_pN ?? 0) > 0
    // A uniform field with no anchor just streams the whole structure (COM drift) —
    // the E-field card shows a warning notice, but the run is allowed (not blocked).
    // NAMD 3: "EField is not compatible with multi-GPU GPUresident".
    if (fieldOn && deviceStr.includes(',')) {
      showToast('NAMD cannot combine an electric field with a multi-GPU run — use a single device.',
        { severity: 'warning' })
      return
    }

    if (isLocalRun && !(await confirmNoConcurrentJob())) return
    // Only warn about a busy GPU when this run actually targets the GPU.
    const runsOnGpu = deviceStr.toLowerCase() !== 'cpu' && deviceStr.toLowerCase() !== 'none'
    if (isLocalRun && runsOnGpu && !(await confirmGpuNotBusy(deviceStr || '0'))) return
    _launching = true
    _paintRunControl()

    const payload = {
      ...proto,
      design_source_path: _currentPartPath() || null,
      execution_target: runTarget,
      cluster_name:   runTarget === 'alpine' ? 'alpine' : null,
      // RunPod hardware belongs to this wizard request. The Clusters card only browses
      // availability/connectivity and cannot substitute a different GPU into the run.
      runpod_gpu_key: mdRunpodGpuKeyFor({
        runTarget, requested: proto.runpod_gpu_key }),
      anchors:        anchors.length ? anchors : null,
      // The ladder pins hard regardless of the stiffness select (its constraints channel
      // is spent on the slow-release restraint), but the ATOM filter applies to both.
      anchor_atoms:   anchors.length ? mdAnchorAtomNames(anchorAtomsSel?.value) : null,
      field:          fieldOn ? { field_pN: fieldSpec.field_pN, dir: fieldSpec.dir } : null,
      run_dir:        getRunDir(),   // shared run-location: write this run into the chosen folder
    }

    console.log(`[${_ts()}] md-jobs: Relax clicked`, payload)
    if (detailEl) detailEl.style.display = ''
    // Show the progress popup BEFORE the disk forecast, not after.  The forecast calls
    // estimate_profile_from_design, which builds the design's whole heavy-atom model —
    // ~26 s on a 6-helix bundle.  Awaiting that first left the button looking dead for
    // half a minute ("I click Relax and nothing happens"), because the only feedback
    // came afterwards.  Feedback first, work second.
    showOpProgress('Relax', 'Sizing the solvated system…', { indeterminate: true })

    // Gate A — pre-flight water-box SIZE check, BEFORE the build. Runs ahead of the disk
    // forecast so a chosen shell feeds that estimate. Only when sizing is auto (shell 0)
    // on a local GPU run; a seeded draft / CPU / manual shell skips it (the backend
    // returns skipped for those too). Best-effort — never blocks a launch on an error.
    //
    // ABSENT counts as auto. The wizard sends only the fields the user touched, so an
    // untouched water shell is not in the payload at all — a `=== 0` test skipped Gate A
    // for exactly the launches that most need it.
    if (isLocalRun && !draftId && runsOnGpu && (payload.water_shell_nm ?? 0) === 0) {
      try {
        const adv = await preflightMdVram(payload)
        const gate = gateAMessage(adv)
        // A protocol that forbids carving never gets a shell applied, whichever tier the
        // advice came back as — it gets one warning with Cancel / Run anyway, and if the
        // user proceeds the package is built at FULL box. Reading `adv.carve_allowed`
        // rather than the tier is what keeps that true: the tiers describe how well a
        // CARVE would fit, which is not a question this protocol is asking.
        const mayCarve = adv?.carve_allowed !== false
        if (gate?.isNotice && mayCarve) {           // A1 — auto-fit a comfortable shell
          payload.water_shell_nm = adv.recommended_shell_nm
          showToast(gate.notice, { severity: 'info' })
        } else if (gate) {                          // a decision, a hard stop, or a warning
          const proceed = await openGateAModal(adv)
          if (!proceed) { hideOpProgress(); _launching = false; runBtn.disabled = false; return }
          if (mayCarve && adv.tier === 'a2') payload.water_shell_nm = adv.recommended_shell_nm
        }
      } catch { /* preflight is best-effort — never block a launch */ }
    }

    // Local-disk forecast only applies to a local run; an Alpine run writes its
    // trajectory on the cluster's scratch, not this machine's disk.  A seeded draft's
    // size isn't known until it solvates, so skip the forecast (parity with the old
    // seed flow, which never forecast either).
    if (isLocalRun && !draftId) {
      try {
        const fc = await estimateMdDisk(payload)
        // If the run won't fit, offer to archive it to a roomier drive and run THERE.
        const rec = await recommendArchive(fc)
        if (!rec.proceed) { hideOpProgress(); _launching = false; runBtn.disabled = false; return }
        payload.run_dir = rec.runDir || null   // suggested archive OR the user's chosen dir
        // No archive suggestion but still tight → the plain low-disk Continue/Cancel warning.
        if (!archiveRecommendation(fc).show && !(await confirmDiskSpaceOk(fc))) {
          hideOpProgress(); _launching = false; runBtn.disabled = false; return
        }
        // Independent of whether the disk is tight: a run this big or this long gets
        // an explicit Proceed/Cancel showing what it will actually cost.
        if (!(await confirmBigRunOk(fc))) {
          hideOpProgress(); _launching = false; runBtn.disabled = false; return
        }
      } catch { /* forecast is best-effort — never block a launch on it */ }
    }

    setOpProgressLabel('Creating job…')

    try {
      console.log(`[${_ts()}] md-jobs: POST /api/md/jobs`)
      // createMdJob stamps the X-NADOC-Doc header so the backend reads the ACTIVE
      // design from THIS tab's document (without it the default/empty doc is used
      // and prep 404s with "No active design"). Returns null on any HTTP error.
      // A draft prepares in place (seed comes from the draft record, not the payload).
      const job = draftId
        ? await api.prepareMdDraft(draftId, payload)
        : await api.createMdJob(payload)
      console.log(`[${_ts()}] md-jobs: response body`, job)

      if (!job) {
        // HTTP error (404 = no active design, 400 = engine missing, etc.)
        hideOpProgress()
        const msg = api.lastErrorMessage() ?? 'Server error'
        console.warn(`[${_ts()}] md-jobs: HTTP error: ${msg}`)
        showToast(msg, 'error')
        return
      }

      hideOpProgress()

      if (job.status === 'failed') {
        // Preparation itself failed (GROMACS crashed, etc.) — came back as 200
        const msg = job.error ?? 'Preparation failed'
        console.warn(`[${_ts()}] md-jobs: job created but failed during prep: ${msg}`)
        showToast(`Prep failed: ${msg}`, 'error')
        await _fetchJobs()
        _selectJob(job.job_id)
        // Deliberately not returned as a success: the Job Wizard stays open on a failed
        // prep so the settings that produced it are still on screen to fix.
        return
      }

      console.log(`[${_ts()}] md-jobs: job created OK job_id=${job.job_id} status=${job.status}`)
      if (job.awaiting_sequence) {
        showToast('Job created — assign scaffold and staple sequences before Run', 'warn')
        await _fetchJobs()
        _reselectJob(job.job_id)
        return job
      }
      // Alpine target: prep runs locally and then STOPS. Nothing is submitted until the
      // user says so — the wizard already sized the request, and this is the window in
      // which anchors and an electric field get attached to the prepared job. A popup
      // here used to close that window the moment prep finished.
      if (payload.execution_target === 'alpine') {
        _pendingAlpineReview = job.job_id
        showToast('Preparing for Alpine — add anchors or a field while it builds, then Submit', 'ok')
      } else {
        showToast(`Preparing: ${job.job_id}`, 'ok')
      }
      await _fetchJobs()
      // A draft keeps its id through prepare — _reselectJob forces the WS to
      // re-subscribe for the now-preparing job (plain _selectJob would early-return).
      _reselectJob(job.job_id)
      return job          // the wizard closes on a truthy result
    } catch (err) {
      hideOpProgress()
      console.error(`[${_ts()}] md-jobs: Run fetch threw`, err)
      showToast(`Error: ${err.message}`, 'error')
    } finally {
      _launching = false
      _paintRunControl()   // reflect the new/selected job's state on the primary control
    }
  }

  // Once a queued-for-Alpine job finishes preparing, SAY SO — and stop there.
  //
  // This used to open the submit-review card automatically, which made the resources it
  // asked about unanswerable in the right place (the node was chosen a wizard ago) and
  // pre-empted the panel, so anchors and an electric field — which attach to a prepared
  // job — could not be set before something demanded a submit decision. The resources now
  // come from the wizard's first step; submitting is the user's own click.
  // Clears the pending flag on prep failure too so it can't fire on a later run.
  function _maybeAnnounceAlpineReady(job) {
    if (!job || job.job_id !== _pendingAlpineReview) return
    if (job.status === 'queued') {
      _pendingAlpineReview = null
      showToast('Package ready for Alpine — attach anchors or a field, then Submit to Alpine',
        { severity: 'info', duration: 8000 })
    } else if (['failed', 'stopped'].includes(job.status)) {
      _pendingAlpineReview = null
    }
  }

  let _resumeHistOpen = false
  resumeHistToggle?.addEventListener('click', () => {
    _resumeHistOpen = !_resumeHistOpen
    if (resumeHistEl) resumeHistEl.style.display = _resumeHistOpen ? '' : 'none'
    if (resumeHistArrow) resumeHistArrow.textContent = _resumeHistOpen ? '▾' : '▸'
  })

  // Resume opens the same review card used to submit (in resume mode) so the user
  // can review/edit resources — e.g. bump the walltime after a promising short run —
  // before officially resuming from the checkpoint.
  resumeBtn?.addEventListener('click', () => {
    if (_remoteSubmitting) return
    if (_selectedId) _submitReview.open(_selectedId, { mode: 'resume' })
  })

  // Is the selected job one the early-stop toggle can control LIVE (a running LOCAL
  // relaxation — not Alpine, not a production child)?  This is now the toggle's ONLY
  // job: its launch-default counterpart moved into the Job Wizard, so the card is simply
  // hidden when nothing live is selected rather than quietly meaning something else.
  function _isLiveRelax(job) {
    return !!job && job.status === 'running' && mdIsLocalTarget(job.execution_target) && !mdIsProductionChild(job)
  }

  // The live early-stop toggle: changing it POSTs an override that the runner applies at
  // the next stage checkpoint, without relaunching.
  earlyStopChk?.addEventListener('change', async () => {
    const job = _selectedJob()
    if (!_isLiveRelax(job) || _earlyStopBusy) return   // not live → just the launch default
    const enabled = earlyStopChk.checked
    // Optimistically lock the toggle in the requested position so it can't be
    // spam-flipped while the POST is in flight; the server-side override then keeps
    // it "pending" (via mdEarlyStopToggleState) until the runner applies it.
    _earlyStopBusy = true
    earlyStopChk.disabled = true
    if (earlyStopPending) earlyStopPending.style.display = ''
    try {
      const d = await api.setMdEarlyStop(_selectedId, enabled)
      console.log(`[${_ts()}] md-jobs: early-stop toggle`, d)
      // Reflect the queued override on the cached job now so any render before the
      // next WS state push (which will carry it from the server) already reads it as
      // pending — otherwise a stale-`_jobs` render could flicker the toggle back.
      const cached = _jobs.find(j => j.job_id === _selectedId)
      if (cached) cached.early_stop_pending = enabled
      showToast(enabled ? 'Early-stop enabled (applies at next checkpoint)'
                        : 'Early-stop disabled', 'info')
    } catch (err) {
      earlyStopChk.checked = !enabled   // revert on failure
      if (earlyStopPending) earlyStopPending.style.display = 'none'
      earlyStopChk.disabled = false
      console.warn(`[${_ts()}] md-jobs: early-stop toggle failed`, err)
      showToast('Early-stop toggle failed', 'warn')
    } finally {
      _earlyStopBusy = false
    }
  })

  // ── Job list rendering ─────────────────────────────────────────────────────
  // Canonical job-list ctx (U3): NAMD converges its list rows onto the shared oxDNA
  // renderer via the pure mdJobRowCtx factory (module scope, unit-tested).
  const _rowCtx = () => mdJobRowCtx({
    selectedId: _selectedId, collapsedIds: _collapsedParents, jobs: _jobs,
    dimColor: _C.dim, warnColor: _C.warn, formatTime: _fmtJobTime,
  })

  function _renderList() {
    if (!listEl) return
    const jobs = _visibleJobs().slice().sort((a, b) => b.created_at - a.created_at)
    const ctx = _rowCtx()
    // Skip the rebuild when nothing visible changed, so the row spinners' CSS
    // animation doesn't restart on every poll (visible stutter).
    const sig = jobListSignature(jobs, ctx)
    if (sig === _listSig && listEl.childElementCount) return
    _listSig = sig
    // Default-collapse an Alpine ENSEMBLE parent the first time we see it, so a fan-out
    // of N replicas reads as ONE expandable item.  Local production fan-outs are NOT
    // auto-collapsed: they're spawned one at a time and the user is watching the child
    // they just started (auto-collapsing would hide it under the parent chevron).  This
    // mutates _collapsedParents before buildJobListModel reads ctx.collapsedIds.
    for (const j of jobs) {
      const hasAlpineReplica = jobs.some(c =>
        c?.parent_job_id === j.job_id && mdIsEnsembleReplica(c) && !mdIsProductionChild(c))
      if (hasAlpineReplica && !_autoCollapsed.has(j.job_id)) {
        _autoCollapsed.add(j.job_id)
        _collapsedParents.add(j.job_id)
      }
    }
    renderJobList(listEl, buildJobListModel(jobs, ctx), {
      onClick: (jobId) => (jobId === _selectedId ? _deselectJob() : _selectJob(jobId)),
      onChevron: (jobId) => _toggleCollapse(jobId),
      onAction: (jobId) => _openVramFix(jobId),   // the "Fix" VRAM-OOM row action
      onContextMenu: (jobId, e) => _openJobRowMenu(jobId, e),
      emptyText: _jobs.length && !_showAllJobs() ? 'No jobs for this part.' : 'No jobs yet.',
      dimColor: _C.dim,
      legendState: _legend,
    })
  }

  /**
   * Right-click on a job row.
   *
   * The wizard asks about two dozen things — protocol, ion chemistry, box padding, the
   * integrator's three axes, the whole 22-stage ladder — and once the job existed there
   * was nowhere to read any of it back. This reopens the wizard itself: editable before
   * execution ownership, locked afterward, always in the layout where it was chosen.
   */
  function _openJobRowMenu(jobId, e) {
    const job = _jobs.find(j => j.job_id === jobId)
    if (!job) return
    e.preventDefault()
    const view = jobSettingsState(job)
    const editable = mdJobEditable(job)
    createContextMenu({
      x: e.clientX, y: e.clientY,
      items: [
        { type: 'header', label: `${job.design_name || 'job'} · ${_fmtJobTime(job.created_at)}` },
        {
          // Jobs created before their request was recorded have nothing to show, and the
          // label says why rather than the item silently doing nothing.
          label: view.available
            ? (editable ? 'Edit…' : 'View settings…')
            : 'Settings were not recorded for this run',
          disabled: !view.available,
          onClick: () => {
            void (editable ? _wizard.openEditable(job) : _wizard.openReadOnly(job))
          },
        },
      ],
    })
  }

  /** Toggle a parent's collapsed state and force a list rebuild (bypassing the
   *  signature short-circuit, since collapse state isn't part of the signature). */
  function _toggleCollapse(jobId) {
    if (_collapsedParents.has(jobId)) _collapsedParents.delete(jobId)
    else _collapsedParents.add(jobId)
    _listSig = null
    _renderList()
  }


  // ── "Fix" flow (downsize / gentle-retry / resume) ─────────────────────────
  async function _openVramFix(jobId) {
    let advice
    try {
      advice = await api.getMdJobFixAdvice(jobId)
      if (!advice) throw new Error(api.lastErrorMessage() ?? 'Server error')
    } catch (err) {
      console.warn(`[${_ts()}] md-jobs: fix-advice failed`, err)
      advice = { failure_kind: 'other', remedy: 'none' }
    }
    openVramFixModal({
      advice,
      onApply: async (action) => {
        if (action.type === 'retry') {
          const d = await api.startMdJob(jobId)
          if (!d) throw new Error(api.lastErrorMessage() ?? 'Server error')
          await _fetchJobs()
          _reselectJob(jobId)   // same id → force WS re-subscribe (see _reselectJob)
          return
        }
        // refit → a fresh job with adjusted settings
        const d = await api.refitMdJob(jobId, action.body)
        if (!d) throw new Error(api.lastErrorMessage() ?? 'Server error')
        await _fetchJobs()
        if (d?.job_id) _selectJob(d.job_id)
      },
    })
  }

  // ── Gate B: GPU-resident fallback decision modal ──────────────────────────
  // A paused job with job.decision (gate:'gpu_resident') auto-opens the modal from
  // _applyJobState (which fires on every WS push / poll for the selected job). Track
  // the open modal + a dismissed jobId so an Escape doesn't get re-opened on the next
  // 3 s tick; reselecting the job (or the decision clearing) resets that.
  let _gateBModal = null       // { close, jobId } while a modal is open
  let _gateBDismissed = null   // jobId the user dismissed without choosing

  function _maybeOpenGpuDecision(job) {
    if (!hasPendingGpuDecision(job)) {
      if (_gateBModal?.jobId === job.job_id) { _gateBModal.close(); _gateBModal = null }
      if (_gateBDismissed === job.job_id) _gateBDismissed = null   // resolved/left paused
      return
    }
    if (_gateBModal?.jobId === job.job_id) return       // already showing for this job
    if (_gateBDismissed === job.job_id) return          // user dismissed; wait for reselect
    _gateBModal?.close()
    const close = openGpuDecisionModal({
      decision: job.decision,
      onChoose: async (choice) => {
        const d = await api.resolveMdGpuDecision(job.job_id, choice)
        if (!d) throw new Error(api.lastErrorMessage() ?? 'Server error')
        _gateBModal = null
        await _fetchJobs()
        _reselectJob(job.job_id)   // same id → re-subscribe WS on the now-running job
      },
      onDismiss: () => { _gateBDismissed = job.job_id; _gateBModal = null },
    })
    _gateBModal = { close, jobId: job.job_id }
  }

  // Dev-only: force the modal to appear on the selected job for visual validation
  // (the real path is dormant when a resident-capable NAMD build is pinned). In the
  // console: __NADOC_DBG__.mdForceGpuDecision(). Buttons will 400 on a job that isn't
  // actually paused server-side — that's expected; it validates layout + wiring.
  function _forceGpuDecisionDemo() {
    const job = _jobs.find(j => j.job_id === _selectedId)
    if (!job) { console.warn('md-jobs: select a job first'); return }
    _gateBDismissed = null
    job.status = 'paused'
    job.decision = {
      gate: 'gpu_resident', severity: 'decision',
      title: "Couldn't use the fastest GPU mode",
      message: 'The fastest GPU mode didn’t start on this structure. It can still finish '
        + 'in a slower GPU mode — same result, about 3× longer.',
      technical_reason: 'FATAL ERROR: CUDA error … buildTileLists … illegal memory access',
      retry_hint: true, degrade_target: 'offload',
      checks: [
        { label: 'GPU found', ok: true },
        { label: 'System fits in memory', ok: true },
        { label: 'Structure minimized cleanly', ok: true },
        { label: 'Fastest GPU mode started', ok: false },
      ],
      options: [
        { id: 'offload', label: 'Run in slower GPU mode', primary: true },
        { id: 'cancel', label: 'Cancel', primary: false },
      ],
    }
    _renderList()        // list ⚠ marker (rowSig now includes decision)
    _applyJobState(job)  // detail modal + Resume control
  }
  // Dev-only: preview a Gate A size decision. __NADOC_DBG__.mdForceGateA('a1'|'a2'|'a3').
  function _forceGateADemo(tier = 'a2') {
    const adv = {
      a1: { skipped: false, tier: 'a1', vram_mb: 12288, recommended_shell_nm: 1.5 },
      a2: { skipped: false, tier: 'a2', vram_mb: 12288, recommended_shell_nm: 1.1, estimated_atoms: 1_800_000 },
      a3: { skipped: false, tier: 'a3', vram_mb: 12288, tightest_shell_nm: 0.8, tightest_atoms: 9_000_000, required_vram_mb: 34_000 },
    }[tier] || null
    const g = gateAMessage(adv)
    if (!g) { console.warn('md-jobs: tier must be a1 | a2 | a3'); return }
    if (g.isNotice) { showToast(g.notice, { severity: 'info' }); return }
    openGateAModal(adv).then((v) => console.log('Gate A resolved (proceed=%s)', v))
  }
  if (typeof window !== 'undefined') {
    window.__NADOC_DBG__ = window.__NADOC_DBG__ || {}
    window.__NADOC_DBG__.mdForceGpuDecision = _forceGpuDecisionDemo
    window.__NADOC_DBG__.mdForceGateA = _forceGateADemo
  }

  // ── Job selection + WS subscription ───────────────────────────────────────
  function _selectJob(jobId) {
    _userDeselected = false   // an explicit pick supersedes a previous deselection
    if (_selectedId === jobId) return
    _gateBDismissed = null   // a fresh selection may re-show a pending decision
    console.log(`[${_ts()}] md-jobs: selecting job ${jobId}`)
    const selectedJob = _jobs.find(j => j.job_id === jobId) || null
    const visualizationAction = mdVisualizationJobSwitchAction({
      display: displayToggle?.checked,
      flex: flexToggle?.checked,
      occupancy: occupancyToggle?.checked,
      trajectory: trajToggle?.checked,
    })
    _selectedId = jobId
    if (visualizationAction === 'display') {
      _displayMeta = null
      _resetDisplayIndicator()
    }
    _closeWs()
    _renderList()
    _openDetailForJob(jobId)
    // Repaint Run/Queue off CURRENT server state: this panel has no status poll, so
    // without this the control could offer ▶ Run for a job the queue would refuse (or
    // hide that the job is already waiting in line).
    void _fetchQueue()
    if (selectionUpdatesVisualization(selectedJob)) void _applyRunConfig(jobId)
    // ▶ Rent & Run is gated on the RunPod pre-flight, and until now that only ran when the
    // run-target RADIO was moved. Selecting a prepared RunPod job is the other moment the
    // answer matters — without this the gate would still be showing whatever it last saw
    // (often nothing at all, for a job created in an earlier session).
    if (_selectedJob()?.execution_target === 'runpod') void _runpod.refresh()
    _paintRunpodGate()   // reveal the RunPod status box for a RunPod job
    void _applyVisualizationJobSwitch(visualizationAction, selectedJob)
  }

  async function _applyVisualizationJobSwitch(action, job) {
    return applyMdVisualizationJobSwitch(action, {
      off: _setTrajOff,
      trajectory: () => _mdHasTrajectory(job) && trajToggle?.checked
        ? _refreshTraj()
        : _setTrajOff(),
      display: async () => {
        solvent?.setJob(_selectedId)
        weld?.setJob(_selectedId)
        await _refreshMdDisplay()
      },
      flex: () => _mdHasTrajectory(job) && flexToggle?.checked ? _refreshFlex() : undefined,
      occupancy: () => mdHasProductionRun(job) && occupancyToggle?.checked
        ? _occupancy?.refresh()
        : undefined,
      none: () => selectionUpdatesVisualization(job) ? _refreshMdPrewarm(true) : undefined,
    })
  }

  /** Repopulate the Anchors + E-field cards with what the selected job carries.
   *  Historical selections retarget every job-scoped card just like live selections. Mirrors
   *  the oxDNA/SNUPI panels' `_applyRunConfig` -> `applyConfig`. NAMD keeps its forces in
   *  the package manifest rather than on the job row, so this reads them over the wire.
   *
   *  Called from `_selectJob` only — an explicit pick, never a status poll — so it cannot
   *  clobber the user mid-edit. */
  async function _applyRunConfig(jobId) {
    if (!jobId) return
    const d = await api.getMdJobForces(jobId)
    if (!d || jobId !== _selectedId) return      // selection moved on while in flight
    // `atom_names` is the job-level filter — the only place a job prepared before
    // per-anchor holds recorded the choice, so it seeds rows that carry no `atoms`.
    _anchorsCard?.applyConfig?.(d.anchors?.requested ?? [],
                               { defaultAtoms: d.anchors?.atom_names ?? null })
    _efieldCard?.applyConfig?.(d.field ?? null)
    _paintForcesProvenance(d)
  }

  /** Paint the provenance line for the selected job's forces. */
  function _paintForcesProvenance(d) {
    if (!forcesProvenanceEl) return
    const { text, tone } = mdForcesProvenance(d)
    forcesProvenanceEl.textContent = text
    forcesProvenanceEl.style.color = tone === 'ok' ? _C.ok : tone === 'warn' ? '#e3b341' : _C.dim
  }

  /** Clicking the ALREADY-selected row deselects it.  Deliberately NON-destructive: unlike
   *  `_selectJob` (which switches jobs) this does NOT call `_setFlexOff` / `_setTrajOff` /
   *  `_stopMdDisplay` / `_updateVizToggles(null)`, so a loaded trajectory, the RMSF map and
   *  the live-display stream all stay on screen with their cached frames intact.  Only
   *  picking a DIFFERENT job unloads them.  The status WebSocket does close — it streams
   *  detail for a job that's no longer being shown — and reopens on re-selection. */
  function _deselectJob() {
    _userDeselected = true
    _selectedId = null
    _displayMeta = null
    _gateBDismissed = null
    _closeWs()
    if (detailEl) detailEl.style.display = 'none'
    if (liveControlsCard) liveControlsCard.style.display = 'none'
    _renderList()
    _paintRunControl()   // nothing selected → the control disables with a hint
  }

  /** A DRAFT's stored prep params, in the wizard's own vocabulary.
   *
   *  A draft is created by "Use as NAMD seed" with the settings that were current then;
   *  opening the wizard for it should start from those rather than from the protocol's
   *  defaults. Returned as a touched-field map so every restored value reads "you set
   *  this" — which is true, and means switching protocol will not silently discard it. */
  function _draftPrefill(job) {
    const p = job?.prep_params || {}
    const out = {}
    for (const key of ['threads', 'devices', 'salt_mode', 'mg_conc_mM', 'ion_conc_mM',
                       'padding_nm', 'water_shell_nm', 'minimize_steps', 'fast',
                       'gpu_resident', 'early_stop_relax',
                       'box_mode']) {
      if (p[key] != null) out[key] = p[key]
    }
    return { presetId: p.relax_preset || null, touched: out }
  }

  /** Re-open a job's detail after a (re)start.  `_selectJob` early-returns when the
   *  id is unchanged, so a resume/retry of the ALREADY-selected job would never
   *  re-subscribe the status WebSocket — the timeline + spinners would freeze while
   *  NAMD actually runs.  Force `_openDetailForJob` in that case (it reopens the WS
   *  for a now-live job); a different id takes the normal `_selectJob` path. */
  function _reselectJob(jobId) {
    if (_selectedId === jobId) _openDetailForJob(jobId)
    else _selectJob(jobId)
  }

  function _openDetailForJob(jobId) {
    const job = _jobs.find(j => j.job_id === jobId)
    if (job) _applyJobState(job)
    if (detailEl) detailEl.style.display = ''
    if (selectionUpdatesVisualization(job)) _fetchDisplayMeta(jobId)
    _fetchJobMetrics(jobId)

    // A job handed to SLURM (slurm_job_id set) runs on the cluster — it pushes NOTHING
    // over the local WebSocket; its detail is refreshed by the SLURM poll
    // (_maybePollRemote → _applyJobState).  Only open the WS for a job running/prepping
    // LOCALLY.  Otherwise do a single REST refresh.
    const onCluster = !!job?.slurm_job_id
    // A draft streams nothing (no prep running yet) — skip the WS; the REST refresh
    // below keeps its state current until "Relax from oxDNA" flips it to preparing.
    if (!onCluster && job?.status !== 'draft' && (!job || !_TERMINAL_STATUSES.has(job.status))) {
      _openWs(jobId)
      _startWsWatchdog()   // safety net: reconnect/unwedge the socket if it drops
    } else {
      _stopWsWatchdog()    // terminal/remote jobs have no local WS to watch
      api.getMdJob(jobId)
        .then(j => {
          if (!j) return
          console.log(`[${_ts()}] md-jobs: REST refresh (terminal/remote)`, j.status)
          _applyJobState(j)
        })
        .catch(err => console.warn(`[${_ts()}] md-jobs: REST refresh failed`, err))
    }
  }

  // ── WebSocket management ───────────────────────────────────────────────────
  function _openWs(jobId) {
    _closeWs()
    const url = `ws://${location.host}/ws/md-jobs/${jobId}`
    console.log(`[${_ts()}] md-jobs: opening WS ${url}`)
    const ws = new WebSocket(url)
    _ws = ws
    _lastWsMsgAt = Date.now()   // start the staleness window fresh so the watchdog waits for onopen

    ws.onopen = () => { _lastWsMsgAt = Date.now(); console.log(`[${_ts()}] md-jobs: WS open`) }

    ws.onmessage = (evt) => {
      _lastWsMsgAt = Date.now()
      let msg
      try { msg = JSON.parse(evt.data) } catch { return }

      if (msg.type === 'state' && msg.job) {
        console.log(`[${_ts()}] md-jobs: WS state status=${msg.job.status} seg=${msg.job.current_segment_idx}/${msg.job.segments?.length ?? 0}`,
                    msg.job.live_metrics ? `T=${msg.job.live_metrics.temperature_k?.toFixed(1)}K` : '')
        const idx = _jobs.findIndex(j => j.job_id === msg.job.job_id)
        if (idx >= 0) _jobs[idx] = msg.job; else _jobs.unshift(msg.job)
        _renderList()
        // Wake the (possibly idle) master job card + progress bar on a status transition
        // pushed over the WS — the master self-polls only while it holds an active node,
        // so a selected job completing (and spawning children) would otherwise not surface
        // there until a manual refresh.  Fires the event only when the set/status changed.
        _notifyIfJobsChanged()
        if (msg.job.job_id === _selectedId) _applyJobState(msg.job, msg.job.live_metrics)
        if (!displayToggle?.checked) _refreshMdPrewarm()
      } else if (msg.type === 'error') {
        console.warn(`[${_ts()}] md-jobs: WS error msg`, msg.message)
        _showDetailError(msg.message)
      }
    }

    ws.onerror = (evt) => console.error(`[${_ts()}] md-jobs: WS error`, evt)

    ws.onclose = (evt) => {
      console.log(`[${_ts()}] md-jobs: WS closed code=${evt.code}`)
      _ws = null
      if (_selectedId) {
        api.getMdJob(_selectedId)
          .then(job => {
            if (!job) return
            const idx = _jobs.findIndex(j => j.job_id === job.job_id)
            if (idx >= 0) _jobs[idx] = job; else _jobs.unshift(job)
            _renderList()
            _applyJobState(job)
          })
          .catch(err => console.warn(`[${_ts()}] md-jobs: post-WS REST refresh failed`, err))
      }
    }
  }

  function _closeWs() {
    if (_ws) {
      console.log(`[${_ts()}] md-jobs: closing WS`)
      try { _ws.close() } catch { /* ok */ }
      _ws = null
    }
  }

  // ── Detail-WS watchdog ────────────────────────────────────────────────────
  // The status WS has no built-in reconnect, and there is no REST poll fallback for
  // a LOCAL running job — a dropped/wedged socket used to freeze the detail card
  // permanently (spinner kept spinning, no data behind it).  This interval reconnects
  // a dropped socket, force-reopens a silent one, and surfaces a backend-down banner.
  function _startWsWatchdog() {
    if (_wsWatchdog) return
    _wsWatchdog = setInterval(_wsWatchdogTick, _WS_WATCHDOG_MS)
  }

  function _stopWsWatchdog() {
    if (_wsWatchdog) { clearInterval(_wsWatchdog); _wsWatchdog = null }
    _wsProbing = false
  }

  async function _wsWatchdogTick() {
    if (_wsProbing) return
    const job = _jobs.find(j => j.job_id === _selectedId)
    const action = mdWatchdogDecision({
      job,
      wsOpen: !!_ws && _ws.readyState === WebSocket.OPEN,
      msSinceMsg: Date.now() - _lastWsMsgAt,
    })
    if (action === 'idle') return
    if (action === 'disarm') { _stopWsWatchdog(); return }

    // 'reconnect' (socket gone) or 'refresh' (socket wedged): probe the backend, heal
    // from the fresh status, then re-open (or stand down if it went terminal/remote).
    _wsProbing = true
    try {
      const fresh = await api.getMdJob(_selectedId)
      if (!fresh) throw new Error(api.lastErrorMessage() ?? 'no job')
      _fetchFails = 0
      _setBackendStale(false)
      const idx = _jobs.findIndex(j => j.job_id === fresh.job_id)
      if (idx >= 0) _jobs[idx] = fresh; else _jobs.unshift(fresh)
      _renderList()
      if (fresh.job_id === _selectedId) _applyJobState(fresh)
      const next = mdWatchdogDecision({ job: fresh, wsOpen: false, msSinceMsg: Infinity })
      if (next === 'disarm') { _closeWs(); _stopWsWatchdog() }
      else _openWs(_selectedId)   // _openWs closes any wedged socket first
    } catch (err) {
      _fetchFails++
      console.warn(`[${_ts()}] md-jobs: watchdog probe failed (${_fetchFails})`, err)
      if (_fetchFails >= 2) _setBackendStale(true)
    } finally {
      _wsProbing = false
    }
  }

  // ── Job detail rendering ──────────────────────────────────────────────────
  function _applyJobState(job, liveMetrics) {
    if (!job) return

    const awaitingSubmit = mdRemoteAwaitingSubmit(job)
    // Alpine-specific status only; the generic run status lives in the master job card.
    if (clusterStatusEl) {
      // An in-flight upload outranks the record's own state: the job is still
      // "prepared, awaiting submit" on disk for the whole transfer, so reading the
      // record alone would show "Prepared — submit below" while a submit is running.
      if (_remoteSubmitting && _remoteSubmitting.jobId === job.job_id) {
        _paintRemoteSubmitting()
      } else if (awaitingSubmit) {
        clusterStatusEl.textContent = job.error
          ? 'Submit to Alpine failed — retry below'
          : 'Prepared — submit to Alpine below'
        clusterStatusEl.style.color = job.error ? _C.err : _C.accent
        clusterStatusEl.style.display = ''
      } else if (mdIsRemoteQueued(job)) {
        // Waiting in the SLURM queue — show how long, not a generic "Queued".
        clusterStatusEl.textContent = `⧗ ${mdQueueWaitLabel(job)}${job.slurm_job_id ? ` (SLURM ${job.slurm_job_id})` : ''}`
        clusterStatusEl.style.color = _C.warn
        clusterStatusEl.style.display = ''
      } else {
        clusterStatusEl.style.display = 'none'
        clusterStatusEl.textContent = ''
      }
    }

    // The primary run control covers start/stop/resume for a local job and the Alpine
    // hand-off (⟳ Preparing… → ☁ Submit to Alpine).
    _paintRunControl()
    // The live early-stop card is shown ONLY for a running local relaxation, because
    // that is the only state in which it does anything. mdEarlyStopToggleState honours
    // the in-flight override so a 3 s state push can't snap the box back off.
    const live = _isLiveRelax(job)
    if (liveControlsCard) liveControlsCard.style.display = live ? '' : 'none'
    if (earlyStopChk && live) {
      const { checked, pending } = mdEarlyStopToggleState(job, _earlyStopBusy)
      earlyStopChk.checked = checked
      earlyStopChk.disabled = pending
      if (earlyStopPending) earlyStopPending.style.display = pending ? '' : 'none'
    }
    // Submitting a prepared job is the PRIMARY control's job now (☁ Submit to Alpine),
    // so there is no separate button here to show or hide.
    // Resume: a timed-out remote job, one-click continue from its last checkpoint.
    if (resumeBtn) resumeBtn.style.display = 'none'
    _renderResumeHistory(job)
    _maybeAnnounceAlpineReady(job)
    // Archive/Delete live in the section-level #simulate-job-actions (visibility/label
    // handled there on the selected node).

    // Show the error box for terminal failures AND for a failed Alpine submit
    // (queued-but-errored) so the rejection reason is visible with the retry button.
    _showDetailError(job)
    _renderTimeline(job)
    _renderMetrics(job, liveMetrics)
    _renderProductionControls(job)
    _updateVizToggles(job)
    _maybeOpenGpuDecision(job)   // Gate B: auto-open/close the GPU fallback modal
  }

  function _renderResumeHistory(job) {
    if (!resumeHistWrap) return
    const rows = mdResumeHistoryRows(job)
    if (!rows.length) { resumeHistWrap.style.display = 'none'; return }
    resumeHistWrap.style.display = ''
    if (resumeHistCount) resumeHistCount.textContent = String(rows.length)
    if (resumeHistEl) resumeHistEl.textContent = rows.join('\n')
  }

  function _showDetailError(job) {
    if (!errorEl) return
    const msg = mdFailureDetailsText(job)
    if (msg) {
      const wasHidden = errorEl.style.display === 'none'
      if (errorBodyEl) errorBodyEl.textContent = msg
      errorEl.style.display = ''
      // Open on the transition into a real failure. A user may collapse it afterward;
      // routine status polls must not fight that choice by reopening it every time.
      if (wasHidden) errorEl.open = true
    } else {
      errorEl.style.display = 'none'
      errorEl.open = false
      if (errorBodyEl) errorBodyEl.textContent = ''
    }
  }

  function _productionAdvisory(health) {
    if (!health || !/production/i.test(health.stage ?? '')) return null
    const wc = health.wc_ref_relative_fraction
    if (wc == null) return null
    const advisory = _wcThresholdForStage(health.stage)
    const hard = _wcHardThresholdForStage(health.stage)
    if (wc < advisory && wc >= hard) return { wc, advisory, hard }
    return null
  }

  // ── Stage timeline ─────────────────────────────────────────────────────────
  function _renderTimeline(job) {
    if (!timelineEl) return
    timelineEl.innerHTML = ''

    const segments = job.segments ?? []
    const minRow = mdMinimizationRow(job)
    if (!segments.length && !minRow) {
      timelineEl.textContent = 'No stages'
      return
    }

    // A stopped/failed/completed job is NOT live: a segment left marked "running"
    // mid-cancel must render as interrupted, never as a spinning stage.
    const jobLive = mdJobIsActive(job)

    const stages = []
    let cur = null
    const healthBySegment = new Map((job.health_samples ?? []).map(h => [h.segment, h]))
    // Minimisation leads the timeline as its own single-dot stage.  It is fed through
    // the SAME row renderer as a segment, so it gets the spinner while running and the
    // ✓ when done without a second code path — which is the whole point of the row.
    if (minRow) {
      stages.push({
        stage: minRow.stage,
        segs: [{ name: minRow.name, stage: minRow.stage, percent: 100,
                 steps: minRow.steps, status: minRow.status, skipped: false }],
      })
    }
    for (const seg of segments) {
      const displayStage = _timelineStage(seg)
      if (!cur || cur.stage !== displayStage) {
        cur = { stage: displayStage, segs: [] }
        stages.push(cur)
      }
      cur.segs.push(seg)
    }

    stages.forEach(({ stage, segs }) => {
      const row = document.createElement('div')
      row.style.cssText = 'display:flex;align-items:center;gap:5px;padding:2px 0;white-space:nowrap'

      const lbl = document.createElement('span')
      lbl.style.cssText = `color:${_C.muted};display:inline-block;width:140px;overflow:hidden;text-overflow:ellipsis;flex-shrink:0`
      lbl.textContent = stage
      lbl.title = stage
      row.appendChild(lbl)

      segs.forEach(seg => {
        const dot = document.createElement('span')
        const health = healthBySegment.get(seg.name)
        const { symbol, color } = _segSymbol(seg.status, health, jobLive, seg.skipped)
        dot.style.cssText = `color:${color};font-size:11px;cursor:default;flex-shrink:0`
        dot.textContent = symbol
        const warnNote = _productionAdvisory(health)
          ? 'WC below advisory'
          : (_isAdvisoryWarning(health) ? (health.reason || 'below health threshold') : null)
        dot.title = seg.skipped
          ? `${seg.name} · skipped — the accelerator detected this stage had already `
            + `satisfied its plateau (energy + base-pairing) requirements, so this `
            + `redundant chunk was not run`
          : (warnNote
            ? `${seg.name} · ${seg.percent}% · ${seg.status} · ${warnNote}`
            : `${seg.name} · ${seg.percent}% · ${seg.status}`)
        row.appendChild(dot)
      })

      const allDone   = segs.every(s => s.status === 'done')
      const anyFailed = segs.some(s => s.status === 'failed')
      const anyRun    = jobLive && segs.some(s => s.status === 'running')
      const anyWarn   = segs.some(s => s.status === 'done'
        && (_isAdvisoryWarning(healthBySegment.get(s.name)) || _productionAdvisory(healthBySegment.get(s.name))))
      if (anyRun) {
        // Spinning circle next to the stage currently running.
        const spin = makeSpinner(_C.warn, 10)
        spin.style.marginLeft = '4px'
        row.appendChild(spin)
      } else {
        const stageStat = document.createElement('span')
        const color = anyFailed ? _C.err : anyWarn ? _C.warn : allDone ? _C.ok : _C.dim
        stageStat.style.cssText = `color:${color};margin-left:4px`
        stageStat.textContent = anyFailed ? '✗' : anyWarn ? '⚠' : allDone ? '✓' : ''
        row.appendChild(stageStat)
      }

      timelineEl.appendChild(row)
    })
  }

  // A checkpoint that dipped below a health threshold (C1' or WC).  Health is
  // advisory — the run is never stopped for it — so any not-passed sample is
  // surfaced as a ⚠ warning on the stage.
  function _isAdvisoryWarning(health) {
    return !!health && health.passed === false
  }

  function _segSymbol(status, health = null, jobLive = true, skipped = false) {
    const advisory = _productionAdvisory(health) || _isAdvisoryWarning(health)
    switch (mdSegGlyphKind(status, { skipped, advisory, jobLive })) {
      // Green right-arrow (not the solid circle): the early-stop accelerator skipped
      // this redundant chunk, so "done but skipped" reads distinctly from "done + ran".
      case 'skipped':  return { symbol: '→', color: _C.ok }
      case 'advisory': return { symbol: '⚠', color: _C.warn }
      case 'done':     return { symbol: '●', color: _C.ok }
      case 'failed':   return { symbol: '✗', color: _C.err }
      case 'running':  return { symbol: '○', color: _C.warn }
      default:         return { symbol: '·', color: _C.dim }
    }
  }

  /** Header spinner on the Health card: spins while the job is computing its first
   *  metrics, so the (empty) card doesn't just look idle. */
  function _setHealthSpinner(active) {
    if (!healthSpinner) return
    const on = healthSpinner.dataset.on === '1'
    if (active && !on) {
      healthSpinner.innerHTML = ''
      healthSpinner.appendChild(makeSpinner(_C.warn, 10))
      healthSpinner.dataset.on = '1'
    } else if (!active && on) {
      healthSpinner.innerHTML = ''
      healthSpinner.dataset.on = '0'
    }
  }

  // ── Metric cards ──────────────────────────────────────────────────────────
  function _renderMetrics(job, live) {
    if (!metricsEl) return

    // Remote (Alpine) run with no local health/metrics: they live on the cluster's
    // scratch until the run finishes and results are fetched.  Show a clear note
    // instead of a metric grid / perpetual "Waiting for first metrics…" spinner.
    if (!mdHasLocalReadouts(job)) {
      _setHealthSpinner(false)
      metricsEl.innerHTML = ''
      const note = mdRemoteReadoutNote(job)
      if (note) {
        const n = document.createElement('div')
        n.style.cssText = `grid-column:1 / -1;font-size:var(--text-xs);color:${_C.muted};padding:4px 2px;line-height:1.4`
        n.textContent = note
        metricsEl.appendChild(n)
      }
      return
    }

    const health = job.health_samples?.[job.health_samples.length - 1]
    const persisted = _latestRecord(_metricsByJob.get(job.job_id) ?? [])
    const liveMx = live ?? (job.live_metrics ?? null)
    const hasMetrics = mdHasMetrics({ ...job, live_metrics: liveMx }, persisted)
    _setHealthSpinner(mdJobIsActive(job) && !hasMetrics)

    // Active but no measurable metric yet → a "Calculating…" placeholder with a
    // spinner instead of a grid of dashes (NAMD emits its first ENERGY line only
    // after minimization warms up).
    if (mdJobIsActive(job) && !hasMetrics) {
      metricsEl.innerHTML = ''
      const wait = document.createElement('div')
      wait.style.cssText = `grid-column:1 / -1;display:flex;align-items:center;gap:6px;font-size:var(--text-xs);color:${_C.muted};padding:4px 2px`
      wait.appendChild(makeSpinner(_C.muted, 11))
      wait.appendChild(document.createTextNode(
        job.status === 'preparing' ? 'Preparing simulation…' : 'Waiting for first metrics…'))
      metricsEl.appendChild(wait)
      return
    }
    metricsEl.innerHTML = ''

    const scalar = liveMx ?? persisted ?? {}
    const pressure = scalar?.pressure_avg_bar ?? scalar?.gpressure_avg_bar ?? scalar?.pressure_bar ?? null
    const pressureTitle = scalar?.pressure_avg_bar != null
      ? `PRESSAVG ${_fmt(scalar.pressure_avg_bar, 2, ' bar')}${scalar.pressure_bar != null ? ` · instant ${_fmt(scalar.pressure_bar, 2, ' bar')}` : ''}`
      : scalar?.gpressure_avg_bar != null
        ? `GPRESSAVG ${_fmt(scalar.gpressure_avg_bar, 2, ' bar')}${scalar.pressure_bar != null ? ` · instant ${_fmt(scalar.pressure_bar, 2, ' bar')}` : ''}`
        : ''

    const wcThreshold = health ? _wcThresholdForStage(health.stage) : 0.85
    const wcAdvisory = _productionAdvisory(health) || _isAdvisoryWarning(health)
    const wcValue = wcAdvisory ? `⚠ ${_fmtPct(health?.wc_ref_relative_fraction ?? null)}` : _fmtPct(health?.wc_ref_relative_fraction ?? null)
    // Fast-mode jobs spend their first segment in a slow strain-relief stage; flag
    // its Speed with a "*" + hover tooltip so the low number doesn't look broken.
    const speedNote = fastPhaseSpeedNote(job, scalar?.ns_per_day ?? null)
    const speedValue = _fmt(scalar?.ns_per_day ?? null, 1, ' ns/day')
    // Raw values feed the state classifier; the formatted strings above are only ever
    // drawn for a VALUE tile.  Keep the two lists keyed the same.
    const raws = {
      temp:        scalar?.temperature_k ?? null,
      pressure,
      basePairs:   health?.c1_paired_fraction ?? null,
      wcHealth:    health?.wc_ref_relative_fraction ?? null,
      speed:       scalar?.ns_per_day ?? null,
      latest:      null,   // filled below — derived, never pending
      brokenBp:    health?.broken_bp_count ?? null,
      shellCharge: health?.charge_within_shell_e ?? null,
    }
    const latestLabel = mdLatestStageLabel(job, health, persisted)
    raws.latest = latestLabel === '—' ? null : latestLabel
    const states = mdHealthTileStates({
      job, health, raws, nowMs: Date.now(), active: mdJobIsActive(job) })

    const cards = [
      { key: 'temp',       label: 'Temp',       value: _fmt(scalar?.temperature_k ?? null, 1, 'K'),          color: _C.text },
      { key: 'pressure',   label: 'Pressure avg', value: _fmt(pressure, 2, 'bar'),                            color: _C.text, title: pressureTitle },
      { key: 'basePairs',  label: 'Base pairs', value: _fmtPct(health?.c1_paired_fraction ?? null),          color: _healthColor(health?.c1_paired_fraction, 0.90) },
      { key: 'wcHealth',   label: 'WC health',  value: wcValue,                                               color: wcAdvisory ? _C.warn : _healthColor(health?.wc_ref_relative_fraction, wcThreshold), wcTrend: true },
      { key: 'speed',      label: 'Speed',      value: (speedNote && speedValue !== '—') ? `${speedValue} *` : speedValue, color: _C.muted, title: speedNote?.tooltip },
      // Falls back to a RUNNING minimisation: it produces no health sample, so a job
      // spending its first half-hour minimising otherwise reads "Latest —".
      { key: 'latest',       label: 'Latest',     value: latestLabel, color: _C.muted },
      // The two published equilibration criteria NADOC used to compute nowhere.
      // Broken pairs is the citable count (their 3 Å + 140° definition), distinct from
      // the WC card above, which is NADOC's own ref-relative gate.
      { key: 'brokenBp',     label: 'Broken bp',  value: health?.broken_bp_count == null ? '—' : String(health.broken_bp_count),
        color: (health?.broken_bp_count ?? 0) > 0 ? _C.warn : _C.text,
        title: 'Broken base pairs, Aksimentiev definition: the central Watson-Crick '
             + 'bond beyond 3 Å or bent past 140°. Their hextube holds near zero once '
             + 'equilibrated.' },
      // The ion atmosphere. It starts at the bare backbone charge and rises toward zero
      // as counterions condense; a trace that never flattens means the cloud has not
      // converged — which is exactly what a slow-diffusing Mg(H₂O)₆ does if it was
      // placed out in the bulk instead of against the DNA.
      { key: 'shellCharge',  label: 'Shell charge', value: health?.charge_within_shell_e == null ? '—' : _fmt(health.charge_within_shell_e, 0, ' e'),
        color: _C.muted,
        title: 'Net charge within 2 nm of the DNA (Aksimentiev §3.4). Should settle to '
             + 'a stable value once the counterion atmosphere has equilibrated.' },
    ]

    cards.forEach(({ key, label, value, color, wcTrend, title }) => {
      const { state, reason } = states[key] ?? { state: TILE_STATE.VALUE, reason: null }
      const card = document.createElement('div')
      card.style.cssText = `background:${_C.bg2};border:1px solid ${_C.border};border-radius:3px;padding:4px 6px;position:relative`
      // The reason a value is missing beats the metric's static explainer — a tile the
      // user is asking "why is this blank?" about should answer that first.
      const tip = state === TILE_STATE.VALUE || !reason
        ? title
        : (title ? `${reason}\n\n${title}` : reason)
      if (tip) card.title = tip
      card.innerHTML = `<div style="font-size:9px;color:${_C.muted};margin-bottom:1px">${label}</div>`
      const valEl = document.createElement('div')
      valEl.style.cssText = `font-size:11px;color:${color};font-weight:600;font-family:var(--font-mono);display:flex;align-items:center;min-height:13px`
      // A spinner may ONLY mean "being computed right now".  Every other absence renders
      // as a dash with a tooltip saying why — an endless spinner is the bug this fixes.
      if (state === TILE_STATE.PENDING) {
        valEl.appendChild(makeSpinner(_C.muted, 9))
      } else if (state === TILE_STATE.FAILED) {
        valEl.style.color = _C.warn
        valEl.textContent = '—'
      } else if (state === TILE_STATE.UNAVAILABLE) {
        valEl.style.color = _C.muted
        valEl.textContent = '—'
      } else {
        valEl.textContent = value
      }
      card.appendChild(valEl)
      if (wcTrend) {
        card.style.cursor = 'default'
        const trend = _buildWcTrendTooltip(job, health)
        if (trend) {
          card.appendChild(trend)
          card.addEventListener('mouseenter', () => { trend.style.display = 'block' })
          card.addEventListener('mouseleave', () => { trend.style.display = 'none' })
        }
      }
      metricsEl.appendChild(card)
    })
  }

  function _buildWcTrendTooltip(job, latestHealth) {
    const stage = latestHealth?.stage
    const samples = (job.health_samples ?? [])
      .filter(h => h.stage === stage && h.wc_ref_relative_fraction != null)
    if (!stage || !samples.length) return null

    const values = samples.map(h => h.wc_ref_relative_fraction)
    const threshold = _wcThresholdForStage(stage)
    const svg = _wcSparkline(values, threshold)
    const first = values[0]
    const last = values[values.length - 1]
    const delta = last - first
    const trend = values.length < 2 ? 'single point' : `${delta >= 0 ? '+' : ''}${(delta * 100).toFixed(1)} pts`
    const lastReason = latestHealth?.reason ? ` · ${latestHealth.reason}` : ''

    const tip = document.createElement('div')
    tip.style.cssText = [
      'display:none',
      'position:absolute',
      'z-index:30',
      'right:0',
      'top:calc(100% + 6px)',
      `background:${_C.bg}`,
      `border:1px solid ${_C.border}`,
      'border-radius:4px',
      'padding:6px',
      'width:156px',
      'box-shadow:0 8px 20px rgba(0,0,0,0.35)',
      'pointer-events:none',
    ].join(';')
    tip.innerHTML = `
      <div style="font-size:9px;color:${_C.muted};white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-bottom:3px">${_escapeHtml(stage)}</div>
      ${svg}
      <div style="display:flex;justify-content:space-between;gap:6px;margin-top:3px;font-size:9px;font-family:var(--font-mono)">
        <span style="color:${_C.muted}">${samples.length} pts</span>
        <span style="color:${delta < 0 ? _C.warn : _C.ok}">${trend}</span>
      </div>
      <div style="margin-top:2px;font-size:9px;color:${_C.muted};white-space:nowrap;overflow:hidden;text-overflow:ellipsis">
        now ${_fmtPct(last)} / min ${_fmtPct(threshold)}${_escapeHtml(lastReason)}
      </div>
    `
    return tip
  }

  function _wcThresholdForStage(stage) {
    if (/unrestrained|production/i.test(stage)) return 0.75
    const m = /k=([0-9.]+)/i.exec(stage ?? '')
    const k = m ? parseFloat(m[1]) : NaN
    if (Number.isFinite(k) && k <= 0.05) return 0.75
    if (Number.isFinite(k) && k <= 1.0) return 0.80
    return 0.85
  }

  function _wcHardThresholdForStage(stage) {
    return /production/i.test(stage ?? '') ? 0.25 : _wcThresholdForStage(stage)
  }

  function _wcSparkline(values, threshold) {
    const w = 140
    const h = 42
    const pad = 4
    const usableW = w - pad * 2
    const usableH = h - pad * 2
    const minV = Math.max(0, Math.min(threshold, ...values) - 0.03)
    const maxV = Math.min(1, Math.max(threshold, ...values) + 0.03)
    const span = Math.max(0.01, maxV - minV)
    const xFor = (i) => values.length === 1 ? w / 2 : pad + (i / (values.length - 1)) * usableW
    const yFor = (v) => pad + (1 - ((v - minV) / span)) * usableH
    const points = values.map((v, i) => `${xFor(i).toFixed(1)},${yFor(v).toFixed(1)}`).join(' ')
    const thresholdY = yFor(threshold).toFixed(1)
    const dots = values.map((v, i) => {
      const color = v >= threshold ? _C.ok : _C.err
      return `<circle cx="${xFor(i).toFixed(1)}" cy="${yFor(v).toFixed(1)}" r="2" fill="${color}"/>`
    }).join('')
    return `
      <svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" role="img" aria-label="WC health trend">
        <line x1="${pad}" y1="${thresholdY}" x2="${w - pad}" y2="${thresholdY}" stroke="${_C.warn}" stroke-width="1" stroke-dasharray="3 3" opacity="0.8"/>
        <polyline points="${points}" fill="none" stroke="${_C.accent}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
        ${dots}
      </svg>
    `
  }

  function _escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, ch => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[ch]))
  }

  function _productionSegments(job) {
    return (job.segments ?? []).filter(seg => /production|prod/i.test(`${seg.stage ?? ''} ${seg.name ?? ''}`))
  }

  function _latestRecord(records, segmentNames = null) {
    const allowed = segmentNames ? new Set(segmentNames) : null
    for (let i = (records?.length ?? 0) - 1; i >= 0; i--) {
      const rec = records[i]
      if (!allowed || allowed.has(rec.segment)) return rec
    }
    return null
  }


  function _timelineStage(seg) {
    const stage = String(seg?.stage ?? '—')
    const name = String(seg?.name ?? '')
    const prodNs = stage.match(/production\s+([0-9.]+)\s*ns/i) || name.match(/production_([0-9p]+)ns/i)
    const completedNs = Number(seg?.completed_ns)
    if (prodNs && Number.isFinite(completedNs) && completedNs >= 0) {
      const shown = completedNs.toFixed(2)
      return `${shown.replace(/\.0+$/, '').replace(/(\.\d*[1-9])0+$/, '$1')} ns production complete`
    }
    if (prodNs) return `${prodNs[1].replace(/p/g, '.')} ns production run`
    if (/MGHH-only handoff/i.test(stage)) return '300K NPT k=0'
    return stage
  }

  // ── Utility formatters ────────────────────────────────────────────────────
  function _fmtJobTime(unixSec) {
    const d = new Date(unixSec * 1000)
    const now = new Date()
    const sameDay = d.toDateString() === now.toDateString()
    const hm = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false })
    if (sameDay) return hm
    const md = `${String(d.getMonth() + 1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`
    return `${md} ${hm}`
  }

  function _fmt(v, decimals, unit) {
    return v == null ? '—' : `${v.toFixed(decimals)}${unit}`
  }

  function _fmtPct(v) {
    return v == null ? '—' : `${(v * 100).toFixed(1)}%`
  }

  function _healthColor(v, threshold) {
    if (v == null)           return _C.muted
    if (v >= threshold)      return _C.ok
    if (v >= threshold - 0.05) return _C.warn
    return _C.err
  }

  function _statusColor(status) {
    const map = {
      queued:    _C.muted, preparing: _C.accent, running:   _C.warn,
      paused:    _C.accent, completed: _C.ok,    failed:    _C.err,
      stopped:   _C.dim,
    }
    return map[status] ?? _C.muted
  }


  // Graphs & Metrics card — a child module reading this panel's job selection.
  const _metricsCard = initMdMetricsCard({
    getSelectedJob: _selectedJob,
    getJobs: () => _jobs,
  })

  // Anchors card — the shared oxDNA scope picker (parameterised ids), feeding NAMD
  // fixedAtoms.  Resolves the current 3D selection to overhang/cluster/domain/strand/
  // base scopes sent in the create payload as `anchors`.
  const _anchorsCard = initOxdnaAnchorsSetup({
    engine: 'namd',
    getSelection: () => (getSelection ? getSelection() : null),
    ids: {
      toggle: 'md-anchors-toggle', arrow: 'md-anchors-arrow', body: 'md-anchors-body',
      add: 'md-anchors-add', clear: 'md-anchors-clear', list: 'md-anchors-list',
      status: 'md-anchors-status', glow: 'md-anchors-glow',
      // NAMD only: gives each row a Hold-atoms <select> and binds this element as
      // "Apply hold to all". The other six instances of this factory pass no `atoms`
      // and render the plain two-column list.
      atoms: 'md-anchors-atoms',
    },
  })

  // Electric-field card — the shared numeric field factory (same one the CanDo panel
  // binds), feeding NAMD's native eFieldOn/eField.  `field_pN` is the cross-engine
  // per-nucleotide force descriptor; the oxDNA card owns the one in-scene arrow gizmo.
  const _efieldCard = initForcesCard({
    engine: 'namd',
    getAnchorCount: () => _anchorsCard?.getAnchors?.()?.length || 0,
  })

  // ── Init ───────────────────────────────────────────────────────────────────
  _setDisplayStatus('Off', _C.dim)
  console.log(`[${_ts()}] md-jobs: panel initialised`)
  _base.initCollapsed(true)   // apply persisted collapse; fires _onOpen if starting open
  // Paint the primary control up front: it acts on the SELECTED job now, so with nothing
  // selected it must read "▶ Run", disabled, with the hint — not the markup's placeholder.
  _paintRunControl()
  if (_isDynamicsTabVisible()) _startMdPrewarm()

  // The panel's external surface: the currently-selected job (consumed by the shared
  // comparison card's getSources and by the Plan-Run overlay's default root, P4).
  return {
    /** Binary solvent frame from the live MD WebSocket → the overlay. Wired in
     *  main.js, because md_panel owns the socket and this panel owns the toggles. */
    acceptLiveSolvent: (buf) => solvent?.liveBlob(buf),

    getSelectedJob: _selectedJob,
    // Immediately re-fetch the job list (used when a job is spawned from somewhere other
    // than this panel). A single fetch populates the list AND re-arms the poll once the
    // new job reads active.
    refresh: _fetchJobs,
    // Select a job in this panel's list (highlight + populate cards) as a row click does.
    // Refetches first if the job isn't listed yet (a just-spawned job).
    selectJob: async (jobId) => {
      if (!jobId) return
      if (!_jobs.find((j) => j.job_id === jobId)) await _fetchJobs()
      return _selectJob(jobId)
    },
    // Drop the selection without unloading anything (the unified Simulate list routes its own
    // click-the-selected-row-to-deselect here).
    deselectJob: _deselectJob,
    /**
     * Open a job's settings. Draft/prepared jobs edit in place; started jobs are locked.
     *
     * Exposed because the list the user actually right-clicks is the UNIFIED Simulate list
     * (`simulate_jobs.js`), whose nodes are a reduced cross-engine shape that does not
     * carry `prep_params`. The full record lives here, so the lookup — and the refetch when
     * this panel has not polled since the job appeared — belong here too.
     */
    openJobSettings: async (jobId) => {
      if (!jobId) return
      if (!_jobs.find((j) => j.job_id === jobId)) await _fetchJobs()
      const job = _jobs.find((j) => j.job_id === jobId)
      if (job) return mdJobEditable(job)
        ? _wizard.openEditable(job)
        : _wizard.openReadOnly(job)
    },
    /** Whether that entry has anything to show — the menu offers it either way, but says
     *  why when a job predates its request being recorded. */
    hasJobSettings: (jobId) =>
      jobSettingsState(_jobs.find((j) => j.job_id === jobId)).available,
    canEditJob: (jobId) => mdJobEditable(_jobs.find((j) => j.job_id === jobId)),
    // Consolidated Archive/Delete (the section-level #simulate-job-actions dispatches to the
    // selected node's engine panel; both operate on this panel's currently-selected job).
    deleteSelected, archiveSelected,
  }
}
