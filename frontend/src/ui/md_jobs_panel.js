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
import { resetControlsToDefaults } from './form_defaults.js'
import { statusBadge, statusKeyFor, makeStatusLegend } from './job_status_symbol.js'
import { shouldForceDisplayReload } from './md_display_state.js'
import { initOxdnaTrajectoryPlayer } from './oxdna_trajectory_player.js'
import { shouldShowFixButton, openVramFixModal } from './md_vram_fix.js'

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

/** Pure: list badge for a job seeded from an oxDNA relaxation, else ''. */
export function seededBadge(job) {
  return job?.seed_oxdna_job_id ? 'oxDNA seeded' : ''
}

/** Pure: is the job in an in-progress state (a spinner should show)? */
export function mdJobIsActive(job) {
  return ['queued', 'preparing', 'running'].includes(job?.status)
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

/** Pure: a stable signature of the job list so _renderList can skip a rebuild when
 *  nothing visible changed — otherwise the row spinners' CSS animation restarts on
 *  every poll (visible stutter).  Mirrors the oxDNA panel. */
export function mdListSignature(jobs, selectedId) {
  return (jobs ?? [])
    .map(j => `${j.job_id}:${j.status}:${j.current_segment_idx ?? ''}:${j.failure_kind ?? ''}`)
    .join('|') + `#${selectedId ?? ''}`
}

/** Pure: should the Display-MD toggle fall back to the inherited oxDNA-seed
 *  positions?  True when the run was oxDNA-seeded AND no MD trajectory frame has
 *  been written yet (the display meta isn't ready) — so the toggle shows the
 *  structure the MD started from instead of nothing. */
export function mdShouldShowInheritedSeed(job, displayMeta) {
  return !!job?.seed_oxdna_job_id && !displayMeta?.ready
}


// ── Public entry point ────────────────────────────────────────────────────────

export function initMdJobsPanel({ mdDisplayController = null, getWorkspacePath = null, getOxdnaDisplay = null, getMdViz = null } = {}) {
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
  const watershellInput = document.getElementById('md-jobs-watershell')
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
  const healthToggle  = document.getElementById('md-jobs-health-toggle')
  const healthBody    = document.getElementById('md-jobs-health-body')
  const healthArrow   = document.getElementById('md-jobs-health-arrow')
  const healthSpinner = document.getElementById('md-jobs-health-spinner')
  const loadFramesBtn = document.getElementById('md-jobs-load-frames-btn')
  const deleteBtn     = document.getElementById('md-jobs-delete-btn')
  const prodBox       = document.getElementById('md-jobs-production')
  const prodStepsInput = document.getElementById('md-jobs-prod-steps')
  const prodTimeEl    = document.getElementById('md-jobs-prod-time')
  const prodContinueChk = document.getElementById('md-jobs-prod-continue')
  const prodBtn       = document.getElementById('md-jobs-prod-btn')
  const prodStatus    = document.getElementById('md-jobs-prod-status')

  // Visualization tools (flexibility map + trajectory scrub) — mirror the oxDNA panel.
  const flexToggle   = document.getElementById('md-jobs-flex-toggle')
  const flexStatus   = document.getElementById('md-jobs-flex-status')
  const flexBar      = document.getElementById('md-jobs-flex-bar')
  const flexLegend   = document.getElementById('md-jobs-flex-legend')
  const trajToggle   = document.getElementById('md-jobs-traj-toggle')
  const trajStatus   = document.getElementById('md-jobs-traj-status')
  const trajControls = document.getElementById('md-jobs-traj-controls')
  const trajPlay     = document.getElementById('md-jobs-traj-play')
  const trajSlider   = document.getElementById('md-jobs-traj-slider')
  const trajMarkers  = document.getElementById('md-jobs-traj-markers')
  const trajLabel    = document.getElementById('md-jobs-traj-label')

  // ── State ──────────────────────────────────────────────────────────────────
  let _jobs         = []     // cached list from API
  let _selectedId   = null   // currently displayed job_id
  let _ws           = null   // active WebSocket
  let _pollTimer    = null   // REST fallback poll interval
  let _advOpen      = false
  let _collapsed    = getSectionCollapsed('dynamics', 'md-jobs-panel', true)
  let _launching    = false
  let _enginesOk    = false  // both NAMD + GROMACS found
  let _threadsInit  = false  // seeded the threads input from server recommendation once
  let _displayTimer = null
  let _prewarmTimer = null
  let _displayJobId = null
  let _displayKey   = null
  let _displayMeta  = null
  let _prewarmKey   = null
  let _listSig      = null   // last-rendered list signature (avoids spinner-restart churn)
  let _legendEl     = null   // status-symbol legend, inserted once after the list
  let _fetchFails   = 0      // consecutive failed job-list polls (backend-down detector)
  let _inheritedSeedShown = null  // oxDNA job id whose seed positions are currently displayed
  let _mdFrameShown = false       // has a real MD frame been displayed for the current display job?
  const _metricsByJob = new Map()

  // Health card: simple collapse (starts open).
  healthToggle?.addEventListener('click', () => {
    const open = healthBody && healthBody.style.display !== 'none'
    if (healthBody) healthBody.style.display = open ? 'none' : ''
    healthArrow?.classList.toggle('is-collapsed', open)
  })

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

  // ── Advanced drawer (collapsible card) ──────────────────────────────────────
  advToggle?.addEventListener('click', () => {
    _advOpen = !_advOpen
    if (advBody) advBody.style.display = _advOpen ? '' : 'none'
    if (advArrow) advArrow.style.transform = _advOpen ? 'rotate(90deg)' : ''
  })

  // ── Jobs card: simple collapse (starts open), mirrors the oxDNA panel ───────
  {
    const t = document.getElementById('md-jobs-list-toggle')
    const bd = document.getElementById('md-jobs-list-body')
    const ar = document.getElementById('md-jobs-list-arrow')
    t?.addEventListener('click', () => {
      const open = bd && bd.style.display !== 'none'
      if (bd) bd.style.display = open ? 'none' : ''
      ar?.classList.toggle('is-collapsed', open)
    })
  }

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

      // Seed the threads input from the server's autodetect (half the logical
      // CPUs) once, so the default matches the host instead of a hardcoded 16.
      if (!_threadsInit && threadsInput && Number.isFinite(d.recommended_threads)) {
        threadsInput.value = String(d.recommended_threads)
        _threadsInit = true
      }

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
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      _jobs = await r.json()
      _jobs.sort((a, b) => b.created_at - a.created_at)
      console.log(`[${_ts()}] md-jobs: fetched ${_jobs.length} jobs`)
      if (_fetchFails > 0) { _fetchFails = 0; _checkEngines() }  // reconnected → restore status line
      _renderList()
      _selectBestJob()
      if (displayToggle?.checked) _refreshMdDisplay()
      else _refreshMdPrewarm()
    } catch (err) {
      _fetchFails++
      console.warn(`[${_ts()}] md-jobs: _fetchJobs failed (${_fetchFails})`, err)
      // Surface a non-responding backend so an active job doesn't silently keep
      // looking "ongoing" — the poll can't confirm it's still alive.  Two strikes
      // avoids flapping on a single dropped request.
      if (_fetchFails >= 2 && namdStatusEl) {
        namdStatusEl.textContent = '⚠ Backend not responding — job status may be stale (is the server running?)'
        namdStatusEl.style.color = _C.err
      }
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
    _setHealthSpinner(false)
    _renderProductionControls(null)
  }

  // Reset every MD INPUT back to its index.html default — used when a design is
  // closed or a different one is opened, so the panel doesn't carry the previous
  // design's (or last-selected job's) settings.  Threads is re-seeded from the
  // host autodetect (clear _threadsInit so the next engine check re-applies it),
  // and salt-mode visibility is re-synced.
  function _resetControlsToDefaults() {
    resetControlsToDefaults([
      presetSel, threadsInput, devicesInput, saltModeSel, mgInput, naclInput,
      paddingInput, watershellInput, minstepsInput, autostartChk, prodStepsInput, prodContinueChk,
    ])
    _threadsInit = false
    _applySaltMode()
    _checkEngines()
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
      _renderProductionControls(job, d)
      if (!d.ready || !d.config_path) {
        _displayJobId = job.job_id
        _displayKey = null
        // Seed placeholder already on screen (if seeded) → leave it; else say waiting.
        if (!_inheritedSeedShown) {
          _setDisplayStatus(`Waiting for trajectory output (${job.status})`, _C.warn, true)
        }
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
  }

  function _stopMdDisplay(status = 'Off') {
    clearInterval(_displayTimer)
    _displayTimer = null
    _displayJobId = null
    _displayKey = null
    if (displayToggle) displayToggle.checked = false
    _mdFrameShown = false
    _clearInheritedSeed()             // drop any inherited oxDNA-seed overlay too (restore native)
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
    _resetControlsToDefaults()   // drop the previous design's MD settings
    _renderList()
    if (displayToggle?.checked) _refreshMdDisplay()
    else _refreshMdPrewarm(true)
  })

  loadFramesBtn?.addEventListener('click', () => {
    if (!_selectedId) return
    _startMdDisplay()
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
    onSeek: (i) => getMdViz?.()?.showFrame(i),
    onBeforePlay: async () => {
      const v = getMdViz?.()
      if (!v) return true
      v.setPlaying(true)
      // CG plays instantly (prebuildHeavy is a no-op for the bead model).
      const r = await v.prebuildHeavy(() => {})
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
  function _setFlexOff() {
    if (getMdViz?.()?.mode?.() === 'rmsf') getMdViz().stopAndRestore()
    if (flexToggle) flexToggle.checked = false
    _setFlexBar('off')
    _setFlexLegend(null, null)
    _setFlexStatus('', _C.dim)
  }
  async function _refreshFlex() {
    const v = getMdViz?.()
    if (!_selectedId || !v) return
    _setFlexStatus('Computing average structure + RMSF…', _C.accent)
    _setFlexBar('computing')
    const r = await v.displayRmsf(_selectedId)
    if (r.ok) {
      _setFlexBar('done')
      _setFlexLegend(r.min, r.max)
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
      if (!_selectedId) { flexToggle.checked = false; showToast('Select an MD job first', 'warn'); return }
      if (!_mdHasTrajectory(_selectedJob())) {
        flexToggle.checked = false; _setFlexStatus('No trajectory frames yet', _C.warn); return
      }
      if (displayToggle?.checked) _stopMdDisplay('Native positions restored')
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
  }
  async function _refreshTraj() {
    const v = getMdViz?.()
    if (!_selectedId || !v) return
    _setTrajStatus('Loading trajectory…', _C.accent)
    const r = await v.loadTrajectory(_selectedId)
    if (r.ok) {
      if (trajControls) trajControls.style.display = ''
      trajPlayer.setTrajectory(r.n_frames, r.markers)
      const nStages = (r.stages || []).length
      _setTrajStatus(`${r.n_frames} frames · ${nStages} segment${nStages === 1 ? '' : 's'}`, _C.ok)
    } else {
      if (trajToggle) trajToggle.checked = false
      if (trajControls) trajControls.style.display = 'none'
      _setTrajStatus(r.reason || 'no trajectory', _C.warn)
    }
  }
  trajToggle?.addEventListener('change', async () => {
    if (trajToggle.checked) {
      if (!_selectedId) { trajToggle.checked = false; showToast('Select an MD job first', 'warn'); return }
      if (!_mdHasTrajectory(_selectedJob())) {
        trajToggle.checked = false; _setTrajStatus('No trajectory yet', _C.warn); return
      }
      if (displayToggle?.checked) _stopMdDisplay('Native positions restored')
      _setFlexOff()
      await _refreshTraj()
    } else {
      _setTrajOff()
    }
  })

  // Enable/disable the viz toggles for the selected job; turn an active tool off if
  // the job switched away or lost its trajectory.
  function _updateVizToggles(job) {
    const ok = _mdHasTrajectory(job)
    for (const t of [flexToggle, trajToggle]) {
      if (!t) continue
      t.disabled = !ok
      const lab = t.closest('label')
      if (lab) { lab.style.opacity = ok ? '1' : '0.5'; lab.style.cursor = ok ? 'pointer' : 'not-allowed' }
    }
  }

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
    else if (state === 'ready') _setDisplayStatus(message, _C.muted, false)
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
      // UI is in Å; API wants nm. 0 = full box (no carve).
      water_shell_nm: (parseFloat(watershellInput?.value ?? '0') || 0) / 10,
      minimize_steps: parseInt(minstepsInput?.value  ?? '10000', 10),
      autostart:      autostartChk?.checked ?? true,
      design_source_path: _currentPartPath() || null,
    }

    console.log(`[${_ts()}] md-jobs: Relax clicked`, payload)
    if (detailEl) detailEl.style.display = ''
    _showPreparingProgress(payload)
    // The POST now returns immediately (job enters 'preparing'); the live
    // solvation bar + ETA is driven by the websocket into the job detail, so the
    // modal only covers the brief create round-trip.
    showOpProgress('Relax', 'Creating job…', { indeterminate: true })

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
      showToast(`Preparing: ${job.job_id}`, 'ok')
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
    // oxDNA-seeded jobs run the SAME restrained relaxation ladder, starting from
    // the seeded (oxDNA-relaxed) structure — they no longer skip it (jumping
    // straight to unrestrained production blew the structure up).
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
    const jobs = _visibleJobs()
    // Skip the rebuild when nothing visible changed, so the row spinners' CSS
    // animation doesn't restart on every poll (visible stutter).
    const sig = mdListSignature(jobs.slice(0, 8), _selectedId)
    if (sig === _listSig && listEl.childElementCount) return
    _listSig = sig
    listEl.innerHTML = ''
    if (!jobs.length) {
      const empty = document.createElement('div')
      empty.style.cssText = `font-size:var(--text-xs);color:${_C.dim};padding:4px 0`
      empty.textContent = _jobs.length && !_showAllJobs()
        ? 'No jobs for this part.'
        : 'No jobs yet.'
      listEl.appendChild(empty)
      return
    }
    jobs.slice(0, 8).forEach((job, i) => {
      const row = document.createElement('div')
      const isSelected = job.job_id === _selectedId
      row.setAttribute('data-job-id', job.job_id)
      row.style.cssText = [
        'display:flex;align-items:center;gap:6px;padding:4px 5px;border-radius:3px;cursor:pointer;margin-bottom:2px',
        `background:${isSelected ? '#161b22' : 'transparent'}`,
        `border:1px solid ${isSelected ? _C.border : 'transparent'}`,
      ].join(';')
      row.addEventListener('click', () => _selectJob(job.job_id))
      const sb = statusBadge(statusKeyFor('namd', job.status))

      // Leading list index.
      const idx = document.createElement('span')
      idx.textContent = `[${i + 1}]`
      idx.style.cssText = `flex-shrink:0;font-size:10px;color:${_C.dim};font-family:var(--font-mono)`
      row.appendChild(idx)

      const name = document.createElement('span')
      name.style.cssText = `flex:1;font-size:var(--text-xs);color:${_C.text};overflow:hidden;text-overflow:ellipsis;white-space:nowrap`
      name.textContent = job.design_name
      row.appendChild(name)

      // "oxDNA seeded" badge — this run started from oxDNA-relaxed coordinates.
      const badge = seededBadge(job)
      if (badge) {
        const seeded = document.createElement('span')
        seeded.title = `Seeded from oxDNA job ${job.seed_oxdna_job_id}`
        seeded.textContent = badge
        seeded.style.cssText = `font-size:9px;color:#4a9eff;border:1px solid #2a4a6a;border-radius:3px;padding:0 4px;flex-shrink:0;margin-right:4px`
        row.appendChild(seeded)
      }

      // Timestamp (HH:MM today, else MM-DD HH:MM)
      const ts = document.createElement('span')
      ts.style.cssText = `font-size:10px;color:${_C.dim};flex-shrink:0;font-family:var(--font-mono)`
      ts.textContent = _fmtJobTime(job.created_at)
      row.appendChild(ts)

      // "Fix" button for a GPU-out-of-memory failure → opens the downsize popup.
      if (shouldShowFixButton(job)) {
        const fix = document.createElement('button')
        fix.textContent = 'Fix'
        fix.title = 'Ran out of GPU memory — adjust settings to fit this card'
        fix.style.cssText =
          `flex-shrink:0;font-size:10px;color:#fff;background:${_C.warn};`
          + 'border:none;border-radius:3px;padding:1px 7px;cursor:pointer;font-weight:600'
        fix.addEventListener('click', (e) => {
          e.stopPropagation()   // don't trigger row selection
          _openVramFix(job.job_id)
        })
        row.appendChild(fix)
      }

      // Status symbol: spinner while active, else the badge shape (tooltip = label).
      const sym = mdJobIsActive(job)
        ? makeSpinner(sb.color, 10)
        : Object.assign(document.createElement('span'), { textContent: sb.symbol })
      sym.style.flexShrink = '0'
      sym.title = sb.label
      if (!mdJobIsActive(job)) sym.style.color = sb.color
      row.appendChild(sym)

      listEl.appendChild(row)
    })
    if (!_legendEl) { _legendEl = makeStatusLegend(); listEl.after(_legendEl) }
  }

  // ── "Fix" flow (downsize / gentle-retry / resume) ─────────────────────────
  async function _openVramFix(jobId) {
    let advice
    try {
      const r = await fetch(`/api/md/jobs/${jobId}/fix-advice`)
      advice = await r.json()
      if (!r.ok) throw new Error(advice?.detail ?? `Server error ${r.status}`)
    } catch (err) {
      console.warn(`[${_ts()}] md-jobs: fix-advice failed`, err)
      advice = { failure_kind: 'other', remedy: 'none' }
    }
    openVramFixModal({
      advice,
      onApply: async (action) => {
        if (action.type === 'retry') {
          const r = await fetch(`/api/md/jobs/${jobId}/start`, {
            method: 'POST', headers: { ...docHeaders() },
          })
          if (!r.ok) throw new Error((await r.json().catch(() => ({})))?.detail ?? `Server error ${r.status}`)
          await _fetchJobs()
          _selectJob(jobId)
          return
        }
        // refit → a fresh job with adjusted settings
        const r = await fetch(`/api/md/jobs/${jobId}/refit`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', ...docHeaders() },
          body: JSON.stringify(action.body),
        })
        const d = await r.json().catch(() => ({}))
        if (!r.ok) throw new Error(d?.detail ?? `Server error ${r.status}`)
        await _fetchJobs()
        if (d?.job_id) _selectJob(d.job_id)
      },
    })
  }

  // ── Job selection + WS subscription ───────────────────────────────────────
  function _selectJob(jobId) {
    if (_selectedId === jobId) return
    console.log(`[${_ts()}] md-jobs: selecting job ${jobId}`)
    _setFlexOff()   // the loaded trajectory / flex map belonged to the previous job
    _setTrajOff()
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
    _updateVizToggles(job)
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

  // Human-friendly "time left" from a seconds estimate.
  function _fmtEta(secs) {
    if (secs == null || !isFinite(secs) || secs < 0) return ''
    const s = Math.round(secs)
    if (s < 60) return `~${s}s left`
    const m = Math.floor(s / 60)
    const r = s % 60
    return r ? `~${m}m ${r}s left` : `~${m}m left`
  }

  // Live solvation/ENM progress while a job is preparing — driven by the
  // `prep_progress` snapshot the backend streams (phase, fraction, ETA, stall
  // warning).  Replaces the old indeterminate "Preparing package" spinner so the
  // user can tell a slow run from a hung one.
  function _renderPrepProgress(job) {
    const p = job.prep_progress
    if (!p) {
      progressEl.innerHTML = `
        <div style="margin-bottom:3px">Preparing package…</div>
        <div style="height:7px;background:${_C.bg2};border:1px solid ${_C.border};border-radius:3px;overflow:hidden">
          <div style="height:100%;width:8%;background:${_C.accent};transition:width 0.3s"></div>
        </div>`
      return
    }
    const pct = Math.max(0, Math.min(100, (p.fraction ?? 0) * 100))
    const phaseNo = (p.phase_index ?? 0) + 1
    const eta = _fmtEta(p.eta_seconds)
    const right = [`${pct.toFixed(0)}%`, eta].filter(Boolean).join(' · ')
    const warn = p.warning
      ? `<div style="margin-top:4px;font-size:10px;color:${_C.warn}">⚠ ${p.warning}</div>`
      : ''
    progressEl.innerHTML = `
      <div style="display:flex;justify-content:space-between;gap:6px;margin-bottom:3px">
        <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${p.message || p.label || 'Preparing…'}</span>
        <span style="font-family:var(--font-mono);color:${_C.text};flex-shrink:0">${right}</span>
      </div>
      <div style="height:7px;background:${_C.bg2};border:1px solid ${_C.border};border-radius:3px;overflow:hidden">
        <div style="height:100%;width:${pct}%;background:${p.warning ? _C.warn : _C.accent};transition:width 0.3s"></div>
      </div>
      <div style="margin-top:3px;font-size:10px;color:${_C.muted}">
        Step ${phaseNo} of ${p.n_phases ?? '?'} · ${p.label ?? ''}
      </div>
      ${warn}
    `
  }

  function _renderProgress(job, live) {
    if (!progressEl) return
    if (job.status === 'preparing') {
      _renderPrepProgress(job)
      return
    }
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
    // A spinner on the progress line while active — most useful during "Preparing
    // package", when the bar can't move yet.  (.nadoc-spinner CSS drives the spin.)
    const spin = mdJobIsActive(job)
      ? `<span class="nadoc-spinner" aria-hidden="true" style="width:9px;height:9px;color:${_C.warn};flex-shrink:0"></span>`
      : ''
    progressEl.innerHTML = `
      <div style="display:flex;align-items:center;justify-content:space-between;gap:6px;margin-bottom:3px">
        <span style="display:flex;align-items:center;gap:5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${spin}<span style="overflow:hidden;text-overflow:ellipsis">${stage}</span></span>
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
      if (anyRun) {
        // Spinning circle next to the stage currently running.
        const spin = makeSpinner(_C.warn, 10)
        spin.style.marginLeft = '4px'
        row.appendChild(spin)
      } else {
        const stageStat = document.createElement('span')
        stageStat.style.cssText = `color:${anyFailed ? _C.err : allDone ? _C.ok : _C.dim};margin-left:4px`
        stageStat.textContent = anyFailed ? '✗' : allDone ? '✓' : ''
        row.appendChild(stageStat)
      }

      timelineEl.appendChild(row)
    })
  }

  // A checkpoint that did not fully pass but the run was allowed to continue: a
  // non-blocking advisory breach (WC ref-relative below threshold; backend
  // `blocking === false`).  Surfaced as ⚠, distinct from a ✗ hard failure.
  function _isAdvisoryWarning(health) {
    return !!health && health.passed === false && health.blocking === false
  }

  function _segSymbol(status, health = null) {
    if (status === 'done' && (_productionAdvisory(health) || _isAdvisoryWarning(health)))
      return { symbol: '⚠', color: _C.warn }
    switch (status) {
      case 'done':    return { symbol: '●', color: _C.ok }
      case 'failed':  return { symbol: '✗', color: _C.err }
      case 'running': return { symbol: '○', color: _C.warn }
      default:        return { symbol: '·', color: _C.dim }
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
    const cards = [
      { label: 'Temp',       value: _fmt(scalar?.temperature_k ?? null, 1, 'K'),          color: _C.text },
      { label: 'Pressure avg', value: _fmt(pressure, 2, 'bar'),                            color: _C.text, title: pressureTitle },
      { label: 'Base pairs', value: _fmtPct(health?.c1_paired_fraction ?? null),          color: _healthColor(health?.c1_paired_fraction, 0.90) },
      { label: 'WC health',  value: wcValue,                                               color: wcAdvisory ? _C.warn : _healthColor(health?.wc_ref_relative_fraction, wcThreshold), wcTrend: true },
      { label: 'Speed',      value: _fmt(scalar?.ns_per_day ?? null, 1, ' ns/day'),        color: _C.muted },
      { label: 'Latest',     value: health ? _shortStage(health.stage) : (persisted?.stage ? _shortStage(persisted.stage) : '—'), color: _C.muted },
    ]

    const jobActive = mdJobIsActive(job)
    cards.forEach(({ label, value, color, wcTrend, title }) => {
      const card = document.createElement('div')
      card.style.cssText = `background:${_C.bg2};border:1px solid ${_C.border};border-radius:3px;padding:4px 6px;position:relative`
      if (title) card.title = title
      // A still-pending value (—) on a running job shows a small spinner so the user
      // knows that card is being calculated, not stuck.
      const pending = jobActive && String(value).replace(/[⚠\s]/g, '') === '—'
      card.innerHTML = `<div style="font-size:9px;color:${_C.muted};margin-bottom:1px">${label}</div>`
      const valEl = document.createElement('div')
      valEl.style.cssText = `font-size:11px;color:${color};font-weight:600;font-family:var(--font-mono);display:flex;align-items:center;min-height:13px`
      if (pending) valEl.appendChild(makeSpinner(_C.muted, 9))
      else valEl.textContent = value
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
