/**
 * LAMMPS jobs panel — launch, monitor, and VISUALISE a managed CPU-parallel oxDNA
 * (LAMMPS CG-DNA) run on the currently-loaded design. Dedicated sibling of the
 * oxDNA/mrDNA panels: LAMMPS runs the SAME oxDNA2 force field, MPI domain-decomposed,
 * for assemblies too large for single-GPU oxDNA.
 *
 * The "Visualizations & processing" card is a faithful copy of the oxDNA one, driven
 * by the same validated rendering code: it runs LAMMPS data through `lammps_display`
 * (which reuses oxdna_display's pure mappers) + the shared `oxdna_trajectory_player`.
 * Four mutually-exclusive views on the SELECTED finished run: display / flexibility
 * (RMSF) / deviation / trajectory, plus an "Align to design pose" modifier.
 *
 * REST-poll based (no WebSocket), like the mrDNA/oxDNA panels.
 *
 * Factory: initLammpsJobsPanel({ designRenderer }) → { refresh }. Cohesive logic lives
 * here or in the pure lammps_jobs_logic.js (module-first law); main.js only imports+inits.
 */

import { initJobsPanelBase } from './jobs_panel_base.js'
import { showToast } from './toast.js'
import {
  progressPct, jobIsActive, anyActive, runButtonState, availabilityMessage,
  jobRowLabel, buildCreatePayload, jobIsViewable, flexStatusText, maxRanks, ranksError, freeRanks,
} from './lammps_jobs_logic.js'
import { buildJobListModel, jobListSignature } from './jobs_panel_model.js'
import { renderJobList } from './jobs_panel_render.js'
import { formatJobTime } from '../scene/trajectory_range.js'
import { filterJobsForPart } from './md_jobs_panel.js'
import { initLammpsDisplay } from './lammps_display.js'
import { initOxdnaTrajectoryPlayer } from './oxdna_trajectory_player.js'
import * as api from '../api/client.js'

const POLL_MS = 1500
const _C = { ok: '#5cb85c', warn: '#e0a800', err: '#d9534f', dim: '#8b949e' }
const _VIEW_RADIOS = ['display', 'flex', 'deviation', 'traj']
const _SHOW_ALL_KEY = 'nadoc:lammps-jobs-show-all'

