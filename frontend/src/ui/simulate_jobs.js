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
 * Selecting any node drives the master card: a status/progress line + one context
 * Run/Stop/Resume button (via the pure `job_run_control.runControlState`, dispatched by
 * the node's engine). Viz dispatches by engine too — an [L] node's display/RMSF/
 * deviation/trajectory come from the LAMMPS controller this card OWNS (`initLammpsDisplay`);
 * an oxDNA node delegates to the oxDNA panel's rich viz via its existing `selectJob(id)`.
 *
 * Factory: initSimulateJobs({ api, getWorkspacePath, designRenderer, oxdnaPanel,
 * engineSelector, getFlexScale }) → { refresh, selectJob, getSelected }. Module-first:
 * cohesive logic lives here / in the pure helpers below; main.js only imports + inits.
 * Physical-layer / display-state only (topology is never touched).
 */

import { buildJobListModel, jobListSignature } from './jobs_panel_model.js'
import { renderJobList } from './jobs_panel_render.js'
import { runControlState, RUN_ACTION } from './job_run_control.js'
import { jobDisplayName, runRowLabel, runChildTitle } from './oxdna_jobs_panel.js'
import { jobIsViewable, flexStatusText, buildCreatePayload } from './lammps_jobs_logic.js'
import { initLammpsDisplay } from './lammps_display.js'
import { initOxdnaTrajectoryPlayer } from './oxdna_trajectory_player.js'
import { formatJobTime } from '../scene/trajectory_range.js'
import { formatBytes } from './format_bytes.js'
import { showToast } from './toast.js'

const POLL_MS = 1500
const _C = { ok: '#5cb85c', warn: '#e0a800', err: '#d9534f', accent: '#4a9eff', dim: '#8a8a8a' }
const _ACTIVE = ['queued', 'preparing', 'running']
const _VIEW_RADIOS = ['display', 'flex', 'deviation', 'traj']

// ── Pure decisions (unit-tested) ──────────────────────────────────────────────

/** Is a node in an in-progress state (active spinner + Stop)? */
export function nodeIsActive(node) {
  return _ACTIVE.includes(node?.status)
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

/** Coarse progress % for the master bar (no extra fetch): LAMMPS from current_step/steps,
 *  oxDNA from stages done/total. */
export function masterProgressPct(node) {
  if (!node) return 0
  if (node.engine === 'lammps') {
    const total = Number(node.steps) || 0
    const cur = Number(node.current_step) || 0
    return total > 0 ? Math.max(0, Math.min(100, Math.round((cur / total) * 100))) : 0
  }
  const st = node.stages || []
  if (!st.length) return 0
  const done = st.filter((s) => s.status === 'done').length
  return Math.round((done / st.length) * 100)
}

/** One-line master status text for the selected node (engine-symmetric). */
export function masterStatusText(node) {
  if (!node) return 'Select a run above, or press ▶ Relax to start one.'
  const eng = node.engine === 'lammps' ? 'LAMMPS (CPU)' : 'oxDNA'
  if (node.engine === 'lammps') {
    if (node.status === 'running') return `${eng} · running · ${masterProgressPct(node)}%`
    return `${eng} · ${node.status}`
  }
  if (node.production_state === 'running') return `${eng} · production running`
  if (node.production_state === 'done') return `${eng} · production done`
  if (node.production_state === 'failed') return `${eng} · production failed`
  return `${eng} · ${node.status}`
}

/** The expandable detail note. A LAMMPS run explains why it ran on CPU; an oxDNA run
 *  gets a brief size line (its rich detail lives in the oxDNA panel). */
export function nodeDetailText(node) {
  if (!node) return ''
  if (node.engine === 'lammps') {
    const cores = Number(node.ranks) || 1
    return `Ran on CPU (LAMMPS, ${cores} core${cores === 1 ? '' : 's'}) because the GPU was busy — ` +
           'the same oxDNA2 force field, multi-core, faster than single-core.'
  }
  const n = Number(node.n_units) || 0
  return n ? `oxDNA (GPU) · ${n.toLocaleString()} nucleotides` : ''
}

// ── Stateful factory ──────────────────────────────────────────────────────────

export function initSimulateJobs({
  api,
  getWorkspacePath = null,
  designRenderer = null,
  oxdnaPanel = null,
  engineSelector = null,
  getFlexScale = null,
} = {}) {
  const $ = (id) => document.getElementById(id)
  const root = $('simulate-jobs')
  const listEl = $('simulate-jobs-list')
  const statusEl = $('simulate-jobs-status')
  const progressBar = root?.querySelector('#simulate-jobs-progress .bar')
  const runBtn = $('simulate-jobs-run-btn')
  const detailEl = $('simulate-jobs-detail')
  if (!root || !listEl) return { refresh: () => {}, selectJob: () => {}, getSelected: () => null }

  // viz card (LAMMPS runs only — oxDNA viz stays in the oxDNA panel)
  const vizCard = $('simulate-jobs-viz')
  const rOff = $('simulate-jobs-viz-off')
  const rDisplay = $('simulate-jobs-display-toggle')
  const rFlex = $('simulate-jobs-flex-toggle')
  const rDeviation = $('simulate-jobs-deviation-toggle')
  const rTraj = $('simulate-jobs-traj-toggle')
  const alignToggle = $('simulate-jobs-align-toggle')
  const trajControls = $('simulate-jobs-traj-controls')
  const _radio = { display: rDisplay, flex: rFlex, deviation: rDeviation, traj: rTraj }
  const _status = {
    display: $('simulate-jobs-display-status'), flex: $('simulate-jobs-flex-status'),
    deviation: $('simulate-jobs-deviation-status'), traj: $('simulate-jobs-traj-status'),
  }

  let _nodes = []
  let _sel = { engine: null, id: null }
  let _listSig = null
  let _busy = false
  let _dynamicsActive = true
  let _pollTimer = null
  const _legend = { el: null }

  const _display = initLammpsDisplay({ designRenderer })
  const _player = initOxdnaTrajectoryPlayer({
    playBtn: $('simulate-jobs-traj-play'),
    slider: $('simulate-jobs-traj-slider'),
    markersEl: $('simulate-jobs-traj-markers'),
    label: $('simulate-jobs-traj-label'),
    onSeek: (i) => _display.showFrame(i),
  })

  const _currentPath = () => (getWorkspacePath ? getWorkspacePath() : null) || null
  const _selectedNode = () => _nodes.find((n) => n.engine === _sel.engine && n.job_id === _sel.id) || null
  const _setStatus = (el, text, color = _C.dim) => { if (el) { el.textContent = text; el.style.color = color } }

  // ── list ─────────────────────────────────────────────────────────────────
  function _rowCtx() {
    return {
      engine: 'oxdna',   // both engines share the status vocab; production_state comes per-row
      selectedId: _sel.id,
      hierarchical: true,
      displayName: jobDisplayName,
      childLabel: runRowLabel,
      childTitle: runChildTitle,
      productionState: (n) => n.production_state,
      isActive: nodeIsActive,
      isStale: (n) => !!n.out_of_date,
      staleClass: 'oxdna-job-stale-warn',
      staleTitle: 'Design changed since this job was relaxed — run a new Relax, or roll the feature log back, before live/production.',
      tags: (n) => n.engine === 'lammps'
        ? [{ text: '[L]', color: '#9e6bff', title: 'Ran on CPU (LAMMPS) — the GPU was busy' }]
        : ((oxdnaPanel?.autorefineJobIds?.() || new Set()).has(n.job_id)
          ? [{ text: '[AR]', color: '#e3b341', title: 'Created by Autorefine skips/loops' }] : []),
      archived: (n) => !!n.archived,
      archivePath: (n) => n.archive_path || '',
      sizeBytes: (n) => n.size_bytes ?? null,
      formatTime: formatJobTime,
      formatSize: formatBytes,
      rowSig: (n) => `${n.engine}:${n.job_id}:${n.status}:${n.production_state}:${n.out_of_date ? 1 : 0}:${n.archived ? 1 : 0}:${n.size_bytes ?? ''}`,
      colors: { dim: _C.dim, warn: _C.warn },
    }
  }

  function _renderList() {
    const ctx = _rowCtx()
    const sig = jobListSignature(_nodes, ctx)
    if (sig === _listSig && listEl.childElementCount > 0) return
    _listSig = sig
    renderJobList(listEl, buildJobListModel(_nodes, ctx), {
      onClick: (jobId) => _select(jobId),
      emptyText: 'No simulation runs for this design yet — press ▶ Relax to start one.',
      dimColor: _C.dim,
      legendState: _legend,
    })
  }

  function _renderMaster() {
    const node = _selectedNode()
    _setStatus(statusEl, masterStatusText(node),
      node?.status === 'failed' ? _C.err : node && nodeIsActive(node) ? _C.warn : _C.dim)
    if (progressBar) progressBar.style.width = node && nodeIsActive(node) ? `${masterProgressPct(node)}%` : '0%'
    if (detailEl) detailEl.textContent = nodeDetailText(node)
    _renderRunButton()
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
    _viewsOff()
    _renderList()
    _renderMaster()
    _dispatchDetail(node)
  }

  // Rich detail + viz dispatch by engine: an oxDNA node lights up the oxDNA panel's own
  // detail/viz (via its selectJob); a LAMMPS node shows this card's viz sub-surface.
  function _dispatchDetail(node) {
    if (node.engine === 'oxdna') {
      if (vizCard) vizCard.style.display = 'none'
      engineSelector?.select?.('oxdna')       // reveal the oxDNA detail host
      oxdnaPanel?.selectJob?.(node.job_id)
    } else {
      if (vizCard) vizCard.style.display = ''
      _updateVizToggles()
    }
  }

  // ── LAMMPS viz (this card owns the LAMMPS display controller) ──────────────
  function _updateVizToggles() {
    const node = _selectedNode()
    const viewable = node?.engine === 'lammps' && jobIsViewable(node)
    for (const key of _VIEW_RADIOS) {
      const r = _radio[key]
      if (!r) continue
      r.disabled = !viewable
      const lbl = r.closest('label')
      if (lbl) { lbl.style.opacity = viewable ? '1' : '0.5'; lbl.style.cursor = viewable ? 'pointer' : 'not-allowed' }
    }
    if (!viewable && !rOff?.checked) _viewsOff()
  }

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
    const node = _selectedNode()
    if (!node || node.engine !== 'lammps') { _viewsOff(); return }
    const sel = node.job_id
    const st = _status[kind]
    _setStatus(st, 'Loading…')
    if (kind !== 'flex' && kind !== 'deviation') getFlexScale?.()?.hide?.()
    let r
    if (kind === 'display') r = await _display.displayJob(sel, !!alignToggle?.checked)
    else if (kind === 'flex') r = await _display.displayRmsf(sel)
    else if (kind === 'deviation') r = await _display.displayDeviation(sel)
    else if (kind === 'traj') r = await _display.loadTrajectory(sel)
    if (_radio[kind] && !_radio[kind].checked) return   // a newer toggle superseded us
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

  // ── fetch + poll ──────────────────────────────────────────────────────────
  async function _fetch() {
    const nodes = await api.listSimJobs(_currentPath(), false).catch(() => null)
    _nodes = Array.isArray(nodes) ? nodes : []
    if (_sel.id && !_selectedNode()) _sel = { engine: null, id: null }   // selection vanished
    _renderList()
    _renderMaster()
    if (_selectedNode()?.engine === 'lammps') _updateVizToggles()
    _schedulePoll()
  }
  function _schedulePoll() {
    if (_pollTimer) { clearTimeout(_pollTimer); _pollTimer = null }
    const bodyVisible = document.getElementById('simulate-body')?.style.display !== 'none'
    if (_dynamicsActive && bodyVisible && _nodes.some(nodeIsActive)) {
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
    _viewsOff()
    _fetch()
  })

  function refresh() { return _fetch() }
  function selectJob(jobId) { return _select(jobId) }

  // Initial populate deferred a tick so late-declared main.js deps (workspace path) exist.
  queueMicrotask(_fetch)

  return { refresh, selectJob, getSelected: () => ({ ..._sel }) }
}
