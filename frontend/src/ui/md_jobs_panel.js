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

import { getSectionCollapsed, setSectionCollapsed } from './section_collapse_state.js'
import { showOpProgress, hideOpProgress, setOpProgressLabel } from './op_progress.js'
import { showToast } from './toast.js'
import { docKey, docHeaders } from '../shared/doc_id.js'

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
const _PRODUCTION_TIMESTEP_FS = 1.0
const _PRODUCTION_STEPS_PER_NS = 1_000_000 / _PRODUCTION_TIMESTEP_FS
const _SHOW_ALL_KEY = 'nadoc:md-jobs-show-all'
const _WORKSPACE_PATH_KEY = 'nadoc:workspace-path'
const _MD_PREWARM_INTERVAL_MS = 30000

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


// ── Public entry point ────────────────────────────────────────────────────────

export function initMdJobsPanel({ mdDisplayController = null, getWorkspacePath = null } = {}) {
  const panel   = document.getElementById('md-jobs-panel')
  const heading = document.getElementById('md-jobs-panel-heading')
  const arrow   = document.getElementById('md-jobs-panel-arrow')
  const body    = document.getElementById('md-jobs-panel-body')
  if (!panel || !heading || !body) return

  // Form elements
  const namdStatusEl  = document.getElementById('md-jobs-namd-status')
  const presetSel     = document.getElementById('md-jobs-preset')
  const runBtn        = document.getElementById('md-jobs-run-btn')
  const advToggle     = document.getElementById('md-jobs-adv-toggle')
  const advArrow      = document.getElementById('md-jobs-adv-arrow')
  const advBody       = document.getElementById('md-jobs-adv-body')
  const threadsInput  = document.getElementById('md-jobs-threads')
  const devicesInput  = document.getElementById('md-jobs-devices')
  const saltModeSel   = document.getElementById('md-jobs-salt-mode')
  const mgInput       = document.getElementById('md-jobs-mg')
  const naclInput     = document.getElementById('md-jobs-nacl')
  const paddingInput  = document.getElementById('md-jobs-padding')
  const minstepsInput = document.getElementById('md-jobs-minsteps')
  const autostartChk  = document.getElementById('md-jobs-autostart')
  const displayToggle = document.getElementById('md-jobs-display-toggle')
  const displayStatus = document.getElementById('md-jobs-display-status')
  const showAllToggle = document.getElementById('md-jobs-show-all')

  // List + detail
  const listEl      = document.getElementById('md-jobs-list')
  const detailEl    = document.getElementById('md-jobs-detail')
  const statusEl    = document.getElementById('md-jobs-detail-status')
  const startBtn    = document.getElementById('md-jobs-start-btn')
  const stopBtn     = document.getElementById('md-jobs-stop-btn')
  const errorEl     = document.getElementById('md-jobs-detail-error')
  const progressEl  = document.getElementById('md-jobs-progress')
  const timelineEl  = document.getElementById('md-jobs-timeline')
  const metricsEl   = document.getElementById('md-jobs-metrics')
  const loadFramesBtn = document.getElementById('md-jobs-load-frames-btn')
  const deleteBtn     = document.getElementById('md-jobs-delete-btn')
  const prodBox       = document.getElementById('md-jobs-production')
  const prodStepsInput = document.getElementById('md-jobs-prod-steps')
  const prodTimeEl    = document.getElementById('md-jobs-prod-time')
  const prodContinueChk = document.getElementById('md-jobs-prod-continue')
  const prodBtn       = document.getElementById('md-jobs-prod-btn')
  const prodStatus    = document.getElementById('md-jobs-prod-status')

  // ── State ──────────────────────────────────────────────────────────────────
  let _jobs         = []     // cached list from API
  let _selectedId   = null   // currently displayed job_id
  let _ws           = null   // active WebSocket
  let _pollTimer    = null   // REST fallback poll interval
  let _advOpen      = false
  let _collapsed    = getSectionCollapsed('dynamics', 'md-jobs-panel', true)
  let _launching    = false
  let _enginesOk    = false  // both NAMD + GROMACS found
  let _displayTimer = null
  let _prewarmTimer = null
  let _displayJobId = null
  let _displayKey   = null
  let _displayMeta  = null
  let _prewarmKey   = null
  const _metricsByJob = new Map()

  if (showAllToggle) showAllToggle.checked = localStorage.getItem(_SHOW_ALL_KEY) === '1'

  // ── Collapse ───────────────────────────────────────────────────────────────
  body.style.display = _collapsed ? 'none' : ''
  arrow.classList.toggle('is-collapsed', _collapsed)
  heading.addEventListener('click', () => {
    _collapsed = !_collapsed
    body.style.display = _collapsed ? 'none' : ''
    arrow.classList.toggle('is-collapsed', _collapsed)
    setSectionCollapsed('dynamics', 'md-jobs-panel', _collapsed)
    if (!_collapsed) _onOpen()
  })

  // ── Advanced drawer ────────────────────────────────────────────────────────
  advToggle?.addEventListener('click', () => {
    _advOpen = !_advOpen
    if (advBody) advBody.style.display = _advOpen ? '' : 'none'
    if (advArrow) advArrow.style.transform = _advOpen ? 'rotate(90deg)' : ''
  })

  function _applySaltMode() {
    const screening = (saltModeSel?.value ?? 'screening') === 'screening'
    if (mgInput) {
      mgInput.disabled = screening
      mgInput.value = screening ? '12.5' : mgInput.value
      mgInput.style.opacity = screening ? '0.55' : '1'
    }
    if (naclInput) {
      naclInput.disabled = screening
      naclInput.value = screening ? '0' : naclInput.value
      naclInput.style.opacity = screening ? '0.55' : '1'
    }
  }
  saltModeSel?.addEventListener('change', _applySaltMode)
  _applySaltMode()

  // ── Engine availability check ─────────────────────────────────────────────
  async function _checkEngines() {
    if (!namdStatusEl) return
    console.log(`[${_ts()}] md-jobs: checking engines`)
    try {
      const r = await fetch('/api/md/namd-available')
      const d = await r.json()
      console.log(`[${_ts()}] md-jobs: engines response`, d)

      _enginesOk = d.available

      if (d.namd_available && d.gmx_available) {
        namdStatusEl.textContent = `NAMD3 + GROMACS found`
        namdStatusEl.style.color = _C.ok
        if (runBtn) runBtn.disabled = false
      } else {
        const missing = []
        if (!d.namd_available) missing.push('NAMD3 (install to ~/Applications/NAMD_3.0.2/)')
        if (!d.gmx_available)  missing.push('GROMACS (install + add gmx to PATH)')
        namdStatusEl.textContent = `Missing: ${missing.join(', ')}`
        namdStatusEl.style.color = _C.err
        if (runBtn) runBtn.disabled = true
      }
    } catch (err) {
      console.warn(`[${_ts()}] md-jobs: engine check failed`, err)
      namdStatusEl.textContent = 'Could not check engine status'
      namdStatusEl.style.color = _C.warn
    }
  }

  // ── Job list fetch ─────────────────────────────────────────────────────────
  async function _fetchJobs() {
    try {
      const r = await fetch('/api/md/jobs')
      _jobs = await r.json()
      _jobs.sort((a, b) => b.created_at - a.created_at)
      console.log(`[${_ts()}] md-jobs: fetched ${_jobs.length} jobs`)
      _renderList()
      _selectBestJob()
      if (displayToggle?.checked) _refreshMdDisplay()
      else _refreshMdPrewarm()
    } catch (err) {
      console.warn(`[${_ts()}] md-jobs: _fetchJobs failed`, err)
    }
  }

  function _selectBestJob() {
    const jobs = _visibleJobs()
    if (!jobs.length) {
      _clearSelectedJob()
      return
    }
    const selected = jobs.find(j => j.job_id === _selectedId)
    const active = jobs.find(j => ['running', 'preparing'].includes(j.status))
    if (!_selectedId || !selected) {
      _selectJob((active ?? jobs[0]).job_id)
      return
    }
    if (active && !['running', 'preparing'].includes(selected.status)) {
      _selectJob(active.job_id)
    }
  }

  function _onOpen() {
    _checkEngines()
    _fetchJobs()
    _startMdPrewarm()
  }

  function _isDynamicsTabVisible() {
    const pane = document.getElementById('tab-content-dynamics')
    return !!pane && !pane.hidden
  }

  function _setDisplayStatus(text, color = _C.dim) {
    if (!displayStatus) return
    displayStatus.textContent = text
    displayStatus.style.color = color
  }

  function _setProductionStatus(text, color = _C.dim) {
    if (!prodStatus) return
    prodStatus.textContent = text
    prodStatus.style.color = color
  }

  function _clearSelectedJob() {
    _selectedId = null
    _displayMeta = null
    _closeWs()
    if (detailEl) detailEl.style.display = 'none'
    if (statusEl) statusEl.textContent = ''
    if (errorEl) {
      errorEl.style.display = 'none'
      errorEl.textContent = ''
    }
    if (progressEl) progressEl.textContent = ''
    if (timelineEl) timelineEl.textContent = ''
    if (metricsEl) metricsEl.textContent = ''
    _renderProductionControls(null)
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

  function _productionSteps() {
    return Math.max(100, parseInt(prodStepsInput?.value ?? '500000', 10) || 500000)
  }

  function _productionNs(steps = _productionSteps()) {
    return steps / _PRODUCTION_STEPS_PER_NS
  }

  function _updateProductionTime() {
    const steps = _productionSteps()
    if (prodStepsInput && String(steps) !== prodStepsInput.value) prodStepsInput.value = String(steps)
    if (prodTimeEl) prodTimeEl.textContent = `${_productionNs(steps).toFixed(3)} ns`
  }

  function _setProductionEnabled(enabled) {
    if (!prodBtn) return
    prodBtn.disabled = !enabled
    prodBtn.style.background = enabled ? '#1a4a1a' : '#122117'
    prodBtn.style.borderColor = enabled ? _C.ok : _C.border
    prodBtn.style.color = enabled ? _C.ok : _C.dim
    prodBtn.style.cursor = enabled ? 'pointer' : 'not-allowed'
  }

  function _renderProductionControls(job, meta = _displayMeta) {
    if (!job) {
      _setProductionEnabled(false)
      _setProductionStatus('Select a relaxed job to enable production', _C.dim)
      return
    }
    const terminalOk = ['completed', 'queued', 'stopped', 'failed'].includes(job.status)
    const continueMode = !!prodContinueChk?.checked
    const ready = terminalOk && (continueMode ? !!meta?.production_continue_available : !!meta?.production_ready)
    if (prodBox) prodBox.style.display = ''
    _setProductionEnabled(ready)
    _updateProductionTime()
    if (!ready) {
      const reason = continueMode
        ? (meta?.production_continue_reason || 'No completed production run is available to continue from')
        : (meta?.production_ready_reason || 'Production unlocks after minimization and restraint release pass health checks')
      _setProductionStatus(reason, _C.dim)
      return
    }
    const checkpoint = continueMode ? meta.production_continue_checkpoint : meta.production_checkpoint
    const readyText = `${continueMode ? 'Continue' : 'Ready'} from ${checkpoint}; ${_productionSteps().toLocaleString()} steps = ${_productionNs().toFixed(3)} ns`
    if (!continueMode && meta.production_warning) {
      _setProductionStatus(`${readyText}. Warning: ${meta.production_warning}`, _C.warn)
      return
    }
    _setProductionStatus(readyText, _C.ok)
  }

  prodStepsInput?.addEventListener('input', () => {
    _updateProductionTime()
    const job = _jobs.find(j => j.job_id === _selectedId)
    _renderProductionControls(job)
  })
  prodContinueChk?.addEventListener('change', () => {
    const job = _jobs.find(j => j.job_id === _selectedId)
    _renderProductionControls(job)
  })
  _updateProductionTime()

  async function _fetchDisplayMeta(jobId = _selectedId) {
    if (!jobId) return null
    try {
      const r = await fetch(`/api/md/jobs/${jobId}/display`)
      const d = await r.json()
      if (!r.ok) throw new Error(d?.detail ?? `Server error ${r.status}`)
      _displayMeta = d
      const job = _jobs.find(j => j.job_id === jobId)
      if (job) _renderProductionControls(job, d)
      return d
    } catch (err) {
      console.warn(`[${_ts()}] md-jobs: display metadata failed`, err)
      return null
    }
  }

  async function _fetchJobMetrics(jobId = _selectedId) {
    if (!jobId) return []
    try {
      const r = await fetch(`/api/md/jobs/${jobId}/metrics`)
      const d = await r.json()
      if (!r.ok) throw new Error(d?.detail ?? `Server error ${r.status}`)
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
      jobs.find(j => j.status === 'running') ??
      jobs[0] ??
      null
    )
  }

  function _jobNeedsLiveDisplay(job) {
    return job?.status === 'queued' || job?.status === 'preparing' || job?.status === 'running'
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

    try {
      const d = await _fetchDisplayMeta(job.job_id)
      if (!d) throw new Error('Could not load MD display metadata')
      _renderProductionControls(job, d)
      if (!d.ready || !d.config_path) {
        _displayJobId = job.job_id
        _displayKey = null
        _setDisplayStatus(`Waiting for trajectory output (${job.status})`, _C.warn)
        return
      }

      const key = `${d.config_path}|${d.trajectory_path ?? ''}|${d.segment_name ?? ''}`
      const forceReload = key !== _displayKey || job.job_id !== _displayJobId
      const live = _jobNeedsLiveDisplay(job)
      _displayJobId = job.job_id
      _displayKey = key
      _setDisplayStatus(forceReload ? `Loading ${d.segment_name ?? 'latest MD segment'}...` : `Refreshing ${d.segment_name ?? 'latest frame'}...`, _C.muted)
      mdDisplayController.displayLatest(d.config_path, { forceReload, live })
      if (!live) {
        clearInterval(_displayTimer)
        _displayTimer = null
      }
    } catch (err) {
      console.warn(`[${_ts()}] md-jobs: display refresh failed`, err)
      _setDisplayStatus(`Display failed: ${err.message}`, _C.err)
    }
  }

  async function _refreshMdPrewarm(force = false) {
    if (displayToggle?.checked) return
    if (!_isDynamicsTabVisible()) return
    if (!mdDisplayController?.prewarmLatest) return

    const job = _selectDisplayJob()
    if (!job) return

    try {
      const d = await _fetchDisplayMeta(job.job_id)
      if (!d?.ready || !d.config_path) return
      const key = `${d.config_path}|${d.trajectory_path ?? ''}|${d.segment_name ?? ''}`
      const forceReload = force || key !== _prewarmKey
      _prewarmKey = key
      mdDisplayController.prewarmLatest(d.config_path, { forceReload })
    } catch (err) {
      console.warn(`[${_ts()}] md-jobs: MD display prewarm failed`, err)
    }
  }

  function _startMdPrewarm() {
    if (_prewarmTimer) return
    _refreshMdPrewarm(true)
    _prewarmTimer = setInterval(_refreshMdPrewarm, _MD_PREWARM_INTERVAL_MS)
  }

  function _stopMdPrewarm() {
    clearInterval(_prewarmTimer)
    _prewarmTimer = null
    _prewarmKey = null
    mdDisplayController?.stopPrewarm?.()
  }

  function _startMdDisplay() {
    if (!displayToggle) return
    displayToggle.checked = true
    clearInterval(_prewarmTimer)
    _prewarmTimer = null
    clearInterval(_displayTimer)
    _setDisplayStatus('Searching for current MD output...', _C.muted)
    _fetchJobs()
    _refreshMdDisplay()
    _displayTimer = setInterval(_refreshMdDisplay, 15000)
  }

  function _stopMdDisplay(status = 'Off') {
    clearInterval(_displayTimer)
    _displayTimer = null
    _displayJobId = null
    _displayKey = null
    if (displayToggle) displayToggle.checked = false
    mdDisplayController?.stopAndRestore?.()
    _setDisplayStatus(status, _C.dim)
    if (_isDynamicsTabVisible()) _startMdPrewarm()
  }

  displayToggle?.addEventListener('change', () => {
    if (displayToggle.checked) _startMdDisplay()
    else _stopMdDisplay('Native positions restored')
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
    _renderList()
    if (displayToggle?.checked) _refreshMdDisplay()
    else _refreshMdPrewarm(true)
  })

  loadFramesBtn?.addEventListener('click', () => {
    if (!_selectedId) return
    _startMdDisplay()
  })

  deleteBtn?.addEventListener('click', async () => {
    if (!_selectedId) return
    const job = _jobs.find(j => j.job_id === _selectedId)
    const label = job ? `${job.design_name} (${job.job_id})` : _selectedId
    if (!window.confirm(`Delete MD job ${label} and all generated files?`)) return
    try {
      const r = await fetch(`/api/md/jobs/${_selectedId}`, { method: 'DELETE' })
      const d = await r.json()
      if (!r.ok) throw new Error(d?.detail ?? `Server error ${r.status}`)
      if (_displayJobId === _selectedId) _stopMdDisplay('Native positions restored')
      showToast('MD job deleted', 'ok')
      _selectedId = null
      await _fetchJobs()
      if (!_jobs.length && detailEl) detailEl.style.display = 'none'
    } catch (err) {
      showToast(`Delete failed: ${err.message}`, 'error')
    }
  })

  prodBtn?.addEventListener('click', async () => {
    if (!_selectedId) return
    const steps = _productionSteps()
    const ns = _productionNs(steps)
    if (prodBtn.disabled) return
    if (prodStatus) {
      prodStatus.textContent = `Appending ${steps.toLocaleString()} production steps (${ns.toFixed(3)} ns)...`
      prodStatus.style.color = _C.muted
    }
    prodBtn.disabled = true
    try {
      const r = await fetch(`/api/md/jobs/${_selectedId}/production`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          steps,
          autostart: true,
          continue_from_production: !!prodContinueChk?.checked,
        }),
      })
      const d = await r.json()
      if (!r.ok) throw new Error(d?.detail ?? `Server error ${r.status}`)
      showToast(`Production started: ${steps.toLocaleString()} steps (${ns.toFixed(3)} ns)`, 'ok')
      await _fetchJobs()
      _selectJob(_selectedId)
    } catch (err) {
      if (prodStatus) {
        prodStatus.textContent = err.message
        prodStatus.style.color = _C.err
      }
      showToast(`Production failed: ${err.message}`, 'error')
    } finally {
      const job = _jobs.find(j => j.job_id === _selectedId)
      _renderProductionControls(job)
    }
  })

  document.querySelectorAll('#left-tab-strip .left-tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      setTimeout(() => {
        if (displayToggle?.checked && !_isDynamicsTabVisible()) {
          _stopMdDisplay('Native positions restored')
        } else if (_isDynamicsTabVisible()) {
          _startMdPrewarm()
        } else {
          _stopMdPrewarm()
        }
      }, 0)
    })
  })

  window.addEventListener('nadoc:left-tab-change', evt => {
    if (evt.detail?.activeTab !== 'dynamics') {
      if (displayToggle?.checked) _stopMdDisplay('Native positions restored')
      else _stopMdPrewarm()
    } else if (!displayToggle?.checked) {
      _startMdPrewarm()
    }
  })

  window.addEventListener('nadoc:md-display-state', evt => {
    if (!displayToggle?.checked) return
    const state = evt.detail?.state
    const message = evt.detail?.message
    if (!message) return
    if (state === 'error') _setDisplayStatus(`Display failed: ${message}`, _C.err)
    else if (state === 'frame') _setDisplayStatus(message, _C.accent)
    else _setDisplayStatus(message, _C.muted)
  })

  // ── Relax button ──────────────────────────────────────────────────────────
  runBtn?.addEventListener('click', async () => {
    if (_launching) {
      console.log(`[${_ts()}] md-jobs: Relax clicked but already launching`)
      return
    }
    _launching = true
    runBtn.disabled = true

    const payload = {
      protocol:       presetSel?.value ?? 'mgh_slow_release',
      threads:        parseInt(threadsInput?.value  ?? '16', 10),
      devices:        devicesInput?.value?.trim()   ?? '0',
      salt_mode:      saltModeSel?.value ?? 'screening',
      mg_conc_mM:     parseFloat(mgInput?.value     ?? '12.5'),
      ion_conc_mM:    parseFloat(naclInput?.value   ?? '0'),
      padding_nm:     parseFloat(paddingInput?.value ?? '1.2'),
      minimize_steps: parseInt(minstepsInput?.value  ?? '10000', 10),
      autostart:      autostartChk?.checked ?? true,
      design_source_path: _currentPartPath() || null,
    }

    console.log(`[${_ts()}] md-jobs: Relax clicked`, payload)
    if (detailEl) detailEl.style.display = ''
    _showPreparingProgress(payload)
    showOpProgress('Relax', 'Solvating structure… (60–120 s)', { indeterminate: true })

    try {
      console.log(`[${_ts()}] md-jobs: POST /api/md/jobs`)
      const r = await fetch('/api/md/jobs', {
        method:  'POST',
        // Doc header is required: the backend reads the ACTIVE design from this
        // tab's document session. Without it the default (empty) doc is used and
        // prep 404s with "No active design."
        headers: { 'Content-Type': 'application/json', ...docHeaders() },
        body:    JSON.stringify(payload),
      })

      console.log(`[${_ts()}] md-jobs: response status=${r.status}`)
      const job = await r.json()
      console.log(`[${_ts()}] md-jobs: response body`, job)

      if (!r.ok) {
        // HTTP error (404 = no active design, 400 = engine missing, etc.)
        hideOpProgress()
        const msg = job?.detail ?? `Server error ${r.status}`
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
        return
      }

      console.log(`[${_ts()}] md-jobs: job created OK job_id=${job.job_id} status=${job.status}`)
      showToast(`Relaxation queued: ${job.job_id}`, 'ok')
      await _fetchJobs()
      _selectJob(job.job_id)
    } catch (err) {
      hideOpProgress()
      console.error(`[${_ts()}] md-jobs: Run fetch threw`, err)
      showToast(`Error: ${err.message}`, 'error')
    } finally {
      _launching = false
      runBtn.disabled = !_enginesOk
    }
  })

  // ── Stop button ────────────────────────────────────────────────────────────
  startBtn?.addEventListener('click', async () => {
    if (!_selectedId) return
    console.log(`[${_ts()}] md-jobs: start ${_selectedId}`)
    try {
      const r = await fetch(`/api/md/jobs/${_selectedId}/start`, { method: 'POST' })
      const d = await r.json()
      console.log(`[${_ts()}] md-jobs: start response`, d)
      if (!r.ok) throw new Error(d?.detail ?? `Server error ${r.status}`)
      showToast('Start requested', 'ok')
      await _fetchJobs()
      _selectJob(_selectedId)
    } catch (err) {
      console.warn(`[${_ts()}] md-jobs: start failed`, err)
      showToast(`Start failed: ${err.message}`, 'error')
    }
  })

  stopBtn?.addEventListener('click', async () => {
    if (!_selectedId) return
    console.log(`[${_ts()}] md-jobs: stop ${_selectedId}`)
    try {
      const r = await fetch(`/api/md/jobs/${_selectedId}/stop`, { method: 'POST' })
      const d = await r.json()
      console.log(`[${_ts()}] md-jobs: stop response`, d)
      showToast('Stop requested', 'warn')
    } catch (err) {
      console.warn(`[${_ts()}] md-jobs: stop failed`, err)
    }
  })

  // ── Job list rendering ─────────────────────────────────────────────────────
  function _renderList() {
    if (!listEl) return
    listEl.innerHTML = ''
    const jobs = _visibleJobs()
    if (!jobs.length) {
      const empty = document.createElement('div')
      empty.style.cssText = `font-size:var(--text-xs);color:${_C.dim};padding:4px 0`
      empty.textContent = _jobs.length && !_showAllJobs()
        ? 'No jobs for this part.'
        : 'No jobs yet.'
      listEl.appendChild(empty)
      return
    }
    jobs.slice(0, 8).forEach(job => {
      const row = document.createElement('div')
      const isSelected = job.job_id === _selectedId
      row.style.cssText = [
        'display:flex;align-items:center;gap:6px;padding:4px 5px;border-radius:3px;cursor:pointer;margin-bottom:2px',
        `background:${isSelected ? '#161b22' : 'transparent'}`,
        `border:1px solid ${isSelected ? _C.border : 'transparent'}`,
      ].join(';')
      row.addEventListener('click', () => _selectJob(job.job_id))

      const dot = document.createElement('span')
      dot.style.cssText = `width:7px;height:7px;border-radius:50%;flex-shrink:0;background:${_statusColor(job.status)}`
      row.appendChild(dot)

      const name = document.createElement('span')
      name.style.cssText = `flex:1;font-size:var(--text-xs);color:${_C.text};overflow:hidden;text-overflow:ellipsis;white-space:nowrap`
      name.textContent = job.design_name
      row.appendChild(name)

      // Timestamp (HH:MM today, else MM-DD HH:MM)
      const ts = document.createElement('span')
      ts.style.cssText = `font-size:10px;color:${_C.dim};flex-shrink:0;margin-right:4px;font-family:var(--font-mono)`
      ts.textContent = _fmtJobTime(job.created_at)
      row.appendChild(ts)

      const chip = document.createElement('span')
      chip.style.cssText = `font-size:10px;color:${_statusColor(job.status)};flex-shrink:0`
      chip.textContent = job.status
      row.appendChild(chip)

      listEl.appendChild(row)
    })
  }

  // ── Job selection + WS subscription ───────────────────────────────────────
  function _selectJob(jobId) {
    if (_selectedId === jobId) return
    console.log(`[${_ts()}] md-jobs: selecting job ${jobId}`)
    _selectedId = jobId
    _displayMeta = null
    _closeWs()
    _renderList()
    _openDetailForJob(jobId)
    if (displayToggle?.checked) _refreshMdDisplay()
    else _refreshMdPrewarm(true)
  }

  function _openDetailForJob(jobId) {
    const job = _jobs.find(j => j.job_id === jobId)
    if (job) _applyJobState(job)
    if (detailEl) detailEl.style.display = ''
    _fetchDisplayMeta(jobId)
    _fetchJobMetrics(jobId)

    if (!job || !_TERMINAL_STATUSES.has(job.status)) {
      _openWs(jobId)
    } else {
      fetch(`/api/md/jobs/${jobId}`)
        .then(r => r.json())
        .then(j => {
          console.log(`[${_ts()}] md-jobs: REST refresh for completed job`, j.status)
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

    ws.onopen = () => console.log(`[${_ts()}] md-jobs: WS open`)

    ws.onmessage = (evt) => {
      let msg
      try { msg = JSON.parse(evt.data) } catch { return }

      if (msg.type === 'state' && msg.job) {
        console.log(`[${_ts()}] md-jobs: WS state status=${msg.job.status} seg=${msg.job.current_segment_idx}/${msg.job.segments?.length ?? 0}`,
                    msg.job.live_metrics ? `T=${msg.job.live_metrics.temperature_k?.toFixed(1)}K` : '')
        const idx = _jobs.findIndex(j => j.job_id === msg.job.job_id)
        if (idx >= 0) _jobs[idx] = msg.job; else _jobs.unshift(msg.job)
        _renderList()
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
        fetch(`/api/md/jobs/${_selectedId}`)
          .then(r => r.json())
          .then(job => {
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
    if (_pollTimer) {
      clearInterval(_pollTimer)
      _pollTimer = null
    }
  }

  // ── Job detail rendering ──────────────────────────────────────────────────
  function _applyJobState(job, liveMetrics) {
    if (!job) return

    if (statusEl) {
      const seg = job.segments?.[job.current_segment_idx]
      const stageLabel = seg ? `${_timelineStage(seg)} · ${seg.percent}%` : ''
      const segsTotal  = job.segments?.length ?? 0
      const segsDone   = job.segments?.filter(s => s.status === 'done').length ?? 0
      statusEl.textContent = _statusLabel(job.status, segsDone, segsTotal, stageLabel)
      statusEl.style.color = _statusColor(job.status)
    }

    if (startBtn) startBtn.style.display = ['queued', 'stopped', 'failed'].includes(job.status) ? '' : 'none'
    if (stopBtn) stopBtn.style.display = (job.status === 'running') ? '' : 'none'

    _showDetailError(['failed', 'stopped'].includes(job.status) ? (job.error ?? 'Unknown error') : null)
    _renderProgress(job, liveMetrics)
    _renderTimeline(job)
    _renderMetrics(job, liveMetrics)
    _renderProductionControls(job)
    if (_TERMINAL_STATUSES.has(job.status) && _displayMeta?.job_id !== job.job_id) {
      _fetchDisplayMeta(job.job_id)
    }
  }

  function _showDetailError(msg) {
    if (!errorEl) return
    if (msg) {
      errorEl.textContent = msg
      errorEl.style.display = ''
    } else {
      errorEl.style.display = 'none'
    }
  }

  function _showPreparingProgress(payload) {
    if (!progressEl) return
    const salt = payload.salt_mode === 'screening' ? 'auto screening' : 'custom salt'
    progressEl.innerHTML = `
      <div style="display:flex;justify-content:space-between;gap:6px;margin-bottom:3px">
        <span>Preparing equilibrium-aware package</span>
        <span style="font-family:var(--font-mono);color:${_C.text};flex-shrink:0">${salt}</span>
      </div>
      <div style="height:7px;background:${_C.bg2};border:1px solid ${_C.border};border-radius:3px;overflow:hidden">
        <div style="height:100%;width:18%;background:${_C.accent};transition:width 0.2s"></div>
      </div>
    `
  }

  function _renderProgress(job, live) {
    if (!progressEl) return
    const segments = job.segments ?? []
    const total = segments.length
    const done = segments.filter(s => s.status === 'done').length
    const runningIdx = segments.findIndex(s => s.status === 'running')
    const activeIdx = runningIdx >= 0 ? runningIdx : Math.min(job.current_segment_idx ?? 0, Math.max(total - 1, 0))
    const active = total ? segments[activeIdx] : null
    const segFrac = active?.status === 'running' ? (live?.segment_progress ?? 0) : 0
    const overall = total ? Math.min(1, Math.max(0, (done + segFrac) / total)) : 0
    const pct = (overall * 100).toFixed(1)
    const segPct = active?.status === 'running' && live?.segment_progress != null
      ? ` · ${Math.round(live.segment_progress * 100)}% segment`
      : ''
    const label = total
      ? `${pct}% overall · ${done}/${total} segments${segPct}`
      : job.status === 'preparing' ? 'Preparing package' : 'No staged run yet'
    const stage = active ? `${_timelineStage(active)} · ${active.percent}%` : job.status
    progressEl.innerHTML = `
      <div style="display:flex;justify-content:space-between;gap:6px;margin-bottom:3px">
        <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${stage}</span>
        <span style="font-family:var(--font-mono);color:${_C.text};flex-shrink:0">${label}</span>
      </div>
      <div style="height:7px;background:${_C.bg2};border:1px solid ${_C.border};border-radius:3px;overflow:hidden">
        <div style="height:100%;width:${pct}%;background:${job.status === 'failed' ? _C.err : job.status === 'completed' ? _C.ok : _C.accent};transition:width 0.2s"></div>
      </div>
      ${_productionRunSummary(job, live)}
    `
  }

  function _productionRunSummary(job, live) {
    const prod = _productionSegments(job)
    if (!prod.length) return ''

    const metrics = _metricsByJob.get(job.job_id) ?? []
    const metricBySegment = new Map(metrics.map(m => [m.segment, m]))
    const healthBySegment = new Map((job.health_samples ?? []).map(h => [h.segment, h]))
    const active = job.segments?.[job.current_segment_idx]
    const totalSteps = prod.reduce((sum, seg) => sum + (seg.steps ?? 0), 0)
    let completedSteps = 0
    for (const seg of prod) {
      const metric = metricBySegment.get(seg.name)
      const health = healthBySegment.get(seg.name)
      if (seg.status === 'done' || health || (metric?.timestep ?? 0) >= (seg.steps ?? 0) * 0.98) {
        completedSteps += seg.steps ?? 0
      } else if (seg.status === 'failed') {
        completedSteps += Math.min(seg.steps ?? 0, metric?.timestep ?? 0)
      } else if (seg.status === 'running' && active?.name === seg.name) {
        completedSteps += Math.min(seg.steps ?? 0, live?.timestep ?? 0)
      }
    }

    const pct = totalSteps ? (completedSteps / totalSteps) * 100 : 0
    const lastMetric = _latestRecord(metrics, prod.map(s => s.name))
    const latestHealth = _latestHealthForSegments(job, prod.map(s => s.name))
    const failed = prod.find(s => s.status === 'failed')
    const advisory = _productionAdvisory(latestHealth)
    const failureText = failed ? _productionFailureText(job, failed, latestHealth, lastMetric) : ''
    const advisoryText = !failed && advisory ? _productionAdvisoryText(advisory) : ''
    const speed = lastMetric?.ns_per_day != null ? ` · ${_fmt(lastMetric.ns_per_day, 1, ' ns/day')}` : ''
    const temp = lastMetric?.temperature_k != null ? ` · ${_fmt(lastMetric.temperature_k, 1, 'K')}` : ''
    const stepsText = `${completedSteps.toLocaleString()}/${totalSteps.toLocaleString()} steps`
    const nsText = `${_productionNs(completedSteps).toFixed(3)}/${_productionNs(totalSteps).toFixed(3)} ns`
    const border = failed ? _C.err : advisory ? _C.warn : _C.border
    const labelColor = failed ? _C.err : advisory ? _C.warn : _C.muted

    return `
      <div style="margin-top:6px;border:1px solid ${border};background:${_C.bg2};border-radius:3px;padding:6px">
        <div style="display:flex;justify-content:space-between;gap:8px;align-items:center">
          <span style="font-size:10px;color:${labelColor};font-weight:600">${advisory ? '⚠ ' : ''}Production</span>
          <span style="font-size:10px;color:${_C.text};font-family:var(--font-mono);white-space:nowrap">${pct.toFixed(1)}%</span>
        </div>
        <div style="margin-top:3px;font-size:10px;color:${_C.muted};font-family:var(--font-mono);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">
          ${stepsText} · ${nsText}${speed}${temp}
        </div>
        ${advisoryText}
        ${failureText}
      </div>
    `
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

  function _productionAdvisoryText(advisory) {
    const margin = advisory.wc - advisory.advisory
    return `
      <div style="margin-top:5px;font-size:10px;color:${_C.warn};line-height:1.35">
        ⚠ WC below advisory threshold. Consider stopping this production run.
      </div>
      <div style="margin-top:2px;font-size:10px;color:${_C.muted};font-family:var(--font-mono)">
        WC ${_fmtPct(advisory.wc)} / advisory ${_fmtPct(advisory.advisory)} (${margin >= 0 ? '+' : ''}${(margin * 100).toFixed(2)} pts); hard stop ${_fmtPct(advisory.hard)}
      </div>
    `
  }

  function _productionFailureText(job, failedSeg, latestHealth, lastMetric) {
    const reason = job.error || latestHealth?.reason || 'Production failed'
    const healthBits = []
    if (latestHealth?.c1_paired_fraction != null) healthBits.push(`C1 ${_fmtPct(latestHealth.c1_paired_fraction)}`)
    if (latestHealth?.wc_ref_relative_fraction != null) {
      const threshold = failedSeg && /production/i.test(latestHealth.stage ?? '')
        ? _wcHardThresholdForStage(latestHealth.stage)
        : _wcThresholdForStage(latestHealth.stage)
      const margin = latestHealth.wc_ref_relative_fraction - threshold
      healthBits.push(`WC ${_fmtPct(latestHealth.wc_ref_relative_fraction)} (${margin >= 0 ? '+' : ''}${(margin * 100).toFixed(2)} pts)`)
    }
    const completed = lastMetric?.segment === failedSeg.name && (lastMetric?.timestep ?? 0) >= (failedSeg.steps ?? 0) * 0.98
    const mode = completed ? 'NAMD completed this split; post-run health gate stopped the job.' : 'NAMD stopped before this split completed.'
    return `
      <div style="margin-top:5px;font-size:10px;color:${_C.err};line-height:1.35">
        ${_escapeHtml(mode)}
      </div>
      <div style="margin-top:2px;font-size:10px;color:${_C.muted};line-height:1.35;word-break:break-word">
        ${_escapeHtml(reason)}
      </div>
      ${healthBits.length ? `<div style="margin-top:2px;font-size:10px;color:${_C.text};font-family:var(--font-mono)">${healthBits.map(_escapeHtml).join(' · ')}</div>` : ''}
    `
  }

  // ── Stage timeline ─────────────────────────────────────────────────────────
  function _renderTimeline(job) {
    if (!timelineEl) return
    timelineEl.innerHTML = ''

    const segments = job.segments ?? []
    if (!segments.length) {
      timelineEl.textContent = 'No stages'
      return
    }

    const stages = []
    let cur = null
    const healthBySegment = new Map((job.health_samples ?? []).map(h => [h.segment, h]))
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
        const { symbol, color } = _segSymbol(seg.status, health)
        dot.style.cssText = `color:${color};font-size:11px;cursor:default;flex-shrink:0`
        dot.textContent = symbol
        const advisory = _productionAdvisory(health)
        dot.title = advisory
          ? `${seg.name} · ${seg.percent}% · ${seg.status} · WC below advisory; consider stopping`
          : `${seg.name} · ${seg.percent}% · ${seg.status}`
        row.appendChild(dot)
      })

      const allDone   = segs.every(s => s.status === 'done')
      const anyFailed = segs.some(s => s.status === 'failed')
      const anyRun    = segs.some(s => s.status === 'running')
      const stageStat = document.createElement('span')
      stageStat.style.cssText = `color:${anyFailed ? _C.err : allDone ? _C.ok : anyRun ? _C.warn : _C.dim};margin-left:4px`
      stageStat.textContent = anyFailed ? '✗' : allDone ? '✓' : anyRun ? '…' : ''
      row.appendChild(stageStat)

      timelineEl.appendChild(row)
    })
  }

  function _segSymbol(status, health = null) {
    if (status === 'done' && _productionAdvisory(health)) return { symbol: '⚠', color: _C.warn }
    switch (status) {
      case 'done':    return { symbol: '●', color: _C.ok }
      case 'failed':  return { symbol: '✗', color: _C.err }
      case 'running': return { symbol: '○', color: _C.warn }
      default:        return { symbol: '·', color: _C.dim }
    }
  }

  // ── Metric cards ──────────────────────────────────────────────────────────
  function _renderMetrics(job, live) {
    if (!metricsEl) return
    metricsEl.innerHTML = ''

    const health = job.health_samples?.[job.health_samples.length - 1]
    const persisted = _latestRecord(_metricsByJob.get(job.job_id) ?? [])
    const scalar = live ?? persisted ?? {}
    const pressure = scalar?.pressure_avg_bar ?? scalar?.gpressure_avg_bar ?? scalar?.pressure_bar ?? null
    const pressureTitle = scalar?.pressure_avg_bar != null
      ? `PRESSAVG ${_fmt(scalar.pressure_avg_bar, 2, ' bar')}${scalar.pressure_bar != null ? ` · instant ${_fmt(scalar.pressure_bar, 2, ' bar')}` : ''}`
      : scalar?.gpressure_avg_bar != null
        ? `GPRESSAVG ${_fmt(scalar.gpressure_avg_bar, 2, ' bar')}${scalar.pressure_bar != null ? ` · instant ${_fmt(scalar.pressure_bar, 2, ' bar')}` : ''}`
        : ''

    const wcThreshold = health ? _wcThresholdForStage(health.stage) : 0.85
    const wcAdvisory = _productionAdvisory(health)
    const wcValue = wcAdvisory ? `⚠ ${_fmtPct(health?.wc_ref_relative_fraction ?? null)}` : _fmtPct(health?.wc_ref_relative_fraction ?? null)
    const cards = [
      { label: 'Temp',       value: _fmt(scalar?.temperature_k ?? null, 1, 'K'),          color: _C.text },
      { label: 'Pressure avg', value: _fmt(pressure, 2, 'bar'),                            color: _C.text, title: pressureTitle },
      { label: 'Base pairs', value: _fmtPct(health?.c1_paired_fraction ?? null),          color: _healthColor(health?.c1_paired_fraction, 0.90) },
      { label: 'WC health',  value: wcValue,                                               color: wcAdvisory ? _C.warn : _healthColor(health?.wc_ref_relative_fraction, wcThreshold), wcTrend: true },
      { label: 'Speed',      value: _fmt(scalar?.ns_per_day ?? null, 1, ' ns/day'),        color: _C.muted },
      { label: 'Latest',     value: health ? _shortStage(health.stage) : (persisted?.stage ? _shortStage(persisted.stage) : '—'), color: _C.muted },
    ]

    cards.forEach(({ label, value, color, wcTrend, title }) => {
      const card = document.createElement('div')
      card.style.cssText = `background:${_C.bg2};border:1px solid ${_C.border};border-radius:3px;padding:4px 6px;position:relative`
      if (title) card.title = title
      card.innerHTML = `
        <div style="font-size:9px;color:${_C.muted};margin-bottom:1px">${label}</div>
        <div style="font-size:11px;color:${color};font-weight:600;font-family:var(--font-mono)">${value}</div>
      `
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

  function _latestHealthForSegments(job, segmentNames) {
    const allowed = new Set(segmentNames)
    const samples = job.health_samples ?? []
    for (let i = samples.length - 1; i >= 0; i--) {
      if (allowed.has(samples[i].segment)) return samples[i]
    }
    return null
  }

  function _shortStage(stage) {
    return String(stage ?? '—')
      .replace(/^300K NPT MGHH-only handoff$/i, '300K NPT k=0')
      .replace(/^310K NPT (?:conservative )?production ([0-9.]+) ns(?: unrestrained)?$/i, '$1 ns production run')
      .replace(/^310K NPT\s+/i, '')
      .replace(/\s+unrestrained$/i, '')
  }

  function _timelineStage(seg) {
    const stage = String(seg?.stage ?? '—')
    const name = String(seg?.name ?? '')
    const prodNs = stage.match(/production\s+([0-9.]+)\s*ns/i) || name.match(/production_([0-9p]+)ns/i)
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

  function _statusLabel(status, done, total, stageLabel) {
    switch (status) {
      case 'preparing':  return 'Preparing (solvating…)'
      case 'queued':     return 'Queued — ready to start'
      case 'running':    return `Running · ${done}/${total} · ${stageLabel}`
      case 'completed':  return `Completed · ${done}/${total} segments`
      case 'failed':     return `Failed after ${done}/${total} segments`
      case 'stopped':    return `Stopped at segment ${done}`
      default:           return status
    }
  }

  // ── Init ───────────────────────────────────────────────────────────────────
  _setDisplayStatus('Off', _C.dim)
  console.log(`[${_ts()}] md-jobs: panel initialised`)
  if (!_collapsed) _onOpen()
  if (_isDynamicsTabVisible()) _startMdPrewarm()
}
