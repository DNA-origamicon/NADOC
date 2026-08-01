/**
 * BLADE jobs panel — launch + monitor a box-free implicit-solvent atomistic relax on the
 * currently-loaded design.
 *
 * Structurally the sibling of snupi_jobs_panel.js (one flat job per run, same shared job-list
 * base, same Run/Stop/Delete), but BLADE differs from the FEM engines in three ways that shape
 * this module:
 *
 *   • The compute is EXTERNAL — OpenMM in the micromamba `gpu` env via a detached worker — so
 *     there IS an availability gate (`GET /blade/available`), and it can legitimately say no.
 *   • Progress is REAL, streamed out of the OpenMM process (minimize occupies the first 25 %,
 *     the Langevin leg the rest), not a wall-clock guess.
 *   • There is ONE protocol (relax), so one Run button — no Coarse/Fine pair.
 *
 * REST-poll based (no WebSocket), exactly like the CanDo/mrDNA/oxDNA panels: while a job is
 * queued/running the panel polls GET /blade/jobs + /blade/jobs/{id}/progress.
 *
 * Deliberately NO Anchors / E-field cards: a relax is unrestrained and box-free, so those
 * controls would be inert (see engine_capabilities.js → blade, which marks them off-with-a-
 * reason rather than hiding them).
 *
 * The relaxed shape is Physical-layer / display-only. A completed job exposes two mutually-
 * exclusive display modes via the bladeDisplay dep: Relaxed shape (deform) and Trajectory
 * (animate the relaxation). There is no flexibility/deviation/cylinder mode — those are FEM
 * products (an NMA basis, an intended-shape comparison) a relax simply does not produce.
 *
 * Factory: initBladeJobsPanel({ bladeDisplay, getWorkspacePath }) →
 * { refresh, getSelectedJob, selectJob, deleteSelected }.  All cohesive logic lives here
 * (module-first law); main.js only imports + inits + does thin wiring.
 */

import { initJobsPanelBase } from './jobs_panel_base.js'
import { showToast } from './toast.js'
import { filterJobsForPart } from './md_jobs_panel.js'
import { buildJobListModel, jobListSignature } from './jobs_panel_model.js'
import { renderJobList } from './jobs_panel_render.js'
import { formatJobTime } from '../scene/trajectory_range.js'
import { confirmNoConcurrentJob } from './job_activity.js'
import { initBladeMetricsCard } from './blade_metrics_card.js'
import * as api from '../api/client.js'

const POLL_MS = 1500

const _C = { ok: '#5cb85c', warn: '#e0a800', err: '#d9534f', accent: '#4a9eff', dim: '#8a8a8a' }

// ── Pure helpers (unit-tested) ────────────────────────────────────────────────

/** Overall progress % string for a job + progress payload. */
export function formatProgress(job, progress) {
  if (!job) return ''
  if (job.status === 'completed') return '100%'
  if (['failed', 'stopped'].includes(job.status)) return ''
  const f = progress?.overall
  if (typeof f === 'number' && f > 0) return `${Math.round(f * 100)}%`
  if (job.status === 'running') return '…'
  return ''
}

/** Display name for a job: source-path stem, else the recorded design name. */
export function jobDisplayName(job) {
  if (!job) return ''
  const src = job.design_source_path
  if (src) {
    const stem = String(src).split('/').pop().replace(/\.[^.]+$/, '')
    if (stem) return stem
  }
  return job.design_name || 'design'
}

/** Is the job in an in-progress state (spinner / keep-polling)? */
export function bladeJobIsActive(job) {
  return ['queued', 'preparing', 'running'].includes(job?.status)
}

/**
 * Should a new launch be blocked (pure; unit-tested)?  True while a launch is mid-flight
 * (``launching``) or ANY BLADE job is still active.  Enforces one-relax-at-a-time and
 * swallows Run double-clicks.
 *
 * This is separate from ``confirmNoConcurrentJob`` (which knows MD/oxDNA jobs) and from the
 * backend sim guard (which refuses a CUDA relax while a heavy production sim owns the card).
 * Three gates, three different questions: this one is only "is BLADE already busy".
 */
export function launchBlocked(launching, jobs, selectedJob) {
  if (launching) return true
  if (Array.isArray(jobs) && jobs.some(bladeJobIsActive)) return true
  return bladeJobIsActive(selectedJob)
}