export function initLammpsJobsPanel({ designRenderer = null, getWorkspacePath = null, forcesSetup = null, getFlexScale = null } = {}) {
  const $ = (id) => document.getElementById(id)
  const panel = $('lammps-jobs-panel')
  const heading = $('lammps-jobs-heading')
  const body = $('lammps-jobs-body')
  if (!panel || !heading || !body) return { refresh: () => {} }

  const arrow = $('lammps-jobs-arrow')
  const statusEl = $('lammps-jobs-status')
  const runBtn = $('lammps-jobs-run-btn')
  const progressBar = panel.querySelector('#lammps-jobs-progress .bar')
  const listEl = $('lammps-jobs-list')
  const advToggle = $('lammps-jobs-adv-toggle')
  const advArrow = $('lammps-jobs-adv-arrow')
  const advBody = $('lammps-jobs-adv-body')
  const inSteps = $('lammps-jobs-steps')
  const inDump = $('lammps-jobs-dump')
  const inTemp = $('lammps-jobs-temp')
  const inSalt = $('lammps-jobs-salt')
  const inRanks = $('lammps-jobs-ranks')
  const coresAutoBtn = $('lammps-jobs-cores-auto')
  const showAllToggle = $('lammps-jobs-show-all')
  // ── Visualizations & processing card ──
  const vizToggle = $('lammps-jobs-viz-toggle')
  const vizArrow = $('lammps-jobs-viz-arrow')
  const vizBody = $('lammps-jobs-viz-body')
  const rOff = $('lammps-jobs-viz-off')
  const rDisplay = $('lammps-jobs-display-toggle')
  const rFlex = $('lammps-jobs-flex-toggle')
  const rDeviation = $('lammps-jobs-deviation-toggle')
  const rTraj = $('lammps-jobs-traj-toggle')
  const alignToggle = $('lammps-jobs-align-toggle')
  const sDisplay = $('lammps-jobs-display-status')
  const sFlex = $('lammps-jobs-flex-status')
  const sDeviation = $('lammps-jobs-deviation-status')
  const sTraj = $('lammps-jobs-traj-status')
  const trajControls = $('lammps-jobs-traj-controls')
  const _radio = { display: rDisplay, flex: rFlex, deviation: rDeviation, traj: rTraj }
  const _status = { display: sDisplay, flex: sFlex, deviation: sDeviation, traj: sTraj }

  let _jobs = []
  let _available = null
  let _launching = false
  let _selectedId = null
  let _listSig = null            // last-rendered list signature (avoids spinner-restart churn)
  const _legend = { el: null }   // status-symbol legend, inserted once after the list

  // Canonical job-list model + renderer (U3): LAMMPS converges to the oxDNA look
  // (list index, status glyph/spinner, legend). Runs are flat (no tree/archive);
  // the inline Stop button on active rows rides the canonical rowAction slot.
  const _STOP_STYLE =
    'flex:0 0 auto;font-size:var(--text-xs);padding:1px 6px;background:#2d1418;' +
    'border:1px solid #d9534f;color:#f0a0a0;border-radius:3px;cursor:pointer'
  function _rowCtx() {
    return {
      engine: 'lammps',
      selectedId: _selectedId,
      hierarchical: false,
      displayName: jobRowLabel,
      isActive: jobIsActive,
      formatTime: formatJobTime,
      rowAction: (job) => jobIsActive(job)
        ? { text: 'Stop', title: 'Stop this run', styleText: _STOP_STYLE } : null,
      rowSig: (j) => `${j.job_id}:${j.status}`,
      colors: { dim: '#8a8a8a', warn: _C.warn },
    }
  }

  // ── display controller + trajectory player (reuse the validated oxDNA code) ──
  const _display = initLammpsDisplay({ designRenderer })
  const _player = initOxdnaTrajectoryPlayer({
    playBtn: $('lammps-jobs-traj-play'),
    slider: $('lammps-jobs-traj-slider'),
    markersEl: $('lammps-jobs-traj-markers'),
    label: $('lammps-jobs-traj-label'),
    onSeek: (i) => _display.showFrame(i),
  })

  const _selectedJob = () => _jobs.find((j) => j.job_id === _selectedId) || null
  function _setStatus(el, text, color = _C.dim) { if (el) { el.textContent = text; el.style.color = color } }

  // ── current-design filtering (mirror the oxDNA/MD panels) ───────────────────
  function _currentPartPath() { return (getWorkspacePath ? getWorkspacePath() : null) || null }
  function _visibleJobs() {
    return filterJobsForPart(_jobs, _currentPartPath(), !!showAllToggle?.checked)
  }
  if (showAllToggle) {
    showAllToggle.checked = localStorage.getItem(_SHOW_ALL_KEY) === '1'
    showAllToggle.addEventListener('change', () => {
      localStorage.setItem(_SHOW_ALL_KEY, showAllToggle.checked ? '1' : '0')
      _renderList()
    })
  }

  // ── collapse (section) + advanced drawer + poll — shared jobs-panel base (U3) ──
  // LAMMPS accommodations: section arrow via the `is-collapsed` class
  // (arrowStyle:'class') and an onClose that turns overlays off + drops the
  // forces gizmo. The base adds the open-guard the bespoke poll lacked (harmless:
  // the old poll only ever rescheduled from `_fetchJobs`, itself open-only).
  const _base = initJobsPanelBase({
    section: 'lammps-jobs-panel',
    els: { heading, body, arrow, advToggle, advArrow, advBody },
    pollMs: POLL_MS,
    arrowStyle: 'class',
    collapsible: false,   // engine header is a static label; Simulate owns the collapse
    hasActive: () => anyActive(_visibleJobs()),
    tick: () => _fetchJobs(),
    onOpen: () => _onOpen(),
    onClose: () => { _viewsOff(); forcesSetup?.detachGizmo?.() },   // retained (no per-panel collapse fires it now)
  })

  // ── collapse (viz card — separate persistence-free disclosure) ───────────────
  if (vizToggle) {
    vizToggle.addEventListener('click', () => {
      const hidden = vizBody.style.display === 'none'
      vizBody.style.display = hidden ? '' : 'none'
      if (vizArrow) vizArrow.classList.toggle('is-collapsed', !hidden)
    })
  }

  // ── availability + run button ─────────────────────────────────────────────
  async function _checkAvailable() {
    _available = await api.lammpsAvailable()
    if (statusEl) {
      statusEl.textContent = availabilityMessage(_available)
      const ok = !!_available?.available && !!_available?.cgdna_capable
      statusEl.style.color = ok ? _C.ok : _C.warn
    }
    _boundRanksInput()
    _syncRunButton()
  }
  // Cap the ranks input at the physical-core ceiling reported by the backend so
  // the user can't dial in a rank count MPI would refuse to launch.
  function _boundRanksInput() {
    if (!inRanks) return
    const cores = maxRanks(_available)
    inRanks.max = String(cores)
    inRanks.title = `Up to ${cores} physical CPU core${cores === 1 ? '' : 's'} available`
    if (Math.floor(Number(inRanks.value)) > cores) inRanks.value = String(cores)
  }
  // ⚡ Set the cores input to however many are FREE right now (re-samples the
  // backend load average → accounts for a NAMD/oxDNA run already using cores).
  async function _optimizeCores() {
    if (!inRanks) return
    _available = await api.lammpsAvailable()   // fresh free-core sample
    _boundRanksInput()
    const free = freeRanks(_available)
    inRanks.value = String(free)
    const total = maxRanks(_available)
    showToast(
      free < total
        ? `Set to ${free} free core${free === 1 ? '' : 's'} (${total - free} busy with other work).`
        : `Set to ${free} core${free === 1 ? '' : 's'} — all free.`,
      { severity: 'ok' })
  }
  coresAutoBtn?.addEventListener('click', _optimizeCores)
  function _syncRunButton() {
    if (!runBtn) return
    const st = runButtonState(_available)
    runBtn.disabled = !st.enabled || _launching
    runBtn.textContent = _launching ? 'Starting…' : st.label
    runBtn.title = st.title
  }
  // `overrides` (when passed by the simulate coordinator's CPU-fallback path) supplies
  // the create-payload args programmatically instead of reading the DOM inputs — this is
  // how "Run on CPU instead" in the GPU-busy dialog launches a LAMMPS run from the oxDNA
  // form. The DOM-driven forces/ranks guards only apply to a user-initiated Run.
  async function _launch(overrides = null) {
    if (_launching) return
    const cores = maxRanks(_available)
    if (!overrides) {
      if (forcesSetup?.fieldNeedsAnchor?.()) {
        showToast('An E-field run needs ≥1 anchor — add a fixed strand/domain in External forces.',
          { severity: 'warn' })
        return
      }
      const rankMsg = ranksError(inRanks?.value, cores)
      if (rankMsg) {
        showToast(rankMsg, { severity: 'warn' })
        return
      }
    }
    _launching = true
    _syncRunButton()
    try {
      let payload
      if (overrides) {
        payload = buildCreatePayload({
          ...overrides, cores,
          designSourcePath: overrides.designSourcePath ?? _currentPartPath(),
        })
      } else {
        const forces = forcesSetup?.getForces?.() || { field: null, anchors: [], wall: null }
        payload = buildCreatePayload({
          steps: inSteps?.value, dumpEvery: inDump?.value,
          temperature: inTemp?.value, salt: inSalt?.value, ranks: inRanks?.value, cores,
          designSourcePath: _currentPartPath(),
          field: forces.field, anchors: forces.anchors, wall: forces.wall,
        })
      }
      const job = await api.createLammpsJob(payload)
      if (!job) {
        showToast(api.lastErrorMessage() || 'Could not start LAMMPS run', { severity: 'error' })
        return
      }
      showToast(`LAMMPS run started (${job.n_atoms} nt)`, { severity: 'ok' })
      await _fetchJobs()
    } finally {
      _launching = false
      _syncRunButton()
    }
  }
  runBtn?.addEventListener('click', () => _launch())   // no arg → DOM-driven launch (not the click Event)

  // ── jobs list + selection + polling ─────────────────────────────────────────
  async function _fetchJobs() {
    const jobs = await api.listLammpsJobs()
    _jobs = Array.isArray(jobs) ? jobs.slice().sort((a, b) => (b.created_at || 0) - (a.created_at || 0)) : []
    if (_selectedId && !_selectedJob()) _selectedId = null   // selected job vanished
    _renderList()
    _renderProgress()
    _updateVizToggles()
    _base.schedulePoll()
  }

  function _renderProgress() {
    if (!progressBar) return
    const active = _visibleJobs().find(jobIsActive)
    progressBar.style.width = active ? `${progressPct(active)}%` : '0%'
  }

  function _renderList() {
    if (!listEl) return
    const jobs = _visibleJobs()
    const ctx = _rowCtx()
    const sig = jobListSignature(jobs, ctx)
    if (sig === _listSig && listEl.childElementCount > 0) return
    _listSig = sig
    renderJobList(listEl, buildJobListModel(jobs, ctx), {
      onClick: (jobId) => _select(jobId),
      onAction: (jobId) => _stop(jobId),
      emptyText: _jobs.length
        ? 'No LAMMPS runs for this design (tick "show all designs" to see others).'
        : 'No LAMMPS runs yet.',
      dimColor: _C.dim,
      legendState: _legend,
    })
  }

  function _select(jobId) {
    if (_selectedId === jobId) return
    _selectedId = jobId
    _viewsOff()                 // a new selection starts from Off (no stale overlay)
    _renderList()
    _updateVizToggles()
  }

  async function _stop(jobId) {
    const ok = await api.stopLammpsJob(jobId)
    if (!ok) showToast(api.lastErrorMessage() || 'Could not stop the run', { severity: 'error' })
    await _fetchJobs()
  }

  // ── viz card: enable radios only for a viewable selection ───────────────────
  function _updateVizToggles() {
    const viewable = jobIsViewable(_selectedJob())
    for (const key of _VIEW_RADIOS) {
      const r = _radio[key]
      if (!r) continue
      r.disabled = !viewable
      const lbl = r.closest('label')
      if (lbl) { lbl.style.opacity = viewable ? '1' : '0.5'; lbl.style.cursor = viewable ? 'pointer' : 'not-allowed' }
    }
    if (!viewable && !rOff?.checked) _viewsOff()
  }

  // ── the four mutually-exclusive views ───────────────────────────────────────
  function _viewsOff() {
    _player.pause?.(); _player.stop()
    if (trajControls) trajControls.style.display = 'none'
    _display.stopAndRestore()
    getFlexScale?.()?.hide?.()
    for (const k of _VIEW_RADIOS) _setStatus(_status[k], '')
    if (rOff) rOff.checked = true
  }

  async function _showView(kind) {
    _player.stop()
    if (trajControls) trajControls.style.display = kind === 'traj' ? '' : 'none'
    const sel = _selectedId
    if (!sel) { _viewsOff(); return }
    const st = _status[kind]
    _setStatus(st, 'Loading…')
    if (kind !== 'flex' && kind !== 'deviation') getFlexScale?.()?.hide?.()   // colour scale only for the maps
    let r
    if (kind === 'display') r = await _display.displayJob(sel, !!alignToggle?.checked)
    else if (kind === 'flex') r = await _display.displayRmsf(sel)
    else if (kind === 'deviation') r = await _display.displayDeviation(sel)
    else if (kind === 'traj') r = await _display.loadTrajectory(sel)
    // a newer selection/toggle superseded us, or the radio was turned off meanwhile
    if (_radio[kind] && !_radio[kind].checked) return
    if (!r || !r.ok) {
      _setStatus(st, (r && r.reason) || 'not ready', _C.warn)
      if (rOff) rOff.checked = true
      _display.stopAndRestore()
      if (trajControls) trajControls.style.display = 'none'
      return
    }
    if (kind === 'display') _setStatus(st, `Showing the final structure (${r.n} beads).`)
    else if (kind === 'flex') {
      _setStatus(st, flexStatusText(r), _C.dim)
      getFlexScale?.()?.show?.({ title: 'RMSF (nm)', min: r.min, max: r.max, mapType: 'flex',
        onRecolor: (lo, hi, cmap) => _display.recolorRmsf(lo, hi, cmap) })
    } else if (kind === 'deviation') {
      _setStatus(st, `Deviation from design: mean ${(r.mean ?? 0).toFixed(2)} nm over ${r.nFrames} frames.`)
      getFlexScale?.()?.show?.({ title: 'Deviation (nm)', min: r.min, max: r.max, mapType: 'deviation',
        onRecolor: (lo, hi, cmap) => _display.recolorDeviation(lo, hi, cmap) })
    } else if (kind === 'traj') { _player.setTrajectory(r.n_frames, r.markers); _setStatus(st, `${r.n_frames} frames — play or scrub.`) }
  }

  rOff?.addEventListener('change', () => { if (rOff.checked) _viewsOff() })
  rDisplay?.addEventListener('change', () => { if (rDisplay.checked) _showView('display') })
  rFlex?.addEventListener('change', () => { if (rFlex.checked) _showView('flex') })
  rDeviation?.addEventListener('change', () => { if (rDeviation.checked) _showView('deviation') })
  rTraj?.addEventListener('change', () => { if (rTraj.checked) _showView('traj') })
  alignToggle?.addEventListener('change', () => { if (rDisplay?.checked) _showView('display') })

  // ── lifecycle ──────────────────────────────────────────────────────────────
  async function _onOpen() {
    await _checkAvailable()
    await _fetchJobs()
  }
  function refresh() { if (_base.isOpen()) _onOpen() }

  _base.initCollapsed(true)
  // a design change invalidates any overlay (it's keyed to the old design)
  window.addEventListener('nadoc:design-changed', () => {
    _selectedId = null
    _viewsOff()
    if (_base.isOpen()) _fetchJobs()
  })

  // `launch(overrides)` lets the simulate coordinator start a LAMMPS run from the
  // oxDNA form (the GPU-busy "Run on CPU instead" path); the Run button uses `_launch()`.
  return { refresh, launch: (overrides) => _launch(overrides) }
}
