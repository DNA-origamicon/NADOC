/**
 * CanDo FEM jobs panel — launch + monitor a native CanDo-replica shape prediction
 * on the currently-loaded design.  Sibling of mrdna_jobs_panel.js, simplified: the
 * FEM solver runs in-process (scipy — no GPU, no external simulator), so there is
 * no availability gate and no NAMD-seed handoff.  Two run modes:
 *
 *   • "Coarse" → the LINEAR solve (fast, ~0.92·CanDo bend, interactive preview).
 *   • "Fine"   → the geometrically-NONLINEAR corotational solve (~1 min, ~0.95).
 *
 * REST-poll based (no WebSocket), exactly like the mrDNA/oxDNA panels: while a job
 * is queued/running the panel polls GET /cando/jobs + /cando/jobs/{id}/progress.
 *
 * The predicted shape is Physical-layer / display-only.  A completed job exposes
 * three mutually-exclusive display modes via the candoDisplay dep (Phase-5 Items 2+3):
 * Predicted shape (deform), Flexibility map (RMSF), and Deviation from design (RMSD).
 *
 * Factory: initCandoJobsPanel({ candoDisplay, getWorkspacePath }) → { refresh,
 * getSelectedJob }.  All cohesive logic lives here (module-first law); main.js only
 * imports + inits + does thin wiring.
 */

import { getSectionCollapsed, setSectionCollapsed } from './section_collapse_state.js'
import { showToast } from './toast.js'
import { filterJobsForPart } from './md_jobs_panel.js'
import { statusBadge, statusKeyFor } from './job_status_symbol.js'
import { formatJobTime } from '../scene/trajectory_range.js'
import { confirmNoConcurrentJob } from './job_activity.js'
import { initCandoMetricsCard } from './cando_metrics_card.js'
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
export function candoJobIsActive(job) {
  return ['queued', 'preparing', 'running'].includes(job?.status)
}

/**
 * Should a new FEM launch be blocked (pure; unit-tested)?  True while a launch is
 * mid-flight (``launching``) or ANY CanDo FEM job is still active — the FEM runs
 * in-process, so ``confirmNoConcurrentJob`` (which only knows MD/oxDNA jobs) can't
 * gate it.  Enforces one-solve-at-a-time and swallows Coarse/Fine double-clicks.
 */
export function launchBlocked(launching, jobs, selectedJob) {
  if (launching) return true
  if (Array.isArray(jobs) && jobs.some(candoJobIsActive)) return true
  return candoJobIsActive(selectedJob)
}