/**
 * The BLADE job a Stop button would act on: the one in flight, if any.
 *
 * The Stop button is ALWAYS rendered (under the run buttons) so the panel never reflows when a run
 * starts — it is merely disabled when this returns null. It targets the ACTIVE job rather than the
 * selected one: a freshly-launched run is what you want to stop, even if you have since clicked an
 * older completed run in the list.
 */
export function runningJob(jobs) {
  return (Array.isArray(jobs) ? jobs : []).find(bladeJobIsActive) || null
}

/** Can this job seed a NAMD run? Only a COMPLETED relax has a relaxed.pdb to hand off. */
export function seedReady(job) {
  return job?.status === 'completed'
}

/** Human name for the force model a job ran with. */
export function correctionLabel(job) {
  return job?.correction === 'unified' ? 'CHARMM+OBC2 + learned correction' : 'CHARMM+OBC2'
}

/** Human name for the run mode. Only 'relax' is implemented; seed_namd is reserved. */
export function modeLabel(job) {
  return job?.mode === 'seed_namd' ? 'Seed NAMD' : 'Relax'
}

/**
 * Fine detail for a running relax: the phase and its step counter, rendered as a second line
 * under the status.
 *
 * This is load-bearing for BLADE in a way it isn't for a fast FEM solve. A 40k-atom origami
 * relax runs for minutes inside a process the server can't see into, so without the streamed
 * step counter there is no way to tell a grinding run from a wedged one. The phase name also
 * explains the one legitimately slow, step-less stretch: `build` is psfgen constructing the
 * CHARMM topology, which on a large design is a minute of apparently-frozen progress.
 */
export function solveDetailText(progress) {
  if (!progress) return ''
  const bits = []
  const { step, n_steps: nSteps, steps_per_s: rate, platform_used: platform } = progress
  if (typeof step === 'number' && nSteps) {
    bits.push(`step ${step.toLocaleString()}/${nSteps.toLocaleString()}`)
  }
  if (rate) bits.push(`${Math.round(rate).toLocaleString()} steps/s`)
  // A CUDA request that fell back to CPU is a ~20x slowdown, not a detail — surface it live
  // rather than letting the user wonder why a 72 s run is still going after 20 minutes.
  if (platform === 'CPU') bits.push('on CPU (~20x slower than CUDA)')
  return bits.length ? `\n${bits.join(' · ')}` : ''
}

/** Human status line for the detail block. */
export function detailStatusText(job, progress) {
  if (!job) return ''
  switch (job.status) {
    case 'queued':
      // A queued job with an error is the sim-guard refusal: prepared and valid, but not started
      // because a heavy sim owns the GPU. Say that, rather than a bare "Queued".
      return job.error ? `Not started — ${job.error}` : 'Queued — preparing to relax.'
    case 'preparing': return 'Writing the design snapshot…'
    case 'running': {
      const pct = formatProgress(job, progress)
      const eta = progress?.eta_seconds
      const etaStr = (typeof eta === 'number' && eta > 0) ? ` · ~${Math.ceil(eta)}s left` : ''
      const phase = progress?.phase ? ` · ${progress.phase}` : ''
      const head = `Relaxing (${correctionLabel(job)}) ${pct}${etaStr}${phase}`
      return `${head}${solveDetailText(progress)}`
    }
    case 'completed': {
      const s = job.sim_seconds ? ` in ${job.sim_seconds}s` : ''
      const n = job.n_atoms ? ` · ${job.n_atoms.toLocaleString()} atoms` : ''
      const p = job.platform_used ? ` · ${job.platform_used}` : ''
      return `Relaxed (${correctionLabel(job)})${s}${n}${p}.`
    }
    case 'stopped': return 'Stopped.'
    case 'failed':  return `Failed: ${job.error || 'see error log'}`
    default:        return job.status || ''
  }
}

/** Timeline glyph for the job's two stages (build → relax). */
export function stageChip(job) {
  const glyph = (st) => st === 'done' ? '●' : st === 'failed' ? '✗' : st === 'running' ? '◐' : '○'
  const stages = job?.stages?.length ? job.stages : [{ name: 'relax', status: undefined }]
  return stages.map((s) => `${glyph(s.status)} ${s.name}`).join('  ')
}

