/**
 * simulate_jobs.js — the unified simulation job list + master Job status card
 * (Phase C of the simulate-panel overhaul).
 *
 * The auto engine-policy picks oxDNA-GPU when the GPU is free and CPU-LAMMPS (the SAME
 * oxDNA2 force field, multi-core) when it's busy. The user shouldn't have to know which
 * ran — so EVERY run started from Simulate appears here in ONE hierarchical list
 * (`GET /simulate/jobs` → a common node shape merging oxDNA + LAMMPS via the shared
 * `job_tree` + `jobs_panel_model`). A LAMMPS run carries only a subtle **[L]** badge and
 * an expandable "ran on CPU because the GPU was busy" note.
 *
 * Selecting any node drives the master card: a status line + one status-coloured progress
 * bar (with the full stage/segment detail as its hover tooltip) + the selected engine's
 * stage timeline at the card bottom + one context Run/Stop/Resume button (via the pure
 * `job_run_control.runControlState`). Detail dispatches by engine — oxDNA/mrDNA/CanDo/NAMD
 * each light up their own panel via `selectJob(id)`; a LAMMPS run (oxDNA's CPU fallback,
 * same oxDNA2 bead model) shows in the oxDNA panel's OWN viz card via `selectLammpsJob(node)`,
 * with its Stop / re-Run on the master button.
 *
 * Factory: initSimulateJobs({ api, getWorkspacePath, oxdnaPanel, mrdnaPanel, candoPanel,
 * mdPanel, engineSelector }) → { refresh, selectJob, setActiveEngine, getSelected }.
 * Module-first: cohesive logic lives here / in the pure helpers below; main.js only inits.
 * Physical-layer / display-state only (topology is never touched).
 */

import { buildJobListModel, jobListSignature } from './jobs_panel_model.js'
import { getRunDir, mountDirectoryButton } from './run_location.js'
import { renderJobList } from './jobs_panel_render.js'
import { createContextMenu } from './primitives/context_menu.js'
import { runControlState, RUN_ACTION } from './job_run_control.js'
import { relaxIndexMap, relaxRowLabel, runRowLabel, runChildTitle } from './oxdna_jobs_panel.js'
import { jobDisplayName as mrdnaDisplayName } from './mrdna_jobs_panel.js'
import { jobDisplayName as candoDisplayName } from './cando_jobs_panel.js'
import { jobDisplayName as snupiDisplayName } from './snupi_jobs_panel.js'
import { jobDisplayName as bladeDisplayName } from './blade_jobs_panel.js'
import { mdJobRowCtx } from './md_jobs_panel.js'
import { mdMinimizationRow } from './md_stage_timeline.js'
import { buildCreatePayload } from './lammps_jobs_logic.js'
import { getSectionCollapsed, setSectionCollapsed } from './section_collapse_state.js'
import { formatJobTime } from '../scene/trajectory_range.js'
import { formatBytes } from './format_bytes.js'
import { showToast } from './toast.js'

const POLL_MS = 1500
const _C = { ok: '#5cb85c', warn: '#e0a800', err: '#d9534f', accent: '#4a9eff', dim: '#8a8a8a' }
const _ACTIVE = ['queued', 'preparing', 'running']

// Per-engine badge shown on rows only in "Show all job types" mode, so a mixed list
// stays legible about which engine each run came from. LAMMPS keeps its own [L] badge
// (it's oxDNA's CPU fallback, grouped under the oxDNA tab) and is omitted here.
const _ENGINE_BADGE = {
  oxdna: { text: '[ox]', color: '#4a9eff', title: 'oxDNA' },
  mrdna: { text: '[mr]', color: '#9e6bff', title: 'mrDNA' },
  cando: { text: '[CD]', color: '#39c5cf', title: 'CanDo FEM' },
  snupi: { text: '[SN]', color: '#d29bff', title: 'SNUPI FEM' },
  blade: { text: '[BL]', color: '#58a6ff', title: 'BLADE implicit-solvent relax' },
  namd:  { text: '[MD]', color: '#3fb950', title: 'NAMD (Molecular Dynamics)' },
}

/** The engine TAB a node belongs to. LAMMPS is oxDNA's transparent CPU fallback, so its
 *  runs live under the oxDNA tab (the auto-policy picks GPU-oxDNA ⇄ CPU-LAMMPS). */
function engineGroup(node) {
  return node?.engine === 'lammps' ? 'oxdna' : node?.engine
}

// ── Pure decisions (unit-tested) ──────────────────────────────────────────────

/** Is a node in an in-progress state (active spinner + Stop)? */
export function nodeIsActive(node) {
  return _ACTIVE.includes(node?.status)
}

/** Is this node's state going to change on its own, so the list must keep polling?
 *
 *  Deliberately NARROWER than `nodeIsActive`: a job that was CREATED but not started
 *  (`＋ New job → Create job`, i.e. `autostart:false`) sits at `queued` forever waiting
 *  for the user, so treating it as active would poll every 1.5 s indefinitely for a row
 *  that cannot change until someone clicks Run. A REMOTE queued job is different — its
 *  scheduler moves it without us — hence the id check.
 *
 *  Kept separate from `nodeIsActive` on purpose: that one drives the spinner and the
 *  master Stop button, where "queued" genuinely should read as pending. */
export function nodeNeedsPolling(node) {
  if (!nodeIsActive(node)) return false
  if (node?.status !== 'queued') return true
  return !!(node?.slurm_job_id || node?.runpod_pod_id)
}

/** Can the selected node be resumed? Only an oxDNA job that was stopped/failed —
 *  LAMMPS has no resume (a finished LAMMPS run is simply re-launchable). */
export function nodeIsResumable(node) {
  return node?.engine === 'oxdna' && ['stopped', 'failed'].includes(node?.status)
}

/** The launch verb for the master control given the selected node (null = the default
 *  front-door Relax). A LAMMPS run or an oxDNA production child reads "Run"; a root
 *  oxDNA relaxation reads "Relax". */
export function verbForNode(node) {
  if (!node) return 'Relax'
  if (node.engine === 'lammps') return 'Run'
  return node.kind === 'run' ? 'Run' : 'Relax'
}

/** Percent → ONE decimal (0.1, 0.2, …), clamped to 0..100.
 *
 *  Whole-percent rounding hid the start of every long run: a 500 ns production is
 *  125M steps, so its first hour is a fraction of a percent and `Math.round` pinned the
 *  bar at a flat 0 while the run was demonstrably progressing. A tenth of a percent is
 *  1.25 ns there — reached in minutes — so the bar leaves 0 almost immediately.
 *  Whole values are unaffected: 50 stays 50, and JS drops the trailing `.0` when
 *  interpolated, so short runs read exactly as before. */
