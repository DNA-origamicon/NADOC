/**
 * SNUPI FEM jobs panel — launch + monitor a native SNUPI shape prediction on the
 * currently-loaded design.  Sibling of cando_jobs_panel.js: SNUPI is the SAME in-process
 * FEM (scipy — no GPU, no external simulator), run with the anisotropic SNUPI material
 * law (validated ≥ CanDo vs MD at $0), so there is no availability gate and no seed
 * handoff.  Two run modes:
 *
 *   • "Coarse" → the LINEAR solve (fast, interactive preview).
 *   • "Fine"   → the geometrically-NONLINEAR corotational solve (~1 min).
 *
 * REST-poll based (no WebSocket), exactly like the CanDo/mrDNA/oxDNA panels: while a job
 * is queued/running the panel polls GET /snupi/jobs + /snupi/jobs/{id}/progress.
 *
 * The predicted shape is Physical-layer / display-only.  A completed job exposes four
 * mutually-exclusive display modes via the snupiDisplay dep: Predicted shape (deform),
 * Flexibility map (RMSF), Deviation from design (RMSD), and CanDo-style cylinders.
 *
 * Advanced knobs: Load steps + Compute RMSF (as CanDo) plus a MATERIAL selector — SNUPI
 * (anisotropic + couplings + compliant crossovers) vs CanDo (isotropic baseline, for an
 * in-tab A/B comparison against the same solver).
 *
 * Factory: initSnupiJobsPanel({ snupiDisplay, getWorkspacePath, getSelection }) →
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
import { initSnupiMetricsCard } from './snupi_metrics_card.js'
import { initForcesCard } from './forces_card.js'
import { initOxdnaAnchorsSetup } from './oxdna_anchors_setup.js'
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
export function snupiJobIsActive(job) {
  return ['queued', 'preparing', 'running'].includes(job?.status)
}

/**
 * Should a new FEM launch be blocked (pure; unit-tested)?  True while a launch is
 * mid-flight (``launching``) or ANY SNUPI FEM job is still active — the FEM runs
 * in-process, so ``confirmNoConcurrentJob`` (which only knows MD/oxDNA jobs) can't gate
 * it.  Enforces one-solve-at-a-time and swallows Coarse/Fine double-clicks.
 */
export function launchBlocked(launching, jobs, selectedJob) {
  if (launching) return true
  if (Array.isArray(jobs) && jobs.some(snupiJobIsActive)) return true
  return snupiJobIsActive(selectedJob)
}

/** Human name for the material law of a job. */
export function materialLabel(job) {
  return job?.material === 'cando' ? 'CanDo (isotropic)' : 'SNUPI'
}

/** Human name for the solver mode of a job. */
export function solverLabel(job) {
  if (job?.dynamics) return job?.hydrodynamics ? 'Dynamics (RPY)' : 'Dynamics (Langevin)'
  return job?.nonlinear ? 'Fine (nonlinear)' : 'Coarse (linear)'
}

/** Human status line for the detail block. */
export function detailStatusText(job, progress) {
  if (!job) return ''
  switch (job.status) {
    case 'queued':    return 'Queued — preparing to solve.'
    case 'preparing': return 'Writing the design snapshot…'
    case 'running': {
      const pct = formatProgress(job, progress)
      const eta = progress?.eta_seconds
      const etaStr = (typeof eta === 'number' && eta > 0) ? ` · ~${Math.ceil(eta)}s left` : ''
      return `Solving ${materialLabel(job)} FEM — ${solverLabel(job)} ${pct}${etaStr}`
    }
    case 'completed': {
      const s = job.sim_seconds ? ` in ${job.sim_seconds}s` : ''
      const n = job.n_nodes ? ` · ${job.n_nodes} bp nodes` : ''
      return `Predicted (${materialLabel(job)}, ${solverLabel(job)})${s}${n}.`
    }
    case 'stopped': return 'Stopped.'
    case 'failed':  return `Failed: ${job.error || 'see error log'}`
    default:        return job.status || ''
  }
}

/** Timeline glyph for the job's single solver stage. */
export function stageChip(job) {
  const glyph = (st) => st === 'done' ? '●' : st === 'failed' ? '✗' : st === 'running' ? '◐' : '○'
  const stages = job?.stages?.length ? job.stages : [{ name: job?.nonlinear ? 'nonlinear' : 'linear', status: undefined }]
  return stages.map((s) => `${glyph(s.status)} ${s.name}`).join('  ')
}

/**
 * Completed-job summary HTML (material / solver / RMSF range).  Pure (unit-tested);
 * returns an HTML string the panel drops into the summary div, or '' when there's
 * nothing to show (job not completed).
 */