/**
 * Completed-job summary HTML (force model / atom count / how far it moved).  Pure
 * (unit-tested); returns an HTML string the panel drops into the summary div, or '' when
 * there's nothing to show (job not completed).
 *
 * rmsd_moved is the headline number: it is how far the structure travelled from idealized
 * B-DNA, i.e. how much the relax actually did. Rg before/after is the collapse/straighten tell
 * — a large drop means the structure compacted, which on an origami usually means something
 * went wrong rather than that it equilibrated.
 */
export function formatSummary(job) {
  if (!job || job.status !== 'completed') return ''
  const bits = [`<b>${correctionLabel(job)}</b>`]
  if (job.n_atoms) bits.push(`${job.n_atoms.toLocaleString()} atoms`)
  if (typeof job.rmsd_moved_A === 'number') bits.push(`moved ${job.rmsd_moved_A.toFixed(2)} Å RMSD`)
  if (typeof job.rg_before_A === 'number' && typeof job.rg_after_A === 'number') {
    bits.push(`Rg ${job.rg_before_A.toFixed(1)} → ${job.rg_after_A.toFixed(1)} Å`)
  }
  if (job.platform_used) bits.push(job.platform_used)
  return bits.join(' · ')
}

// ── Factory ───────────────────────────────────────────────────────────────────