function _pct1(x) {
  return Math.max(0, Math.min(100, Math.round(x * 1000) / 10))
}

/** Progress % (one decimal) for the ONE master bar (no extra fetch): completed → 100;
 *  LAMMPS from current_step/steps; NAMD from the backend live fraction (else segments
 *  done/total); oxDNA likewise from stages; mrDNA/CanDo have no granular signal → 0
 *  while running (the bar COLOR conveys state). */
export function masterProgressPct(node) {
  if (!node) return 0
  if (node.status === 'completed' || node.production_state === 'done') return 100
  if (node.engine === 'lammps') {
    const total = Number(node.steps) || 0
    const cur = Number(node.current_step) || 0
    return total > 0 ? _pct1(cur / total) : 0
  }
  if (node.engine === 'namd') {
    // Prefer the live within-segment fraction the backend stamps on a RUNNING NAMD job
    // (so a single-segment production child advances instead of sitting at 0 % until its
    // one segment flips to done). Fall back to the done/total segment count otherwise.
    if (node.progress_fraction != null) {
      return _pct1(Number(node.progress_fraction))
    }
    const seg = node.segments || []
    if (!seg.length) return 0
    return _pct1(seg.filter((s) => s.status === 'done').length / seg.length)
  }
  // oxDNA: prefer the live within-stage fraction the backend stamps on a running job
  // (so a SINGLE-stage run — e-field / surface / production child — advances smoothly
  // instead of sitting at 0 % until its one stage flips to done). Fall back to the
  // completed-stage count for jobs without it (queued / older list payloads).
  if (node.progress_fraction != null) {
    return _pct1(Number(node.progress_fraction))
  }
  const st = node.stages || []
  if (!st.length) return 0
  return _pct1(st.filter((s) => s.status === 'done').length / st.length)
}

/** Fill colour of the master bar, by status: green done · red failed · orange WARNING
 *  (design changed since the run — stale/out-of-date) · grey stopped/queued · blue active. */
export function masterProgressColor(node) {
  if (!node) return _C.accent
  if (node.out_of_date) return _C.warn                                   // orange — stale
  if (node.status === 'failed' || node.production_state === 'failed') return _C.err
  if (node.status === 'completed' || node.production_state === 'done') return _C.ok
  if (node.status === 'stopped' || node.status === 'queued') return _C.dim
  return _C.accent                                                        // running / preparing
}

/** The full progress detail (stage / segments / % / status) — shown as the master bar's
 *  hover TOOLTIP (what used to sit inline in each engine's #*-jobs-progress). */
export function masterProgressTooltip(node) {
  if (!node) return ''
  const pct = masterProgressPct(node)
  const stale = node.out_of_date ? '\n⚠ design changed since this run' : ''
  if (node.engine === 'lammps') {
    return `LAMMPS (CPU) · ${node.status}${node.status === 'running' ? ` · ${pct}%` : ''}${stale}`
  }
  if (node.engine === 'namd') {
    const seg = node.segments || []
    const done = seg.filter((s) => s.status === 'done').length
    const run = seg.find((s) => s.status === 'running')
    const lines = [`NAMD · ${node.status}`]
    if (seg.length) lines.push(`${done}/${seg.length} segments · ${pct}% overall`)
    // Minimisation runs before segment 1 and is not one of them, so the bar legitimately
    // sits at 0 % throughout — say what it is doing rather than let it look stalled.
    const min = mdMinimizationRow(node)
    if (min && min.status === 'running') {
      const step = Number(node?.live_metrics?.segment === min.name ? node.live_metrics?.step : NaN)
      const total = Number(min.steps)
      const detail = Number.isFinite(step) && total > 0
        ? ` · ${Math.max(0, Math.min(total, Math.round(step))).toLocaleString()} / ${total.toLocaleString()} steps`
        : ''
      lines.push(`Current: ${min.stage} (before segment 1)${detail}`)
    }
    if (run) lines.push(`Current: ${run.name || run.stage || 'running'}${run.percent != null ? ` · ${run.percent}%` : ''}`)
    return lines.join('\n') + stale
  }
  const eng = engineLabel(node)
  const state = node.production_state && node.production_state !== 'none'
    ? `production ${node.production_state}` : node.status
  const st = node.stages || []
  const parts = [`${eng} · ${state}`]
  if (st.length) parts.push(`${st.filter((s) => s.status === 'done').length}/${st.length} stages · ${pct}%`)
  return parts.join('\n') + stale
}

/** Human engine label for a node — used by the status line + tooltip so a NAMD/mrDNA/
 *  CanDo run isn't mislabeled "oxDNA". */
export function engineLabel(node) {
  switch (node?.engine) {
    case 'lammps': return 'LAMMPS (CPU)'
    case 'namd':   return 'NAMD'
    case 'mrdna':  return 'mrDNA'
    case 'cando':  return 'CanDo'
    case 'snupi':  return 'SNUPI'
    case 'blade':  return 'BLADE'
    case 'oxdna':  return 'oxDNA'
    default:       return node?.engine || 'run'
  }
}

function _stepTotal(node) {
  const direct = Number(node?.steps ?? node?.total_steps ?? node?.n_steps)
  if (Number.isFinite(direct) && direct > 0) return direct
  const parts = node?.engine === 'namd' ? (node.segments || []) : (node.stages || [])
  const values = parts.map(p => Number(p.steps ?? p.total_steps ?? p.num_steps ?? p.n_steps) || 0)
  const sum = values.reduce((a, b) => a + b, 0)
  if (sum > 0) return sum
  if (node?.engine === 'mrdna') return (Number(node.coarse_steps) || 0) + (Number(node.fine_steps) || 0)
  // Linear FEM solves are one solve step; nonlinear CanDo/SNUPI normally expose n_steps.
  if (node?.engine === 'cando' || node?.engine === 'snupi' || node?.engine === 'blade') return 1
  return 0
}

/** Time left on the whole job, as ` · ~2d 06h remaining`, or '' when no engine-supplied
 *  estimate exists. "remaining" rather than "left" so it can't be misread as a second
 *  step count next to "… 124,035,000 left". */
function _etaSuffix(node) {
  const eta = Number(node?.eta_seconds)
  return Number.isFinite(eta) && eta > 0 ? ` · ~${formatEta(eta)} remaining` : ''
}

/** Marks a bar whose position is CARRIED FORWARD from the last cluster reading rather
 *  than measured.  A remote job is only observable while the user is signed in (Duo),
 *  so between sign-ins the number is a projection at the last known rate — it has to
 *  read as one, or a stale estimate passes for a live measurement. */
export function progressIsEstimated(node) {
  return !!node?.progress_estimated
}

