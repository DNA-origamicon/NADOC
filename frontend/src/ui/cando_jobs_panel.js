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
  async function _launch(nonlinear) {
    if (!(await confirmNoConcurrentJob())) return
    const body_ = {
      nonlinear,
      n_steps:   Math.max(1, parseInt(stepsInput?.value, 10) || 20),
      with_rmsf: rmsfInput ? !!rmsfInput.checked : true,
      autostart: true,
      design_source_path: getWorkspacePath?.() || null,
    }
    if (coarseBtn) coarseBtn.disabled = true
    if (fineBtn) fineBtn.disabled = true
    const job = await api.createCandoJob(body_)
    if (coarseBtn) coarseBtn.disabled = false
    if (fineBtn) fineBtn.disabled = false
    if (!job) {
      showToast(api.lastErrorMessage() || 'Failed to start CanDo FEM prediction', { severity: 'error' })
      return
    }
    _selectedId = job.job_id
    await _fetchJobs()
  }
  coarseBtn?.addEventListener('click', () => _launch(false))
  fineBtn?.addEventListener('click', () => _launch(true))

  // ── Jobs list + poll ────────────────────────────────────────────────────────
  async function _fetchJobs() {
    const all = await api.listCandoJobs()
    if (!Array.isArray(all)) return
    _jobs = filterJobsForPart(all, getWorkspacePath?.() || null, showAll?.checked)
    _renderList()
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
    if (_jobs.some(candoJobIsActive)) return true
    const job = _selectedJob()
    return job ? candoJobIsActive(job) : false
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
    _scheduleNextPoll()
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