/** Human name for the solver mode of a job. */
export function solverLabel(job) {
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
      return `Solving FEM — ${solverLabel(job)} ${pct}${etaStr}`
    }
    case 'completed': {
      const s = job.sim_seconds ? ` in ${job.sim_seconds}s` : ''
      const n = job.n_nodes ? ` · ${job.n_nodes} bp nodes` : ''
      return `Predicted (${solverLabel(job)})${s}${n}.`
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
 * Completed-job summary HTML (solver / RMSF range).  Pure (unit-tested); returns an
 * HTML string the panel drops into the summary div, or '' when there's nothing to
 * show (job not completed).
 */
export function formatSummary(job) {
  if (!job || job.status !== 'completed') return ''
  const bits = [`<b>${solverLabel(job)}</b> solve`]
  if (job.n_nodes) bits.push(`${job.n_nodes} bp nodes`)
  if (typeof job.rmsf_min_nm === 'number' && typeof job.rmsf_max_nm === 'number') {
    bits.push(`RMSF ${job.rmsf_min_nm.toFixed(2)}–${job.rmsf_max_nm.toFixed(2)} nm`)
  }
  return bits.join(' · ')
}

const _fmtNm = (v) => (v == null ? '—' : `${Number(v).toFixed(2)} nm`)
const _fmtDeg = (v) => (v == null ? '—' : `${Number(v).toFixed(1)}°`)

/**
 * Live status line for a CanDo-autorefine poll payload ``{state, phase, last_event, result,
 * error}`` (pure; unit-tested).  While running + on an iteration event it shows the iteration
 * index and the CURRENT vs TARGET twist / curvature / deviation; on done it summarises the edit
 * count + before/after deviation.
 */
export function autorefineStatusText(run) {
  if (!run) return ''
  if (run.state === 'error') return `Failed: ${run.error || 'autorefine error'}`
  if (run.state === 'stopped') return 'Stopped.'
  if (run.state === 'done') {
    const m = run.result?.metrics
    const kept = run.result?.edits_kept?.length ?? 0
    const editStr = `${kept} edit${kept === 1 ? '' : 's'}`
    if (m) return `Done · ${editStr} · deviation ${_fmtNm(m.after?.deviation)} (was ${_fmtNm(m.before?.deviation)})`
    return `Done · ${editStr}`
  }
  // Prefer the last ITERATION event's metrics (retained by the route) so the twist/curve/deviation
  // line persists through the interspersed trial events; fall back to phase text otherwise.
  const it = run.last_iteration
    || (run.last_event?.phase === 'iteration' ? run.last_event : null)
  if (it) {
    const c = it.current || {}, t = it.target || {}
    const of = it.n_hotspots ? `/${it.n_hotspots}` : ''
    return `Iteration ${it.iteration ?? 0}${of} · dev ${_fmtNm(c.deviation)}→${_fmtNm(t.deviation)}`
      + ` · curve ${_fmtDeg(c.bend_deg)}→${_fmtDeg(t.bend_deg)}`
      + ` · twist ${_fmtDeg(c.twist_deg)}→${_fmtDeg(t.twist_deg)}`
  }
  const ev = run.last_event || {}
  if (ev.phase === 'baseline') return 'Solving baseline shape…'
  if (ev.phase === 'hotspots') return `Found ${ev.n} deviation hotspot${ev.n === 1 ? '' : 's'}…`
  return 'Autorefining…'
}

/** Compact before→after result summary HTML for a finished autorefine (pure; unit-tested). */
export function autorefineResultHtml(result) {
  if (!result) return ''
  const m = result.metrics || {}
  const kept = result.edits_kept?.length ?? 0
  const mode = result.mode === 'skips_only' ? 'skips' : 'loops+skips'
  const rows = [
    `deviation ${_fmtNm(m.before?.deviation)} → <b>${_fmtNm(m.after?.deviation)}</b> (target 0)`,
    `curvature ${_fmtDeg(m.before?.bend_deg)} → <b>${_fmtDeg(m.after?.bend_deg)}</b> (target ${_fmtDeg(m.target?.bend_deg)})`,
    `twist ${_fmtDeg(m.before?.twist_deg)} → <b>${_fmtDeg(m.after?.twist_deg)}</b> (target ${_fmtDeg(m.target?.twist_deg)})`,
  ]
  return `<div style="font-size:11px;color:#8b949e;line-height:1.5">`
    + `<div>${kept} ${mode} edit${kept === 1 ? '' : 's'} kept</div>`
    + rows.map((r) => `<div>${r}</div>`).join('') + `</div>`
}

// ── Factory ───────────────────────────────────────────────────────────────────

export function initCandoJobsPanel({ candoDisplay = null, getWorkspacePath = null } = {}) {
  const $ = (id) => document.getElementById(id)
  const panel = $('cando-jobs-panel')
  const heading = $('cando-jobs-heading')
  const body = $('cando-jobs-body')
  if (!panel || !heading || !body) return { refresh: () => {}, getSelectedJob: () => null }

  const arrow = $('cando-jobs-arrow')
  const coarseBtn = $('cando-jobs-coarse-btn')
  const fineBtn = $('cando-jobs-fine-btn')
  const progressEl = $('cando-jobs-progress')
  const advToggle = $('cando-jobs-adv-toggle')
  const advArrow = $('cando-jobs-adv-arrow')
  const advBody = $('cando-jobs-adv-body')
  const displayToggle = $('cando-display-toggle')
  const displayArrow = $('cando-display-arrow')
  const displayCard = $('cando-display-card')
  const stepsInput = $('cando-jobs-n-steps')
  const rmsfInput = $('cando-jobs-with-rmsf')
  const showAll = $('cando-jobs-show-all')
  const listEl = $('cando-jobs-list')
  const detail = $('cando-jobs-detail')
  const detailStatus = $('cando-jobs-detail-status')
  const timeline = $('cando-jobs-timeline')
  const summaryEl = $('cando-jobs-summary')
  const detailError = $('cando-jobs-detail-error')
  const stopBtn = $('cando-jobs-stop-btn')
  const deleteBtn = $('cando-jobs-delete-btn')
  const displayStatus = $('cando-jobs-display-status')
  const modeRadios = () => Array.from(panel.querySelectorAll('.cando-display-mode'))
  const checkedMode = () => modeRadios().find((r) => r.checked)?.value || 'off'
  const setMode = (value) => modeRadios().forEach((r) => { r.checked = r.value === value })

  let _jobs = []
  let _selectedId = null
  let _progress = null
  let _pollTimer = null
  let _launching = false   // re-entrancy guard: a launch is between click and job-registered

  const _selectedJob = () => _jobs.find((j) => j.job_id === _selectedId) || null

  // Graphs & Metrics card — a child module reading the panel's job selection.
  const _metricsCard = initCandoMetricsCard({ getSelectedJob: _selectedJob })

  // ── Collapse ────────────────────────────────────────────────────────────────
  function _applyCollapsed(collapsed) {
    body.style.display = collapsed ? 'none' : ''
    if (arrow) arrow.textContent = collapsed ? '▸' : '▾'
    if (!collapsed) _onOpen()
    else _clearPoll()
  }
  heading.addEventListener('click', () => {
    const next = body.style.display !== 'none'
    setSectionCollapsed('dynamics', 'cando-jobs-panel', next)
    _applyCollapsed(next)
  })
  if (advToggle) {
    advToggle.addEventListener('click', () => {
      const hidden = advBody.style.display === 'none'
      advBody.style.display = hidden ? '' : 'none'
      if (advArrow) advArrow.textContent = hidden ? '▾' : '▸'
    })
  }
  // Display card (the mutually-exclusive viz-mode radios) — collapsible, starts open.
  if (displayToggle) {
    displayToggle.addEventListener('click', () => {
      const hidden = displayCard.style.display === 'none'
      displayCard.style.display = hidden ? '' : 'none'
      if (displayArrow) displayArrow.textContent = hidden ? '▾' : '▸'
    })
  }

  // ── Run (Coarse = linear preview; Fine = nonlinear corotational) ──────────────
  /** Disable Coarse/Fine while a solve is being launched or is still running, so a
   *  second click can't spawn a duplicate job (the FEM is in-process — no external
   *  concurrency gate). Re-enabled by _fetchJobs' poll once the job finishes. */
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
    // Synchronous guard: bail before any await so a fast double-click can't slip a
    // second launch through while the first is still awaiting the confirm / create.
    if (launchBlocked(_launching, _jobs, _selectedJob())) return
    _launching = true
    _updateLaunchButtons()
    try {
      if (!(await confirmNoConcurrentJob())) return
      const body_ = {
        nonlinear,
        n_steps:   Math.max(1, parseInt(stepsInput?.value, 10) || 20),
        with_rmsf: rmsfInput ? !!rmsfInput.checked : true,
        autostart: true,
        design_source_path: getWorkspacePath?.() || null,
      }
      const job = await api.createCandoJob(body_)
      if (!job) {
        showToast(api.lastErrorMessage() || 'Failed to start CanDo FEM prediction', { severity: 'error' })
        return
      }
      _selectedId = job.job_id
      await _fetchJobs()
    } finally {
      _launching = false
      _updateLaunchButtons()   // stays disabled if the new job is now active
    }
  }
  coarseBtn?.addEventListener('click', () => _launch(false))
  fineBtn?.addEventListener('click', () => _launch(true))

  // ── Autorefine (Phase-5 Item 4): FEM-oracle greedy loop/skip tuning ───────────
  const arBtn = $('cando-jobs-autorefine-btn')
  const arStopBtn = $('cando-jobs-autorefine-stop-btn')
  const arStatus = $('cando-jobs-autorefine-status')
  const arResult = $('cando-jobs-autorefine-result')
  const _SPIN = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']
  let _arRunning = false
  let _arRunId = null
  let _arPollTimer = null
  let _arSpin = 0
  let _arSpinTimer = null
  let _arBase = ''
  let _arColor = _C.dim

  function _renderArStatus() {
    if (!arStatus) return
    arStatus.textContent = (_arRunning ? _SPIN[_arSpin % _SPIN.length] + ' ' : '') + (_arBase || '')
    arStatus.style.color = _arColor
  }
  function _setArStatus(text, color, spinning = false) {
    _arBase = text || ''; _arColor = color || _C.dim
    if (spinning && !_arSpinTimer) _arSpinTimer = setInterval(() => { _arSpin++; _renderArStatus() }, 120)
    else if (!spinning && _arSpinTimer) { clearInterval(_arSpinTimer); _arSpinTimer = null }
    _renderArStatus()
  }
  function _clearArPoll() { if (_arPollTimer) { clearTimeout(_arPollTimer); _arPollTimer = null } }
  function _updateArButton() {
    if (!arBtn) return
    arBtn.disabled = _arRunning
    arBtn.style.cursor = _arRunning ? 'not-allowed' : 'pointer'
    arBtn.style.opacity = _arRunning ? '0.5' : '1'
    if (arStopBtn) arStopBtn.style.display = _arRunning ? '' : 'none'
  }

  async function _applyArResult(runId) {
    const applied = await api.applyCandoAutorefine(runId)
    if (!applied || !applied.design) {
      showToast(api.lastErrorMessage() || 'Failed to apply autorefine marks', { severity: 'error' })
      return
    }
    api.syncDesignResponse(applied)   // updates editor + Feature Log, fires nadoc:design-changed
    showToast('Autorefine loop/skips applied to the design', { severity: 'info' })
  }

  function _renderArResult(runId, result) {
    if (!arResult) return
    arResult.innerHTML = ''
    if (!result || !(result.edits_kept?.length)) {
      arResult.innerHTML = `<div style="font-size:11px;color:${_C.dim}">No improving edit found — the design already matches its intended shape as closely as the loop/skips allow.</div>`
      return
    }
    const box = document.createElement('div')
    box.innerHTML = autorefineResultHtml(result)
    const apply = document.createElement('button')
    apply.textContent = '✓ Apply to design'
    apply.style.cssText = 'margin-top:5px;font-size:var(--text-xs);padding:5px 8px;background:#122117;border:1px solid #3fb950;color:#3fb950;border-radius:3px;cursor:pointer;font-weight:600'
    apply.addEventListener('click', async () => {
      apply.disabled = true; apply.textContent = 'Applying…'
      await _applyArResult(runId)
      apply.textContent = '✓ Applied'
    })
    box.appendChild(apply)
    arResult.appendChild(box)
  }

  async function _pollAutorefine(runId) {
    let run
    try { run = await api.getCandoAutorefine(runId) } catch { run = null }
    if (!run) { _arPollTimer = setTimeout(() => _pollAutorefine(runId), 1200); return }
    if (run.state === 'running') {
      _setArStatus(autorefineStatusText(run), _C.warn, true)
      _arPollTimer = setTimeout(() => _pollAutorefine(runId), 1000)
      return
    }
    // terminal (done / stopped / error)
    _arRunning = false
    _updateArButton()
    const color = run.state === 'error' ? _C.err : run.state === 'stopped' ? _C.dim : _C.ok
    _setArStatus(autorefineStatusText(run), color, false)
    if (run.state === 'done') _renderArResult(runId, run.result)
  }

  async function _startAutorefine() {
    if (_arRunning) return
    if (!(await confirmNoConcurrentJob())) return
    _arRunning = true; _arRunId = null
    if (arResult) arResult.innerHTML = ''
    _updateArButton()
    _setArStatus('Starting autorefine…', _C.warn, true)
    // Coarse (linear) FEM oracle per trial — fast; the user re-runs a Fine job to confirm.
    const r = await api.startCandoAutorefine({ nonlinear: false })
    if (!r || !r.autorefine_id) {
      _arRunning = false; _updateArButton()
      _setArStatus('Failed to start: ' + (api.lastErrorMessage() || 'no marks or bend/twist to refine'), _C.err, false)
      return
    }
    _arRunId = r.autorefine_id
    _pollAutorefine(_arRunId)
  }
  arBtn?.addEventListener('click', _startAutorefine)
  arStopBtn?.addEventListener('click', async () => {
    if (!_arRunId) return
    if (arStopBtn) arStopBtn.disabled = true
    _setArStatus('Stopping…', _C.dim, true)
    await api.stopCandoAutorefine(_arRunId)
    if (arStopBtn) arStopBtn.disabled = false
  })

  // ── Jobs list + poll ────────────────────────────────────────────────────────
  async function _fetchJobs() {
    const all = await api.listCandoJobs()
    if (!Array.isArray(all)) return
    _jobs = filterJobsForPart(all, getWorkspacePath?.() || null, showAll?.checked)
    _renderList()
    _updateLaunchButtons()   // re-enable Coarse/Fine once no job is active
    if (_selectedId) {
      _progress = await api.getCandoProgress(_selectedId)
      const job = _selectedJob()
      // Live-follow: re-apply the active display mode when a running job completes.
      if (job && job.status === 'completed' && candoDisplay?.deformActive?.()
          && candoDisplay.deformJobId?.() === _selectedId) {
        await candoDisplay.refresh?.()
      }
      _renderDetail()
    }
    _scheduleNextPoll()
  }

  function _hasActiveJob() {
    return launchBlocked(false, _jobs, _selectedJob())
  }

  function _clearPoll() {
    if (_pollTimer) { clearTimeout(_pollTimer); _pollTimer = null }
  }
  function _scheduleNextPoll() {
    _clearPoll()
    if (body.style.display === 'none') return
    if (_hasActiveJob()) _pollTimer = setTimeout(_fetchJobs, POLL_MS)
  }

  function _renderList() {
    if (!listEl) return
    listEl.innerHTML = ''
    if (!_jobs.length) {
      const empty = document.createElement('div')
      empty.style.cssText = `color:${_C.dim};font-size:11px;padding:4px`
      empty.textContent = 'No CanDo FEM jobs for this design yet.'
      listEl.appendChild(empty)
      return
    }
    for (const job of _jobs) {
      const row = document.createElement('div')
      row.style.cssText =
        `display:flex;align-items:center;gap:6px;padding:3px 4px;cursor:pointer;font-size:11px;` +
        `border-radius:3px;${job.job_id === _selectedId ? 'background:#2a3a4a;' : ''}`
      const badge = statusBadge(statusKeyFor('cando', job.status))
      row.innerHTML =
        `<span title="${job.status}">${badge?.symbol ?? '•'}</span>` +
        `<span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${jobDisplayName(job)}</span>` +
        `<span style="color:${_C.dim}">${job.nonlinear ? 'Fine' : 'Coarse'}</span>` +
        `<span style="color:${_C.dim}">${formatJobTime(job.created_at)}</span>`
      row.addEventListener('click', () => _selectJob(job.job_id))
      listEl.appendChild(row)
    }
  }

  async function _selectJob(jobId) {
    _selectedId = jobId
    _progress = await api.getCandoProgress(jobId)
    _renderList()
    _renderDetail()
    await _retargetDisplayToSelection()
    _scheduleNextPoll()
  }

  /** When a display mode is active and the user selects a DIFFERENT job, retarget the
   *  active mode to the newly-selected job so the 3D model updates to THIS job's
   *  snapshot + predicted shape (rather than keeping the previous job's shape on
   *  screen).  Turns the display off if the new job can't support the current mode. */
  async function _retargetDisplayToSelection() {
    if (!candoDisplay?.deformActive?.()) return
    if (candoDisplay.deformJobId?.() === _selectedId) return   // already showing this job
    const mode = checkedMode()
    const job = _selectedJob()
    const canShow = mode !== 'off' && job?.status === 'completed'
      && (mode !== 'flex' || !!job?.rmsf_max_nm)
    if (!canShow) {
      candoDisplay.stopDeform?.(); setMode('off'); _syncDisplayStatus()
      return
    }
    const r = await candoDisplay[_MODE_FNS[mode]]?.(_selectedId)
    if (!r?.ok) { candoDisplay.stopDeform?.(); setMode('off') }
    _syncDisplayStatus()
  }

  function _renderDetail() {
    const job = _selectedJob()
    _syncDisplayModes()   // the Display card is always visible; gate its radios here
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
    if (deleteBtn) deleteBtn.disabled = job.status === 'running'
    _syncDisplayStatus()
    _metricsCard?.sync()
  }

  /** Gate the always-visible Display card's radios: enabled only for a completed job
   *  (+ the candoDisplay dep); the Flexibility map additionally needs computed RMSF.
   *  No selection / an unfinished job leaves every radio locked. */
  function _syncDisplayModes() {
    const job = _selectedJob()
    const ready = job?.status === 'completed'
    modeRadios().forEach((r) => {
      const needsRmsf = r.value === 'flex'
      r.disabled = !ready || !candoDisplay || (needsRmsf && !job?.rmsf_max_nm)
    })
  }

  /** Readout under the radios: the active mode + its scalar range / RMSD. */
  function _syncDisplayStatus() {
    if (!displayStatus) return
    const mode = candoDisplay?.mode?.()
    if (!mode) { displayStatus.textContent = ''; return }
    const s = candoDisplay?.lastStats?.()
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
      await api.stopCandoJob(_selectedId)
      await _fetchJobs()
    })
  }
  if (deleteBtn) {
    deleteBtn.addEventListener('click', async () => {
      if (!_selectedId) return
      const r = await api.deleteCandoJob(_selectedId)
      if (r?.ok) {
        if (candoDisplay?.deformJobId?.() === _selectedId) candoDisplay.stopDeform?.()
        _selectedId = null
        detail && (detail.style.display = 'none')
        await _fetchJobs()
      } else {
        showToast(api.lastErrorMessage() || 'Delete failed', { severity: 'error' })
      }
    })
  }

  // ── Display-mode radios (Off / Predicted shape / Flexibility / Deviation) ─────
  // Mutually exclusive; each supersedes the shared FEM overlay + scalar-colour channel.
  const _MODE_FNS = { deform: 'showDeform', flex: 'showFlex', deviation: 'showDeviation', cando: 'showCandoStyle' }
  async function _onModeChange() {
    if (!candoDisplay) { setMode('off'); return }
    const mode = checkedMode()
    if (mode === 'off') { candoDisplay.stopDeform?.(); _syncDisplayStatus(); return }
    if (!_selectedId) { setMode('off'); return }
    const r = await candoDisplay[_MODE_FNS[mode]]?.(_selectedId)
    if (!r?.ok) {
      setMode('off'); candoDisplay.stopDeform?.()
      showToast(mode === 'flex' ? 'RMSF not available for this job'
        : 'Predicted positions not ready', { severity: 'warn' })
    }
    _syncDisplayStatus()
  }
  modeRadios().forEach((r) => r.addEventListener('change', _onModeChange))
  if (showAll) showAll.addEventListener('change', _fetchJobs)

  // ── Cross-panel coordination ──────────────────────────────────────────────────
  function _stopDisplays() {
    candoDisplay?.stopAndRestore?.()
    setMode('off')
    _syncDisplayStatus()
    _metricsCard?.refresh()   // cached flex/deviation graphs no longer match the design
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

  const collapsed = getSectionCollapsed('dynamics', 'cando-jobs-panel', true)
  _applyCollapsed(collapsed)

  return { refresh: _fetchJobs, getSelectedJob: _selectedJob }
}