/** Prefix for an estimated readout: "~" the way the ETA already hedges. */
function _estPrefix(node) {
  return progressIsEstimated(node) ? '~' : ''
}

/** Engine-symmetric numeric progress appended beneath the unified Jobs bar. */
export function masterStepText(node) {
  if (!node) return ''
  const pct = masterProgressPct(node)
  const min = node?.engine === 'namd' ? mdMinimizationRow(node) : null
  const liveMinStep = Number(node?.live_metrics?.segment === min?.name ? node.live_metrics?.step : NaN)
  // While minimising, show that phase's exact counter. The backend's progress_fraction
  // is whole-job progress (minimisation + ladder), so deriving a minimisation step from
  // it would display a plausible but incorrect number.
  if (min?.status === 'running' && Number(min.steps) > 0 && Number.isFinite(liveMinStep)) {
    const total = Number(min.steps)
    const completed = Math.max(0, Math.min(total, Math.round(liveMinStep)))
    const phasePct = _pct1(completed / total)
    return `${phasePct}% minimization · ${completed.toLocaleString()} / ${total.toLocaleString()} steps`
      + ` · ${(total - completed).toLocaleString()} left${_etaSuffix(node)}`
  }
  const total = _stepTotal(node)
  const est = _estPrefix(node)
  const tail = progressIsEstimated(node)
    ? ' · estimated from last cluster sync'
    : node?.progress_last_known ? ' · last known' : ''
  if (!(total > 0)) return `${est}${pct}%${_etaSuffix(node)}${tail}`
  const explicit = Number(node.current_step ?? node.completed_steps ?? node.steps_completed)
  // Derive the step count from the RAW fraction, not the displayed percent: rounding to
  // a tenth of a percent is 125,000 steps of slop on a 125M-step production, which would
  // make the step readout visibly disagree with the checkpoint it came from.
  const fraction = Number(node.progress_fraction)
  const completed = Number.isFinite(explicit)
    ? Math.max(0, Math.min(total, Math.round(explicit)))
    : Number.isFinite(fraction)
      ? Math.max(0, Math.min(total, Math.round(total * fraction)))
      : Math.max(0, Math.min(total, Math.round(total * pct / 100)))
  const left = Math.max(0, total - completed)
  return `${est}${pct}% · ${completed.toLocaleString()} / ${total.toLocaleString()} steps`
       + ` · ${left.toLocaleString()} left${_etaSuffix(node)}${tail}`
}

/** One-line master status text for the selected node (engine-symmetric). */
export function masterStatusText(node) {
  if (!node) return 'Select a run above, or press ▶ Relax to start one.'
  const eng = engineLabel(node)
  if (node.engine === 'lammps') {
    return `${eng} · ${node.status} · ${masterStepText(node)}`
  }
  if (node.production_state === 'running') return `${eng} · production running · ${masterStepText(node)}`
  if (node.production_state === 'done') return `${eng} · production done · ${masterStepText(node)}`
  if (node.production_state === 'failed') return `${eng} · production failed · ${masterStepText(node)}`
  // NAMD (and any engine with a live/segment fraction) shows overall % while running so a
  // single-segment production reads as progress, not a bare "running".
  if (node.engine === 'namd' && node.status === 'running') return `${eng} · running · ${masterStepText(node)}`
  if (node.engine === 'namd' && node.progress_last_known) {
    return `${eng} · ${node.status} · ${masterStepText(node)}`
      + (node.runpod_sync_notice ? ` · ⚠ ${node.runpod_sync_notice}` : '')
  }
  // BLADE reports a REAL fraction streamed out of the OpenMM process, plus its phase. Naming the
  // phase matters here: `build` is psfgen constructing the CHARMM topology, which on a large design
  // is a minute of legitimately step-less work that would otherwise read as a stuck bar.
  // (The ETA is no longer appended here — `masterStepText` carries it for every engine.)
  if (node.engine === 'blade' && node.status === 'running') {
    const parts = [`${eng} · running · ${masterStepText(node)}`]
    if (node.phase) parts.push(node.phase)
    return parts.join(' · ')
  }
  // SNUPI reports a REAL fraction (a fixed GJF step count) + an ETA measured from the observed rate,
  // plus the current phase — building the hydrodynamic friction is a slow, step-less phase, so name it
  // or the bar looks stuck. This line sits directly under the master bar.
  if (node.engine === 'snupi' && node.status === 'running') {
    const parts = [`${eng} · running · ${masterStepText(node)}`]
    if (node.phase) parts.push(node.phase)
    return parts.join(' · ')
  }
  const stages = node.stages || node.segments || []
  const stageText = stages.length
    ? `${stages.filter(s => s.status === 'done').length}/${stages.length} ${node.engine === 'namd' ? 'segments' : 'stages'}`
    : ''
  return [`${eng} · ${node.status}`, stageText, masterStepText(node)].filter(Boolean).join(' · ')
}

/** Requested SLURM allocation and its wall-clock remainder. Queue time is deliberately
 * excluded: slurm_started_at is stamped only when the scheduler reports RUNNING. */
export function slurmAllocationText(node, nowMs = Date.now()) {
  if (node?.engine !== 'namd' || node?.execution_target !== 'alpine') return ''
  const walltime = node?.resources?.walltime || node?.requested_resources?.walltime
  if (!walltime) return ''
  const parts = String(walltime).split(':').map(Number)
  if (parts.length !== 3 || parts.some((n) => !Number.isFinite(n) || n < 0)) return ''
  const total = parts[0] * 3600 + parts[1] * 60 + parts[2]
  if (!(total > 0)) return ''
  const started = Number(node.slurm_started_at)
  if (!Number.isFinite(started) || started <= 0) {
    return `SLURM runtime requested: ${walltime} · starts counting when the job begins`
  }
  const ran = Math.max(0, nowMs / 1000 - started)
  const remaining = Math.max(0, total - ran)
  const state = remaining > 0 ? `${formatEta(remaining)} remaining` : 'allocation elapsed'
  return `SLURM runtime requested: ${walltime} · ${formatEta(ran)} run · ${state}`
}

/** Alpine output can be accepted and transferred whether the allocation is live or has
 * already paused/stopped/failed. `archived` does NOT exclude it: archive-from-birth jobs
 * already have a destination directory but can still have unfetched output on Alpine. */
export function canEndAndDownload(node) {
  return node?.engine === 'namd'
    && node?.execution_target === 'alpine'
}

/** Seconds → a two-unit duration: `45s` · `1m 35s` · `3h 07m` · `2d 06h`.
 *
 *  Coarsens as it grows: a NAMD production is measured in DAYS (a 500 ns run at 221
 *  ns/day is ~2d 6h), and the m:ss form this used to always emit would have rendered
 *  that as "3255m 12s". Sub-hour output is unchanged — the FEM/SNUPI solves that were
 *  its only callers still read exactly as before. */