export function formatSummary(job) {
  if (!job || job.status !== 'completed') return ''
  const bits = [`<b>${materialLabel(job)}</b> · ${solverLabel(job)} solve`]
  if (job.n_nodes) bits.push(`${job.n_nodes} bp nodes`)
  if (typeof job.rmsf_min_nm === 'number' && typeof job.rmsf_max_nm === 'number') {
    bits.push(`RMSF ${job.rmsf_min_nm.toFixed(2)}–${job.rmsf_max_nm.toFixed(2)} nm`)
  }
  return bits.join(' · ')
}

// ── Factory ───────────────────────────────────────────────────────────────────

export function initSnupiJobsPanel({ snupiDisplay = null, getWorkspacePath = null, getSelection = null } = {}) {
  const $ = (id) => document.getElementById(id)
  const panel = $('snupi-jobs-panel')
  const heading = $('snupi-jobs-heading')
  const body = $('snupi-jobs-body')
  if (!panel || !body) return { refresh: () => {}, getSelectedJob: () => null, selectJob: () => {}, deleteSelected: () => false }

  const arrow = $('snupi-jobs-arrow')
  const coarseBtn = $('snupi-jobs-coarse-btn')
  const fineBtn = $('snupi-jobs-fine-btn')
  const progressEl = $('snupi-jobs-progress')
  const advToggle = $('snupi-jobs-adv-toggle')
  const advArrow = $('snupi-jobs-adv-arrow')
  const advBody = $('snupi-jobs-adv-body')
  const displayToggle = $('snupi-display-toggle')
  const displayArrow = $('snupi-display-arrow')
  const displayCard = $('snupi-display-card')
  const stepsInput = $('snupi-jobs-n-steps')
  const rmsfInput = $('snupi-jobs-with-rmsf')
  const materialSelect = $('snupi-jobs-material')
  const dynamicsInput = $('snupi-jobs-dynamics')
  const hydroInput = $('snupi-jobs-hydrodynamics')
  const showAll = $('snupi-jobs-show-all')
  const listEl = $('snupi-jobs-list')
  const detail = $('snupi-jobs-detail')
  const detailStatus = $('snupi-jobs-detail-status')
  const timeline = $('snupi-jobs-timeline')
  const summaryEl = $('snupi-jobs-summary')
  const detailError = $('snupi-jobs-detail-error')
  const stopBtn = $('snupi-jobs-stop-btn')
  const displayStatus = $('snupi-jobs-display-status')
  const modeRadios = () => Array.from(panel.querySelectorAll('.snupi-display-mode'))
  const checkedMode = () => modeRadios().find((r) => r.checked)?.value || 'off'
  const setMode = (value) => modeRadios().forEach((r) => { r.checked = r.value === value })

  let _jobs = []
  let _selectedId = null
  let _progress = null
  let _launching = false   // re-entrancy guard
  let _listSig = null
  const _legend = { el: null }

  const _selectedJob = () => _jobs.find((j) => j.job_id === _selectedId) || null

  // Canonical job-list model + renderer (converges to the oxDNA look). SNUPI jobs are flat
  // (no parent/child tree); the Coarse/Fine solver mode rides the leading-tag slot.
  function _rowCtx() {
    return {
      engine: 'snupi',
      selectedId: _selectedId,
      hierarchical: false,
      displayName: jobDisplayName,
      isActive: snupiJobIsActive,
      formatTime: formatJobTime,
      tags: (job) => [{
        text: job.nonlinear ? 'Fine' : 'Coarse', color: _C.dim,
        title: `${materialLabel(job)} · ${job.nonlinear ? 'Fine (nonlinear)' : 'Coarse (linear)'}`,
      }],
      rowSig: (j) => `${j.job_id}:${j.status}:${j.nonlinear ? 1 : 0}:${j.material || 'snupi'}`,
      colors: { dim: _C.dim, warn: _C.warn },
    }
  }

  // Graphs & Metrics card — a child module reading the panel's job selection.
  const _metricsCard = initSnupiMetricsCard({ getSelectedJob: _selectedJob })

  // Anchors + Electric-field cards — mimics of the oxDNA panel's, feeding the FEM solve
  // (C1/C2). The anchors card shares the exact oxDNA scope resolver (parameterised ids);
  // the field card is numeric-only (no in-scene gizmo, like CanDo).
  const _anchorsCard = initOxdnaAnchorsSetup({
    getSelection: () => (getSelection ? getSelection() : null),
    ids: {
      toggle: 'snupi-anchors-toggle', arrow: 'snupi-anchors-arrow', body: 'snupi-anchors-body',
      add: 'snupi-anchors-add', clear: 'snupi-anchors-clear', list: 'snupi-anchors-list',
      status: 'snupi-anchors-status',
    },
  })
  const _efieldCard = initForcesCard({
    engine: 'snupi',
    getAnchorCount: () => _anchorsCard?.getAnchors?.()?.length || 0,
  })

  // ── Shared scaffold: collapse + advanced drawer + poll loop ────────────────────
  const _base = initJobsPanelBase({
    section: 'snupi-jobs-panel',
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

  // ── Run (Coarse = linear preview; Fine = nonlinear corotational) ──────────────
  function _updateLaunchButtons() {
    const busy = launchBlocked(_launching, _jobs, _selectedJob())
    for (const btn of [coarseBtn, fineBtn]) {
      if (!btn) continue
      btn.disabled = busy
      btn.style.cursor = busy ? 'not-allowed' : 'pointer'
      btn.style.opacity = busy ? '0.5' : '1'
    }
  }

  async function _launch(nonlinear) {
    if (launchBlocked(_launching, _jobs, _selectedJob())) return
    _launching = true
    _updateLaunchButtons()
    try {
      if (!(await confirmNoConcurrentJob())) return
      const anchors = _anchorsCard.getAnchors()
      const fieldSpec = _efieldCard.getFieldSpec()
      const fieldOn = _efieldCard.isEnabled()
      const mat = materialSelect?.value === 'cando' ? 'cando' : 'snupi'
      const body_ = {
        nonlinear,
        n_steps:   Math.max(1, parseInt(stepsInput?.value, 10) || 20),
        with_rmsf: rmsfInput ? !!rmsfInput.checked : true,
        material:  mat,
        dynamics:      dynamicsInput ? !!dynamicsInput.checked : false,
        hydrodynamics: hydroInput ? !!hydroInput.checked : false,
        autostart: true,
        design_source_path: getWorkspacePath?.() || null,
        anchors: anchors.length ? anchors : null,
        field:   fieldOn ? { field_pN: fieldSpec.field_pN, dir: fieldSpec.dir } : null,
      }
      const job = await api.createSnupiJob(body_)
      if (!job) {
        showToast(api.lastErrorMessage() || 'Failed to start SNUPI FEM prediction', { severity: 'error' })
        return
      }
      _selectedId = job.job_id
      await _fetchJobs()
    } finally {
      _launching = false
      _updateLaunchButtons()
    }
  }
  coarseBtn?.addEventListener('click', () => _launch(false))
  fineBtn?.addEventListener('click', () => _launch(true))

  // ── Jobs list + poll ────────────────────────────────────────────────────────
  async function _fetchJobs() {
    const all = await api.listSnupiJobs()
    if (!Array.isArray(all)) return
    _jobs = filterJobsForPart(all, getWorkspacePath?.() || null, showAll?.checked)
    _renderList()
    _updateLaunchButtons()
    if (_selectedId) {
      _progress = await api.getSnupiProgress(_selectedId)
      const job = _selectedJob()
      // Live-follow: re-apply the active display mode when a running job completes.
      if (job && job.status === 'completed' && snupiDisplay?.deformActive?.()
          && snupiDisplay.deformJobId?.() === _selectedId) {
        await snupiDisplay.refresh?.()
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
      onClick: (jobId) => _selectJob(jobId),
      emptyText: 'No SNUPI FEM jobs for this design yet.',
      dimColor: _C.dim,
      legendState: _legend,
    })
  }

  async function _selectJob(jobId) {
    _selectedId = jobId
    _progress = await api.getSnupiProgress(jobId)
    _renderList()
    _renderDetail()
    await _retargetDisplayToSelection()
    _base.schedulePoll()
  }

  /** When a display mode is active and the user selects a DIFFERENT job, retarget the
   *  active mode to the newly-selected job. */
  async function _retargetDisplayToSelection() {
    if (!snupiDisplay?.deformActive?.()) return
    if (snupiDisplay.deformJobId?.() === _selectedId) return
    const mode = checkedMode()
    const job = _selectedJob()
    const canShow = mode !== 'off' && job?.status === 'completed'
      && (mode !== 'flex' || !!job?.rmsf_max_nm)
    if (!canShow) {
      snupiDisplay.stopDeform?.(); setMode('off'); _syncDisplayStatus()
      return
    }
    const r = await snupiDisplay[_MODE_FNS[mode]]?.(_selectedId)
    if (!r?.ok) { snupiDisplay.stopDeform?.(); setMode('off') }
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
    if (progressEl) {
      const pct = _progress?.overall != null ? Math.round(_progress.overall * 100) : 0
      progressEl.style.display = job.status === 'running' ? '' : 'none'
      progressEl.querySelector('.bar')?.style.setProperty('width', `${pct}%`)
    }
    if (detailError) {
      detailError.style.display = job.status === 'failed' ? '' : 'none'
      detailError.textContent = job.status === 'failed' ? (job.error || 'Solve failed.') : ''
    }
    if (stopBtn) stopBtn.style.display = job.status === 'running' ? '' : 'none'
    _syncDisplayStatus()
    _metricsCard?.sync()
  }

  /** Gate the always-visible Display card's radios: enabled only for a completed job. */
  function _syncDisplayModes() {
    const job = _selectedJob()
    const ready = job?.status === 'completed'
    modeRadios().forEach((r) => {
      const needsRmsf = r.value === 'flex'
      const needsTraj = r.value === 'trajectory'   // only dynamics jobs cache a trajectory
      r.disabled = !ready || !snupiDisplay || (needsRmsf && !job?.rmsf_max_nm) || (needsTraj && !job?.dynamics)
    })
  }

  /** Readout under the radios: the active mode + its scalar range / RMSD. */
  function _syncDisplayStatus() {
    if (!displayStatus) return
    const mode = snupiDisplay?.mode?.()
    if (!mode) { displayStatus.textContent = ''; return }
    const s = snupiDisplay?.lastStats?.()
    if (mode === 'flex' && s?.kind === 'flex') {
      displayStatus.textContent = `Flexibility (RMSF) ${s.min.toFixed(2)}–${s.max.toFixed(2)} nm`
    } else if (mode === 'deviation' && s?.kind === 'deviation') {
      displayStatus.textContent =
        `Deviation from design — RMSD ${s.rmsd.toFixed(2)} nm (max ${s.max.toFixed(2)} nm)`
    } else if (mode === 'cando' && s?.kind === 'cando') {
      displayStatus.textContent =
        `CanDo-style cylinders — ${s.helices} helix tubes, ${s.joints} crossover joints`
    } else {
      displayStatus.textContent = 'Showing predicted shape.'
    }
  }

  // ── Control buttons ───────────────────────────────────────────────────────────
  if (stopBtn) {
    stopBtn.addEventListener('click', async () => {
      if (!_selectedId) return
      await api.stopSnupiJob(_selectedId)
      await _fetchJobs()
    })
  }
  // Delete the selected SNUPI job. Invoked by the consolidated #simulate-job-actions
  // Delete button (dispatched by the master card on the selected node).
  async function deleteSelected() {
    if (!_selectedId) return false
    const r = await api.deleteSnupiJob(_selectedId)
    if (r?.ok) {
      if (snupiDisplay?.deformJobId?.() === _selectedId) snupiDisplay.stopDeform?.()
      _selectedId = null
      detail && (detail.style.display = 'none')
      await _fetchJobs()
      return true
    }
    showToast(api.lastErrorMessage() || 'Delete failed', { severity: 'error' })
    return false
  }

  // ── Display-mode radios (Off / Predicted shape / Flexibility / Deviation / CanDo) ──
  const _MODE_FNS = { deform: 'showDeform', flex: 'showFlex', deviation: 'showDeviation', cando: 'showCandoStyle', trajectory: 'showTrajectory' }
  async function _onModeChange() {
    if (!snupiDisplay) { setMode('off'); return }
    const mode = checkedMode()
    if (mode !== 'trajectory') snupiDisplay.stopTrajectory?.()   // leaving the player → halt the loop
    if (mode === 'off') { snupiDisplay.stopDeform?.(); _syncDisplayStatus(); return }
    if (!_selectedId) { setMode('off'); return }
    const r = await snupiDisplay[_MODE_FNS[mode]]?.(_selectedId)
    if (!r?.ok) {
      setMode('off'); snupiDisplay.stopDeform?.()
      showToast(mode === 'flex' ? 'RMSF not available for this job'
        : mode === 'trajectory' ? 'No trajectory — run a Langevin dynamics job (Advanced ▸ Langevin dynamics)'
        : 'Predicted positions not ready', { severity: 'warn' })
    }
    _syncDisplayStatus()
  }
  modeRadios().forEach((r) => r.addEventListener('change', _onModeChange))
  if (showAll) showAll.addEventListener('change', _fetchJobs)

  // ── Cross-panel coordination ──────────────────────────────────────────────────
  function _stopDisplays() {
    snupiDisplay?.stopAndRestore?.()
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
    _fetchJobs()
  }

  _base.initCollapsed(true)

  // selectJob: highlight + populate this panel's detail as a row click does — used by
  // the unified Simulate list to route a SNUPI node's selection here.
  async function selectJob(jobId) {
    if (!jobId) return
    if (!_jobs.find((j) => j.job_id === jobId)) await _fetchJobs()
    return _selectJob(jobId)
  }
  return { refresh: _fetchJobs, getSelectedJob: _selectedJob, selectJob, deleteSelected }
}