export function initBladeJobsPanel({ bladeDisplay = null, getWorkspacePath = null, getSelection = null } = {}) {
  const $ = (id) => document.getElementById(id)
  const panel = $('blade-jobs-panel')
  const heading = $('blade-jobs-heading')
  const body = $('blade-jobs-body')
  if (!panel || !body) return { refresh: () => {}, getSelectedJob: () => null, selectJob: () => {}, deleteSelected: () => false }

  const arrow = $('blade-jobs-arrow')
  const runBtn = $('blade-jobs-run-btn')
  const availStatus = $('blade-jobs-status')
  const advToggle = $('blade-jobs-adv-toggle')
  const advArrow = $('blade-jobs-adv-arrow')
  const advBody = $('blade-jobs-adv-body')
  const displayToggle = $('blade-display-toggle')
  const displayArrow = $('blade-display-arrow')
  const displayCard = $('blade-display-card')
  const correctionSelect = $('blade-jobs-correction')
  const minimizeInput = $('blade-jobs-minimize-iters')
  const langevinInput = $('blade-jobs-langevin-ps')
  const cutoffInput = $('blade-jobs-cutoff')
  const tempInput = $('blade-jobs-temp')
  const trajFramesInput = $('blade-jobs-traj-frames')
  const platformSelect = $('blade-jobs-platform')
  const showAll = $('blade-jobs-show-all')
  const listEl = $('blade-jobs-list')
  const detail = $('blade-jobs-detail')
  const detailStatus = $('blade-jobs-detail-status')
  const timeline = $('blade-jobs-timeline')
  const summaryEl = $('blade-jobs-summary')
  const detailError = $('blade-jobs-detail-error')
  const stopBtn = $('blade-jobs-stop-btn')
  const seedBtn = $('blade-jobs-seed-btn')
  const seedStatus = $('blade-jobs-seed-status')
  const displayStatus = $('blade-jobs-display-status')
  const modeRadios = () => Array.from(panel.querySelectorAll('.blade-display-mode'))
  const checkedMode = () => modeRadios().find((r) => r.checked)?.value || 'off'
  const setMode = (value) => modeRadios().forEach((r) => { r.checked = r.value === value })

  let _jobs = []
  let _selectedId = null
  let _progress = null
  let _launching = false   // re-entrancy guard
  let _seeding = false     // NAMD-seed handoff in flight
  let _listSig = null
  const _legend = { el: null }

  const _selectedJob = () => _jobs.find((j) => j.job_id === _selectedId) || null

  // Canonical job-list model + renderer (converges to the oxDNA look). BLADE jobs are flat
  // (no parent/child tree); the run mode rides the leading-tag slot.
  function _rowCtx() {
    return {
      engine: 'blade',
      selectedId: _selectedId,
      hierarchical: false,
      displayName: jobDisplayName,
      isActive: bladeJobIsActive,
      formatTime: formatJobTime,
      tags: (job) => [{
        text: modeLabel(job), color: _C.dim,
        title: `${modeLabel(job)} · ${correctionLabel(job)}`,
      }],
      rowSig: (j) => `${j.job_id}:${j.status}:${j.mode || 'relax'}:${j.correction || 'baseline'}`,
      colors: { dim: _C.dim, warn: _C.warn },
    }
  }

  // Graphs & Metrics card — a child module reading the panel's job selection.
  const _metricsCard = initBladeMetricsCard({ getSelectedJob: _selectedJob })

  // NO Anchors / E-field cards here, unlike the FEM panels: a BLADE relax is unrestrained
  // (no Dirichlet BC) and box-free (no body-force term), so those controls would be inert.
  // engine_capabilities.js marks them off-with-a-reason so the unified stack can grey them
  // with a tooltip rather than silently omit them.

  // ── Shared scaffold: collapse + advanced drawer + poll loop ────────────────────
  const _base = initJobsPanelBase({
    section: 'blade-jobs-panel',
    els: { heading, body, arrow, advToggle, advArrow, advBody },
    pollMs: POLL_MS,
    collapsible: false,   // engine header is a static label; Simulate owns the collapse
    hasActive: () => _hasActiveJob(),
    tick: () => _fetchJobs(),
    onOpen: () => _onOpen(),
  })
  // Display card (the mutually-exclusive viz-mode radios) — collapsible, starts open.
  if (displayToggle) {
    displayToggle.addEventListener('click', () => {
      const hidden = displayCard.style.display === 'none'
      displayCard.style.display = hidden ? '' : 'none'
      if (displayArrow) displayArrow.textContent = hidden ? '▾' : '▸'
    })
  }

  // ── Availability gate ─────────────────────────────────────────────────────────
  // BLADE needs an OpenMM env + psfgen, neither of which ships with NADOC. A missing env is an
  // EXPECTED state, so say so on the status line and disable Run — rather than letting the user
  // click Run and get a 503 they have to decode. Probed once per tab open (it spawns an
  // interpreter, so it is not cheap enough to poll).
  let _available = null   // null = not probed yet; {available, reason}
  async function _checkAvailability() {
    _available = await api.bladeAvailable()
    if (availStatus) {
      const ok = !!_available?.available
      availStatus.style.color = ok ? '#8b949e' : '#e0a800'
      availStatus.textContent = ok
        ? `OpenMM ready — ${_available.reason || ''}`
        : `⚠ ${_available?.reason || 'BLADE is not available on this machine.'}`
    }
    _updateLaunchButtons()
  }

  // ── Run (one protocol: relax) ─────────────────────────────────────────────────
  function _updateLaunchButtons() {
    // Unavailable blocks Run just as hard as a busy engine does, but for a different reason —
    // keep the two distinguishable in the tooltip so the fix is obvious.
    const busy = launchBlocked(_launching, _jobs, _selectedJob())
    const unavailable = _available !== null && !_available.available
    const blocked = busy || unavailable
    if (runBtn) {
      runBtn.disabled = blocked
      runBtn.style.cursor = blocked ? 'not-allowed' : 'pointer'
      runBtn.style.opacity = blocked ? '0.5' : '1'
      runBtn.title = unavailable
        ? (_available?.reason || 'BLADE is not available on this machine.')
        : busy
          ? 'A BLADE relax is already running.'
          : 'Relax the design with BLADE — CHARMM36 + OBC2 implicit solvent in OpenMM.'
    }
    _syncStopBtn()
  }

  /** Stop is always present under the Run button; greyed out (disabled) until a run is in
   *  flight. The :disabled styling lives in index.html so the two states can't drift apart. */
  function _syncStopBtn() {
    if (!stopBtn) return
    stopBtn.disabled = !runningJob(_jobs)
  }

  const _num = (el, dflt) => {
    const v = parseFloat(el?.value)
    return Number.isFinite(v) ? v : dflt
  }

  async function _launch() {
    if (launchBlocked(_launching, _jobs, _selectedJob())) return
    _launching = true
    _updateLaunchButtons()
    try {
      if (!(await confirmNoConcurrentJob())) return
      const body_ = {
        mode: 'relax',
        correction: correctionSelect?.value === 'unified' ? 'unified' : 'baseline',
        minimize_iters: Math.max(0, Math.round(_num(minimizeInput, 400))),
        langevin_ps: Math.max(0.1, _num(langevinInput, 3)),
        nb_cutoff_A: _num(cutoffInput, 18),
        temp_K: _num(tempInput, 300),
        traj_frames: Math.max(0, Math.round(_num(trajFramesInput, 60))),
        platform: platformSelect?.value === 'CPU' ? 'CPU' : 'CUDA',
        autostart: true,
        design_source_path: getWorkspacePath?.() || null,
      }
      const job = await api.createBladeJob(body_)
      if (!job) {
        showToast(api.lastErrorMessage() || 'Failed to start BLADE relax', { severity: 'error' })
        return
      }
      _selectedId = job.job_id
      await _fetchJobs()
      // The backend leaves a sim-guard-refused job QUEUED with the reason on it rather than
      // failing it — surface that here, or a Run click looks like it silently did nothing.
      if (job.status === 'queued' && job.error) {
        showToast(job.error, { severity: 'warn' })
      }
    } finally {
      _launching = false
      _updateLaunchButtons()
    }
  }
  runBtn?.addEventListener('click', () => _launch())

  // ── Jobs list + poll ────────────────────────────────────────────────────────
  async function _fetchJobs() {
    const all = await api.listBladeJobs()
    if (!Array.isArray(all)) return
    _jobs = filterJobsForPart(all, getWorkspacePath?.() || null, showAll?.checked)
    _renderList()
    _updateLaunchButtons()
    if (_selectedId) {
      _progress = await api.getBladeProgress(_selectedId)
      const job = _selectedJob()
      // Live-follow: re-apply the active display mode when a running job completes.
      if (job && job.status === 'completed' && bladeDisplay?.deformActive?.()
          && bladeDisplay.deformJobId?.() === _selectedId) {
        await bladeDisplay.refresh?.()
      }
      _renderDetail()
    }
    _notifyIfJobsChanged()
    _base.schedulePoll()
  }

  // Wake the master job list + progress bar (simulate_jobs.js) whenever THIS panel's job
  // set/statuses change — the idle-wake contract (the master self-polls only while it
  // already holds an active node).
  let _prevJobsSig = null
  function _notifyIfJobsChanged() {
    const sig = _jobs.map(j => `${j.job_id}:${j.status}`).sort().join('|')
    if (_prevJobsSig !== null && sig !== _prevJobsSig) {
      window.dispatchEvent(new CustomEvent('nadoc:sim-jobs-changed'))
    }
    _prevJobsSig = sig
  }

  function _hasActiveJob() {
    return launchBlocked(false, _jobs, _selectedJob())
  }

  function _renderList() {
    if (!listEl) return
    const ctx = _rowCtx()
    const sig = jobListSignature(_jobs, ctx)
    if (sig === _listSig && listEl.childElementCount > 0) return
    _listSig = sig
    renderJobList(listEl, buildJobListModel(_jobs, ctx), {
      onClick: (jobId) => (jobId === _selectedId ? _deselectJob() : _selectJob(jobId)),
      emptyText: 'No BLADE relax jobs for this design yet.',
      dimColor: _C.dim,
      legendState: _legend,
    })
  }

  async function _selectJob(jobId) {
    _selectedId = jobId
    _progress = await api.getBladeProgress(jobId)
    _renderList()
    _renderDetail()
    await _retargetDisplayToSelection()
    _base.schedulePoll()
  }

  /** Clicking the ALREADY-selected row deselects it: the highlight + detail clear, but the
   *  relaxed-shape / trajectory overlay stays on screen and bladeDisplay keeps its loaded
   *  data (deselecting never discards cached visualization — only selecting a DIFFERENT job
   *  retargets it, via `_retargetDisplayToSelection`, deliberately not called here). */
  function _deselectJob() {
    _selectedId = null
    _progress = null
    _renderList()
    _renderDetail()
    _base.schedulePoll()
  }

  /** When a display mode is active and the user selects a DIFFERENT job, retarget the
   *  active mode to the newly-selected job. */
  async function _retargetDisplayToSelection() {
    if (!bladeDisplay?.deformActive?.()) return
    if (bladeDisplay.deformJobId?.() === _selectedId) return
    const mode = checkedMode()
    const job = _selectedJob()
    const canShow = mode !== 'off' && job?.status === 'completed'
    if (!canShow) {
      bladeDisplay.stopDeform?.(); setMode('off'); _syncDisplayStatus()
      return
    }
    const r = await bladeDisplay[_MODE_FNS[mode]]?.(_selectedId)
    if (!r?.ok) { bladeDisplay.stopDeform?.(); setMode('off') }
    _syncDisplayStatus()
  }

  function _renderDetail() {
    const job = _selectedJob()
    _syncDisplayModes()
    if (!detail) return
    if (!job) { detail.style.display = 'none'; _syncDisplayStatus(); return }
    detail.style.display = ''
    if (detailStatus) detailStatus.textContent = detailStatusText(job, _progress)
    if (timeline) timeline.textContent = stageChip(job)
    if (summaryEl) {
      const html = formatSummary(job)
      summaryEl.style.display = html ? '' : 'none'
      summaryEl.innerHTML = html
    }
    // NO progress bar here: the one bar lives in the unified Jobs card, fed by the live
    // `progress_fraction` this engine stamps on running jobs. See index.html.
    if (detailError) {
      detailError.style.display = job.status === 'failed' ? '' : 'none'
      detailError.textContent = job.status === 'failed' ? (job.error || 'Relax failed.') : ''
    }
    _syncStopBtn()
    _syncSeedBtn(job)
    _syncDisplayStatus()
    _metricsCard?.sync()
  }

  /** Enable "Use as NAMD seed" only for a completed relax (a relaxed.pdb exists to hand off).
   *  Mirrors the oxDNA/mrDNA seed-button enable/style idiom. */
  function _syncSeedBtn(job) {
    if (!seedBtn || _seeding) return
    const ok = seedReady(job)
    seedBtn.disabled = !ok
    seedBtn.style.cursor = ok ? 'pointer' : 'not-allowed'
    seedBtn.style.background = ok ? '#21262d' : '#122117'
    seedBtn.style.color = ok ? '#c9d1d9' : '#484f58'
  }

  function _setSeedStatus(text, color) {
    if (seedStatus) { seedStatus.textContent = text; seedStatus.style.color = color || '#8b949e' }
  }

  /** Gate the always-visible Display card's radios: enabled only for a completed job.
   *  Trajectory additionally needs frames — a job run with traj_frames=0 kept only the settled
   *  structure, so the player would have nothing to scrub. */
  function _syncDisplayModes() {
    const job = _selectedJob()
    const ready = job?.status === 'completed'
    // Deselecting leaves the previous job's overlay up (cached, not cleared), so "Off"
    // stays clickable with nothing selected — otherwise it could only be taken down by
    // re-selecting the job first.
    const overlayUp = !!bladeDisplay?.deformActive?.()
    modeRadios().forEach((r) => {
      if (r.value === 'off') { r.disabled = !bladeDisplay || (!ready && !overlayUp); return }
      const needsTraj = r.value === 'trajectory'
      r.disabled = !ready || !bladeDisplay || (needsTraj && !job?.traj_frames)
    })
  }

  /** Readout under the radios: what the active mode is showing. */
  function _syncDisplayStatus() {
    if (!displayStatus) return
    const mode = bladeDisplay?.mode?.()
    if (!mode) { displayStatus.textContent = ''; return }
    const s = bladeDisplay?.lastStats?.()
    if (mode === 'trajectory' && s?.kind === 'trajectory') {
      displayStatus.textContent = `Relaxation trajectory — ${s.frames} frames`
    } else {
      displayStatus.textContent = 'Showing the relaxed (settled) shape.'
    }
  }

  // ── Control buttons ───────────────────────────────────────────────────────────
  if (stopBtn) {
    stopBtn.addEventListener('click', async () => {
      // Stop the job that is actually IN FLIGHT, not merely the selected one — you may have clicked
      // an older completed run in the list while the new one is still solving.
      const job = runningJob(_jobs)
      if (!job) return
      await api.stopBladeJob(job.job_id)
      await _fetchJobs()
    })
  }

  // ── Use as NAMD seed ──────────────────────────────────────────────────────────
  // Hand the relaxed structure to the NAMD engine: create a NAMD DRAFT seeded from the
  // EXACT relaxed all-atom coordinates (blade_job_id), so the user sets salt/protocol in the
  // NAMD tab and presses "Relax from BLADE" to solvate + run. Fires the same events oxDNA/mrDNA
  // do, so main.js flips to the NAMD tab and md_jobs_panel selects the new draft — no
  // navigation code needed here. The link is provenance (seed_blade_job_id), not tree nesting:
  // cross-engine parent/child isn't supported, so the NAMD run is its own root row.
  if (seedBtn) {
    seedBtn.addEventListener('click', async () => {
      const job = _selectedJob()
      if (!job || seedBtn.disabled || _seeding || !seedReady(job)) return
      if (!(await confirmNoConcurrentJob())) return
      _seeding = true
      seedBtn.disabled = true
      _setSeedStatus('Creating NAMD draft…', '#4a9eff')
      const created = await api.createMdJob({
        blade_job_id: job.job_id,
        design_source_path: job.design_source_path || getWorkspacePath?.() || null,
        draft: true,
        autostart: true,   // remembered on the draft → "Relax from BLADE" runs it
      })
      _seeding = false
      if (created?.job_id && created.status !== 'failed') {
        _setSeedStatus('NAMD draft created — set options + "Relax from BLADE" in the NAMD tab.', '#5cb85c')
        showToast('NAMD draft created — configure it, then Relax from BLADE', { severity: 'ok' })
        window.dispatchEvent(new CustomEvent('nadoc:md-job-created', { detail: { jobId: created.job_id } }))
        window.dispatchEvent(new CustomEvent('nadoc:sim-jobs-changed'))
      } else {
        _setSeedStatus(created?.error || api.lastErrorMessage() || 'Failed to create NAMD seed', '#d9534f')
      }
      _syncSeedBtn(_selectedJob())
    })
  }
  // Delete the selected BLADE job. Invoked by the consolidated #simulate-job-actions
  // Delete button (dispatched by the master card on the selected node).
  async function deleteSelected() {
    if (!_selectedId) return false
    const r = await api.deleteBladeJob(_selectedId)
    if (r?.ok) {
      if (bladeDisplay?.deformJobId?.() === _selectedId) bladeDisplay.stopDeform?.()
      _selectedId = null
      detail && (detail.style.display = 'none')
      await _fetchJobs()
      return true
    }
    showToast(api.lastErrorMessage() || 'Delete failed', { severity: 'error' })
    return false
  }

  // ── Display-mode radios (Off / Relaxed shape / Trajectory) ──
  const _MODE_FNS = { deform: 'showDeform', trajectory: 'showTrajectory' }
  async function _onModeChange() {
    if (!bladeDisplay) { setMode('off'); return }
    const mode = checkedMode()
    if (mode !== 'trajectory') bladeDisplay.stopTrajectory?.()   // leaving the player → halt the loop
    if (mode === 'off') { bladeDisplay.stopDeform?.(); _syncDisplayStatus(); return }
    if (!_selectedId) { setMode('off'); return }
    const r = await bladeDisplay[_MODE_FNS[mode]]?.(_selectedId)
    if (!r?.ok) {
      setMode('off'); bladeDisplay.stopDeform?.()
      showToast(mode === 'trajectory'
        ? 'No trajectory for this run — relaunch with Advanced ▸ Trajectory frames above 0'
        : 'Relaxed positions not ready', { severity: 'warn' })
    }
    _syncDisplayStatus()
  }
  modeRadios().forEach((r) => r.addEventListener('change', _onModeChange))
  if (showAll) showAll.addEventListener('change', _fetchJobs)

  // ── Cross-panel coordination ──────────────────────────────────────────────────
  function _stopDisplays() {
    bladeDisplay?.stopAndRestore?.()
    setMode('off')
    _syncDisplayStatus()
    _metricsCard?.refresh()
  }
  window.addEventListener('nadoc:left-tab-change', (e) => {
    if (e.detail?.from === 'dynamics') _stopDisplays()
  })
  window.addEventListener('nadoc:design-changed', () => { _stopDisplays() })
  window.addEventListener('nadoc:workspace-path-change', () => { _selectedId = null; _fetchJobs() })

  // ── Open ──────────────────────────────────────────────────────────────────────
  function _onOpen() {
    // Probe availability once per open (it spawns an interpreter — too slow to poll).
    if (_available === null) _checkAvailability()
    _fetchJobs()
  }

  _base.initCollapsed(true)

  // selectJob: highlight + populate this panel's detail as a row click does — used by
  // the unified Simulate list to route a BLADE node's selection here.
  async function selectJob(jobId) {
    if (!jobId) return
    if (!_jobs.find((j) => j.job_id === jobId)) await _fetchJobs()
    return _selectJob(jobId)
  }
  return { refresh: _fetchJobs, getSelectedJob: _selectedJob, selectJob, deleteSelected,
           // Drop the selection without touching the display (the unified Simulate list
           // routes its own click-the-selected-row-to-deselect here).
           deselectJob: _deselectJob }
}