export function formatEta(seconds) {
  const s = Math.max(0, Math.ceil(Number(seconds) || 0))
  if (s < 60) return `${s}s`
  if (s < 3600) return `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, '0')}s`
  const pad = (n) => String(n).padStart(2, '0')
  if (s < 86400) return `${Math.floor(s / 3600)}h ${pad(Math.floor((s % 3600) / 60))}m`
  return `${Math.floor(s / 86400)}d ${pad(Math.floor((s % 86400) / 3600))}h`
}

/**
 * The expandable detail note under the master bar. This note is oxDNA-SPECIFIC: an oxDNA run gets a
 * brief size line (its rich detail lives in the oxDNA panel), and a LAMMPS run explains why it fell
 * back to CPU (LAMMPS runs are oxDNA's CPU fallback and group under the oxDNA tab).
 *
 * ``activeEngine`` is the engine TAB currently selected. The note only renders on the oxDNA tab: with
 * "Show all job types" on you can select an oxDNA run from any tab, and an oxDNA-flavoured line has no
 * business appearing under, say, the SNUPI panel.
 *
 * It also returns '' for every other engine. It used to FALL THROUGH — any non-LAMMPS node with
 * ``n_units`` was labelled "oxDNA (GPU) · N nucleotides", so selecting a SNUPI / mrDNA / CanDo / NAMD
 * run claimed it had run on oxDNA. Engines other than oxDNA have no detail note here; theirs lives in
 * their own panel.
 */
export function nodeDetailText(node, activeEngine = 'oxdna') {
  if (!node) return ''
  if (activeEngine !== 'oxdna') return ''            // not the oxDNA tab → no oxDNA note
  if (node.engine === 'lammps') {
    const cores = Number(node.ranks) || 1
    return `Ran on CPU (LAMMPS, ${cores} core${cores === 1 ? '' : 's'}) because the GPU was busy — ` +
           'the same oxDNA2 force field, multi-core, faster than single-core.'
  }
  if (node.engine !== 'oxdna') return ''             // never label another engine's run "oxDNA"
  const n = Number(node.n_units) || 0
  return n ? `oxDNA (GPU) · ${n.toLocaleString()} nucleotides` : ''
}

// ── Stateful factory ──────────────────────────────────────────────────────────

export function initSimulateJobs({
  api,
  getWorkspacePath = null,
  oxdnaPanel = null,
  mrdnaPanel = null,
  candoPanel = null,
  snupiPanel = null,
  bladePanel = null,
  mdPanel = null,
  engineSelector = null,
} = {}) {
  const $ = (id) => document.getElementById(id)
  const root = $('simulate-jobs')
  const listEl = $('simulate-jobs-list')
  const statusEl = $('simulate-jobs-status')
  const allocationEl = $('simulate-jobs-allocation')
  const progressBar = root?.querySelector('#simulate-jobs-progress .bar')
  const progressWrap = $('simulate-jobs-progress')
  const runBtn = $('simulate-jobs-run-btn')
  const endDownloadBtn = $('simulate-jobs-end-download-btn')
  const detailEl = $('simulate-jobs-detail')
  // The one stage-timeline block at the bottom of the jobs card + each engine's timeline
  // element (relocated here from its panel by main.js); the selected engine's is shown.
  const timelineBlock = $('simulate-jobs-timeline')
  const _timelineEls = {
    oxdna: $('oxdna-jobs-timeline'), namd: $('md-jobs-timeline'),
    mrdna: $('mrdna-jobs-timeline'), cando: $('cando-jobs-timeline'),
    snupi: $('snupi-jobs-timeline'),
    blade: $('blade-jobs-timeline'),
  }
  if (!root || !listEl) return { refresh: () => {}, selectJob: () => {}, getSelected: () => null, setActiveEngine: () => {} }

  // collapsible "Jobs" card (header/body/chevron) + "Show all job types" toggle + the
  // engine-scope label in the header.
  const cardHeader = $('simulate-jobs-toggle')
  const cardBody = $('simulate-jobs-body')
  const cardArrow = $('simulate-jobs-arrow')
  const engineLabel = $('simulate-jobs-engine-label')
  const showAllToggle = $('simulate-jobs-show-all-types')

  // Consolidated Change-directory/Delete controls above the jobs card. Acts on
  // the selected run by dispatching to that run's engine panel; hidden until a deletable
  // run is selected. Directory moves are supported by oxDNA / NAMD.
  const actionsHost = $('simulate-job-actions')
  const archiveActionBtn = $('simulate-jobs-archive-btn')
  const deleteActionBtn = $('simulate-jobs-delete-btn')
  const archiveProgress = $('simulate-jobs-archive-progress')

  // The ONE shared "📁 Directory" button, above the jobs list — sets where new runs (any
  // engine) write their large trajectories. Each engine's create reads getRunDir().
  mountDirectoryButton($('simulate-run-dir'), { api })

  let _nodes = []
  let _sel = { engine: null, id: null }
  let _listSig = null
  let _busy = false
  let _dynamicsActive = true
  let _pollTimer = null
  let _activeEngine = engineSelector?.getSelected?.() || 'oxdna'
  let _showAllTypes = false
  // job_id → {phase:'downloading'|'moving'|'done', pct, moved, total}. Kept outside the
  // fetched node so a list refresh cannot erase feedback while the request is in flight.
  const _endTransfers = new Map()
  const _legend = { el: null }

  // Nodes shown for the current view: the active engine tab's runs (LAMMPS grouped under
  // oxDNA), or every engine's when "Show all job types" is on.
  const _visibleNodes = () =>
    _showAllTypes ? _nodes : _nodes.filter((n) => engineGroup(n) === _activeEngine)

  const _currentPath = () => (getWorkspacePath ? getWorkspacePath() : null) || null
  const _selectedNode = () => _nodes.find((n) => n.engine === _sel.engine && n.job_id === _sel.id) || null
  const _setStatus = (el, text, color = _C.dim) => { if (el) { el.textContent = text; el.style.color = color } }
  // The engine panel owning a node's Archive/Delete (LAMMPS has no panel — its runs are
  // oxDNA's CPU fallback and carry no per-job delete UI).
  const _panelFor = (node) =>
    ({ oxdna: oxdnaPanel, mrdna: mrdnaPanel, cando: candoPanel, snupi: snupiPanel,
       blade: bladePanel, namd: mdPanel }[node?.engine]) || null

  // ── list ─────────────────────────────────────────────────────────────────
  // Per-engine row labels: each engine's own display/child-label fns render its rows
  // in the shared list. NAMD reuses its canonical row ctx (mdJobRowCtx) so its
  // production/replica labels, seeded/remote badges + hourglass override stay identical
  // to the NAMD tab; oxDNA/mrDNA/CanDo use their exported label fns.
  function _mdCtx(nodes) {
    return mdJobRowCtx({ jobs: nodes.filter((n) => n.engine === 'namd'),
                         selectedId: _sel.id, formatTime: formatJobTime })
  }
  function _displayName(n, md, relaxNo, pos) {
    switch (n.engine) {
      case 'oxdna': case 'lammps': return relaxRowLabel(n, relaxNo.get(n.job_id))
      case 'mrdna': return mrdnaDisplayName(n)
      case 'cando': return candoDisplayName(n)
      case 'snupi': return snupiDisplayName(n)
      case 'blade': return bladeDisplayName(n)
      case 'namd':  return md.displayName(n, pos)
      default:      return n.job_id
    }
  }
  function _childLabel(n, i, md) {
    if (n.engine === 'oxdna') return runRowLabel(n, i)
    if (n.engine === 'namd') return md.childLabel(n, i)
    return ''
  }
  function _childTitle(n, md) {
    if (n.engine === 'oxdna') return runChildTitle(n)
    if (n.engine === 'namd') return md.childTitle(n)
    return null
  }
  function _tags(n) {
    const out = []
    if (_showAllTypes && n.engine !== 'lammps' && _ENGINE_BADGE[n.engine]) {
      const b = _ENGINE_BADGE[n.engine]
      out.push({ text: b.text, color: b.color, title: b.title })
    }
    if (n.engine === 'lammps') {
      out.push({ text: '[L]', color: '#9e6bff', title: 'Ran on CPU (LAMMPS) — the GPU was busy' })
    } else if (n.engine === 'oxdna' && (oxdnaPanel?.autorefineJobIds?.() || new Set()).has(n.job_id)) {
      out.push({ text: '[AR]', color: '#e3b341', title: 'Created by Autorefine skips/loops' })
    }
    return out
  }

  function _rowCtx(nodes) {
    const md = _mdCtx(nodes)
    // "relax N" numbering is scoped to the oxDNA group (GPU oxDNA + its CPU/LAMMPS
    // fallback runs) over ALL nodes, so it reads the same here as on the oxDNA tab
    // and in the animation panel's trajectory dropdown — showing other engines or
    // hiding a design must not renumber it.
    const relaxNo = relaxIndexMap(_nodes.filter((n) => engineGroup(n) === 'oxdna'))
    return {
      engine: 'oxdna',                       // fallback; engineOf resolves per row
      engineOf: (n) => (n.engine === 'lammps' ? 'lammps' : n.engine),
      selectedId: _sel.id,
      hierarchical: true,
      displayName: (n, pos) => _displayName(n, md, relaxNo, pos),
      childLabel: (n, i) => _childLabel(n, i, md),
      childTitle: (n) => _childTitle(n, md),
      productionState: (n) => (n.engine === 'oxdna' ? n.production_state : null),
      isActive: nodeIsActive,
      isStale: (n) => !!n.out_of_date,
      staleClass: 'oxdna-job-stale-warn',
      staleTitle: 'Design changed since this job was relaxed — run a new Relax, or roll the feature log back, before live/production.',
      tags: _tags,
      postLabelMarkers: (n, meta) => (n.engine === 'namd' ? md.postLabelMarkers(n, meta) : []),
      symbolOverride: (n) => (n.engine === 'namd' ? md.symbolOverride(n) : null),
      showIndex: (n) => n.engine !== 'namd',
      compactColumns: (n) => n.engine === 'namd',
      archived: (n) => !!n.archived,
      archivePath: (n) => n.archive_path || '',
      sizeBytes: (n) => n.size_bytes ?? null,
      formatTime: formatJobTime,
      formatSize: formatBytes,
      sizeLabel: (n, total) => n.engine === 'namd' && n.dcd_size_bytes != null && total != null
        ? `${formatBytes(n.dcd_size_bytes)} DCD / ${formatBytes(total)} total`
        : (total ? formatBytes(total) : ''),
      rowSig: (n) => `${n.engine}:${n.job_id}:${n.status}:${n.production_state}:${n.out_of_date ? 1 : 0}:${n.archived ? 1 : 0}:${n.size_bytes ?? ''}:${n.dcd_size_bytes ?? ''}`,
      colors: { dim: _C.dim, warn: _C.warn },
    }
  }

  function _renderList() {
    const nodes = _visibleNodes()
    const ctx = _rowCtx(nodes)
    const sig = `${_activeEngine}:${_showAllTypes ? 1 : 0}|` + jobListSignature(nodes, ctx)
    if (sig === _listSig && listEl.childElementCount > 0) return
    _listSig = sig
    renderJobList(listEl, buildJobListModel(nodes, ctx), {
      onClick: (jobId) => (jobId === _sel.id ? _deselect() : _select(jobId)),
      onContextMenu: (jobId, e) => _openRowMenu(jobId, e),
      emptyText: _showAllTypes
        ? 'No simulation runs for this design yet — press ▶ Relax to start one.'
        : `No ${_activeEngine === 'namd' ? 'NAMD' : _activeEngine} runs for this design yet. Toggle “Show all job types” to see every engine’s runs.`,
      dimColor: _C.dim,
      legendState: _legend,
    })
  }

  /**
   * Right-click on a row of the unified list.
   *
   * NAMD only for now: the Job Wizard asks about two dozen things — protocol, ion
   * chemistry, box padding, the integrator's three axes, the whole stage ladder — and once
   * the job existed there was nowhere to read any of it back. Other engines have no
   * equivalent setup surface to reopen, so their rows get no menu and keep the browser's.
   */
  function _openRowMenu(jobId, e) {
    const node = _nodes.find((n) => n.job_id === jobId)
    if (node?.engine !== 'namd' || !mdPanel?.openJobSettings) return
    e.preventDefault()
    createContextMenu({
      x: e.clientX, y: e.clientY,
      items: [
        { type: 'header', label: `${node.design_name || 'job'} · ${formatJobTime(node.created_at)}` },
        {
          // A job created before its request was recorded has nothing to show, and the
          // label says why rather than the item silently doing nothing.
          label: mdPanel.hasJobSettings?.(jobId) === false
            ? 'Settings were not recorded for this run'
            : 'View settings…',
          disabled: mdPanel.hasJobSettings?.(jobId) === false,
          onClick: () => { void mdPanel.openJobSettings(jobId) },
        },
      ],
    })
  }

  function _renderMaster() {
    const node = _selectedNode()
    let transfer = node ? _endTransfers.get(node.job_id) : null
    if (!transfer && node?.execution_target === 'alpine') {
      const ds = node.download_status
      if (ds?.state === 'verified') transfer = { phase: 'done', pct: 100, ...ds }
      else if (ds?.state === 'processing') transfer = { phase: 'processing', pct: 100, ...ds }
      else if (ds?.state === 'downloading') {
        const moved = Math.min(Number(ds.transferred_bytes ?? ds.verified_bytes) || 0,
          Number(ds.total_bytes) || Infinity)
        const pct = ds.total_bytes ? Math.min(100, Math.round(moved / ds.total_bytes * 100)) : 0
        transfer = { phase: 'downloading', moved, total: ds.total_bytes, pct, ...ds }
      } else if (ds?.state === 'interrupted' || node.status === 'completed') {
        const pct = ds?.total_bytes ? Math.round((ds.verified_bytes || 0) / ds.total_bytes * 100) : 0
        transfer = { phase: 'unverified', pct, ...(ds || {}) }
      }
    }
    const transferText = transfer?.phase === 'downloading'
      ? `Downloading results from Alpine${transfer.total ? ` · ${formatBytes(transfer.moved || 0)} / ${formatBytes(transfer.total)} (${transfer.pct || 0}%)` : ''}…`
      : transfer?.phase === 'moving'
        ? `Moving downloaded results · ${formatBytes(transfer.moved || 0)} / ${formatBytes(transfer.total || 0)} (${transfer.pct || 0}%)`
        : transfer?.phase === 'processing'
          ? 'Download verified — processing trajectory health and metrics…'
        : transfer?.phase === 'done' ? 'Download verified complete — every Alpine result file matches its remote size.'
          : transfer?.phase === 'unverified' || transfer?.phase === 'interrupted'
            ? `Download incomplete locally${transfer.total_bytes ? ` · ${formatBytes(transfer.verified_bytes || 0)} / ${formatBytes(transfer.total_bytes)}` : ''}`
              + `${transfer.local_verification_error ? ` · ${transfer.local_verification_error}` : ''}. Retry to resume.` : ''
    _setStatus(statusEl, transferText || masterStatusText(node),
      transfer ? (transfer.phase === 'done' ? _C.ok
        : ['unverified', 'interrupted'].includes(transfer.phase) ? _C.warn : _C.accent)
        : node?.status === 'failed' ? _C.err : node && nodeIsActive(node) ? _C.warn : _C.dim)
    if (allocationEl) {
      const allocation = slurmAllocationText(node)
      allocationEl.textContent = allocation
      allocationEl.style.display = allocation ? '' : 'none'
    }
    // ONE progress bar (below the list): width from the node, colour by status, and the
    // detailed stage/segment text as a hover tooltip.
    if (progressBar) {
      progressBar.style.width = transfer
        ? `${transfer.phase === 'downloading' && !transfer.total ? 100 : ['done', 'processing'].includes(transfer.phase) ? 100 : transfer.pct || 0}%`
        : `${node ? masterProgressPct(node) : 0}%`
      progressBar.style.background = transfer?.phase === 'done' ? _C.ok
        : ['unverified', 'interrupted'].includes(transfer?.phase) ? _C.warn
        : transfer ? 'repeating-linear-gradient(135deg,#4a9eff 0,#4a9eff 8px,#2f6fae 8px,#2f6fae 16px)'
          : node ? masterProgressColor(node) : _C.accent
      progressBar.style.opacity = ['downloading', 'processing'].includes(transfer?.phase) ? '0.65' : '1'
    }
    if (progressWrap) progressWrap.title = transferText || (node ? masterProgressTooltip(node) : '')
    if (detailEl) {
      // oxDNA-only note, gated to the oxDNA tab. Collapse the element when there's nothing to say,
      // so other engines don't get a blank gap under the bar.
      const text = nodeDetailText(node, _activeEngine)
      detailEl.textContent = text
      detailEl.style.display = text ? '' : 'none'
    }
    _renderTimeline(node)
    _renderRunButton()
    _renderActions(node)
    if (endDownloadBtn) {
      const show = canEndAndDownload(node)
      const transferLocked = ['downloading', 'moving', 'processing', 'done'].includes(transfer?.phase)
      endDownloadBtn.style.display = show ? '' : 'none'
      endDownloadBtn.disabled = _busy || transferLocked
      endDownloadBtn.textContent = transfer?.phase === 'done' ? 'Download complete'
        : transfer?.phase === 'processing' ? 'Processing…'
          : ['downloading', 'moving'].includes(transfer?.phase) ? 'Downloading…'
          : transfer ? 'Retry download' : 'End run and download'
      endDownloadBtn.style.opacity = endDownloadBtn.disabled ? '0.5' : '1'
      endDownloadBtn.style.cursor = endDownloadBtn.disabled ? 'not-allowed' : 'pointer'
    }
  }

  // ── consolidated Change directory / Delete (above the jobs card) ───────────
  function _renderActions(node = _selectedNode()) {
    const eng = node?.engine
    const canDelete = !!node && eng !== 'lammps' && node.status !== 'running'
    const canArchive = canDelete && (eng === 'oxdna' || eng === 'namd')
    if (actionsHost) actionsHost.style.display = canDelete ? '' : 'none'
    if (deleteActionBtn) deleteActionBtn.style.display = canDelete ? '' : 'none'
    if (archiveActionBtn) {
      archiveActionBtn.style.display = canArchive ? '' : 'none'
      archiveActionBtn.textContent = 'Change directory'
    }
  }

  // Byte-move progress for an archive/unarchive (rendered here, driven by the engine panel).
  function _setArchiveProgress(st) {
    if (!archiveProgress) return
    if (!st) { archiveProgress.style.display = 'none'; archiveProgress.textContent = ''; return }
    const pct = st.total_bytes ? Math.round((st.moved_bytes / st.total_bytes) * 100) : 0
    archiveProgress.style.display = ''
    archiveProgress.textContent =
      `${formatBytes(st.moved_bytes || 0)} / ${formatBytes(st.total_bytes || 0)} (${pct}%)`
  }

  async function _onArchive() {
    const node = _selectedNode()
    const panel = _panelFor(node)
    if (!panel?.archiveSelected) return
    if (archiveActionBtn) archiveActionBtn.disabled = true
    if (deleteActionBtn) deleteActionBtn.disabled = true
    try {
      await panel.archiveSelected({ onProgress: _setArchiveProgress })
    } finally {
      if (archiveActionBtn) archiveActionBtn.disabled = false
      if (deleteActionBtn) deleteActionBtn.disabled = false
      _setArchiveProgress(null)
      await _fetch()
    }
  }
  async function _onDelete() {
    const node = _selectedNode()
    const panel = _panelFor(node)
    if (!panel?.deleteSelected) return
    const ok = await panel.deleteSelected()
    if (ok) { _sel = { engine: null, id: null }; await _fetch() }
  }
  archiveActionBtn?.addEventListener('click', _onArchive)
  deleteActionBtn?.addEventListener('click', _onDelete)

  // Show the selected engine's stage timeline (relocated to the bottom of the jobs card);
  // hide the others. LAMMPS has no stage timeline.
  function _renderTimeline(node) {
    const eng = node && node.engine !== 'lammps' ? node.engine : null
    let anyShown = false
    for (const [k, el] of Object.entries(_timelineEls)) {
      if (!el) continue
      const show = k === eng
      el.style.display = show ? '' : 'none'
      if (show) anyShown = true
    }
    if (timelineBlock) timelineBlock.style.display = anyShown ? '' : 'none'
  }

  function _runControl() {
    return runControlState(_selectedNode(), {
      verb: verbForNode(_selectedNode()),
      isActive: nodeIsActive,
      isResumable: nodeIsResumable,
      busy: _busy,
    })
  }
  function _renderRunButton() {
    if (!runBtn) return
    // LAMMPS-only: an oxDNA node's Relax/Stop/Resume lives in the oxDNA panel, so a button
    // here too would duplicate it (two "▶ Relax" stacked). An [L] node has no other
    // control, so the master card owns its Stop / re-Run.
    const node = _selectedNode()
    if (!node || node.engine !== 'lammps') { runBtn.style.display = 'none'; return }
    runBtn.style.display = ''
    const rc = _runControl()
    runBtn.textContent = _busy ? 'Working…' : rc.label
    runBtn.disabled = rc.disabled
    runBtn.dataset.runAction = rc.action
  }

  // ── selection ────────────────────────────────────────────────────────────
  function _select(jobId) {
    const node = _nodes.find((n) => n.job_id === jobId)
    if (!node) return
    if (_sel.engine === node.engine && _sel.id === jobId) return
    _sel = { engine: node.engine, id: jobId }
    _renderList()
    _renderMaster()
    _dispatchDetail(node)
  }

  // Clicking the ALREADY-selected row deselects it: the highlight, master card and job
  // actions clear here, and the owning engine panel drops its own selection the same
  // non-destructive way — nothing loaded for that job (trajectory, RMSF/deviation map,
  // relaxed overlay, live stream) is unloaded.  Only selecting a DIFFERENT job does that.
  function _deselect() {
    const node = _selectedNode()
    _sel = { engine: null, id: null }
    _renderList()
    _renderMaster()
    if (!node) return
    // A LAMMPS run is shown in the oxDNA panel's viz card (selectLammpsJob), so its
    // deselection routes there too.
    const panel = { oxdna: oxdnaPanel, lammps: oxdnaPanel, mrdna: mrdnaPanel, cando: candoPanel,
                    snupi: snupiPanel, blade: bladePanel, namd: mdPanel }[node.engine]
    panel?.deselectJob?.()
  }

  // Rich detail dispatch by engine: reveal the selected job's engine tab and light up
  // that panel's own detail/viz via selectJob (identical to a row click on that tab).
  // A LAMMPS run is the CPU fallback for oxDNA (same oxDNA2 bead model), so it shows in
  // the oxDNA panel's OWN viz card via selectLammpsJob — same display/RMSF/deviation/
  // trajectory tools, just a different loader.
  function _dispatchDetail(node) {
    if (node.engine === 'lammps') {
      engineSelector?.select?.('oxdna')
      oxdnaPanel?.selectLammpsJob?.(node)
      return
    }
    const panel = { oxdna: oxdnaPanel, mrdna: mrdnaPanel, cando: candoPanel, snupi: snupiPanel,
                    blade: bladePanel, namd: mdPanel }[node.engine]
    if (!panel) return
    engineSelector?.select?.(node.engine)     // reveal that engine's detail host
    panel?.selectJob?.(node.job_id)
  }

  // ── run / stop / resume (dispatch by node engine) ──────────────────────────
  async function _onRun() {
    if (_busy) return
    const node = _selectedNode()
    const action = _runControl().action
    _busy = true; _renderRunButton()
    try {
      if (action === RUN_ACTION.STOP) await _stop(node)
      else if (action === RUN_ACTION.RESUME) await _resume(node)
      else await _run(node)               // RUN
    } finally {
      _busy = false
      await _fetch()                      // repaint from fresh state
    }
  }
  async function _stop(node) {
    if (!node) return
    const ok = node.engine === 'lammps'
      ? await api.stopLammpsJob(node.job_id)
      : await api.stopOxdnaJob(node.job_id)
    if (!ok) showToast(api.lastErrorMessage?.() || 'Could not stop the run', { severity: 'error' })
  }
  async function _resume(node) {
    if (!node || node.engine !== 'oxdna') return
    await api.startOxdnaJob(node.job_id)
  }
  async function _run(node) {
    // Nothing / an oxDNA job selected → the front-door action is an oxDNA relax (owns
    // the GPU-busy dialog + disk forecast in the oxDNA panel). A LAMMPS job selected →
    // re-launch it directly from its stored params (there's no manual LAMMPS launch UI).
    if (!node || node.engine === 'oxdna') { await oxdnaPanel?.launchRelax?.(); return }
    const payload = buildCreatePayload({
      steps: node.steps, dumpEvery: node.dump_every, temperature: node.temperature,
      salt: node.salt_molar, ranks: node.ranks,
      designSourcePath: node.design_source_path || _currentPath(),
    })
    const job = await api.createLammpsJob(payload)
    if (!job) showToast(api.lastErrorMessage?.() || 'Could not start the LAMMPS run', { severity: 'error' })
    else showToast(`LAMMPS run started (${job.n_atoms} nt)`, { severity: 'ok' })
  }
  runBtn?.addEventListener('click', _onRun)
  async function _pollEndMove(jobId) {
    for (;;) {
      const st = await api.mdArchiveStatus(jobId)
      if (!st) throw new Error(api.lastErrorMessage?.() || 'Could not read transfer progress')
      if (st.state === 'error') throw new Error(st.error || 'Directory move failed')
      const total = Number(st.total_bytes) || 0
      const moved = Number(st.moved_bytes) || 0
      _endTransfers.set(jobId, {
        phase: st.state === 'done' ? 'done' : 'moving', moved, total,
        pct: total > 0 ? Math.min(100, Math.round(moved / total * 100)) : 0,
      })
      _renderMaster()
      if (st.state === 'done') return
      await new Promise((resolve) => setTimeout(resolve, 700))
    }
  }
  function _watchDownloadProgress(jobId) {
    let stopped = false
    void (async () => {
      while (!stopped) {
        try {
          const st = await api.mdDownloadStatus(jobId)
          if (st?.state === 'downloading') {
            const transferred = Number(st.transferred_bytes ?? st.verified_bytes) || 0
            const total = Number(st.total_bytes) || 0
            _endTransfers.set(jobId, {
              phase: 'downloading', moved: transferred, total,
              pct: total > 0 ? Math.min(100, Math.round(transferred / total * 100)) : 0,
            })
            _renderMaster()
          }
        } catch { /* the POST owns the actionable error; polling is advisory */ }
        if (!stopped) await new Promise((resolve) => setTimeout(resolve, 700))
      }
    })()
    return () => { stopped = true }
  }
  endDownloadBtn?.addEventListener('click', async () => {
    const node = _selectedNode()
    if (_busy || node?.engine !== 'namd') return
    const destRoot = getRunDir()
    if (!destRoot) {
      showToast('Choose a storage directory first.', { severity: 'warning' })
      return
    }
    _busy = true
    _endTransfers.set(node.job_id, { phase: 'downloading', pct: 0, moved: 0, total: 0 })
    _renderMaster()
    const stopWatching = _watchDownloadProgress(node.job_id)
    try {
      const result = await api.finishMdJob(node.job_id, destRoot)
      await stopWatching()
      if (!result) throw new Error(api.lastErrorMessage?.() || 'Transfer could not be started')
      if (result.verified !== true) throw new Error('Server did not verify the downloaded files')
      if (result.action === 'archive') await _pollEndMove(node.job_id)
      else {
        _endTransfers.set(node.job_id, { phase: 'done', pct: 100, moved: 0, total: 0 })
        _renderMaster()
      }
      showToast('Run ended and results downloaded.', { severity: 'ok' })
      await _fetch()
    } catch (err) {
      await stopWatching()
      _endTransfers.delete(node.job_id) // unlock retry after a genuine failure
      showToast(err.message, { severity: 'error' })
    } finally {
      await stopWatching()
      _busy = false; _renderMaster()
    }
  })

  // ── fetch + poll ──────────────────────────────────────────────────────────
  async function _fetch() {
    const nodes = await api.listSimJobs(_currentPath(), false).catch(() => null)
    _nodes = Array.isArray(nodes) ? nodes : []
    if (_sel.id && !_selectedNode()) _sel = { engine: null, id: null }   // selection vanished
    _renderList()
    _renderMaster()
    _schedulePoll()
  }
  function _schedulePoll() {
    if (_pollTimer) { clearTimeout(_pollTimer); _pollTimer = null }
    const bodyVisible = document.getElementById('simulate-body')?.style.display !== 'none'
    if (_dynamicsActive && bodyVisible && _nodes.some(nodeNeedsPolling)) {
      _pollTimer = setTimeout(_fetch, POLL_MS)
    }
  }

  // ── lifecycle ─────────────────────────────────────────────────────────────
  window.addEventListener('nadoc:left-tab-change', (e) => {
    _dynamicsActive = e.detail?.activeTab === 'dynamics'
    if (_dynamicsActive) _fetch()
    else if (_pollTimer) { clearTimeout(_pollTimer); _pollTimer = null }
  })
  // A design edit / feature-log seek re-evaluates staleness + list membership.
  window.addEventListener('nadoc:design-changed', () => _fetch())
  // A design switch re-filters the list + drops any selection/overlay (keyed to the old design).
  window.addEventListener('nadoc:workspace-path-change', () => {
    _sel = { engine: null, id: null }
    _fetch()
  })
  // A job launched / stopped / resumed from an engine panel (each polls its OWN hidden
  // list) must WAKE the master: its poll re-arms only while it already has an active
  // node, so a launch made while the master is idle would otherwise not surface until a
  // manual refresh. _fetch() picks up the new job AND re-arms the poll from there.
  window.addEventListener('nadoc:sim-jobs-changed', () => _fetch())

  // ── engine scope: filter to the active tab + "Show all job types" toggle ───
  function _engineTabName() {
    return { oxdna: 'oxDNA', mrdna: 'mrDNA', cando: 'CanDo', snupi: 'SNUPI', blade: 'BLADE',
             namd: 'NAMD' }[_activeEngine] || _activeEngine
  }
  function _updateEngineLabel() {
    if (engineLabel) engineLabel.textContent = _showAllTypes ? '· all engines' : `· ${_engineTabName()}`
  }
  /** Called by the engine selector's onSelect (main.js): the list re-scopes to the
   *  newly-active tab. No-op refetch — the same design's nodes are re-filtered client-side.
   *  Switching to a different engine tab also drops a selection that belongs to the OLD
   *  engine (a NAMD job selected, then the SNUPI tab clicked): the master card — status,
   *  progress bar, stage timeline, detail, run/archive buttons — is shared across engines,
   *  so clearing the selection + re-rendering it prevents the previous engine's stages from
   *  lingering under the new tab. In "show all job types" mode every run stays visible, so
   *  the selection (still highlighted in the list) is preserved. */
  function setActiveEngine(engine) {
    if (!engine || engine === _activeEngine) return
    _activeEngine = engine
    _updateEngineLabel()
    if (_sel.id && !_visibleNodes().some((n) => n.engine === _sel.engine && n.job_id === _sel.id)) {
      _sel = { engine: null, id: null }
    }
    // ALWAYS re-render the master block on a tab switch, not only when the selection was cleared:
    // in "show all job types" mode the selection SURVIVES the switch, and the detail note is gated on
    // the active tab (oxDNA-only) — without this it would linger under another engine's panel.
    _renderMaster()
    _renderList()
  }
  showAllToggle?.addEventListener('change', () => {
    _showAllTypes = !!showAllToggle.checked
    _updateEngineLabel()
    _renderList()
  })

  // ── collapsible "Jobs" card (persisted per Dynamics tab) ───────────────────
  function _applyCollapsed(collapsed) {
    if (cardBody) cardBody.style.display = collapsed ? 'none' : ''
    if (cardArrow) cardArrow.classList.toggle('is-collapsed', collapsed)
  }
  let _collapsed = getSectionCollapsed('dynamics', 'simulate-jobs', false)
  _applyCollapsed(_collapsed)
  _updateEngineLabel()
  cardHeader?.addEventListener('click', () => {
    _collapsed = !_collapsed
    setSectionCollapsed('dynamics', 'simulate-jobs', _collapsed)
    _applyCollapsed(_collapsed)
  })

  function refresh() { return _fetch() }
  function selectJob(jobId) { return _select(jobId) }

  // Initial populate deferred a tick so late-declared main.js deps (workspace path) exist.
  queueMicrotask(_fetch)

  return { refresh, selectJob, setActiveEngine, getSelected: () => ({ ..._sel }) }
}
