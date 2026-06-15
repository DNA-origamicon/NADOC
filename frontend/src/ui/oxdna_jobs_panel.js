/**
 * oxDNA relaxation jobs panel (Dynamics tab).
 *
 * Sibling of md_jobs_panel.js: launches and monitors a managed 3-stage oxDNA
 * coarse-grained relaxation on the CURRENTLY-LOADED design, shows a scrollable
 * jobs list filtered to that design, a stage timeline, per-stage health
 * readouts, and an "OxDNA display" toggle that deforms the NADOC model to the
 * job's last relaxed positions (oxdna_display.js).
 *
 * REST-poll based (no WebSocket) — an oxDNA relaxation is short and single-frame
 * compared to a NAMD trajectory, so a light poll while the panel is open is
 * enough.  oxDNA output is display state only; topology is never touched.
 *
 * Factory: initOxdnaJobsPanel({ oxdnaDisplay, getWorkspacePath }) — pulls API
 * via dynamic import of api/client.js (mirrors md_jobs_panel usage).
 */

import { getSectionCollapsed, setSectionCollapsed } from './section_collapse_state.js'
import { showToast } from './toast.js'
import { filterJobsForPart } from './md_jobs_panel.js'
import { initFlexScale } from './flex_scale.js'
import * as api from '../api/client.js'

const POLL_MS = 1500

const _C = {
  ok:   '#5cb85c', warn: '#e0a800', err: '#d9534f',
  accent: '#4a9eff', dim: '#8a8a8a', text: '#d8d8d8',
}

const _STATUS_COLOR = {
  queued: _C.dim, preparing: _C.accent, running: _C.warn,
  completed: _C.ok, failed: _C.err, stopped: _C.dim,
}

/** Pure: overall progress % string for a job + progress payload. */
export function formatProgress(job, progress) {
  const total = job?.stages?.length ?? 0
  const done = job?.stages?.filter(s => s.status === 'done').length ?? 0
  const frac = progress?.overall ?? (total ? done / total : 0)
  return { pct: Math.round(frac * 100), done, total }
}

/** Pure: human ETA from seconds ("45s" / "2m 30s" / "1h 5m"); '' when unknown. */
export function formatEta(seconds) {
  if (seconds == null || !isFinite(seconds) || seconds < 0) return ''
  const s = Math.round(seconds)
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60), rs = s % 60
  if (m < 60) return rs ? `${m}m ${rs}s` : `${m}m`
  const h = Math.floor(m / 60), rm = m % 60
  return rm ? `${h}h ${rm}m` : `${h}h`
}

/** Pure: the name to show for a job — prefer the loaded file name (design_source_path
 * stem) over design_name, which a "save as" can leave stale (e.g. 6hb_OxDNA_test
 * carrying "6hb_primitive"). */
export function jobDisplayName(job) {
  const src = job?.design_source_path
  if (src) {
    const base = String(src).split(/[\\/]/).pop() || src
    const stem = base.replace(/\.[^.]+$/, '')
    if (stem) return stem
  }
  return job?.design_name || 'design'
}

/** Pure: latest health sample of a job (or null). */
export function latestHealth(job) {
  const hs = job?.health_samples
  return hs && hs.length ? hs[hs.length - 1] : null
}

/** Pure: the detail status line text for a job — the begin/monitor/finish readout. */
export function detailStatusText(job, progress) {
  const { pct, done, total } = formatProgress(job, progress)
  if (job?.status === 'running') {
    const stageName = job.stages?.[job.current_stage_idx]?.name ?? '—'
    return `Running · ${done}/${total} stages · ${stageName} · ${pct}%`
  }
  return `${job?.status ?? 'unknown'} · ${done}/${total} stages`
}

const _STAGE_GLYPH = { done: '●', failed: '✗', running: '○', pending: '·' }

/** Pure: per-stage timeline chips (glyph + kind + status) for a job. */
export function stageChips(job) {
  return (job?.stages || []).map((s) => ({
    kind: s.kind,
    status: s.status,
    glyph: _STAGE_GLYPH[s.status] || '·',
  }))
}

/** Pure: production-stage state — 'none' | 'running' | 'done' | 'failed'. */
export function productionState(job) {
  const prod = (job?.stages || []).find(s => s.kind === 'production')
  if (!prod) return 'none'
  if (prod.status === 'done')   return 'done'
  if (prod.status === 'failed') return 'failed'
  if (prod.status === 'running' || prod.status === 'pending') return 'running'
  return 'none'
}

/** Pure: a job whose relaxation has completed can seed a NAMD run (Phase 2).
 *  A completed status means the relaxation (and any production) finished, so a
 *  relaxed last_conf exists to hand off to NAMD. */
export function seedReady(job) {
  return job?.status === 'completed'
}

/** Pure: list/detail status label + color — derives "production ready" + production states. */
export function jobListStatus(job) {
  const ps = productionState(job)
  if (job?.status === 'completed' && ps === 'none') return { label: 'production ready', color: _C.accent }
  if (ps === 'running') return { label: 'production', color: _C.warn }
  if (ps === 'done')    return { label: 'production done', color: _C.ok }
  if (ps === 'failed')  return { label: 'production failed', color: _C.err }
  return { label: job?.status ?? 'unknown', color: _STATUS_COLOR[job?.status] || _C.dim }
}

export function initOxdnaJobsPanel({ oxdnaDisplay = null, getWorkspacePath = null } = {}) {
  const panel   = document.getElementById('oxdna-jobs-panel')
  const heading = document.getElementById('oxdna-jobs-heading')
  const arrow   = document.getElementById('oxdna-jobs-arrow')
  const body    = document.getElementById('oxdna-jobs-body')
  if (!panel || !heading || !body) return

  const statusEl      = document.getElementById('oxdna-jobs-status')
  const runBtn        = document.getElementById('oxdna-jobs-run-btn')
  const prodBtn       = document.getElementById('oxdna-jobs-prod-btn')
  const prodStepsInput = document.getElementById('oxdna-jobs-prod-steps')
  const prodStatus    = document.getElementById('oxdna-jobs-prod-status')
  const exportBtn     = document.getElementById('oxdna-jobs-export-btn')
  const advToggle     = document.getElementById('oxdna-jobs-adv-toggle')
  const advArrow      = document.getElementById('oxdna-jobs-adv-arrow')
  const advBody       = document.getElementById('oxdna-jobs-adv-body')
  const backendSel    = document.getElementById('oxdna-jobs-backend')
  const deviceInput   = document.getElementById('oxdna-jobs-device')
  const saltInput     = document.getElementById('oxdna-jobs-salt')
  const mcStepsInput  = document.getElementById('oxdna-jobs-mc-steps')
  const mdStepsInput  = document.getElementById('oxdna-jobs-md-steps')
  const equilStepsInput = document.getElementById('oxdna-jobs-equil-steps')
  const bpGateInput   = document.getElementById('oxdna-jobs-bp-gate')
  const showAllToggle = document.getElementById('oxdna-jobs-show-all')

  const listEl     = document.getElementById('oxdna-jobs-list')
  const detailEl   = document.getElementById('oxdna-jobs-detail')
  const detailStatus = document.getElementById('oxdna-jobs-detail-status')
  const startBtn   = document.getElementById('oxdna-jobs-start-btn')
  const stopBtn    = document.getElementById('oxdna-jobs-stop-btn')
  const deleteBtn  = document.getElementById('oxdna-jobs-delete-btn')
  const errorEl    = document.getElementById('oxdna-jobs-detail-error')
  const progressEl = document.getElementById('oxdna-jobs-progress')
  const timelineEl = document.getElementById('oxdna-jobs-timeline')
  const healthEl   = document.getElementById('oxdna-jobs-health')
  const displayToggle = document.getElementById('oxdna-jobs-display-toggle')
  const displayStatus = document.getElementById('oxdna-jobs-display-status')
  const flexToggle    = document.getElementById('oxdna-jobs-flex-toggle')
  const flexStatus    = document.getElementById('oxdna-jobs-flex-status')
  const flexBar       = document.getElementById('oxdna-jobs-flex-bar')
  const flexLegend    = document.getElementById('oxdna-jobs-flex-legend')
  const seedBtn       = document.getElementById('oxdna-jobs-seed-btn')
  const seedStatus    = document.getElementById('oxdna-jobs-seed-status')

  // ── State ──────────────────────────────────────────────────────────────────
  let _jobs       = []
  let _selectedId = null
  let _progress   = null
  let _pollTimer  = null
  let _collapsed  = getSectionCollapsed('dynamics', 'oxdna-jobs-panel', true)
  let _advOpen    = false
  let _available  = false
  let _launching  = false
  let _seeding    = false
  let _flexBusy   = false

  // Workspace colour-scale widget (middle-right); editing its bounds re-colours
  // the active flexibility map live without re-fetching.
  const flexScale = initFlexScale({
    onBoundsChange: (lo, hi) => oxdnaDisplay?.recolorRmsf(lo, hi),
  })
  const _SHOW_ALL_KEY = 'nadoc:oxdna-jobs-show-all'

  if (showAllToggle) showAllToggle.checked = localStorage.getItem(_SHOW_ALL_KEY) === '1'

  // ── Collapse ───────────────────────────────────────────────────────────────
  body.style.display = _collapsed ? 'none' : ''
  arrow?.classList.toggle('is-collapsed', _collapsed)
  heading.addEventListener('click', () => {
    _collapsed = !_collapsed
    body.style.display = _collapsed ? 'none' : ''
    arrow?.classList.toggle('is-collapsed', _collapsed)
    setSectionCollapsed('dynamics', 'oxdna-jobs-panel', _collapsed)
    if (!_collapsed) _onOpen()
  })

  advToggle?.addEventListener('click', () => {
    _advOpen = !_advOpen
    if (advBody) advBody.style.display = _advOpen ? '' : 'none'
    if (advArrow) advArrow.style.transform = _advOpen ? 'rotate(90deg)' : ''
  })

  // ── Availability ─────────────────────────────────────────────────────────
  async function _checkAvailable() {
    if (!statusEl) return
    const d = await api.oxdnaAvailable().catch(() => null)
    _available = !!d?.available
    if (_available) {
      _setStatus(`oxDNA ready · ${d.oxdna_bin}`, _C.ok)
      if (deviceInput && d.recommended_device && !deviceInput.dataset.userSet) {
        deviceInput.value = d.recommended_device
      }
    } else {
      _setStatus('oxDNA binary not found — set $OXDNA_BIN or build ~/oxDNA', _C.err)
    }
    _updateButtons(_selectedJob())
  }
  deviceInput?.addEventListener('input', () => { if (deviceInput) deviceInput.dataset.userSet = '1' })

  function _setStatus(text, color = _C.dim) {
    if (statusEl) { statusEl.textContent = text; statusEl.style.color = color }
  }
  function _setDisplayStatus(text, color = _C.dim) {
    if (displayStatus) { displayStatus.textContent = text; displayStatus.style.color = color }
  }

  // ── Job filtering (current design only, unless "show all") ────────────────
  function _currentPartPath() {
    const raw = getWorkspacePath ? getWorkspacePath() : null
    return raw || null
  }
  function _visibleJobs() {
    return filterJobsForPart(_jobs, _currentPartPath(), !!showAllToggle?.checked)
  }

  showAllToggle?.addEventListener('change', () => {
    localStorage.setItem(_SHOW_ALL_KEY, showAllToggle.checked ? '1' : '0')
    _renderList()
  })

  // ── Fetch + poll ───────────────────────────────────────────────────────────
  async function _fetchJobs() {
    const jobs = await api.listOxdnaJobs().catch(() => null)
    if (Array.isArray(jobs)) {
      _jobs = jobs
      _renderList()
      if (_selectedId) {
        const sel = _jobs.find(j => j.job_id === _selectedId)
        if (sel) {
          _progress = await api.getOxdnaProgress(_selectedId).catch(() => null)
          _renderDetail(sel)
          if (oxdnaDisplay?.isActive() && sel.status === 'completed') {
            // Refresh deformed view once the run finishes.
            _refreshDisplay()
          }
        }
      }
    }
    _scheduleNextPoll()
  }

  function _hasActiveJob() {
    return _visibleJobs().some(j => ['queued', 'preparing', 'running'].includes(j.status))
  }
  function _scheduleNextPoll() {
    if (_pollTimer) { clearTimeout(_pollTimer); _pollTimer = null }
    if (_collapsed) return
    if (_hasActiveJob() || (_selectedId && _jobs.find(j => j.job_id === _selectedId && j.status === 'running'))) {
      _pollTimer = setTimeout(_fetchJobs, POLL_MS)
    }
  }

  function _onOpen() {
    _checkAvailable()
    _fetchJobs()
  }

  // ── Launch ─────────────────────────────────────────────────────────────────
  runBtn?.addEventListener('click', async () => {
    if (_launching || !_available) return
    _launching = true
    runBtn.disabled = true
    _setStatus('Preparing relaxation job…', _C.accent)
    const body = {
      backend:            backendSel?.value || 'CUDA',
      device:             deviceInput?.value || '0',
      salt_concentration: parseFloat(saltInput?.value || '0.5'),
      mc_steps:           parseInt(mcStepsInput?.value || '1000', 10),
      md_relax_steps:     parseInt(mdStepsInput?.value || '1000000', 10),
      equil_steps:        parseInt(equilStepsInput?.value || '100000', 10),
      min_bp_retained:    parseFloat(bpGateInput?.value || '0.5'),
      autostart:          true,
      design_source_path: _currentPartPath(),
    }
    const job = await api.createOxdnaJob(body).catch(() => null)
    _launching = false
    _updateButtons(_selectedJob())
    if (job?.job_id) {
      _selectedId = job.job_id
      showToast('oxDNA relaxation started', 'ok')
      _setStatus('Relaxation running…', _C.warn)
      await _fetchJobs()
    } else {
      const detail = api.lastErrorMessage?.()
      _setStatus(detail || 'Failed to start relaxation (see console)', _C.err)
    }
  })

  // ── List ─────────────────────────────────────────────────────────────────
  function _renderList() {
    if (!listEl) return
    const jobs = _visibleJobs().slice().sort((a, b) => b.created_at - a.created_at)
    if (!jobs.length) {
      listEl.innerHTML = `<div style="color:${_C.dim};padding:6px 4px;font-size:11px">No oxDNA jobs for this design yet.</div>`
      return
    }
    listEl.innerHTML = ''
    for (const job of jobs) {
      const row = document.createElement('div')
      row.style.cssText =
        `display:flex;align-items:center;gap:6px;padding:4px 6px;cursor:pointer;border-radius:4px;` +
        `font-size:11px;${job.job_id === _selectedId ? 'background:#2a3a4a;' : ''}`
      const dot = document.createElement('span')
      dot.textContent = '●'
      const ls = jobListStatus(job)
      dot.style.color = ls.color
      const label = document.createElement('span')
      label.style.flex = '1'
      label.textContent = jobDisplayName(job)
      const st = document.createElement('span')
      st.style.color = ls.color
      st.textContent = ls.label
      row.append(dot, label, st)
      row.addEventListener('click', async () => {
        _selectedId = job.job_id
        _progress = await api.getOxdnaProgress(job.job_id).catch(() => null)
        _renderList()
        _renderDetail(job)
        _scheduleNextPoll()
      })
      listEl.appendChild(row)
    }
  }

  // ── Detail ─────────────────────────────────────────────────────────────────
  function _renderDetail(job) {
    if (!detailEl) return
    detailEl.style.display = ''

    if (detailStatus) {
      const ls = jobListStatus(job)
      detailStatus.textContent = job.status === 'running'
        ? detailStatusText(job, _progress)
        : ls.label
      detailStatus.style.color = ls.color
    }

    if (startBtn) startBtn.style.display = ['queued', 'stopped', 'failed'].includes(job.status) ? '' : 'none'
    if (stopBtn)  stopBtn.style.display  = job.status === 'running' ? '' : 'none'
    if (deleteBtn) deleteBtn.style.display = job.status === 'running' ? 'none' : ''

    _updateButtons(job)

    if (errorEl) {
      errorEl.style.display = job.error ? '' : 'none'
      errorEl.textContent = job.error || ''
    }

    _renderProgress(job)
    _renderTimeline(job)
    _renderHealth(job)
  }

  function _renderProgress(job) {
    if (!progressEl) return
    const idx = job.current_stage_idx
    const cur = job.stages?.[idx]
    let barPct = formatProgress(job, _progress).pct
    let label = ''
    // During a production run, show steps completed out of the production total.
    if (productionState(job) === 'running' && cur?.kind === 'production') {
      const frac = _progress?.stage_fraction ?? 0
      barPct = Math.round(frac * 100)
      const done = Math.round(frac * (cur.steps || 0))
      label = `Production: ${done.toLocaleString()} / ${(cur.steps || 0).toLocaleString()} steps`
    }
    // Estimated time to completion (current run — relax or production).
    const eta = job.status === 'running' ? formatEta(_progress?.eta_seconds) : ''
    if (eta) label = label ? `${label} · ETA ~${eta}` : `ETA ~${eta}`
    const color = job.status === 'failed' ? _C.err : job.status === 'completed' ? _C.ok : _C.accent
    progressEl.innerHTML =
      `<div style="height:7px;background:#222;border-radius:4px;overflow:hidden">` +
      `<div style="height:100%;width:${barPct}%;background:${color};transition:width .3s"></div></div>` +
      (label ? `<div style="font-size:10px;color:${_C.dim};margin-top:2px">${label}</div>` : '')
  }

  function _renderTimeline(job) {
    if (!timelineEl) return
    const color = { done: _C.ok, failed: _C.err, running: _C.warn, pending: _C.dim }
    timelineEl.innerHTML = ''
    for (const c of stageChips(job)) {
      const chip = document.createElement('span')
      chip.style.cssText = `display:inline-flex;align-items:center;gap:3px;margin-right:10px;font-size:11px;color:${color[c.status] || _C.dim}`
      chip.innerHTML = `<span>${c.glyph}</span><span>${c.kind}</span>`
      timelineEl.appendChild(chip)
    }
  }

  function _renderHealth(job) {
    if (!healthEl) return
    const h = latestHealth(job)
    const cards = [
      ['Base pairs', h?.bp_retained_fraction != null ? `${Math.round(h.bp_retained_fraction * 100)}%` : '—',
        h && h.bp_retained_fraction != null && h.bp_retained_fraction < 0.8 ? _C.warn : _C.ok],
      ['Pot. energy', h?.potential_energy != null ? h.potential_energy.toFixed(3) : '—', _C.text],
      ['Max clash', h?.max_backbone_clash != null ? `${h.max_backbone_clash.toFixed(2)} nm` : '—',
        h && h.max_backbone_clash != null && h.max_backbone_clash > 1.5 ? _C.warn : _C.text],
      ['Speed', h?.steps_per_s != null ? `${Math.round(h.steps_per_s)} st/s` : '—', _C.dim],
    ]
    healthEl.innerHTML = ''
    healthEl.style.cssText = 'display:grid;grid-template-columns:1fr 1fr;gap:4px;margin-top:6px'
    for (const [label, val, col] of cards) {
      const c = document.createElement('div')
      c.style.cssText = 'background:#1c1c1c;border-radius:4px;padding:4px 6px'
      c.innerHTML = `<div style="font-size:9px;color:${_C.dim}">${label}</div>` +
                    `<div style="font-size:13px;color:${col}">${val}</div>`
      healthEl.appendChild(c)
    }
  }

  // ── Production (enabled only after a relaxation completes — mirrors MD) ─────
  // Central button-state: Relax + Production grey out while a production run is
  // active; Show RMSD unlocks only after a production stage completes.
  function _updateButtons(job) {
    const ps = productionState(job)
    const prodRunning = job?.status === 'running' && ps === 'running'
    const prodReady = job?.status === 'completed' && ps === 'none'

    // Relax — disabled while unavailable, launching, or a production run is active.
    if (runBtn) runBtn.disabled = !_available || _launching || prodRunning

    if (prodBtn) {
      prodBtn.disabled = !prodReady
      prodBtn.style.cursor = prodReady ? 'pointer' : 'not-allowed'
      prodBtn.style.background = prodReady ? '#1a4a1a' : '#122117'
      prodBtn.style.borderColor = prodReady ? '#3fb950' : '#30363d'
      prodBtn.style.color = prodReady ? '#3fb950' : '#484f58'
    }
    if (prodRunning) _setProdStatus('Production running…', _C.warn)
    else if (ps === 'done')   _setProdStatus('Production complete.', _C.ok)
    else if (ps === 'failed') _setProdStatus('Production failed.', _C.err)
    else _setProdStatus(prodReady ? 'Ready to run production from the relaxed structure.'
                                  : 'Production unlocks after relaxation completes.', _C.dim)

    // Flexibility map (RMSF) — toggle unlocks only after a production run finishes.
    if (flexToggle && !_flexBusy) {
      const ok = ps === 'done'
      flexToggle.disabled = !ok
      const lab = flexToggle.closest('label')
      if (lab) { lab.style.opacity = ok ? '1' : '0.5'; lab.style.cursor = ok ? 'pointer' : 'not-allowed' }
      if (!ok && flexStatus && oxdnaDisplay?.mode() !== 'rmsf') {
        _setFlexStatus(ps === 'running' ? 'Running production…' : 'Waiting for production', _C.dim)
      }
    }

    // Use as NAMD seed — only once the relaxation has completed.
    if (seedBtn && !_seeding) {
      const ok = seedReady(job)
      seedBtn.disabled = !ok
      seedBtn.style.cursor = ok ? 'pointer' : 'not-allowed'
      seedBtn.style.background = ok ? '#21262d' : '#122117'
      seedBtn.style.color = ok ? '#c9d1d9' : '#484f58'
    }
  }
  function _setProdStatus(text, color = _C.dim) {
    if (prodStatus) { prodStatus.textContent = text; prodStatus.style.color = color }
  }
  function _selectedJob() { return _jobs.find(j => j.job_id === _selectedId) || null }

  prodBtn?.addEventListener('click', async () => {
    if (!_selectedId || prodBtn.disabled) return
    const steps = parseInt(prodStepsInput?.value || '5000000', 10)
    prodBtn.disabled = true
    if (runBtn) runBtn.disabled = true     // grey out both immediately on press
    _setProdStatus('Starting production run…', _C.accent)
    const r = await api.appendOxdnaProduction(_selectedId, { steps })
    if (r?.status === 'running') {
      showToast('oxDNA production started', 'ok')
      _setProdStatus('Production running…', _C.warn)
      await _fetchJobs()
    } else {
      _setProdStatus(api.lastErrorMessage?.() || 'Failed to start production (see console)', _C.err)
      prodBtn.disabled = false
    }
  })

  exportBtn?.addEventListener('click', async () => {
    exportBtn.disabled = true
    const prev = exportBtn.textContent
    exportBtn.textContent = 'Preparing ZIP…'
    const ok = await api.exportOxdna()
    exportBtn.textContent = ok ? 'ZIP downloaded' : 'Export failed — see console'
    setTimeout(() => { exportBtn.textContent = prev; exportBtn.disabled = false }, 2000)
  })

  // ── Flexibility map (production avg structure recoloured by per-base RMSF) ───
  function _setFlexStatus(text, color = _C.dim) {
    if (flexStatus) { flexStatus.textContent = text; flexStatus.style.color = color }
  }
  function _setFlexBar(state) {
    // state: 'computing' (indeterminate stripe) | 'done' | 'off'
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
    // viridis ramp: dark-purple (rigid) → yellow (flexible)
    flexLegend.innerHTML =
      `<div style="display:flex;align-items:center;gap:5px;font-size:9px;color:${_C.dim};margin-top:3px">` +
      `<span>${min.toFixed(2)} nm</span>` +
      `<span style="flex:1;height:7px;border-radius:3px;background:linear-gradient(90deg,#440154,#3b528b,#21918c,#5dc863,#fde725)"></span>` +
      `<span>${max.toFixed(2)} nm</span></div>` +
      `<div style="font-size:9px;color:${_C.dim}">rigid → flexible (RMSF)</div>`
  }
  function _setFlexOff() {
    if (oxdnaDisplay?.mode() === 'rmsf') oxdnaDisplay.stopAndRestore()
    if (flexToggle) flexToggle.checked = false
    flexScale.hide()
    _setFlexBar('off')
    _setFlexLegend(null, null)
    _setFlexStatus('Off', _C.dim)
  }
  async function _refreshFlex() {
    if (!_selectedId || !oxdnaDisplay) return
    _flexBusy = true
    _setFlexStatus('Computing average structure + RMSF…', _C.accent)
    _setFlexBar('computing')
    const r = await oxdnaDisplay.displayRmsf(_selectedId)
    _flexBusy = false
    if (r.ok) {
      _setFlexBar('done')
      _setFlexLegend(r.min, r.max)
      flexScale.show(r.min, r.max)
      _setFlexStatus(`Avg of production · ${r.n} bases coloured by RMSF`, _C.ok)
    } else {
      _setFlexBar('off')
      _setFlexLegend(null, null)
      _setFlexStatus(r.reason === 'waiting for production' ? 'Waiting for production'
                                                          : (r.reason || 'no data'), _C.warn)
      if (flexToggle) flexToggle.checked = false
    }
    _updateButtons(_selectedJob())
  }
  flexToggle?.addEventListener('change', async () => {
    if (flexToggle.checked) {
      if (!_selectedId) { flexToggle.checked = false; showToast('Select an oxDNA job first', 'warn'); return }
      if (productionState(_selectedJob()) !== 'done') {
        flexToggle.checked = false; _setFlexStatus('Waiting for production', _C.warn); return
      }
      if (displayToggle?.checked) _setDisplayOff()   // mutually exclusive with OxDNA display
      await _refreshFlex()
    } else {
      _setFlexOff()
    }
  })

  // ── Use as NAMD seed (Phase 2 — feed relaxed coords into a NAMD MD run) ─────
  function _setSeedStatus(text, color = _C.dim) {
    if (seedStatus) { seedStatus.textContent = text; seedStatus.style.color = color }
  }
  seedBtn?.addEventListener('click', async () => {
    if (!_selectedId || seedBtn.disabled || _seeding) return
    const src = _selectedJob()
    _seeding = true
    seedBtn.disabled = true
    _setSeedStatus('Building NAMD seed + solvating (this can take 1–2 min)…', _C.accent)
    const job = await api.createMdJob({
      oxdna_job_id: _selectedId,
      design_source_path: src?.design_source_path || _currentPartPath(),
      autostart: false,
    })
    _seeding = false
    if (job?.job_id && job.status !== 'failed') {
      _setSeedStatus('NAMD seed job created — see Molecular Dynamics below.', _C.ok)
      showToast('NAMD seed job created from relaxed oxDNA structure', 'ok')
      _revealMdPanel()
    } else {
      const detail = job?.error || api.lastErrorMessage?.()
      _setSeedStatus(detail || 'Failed to create NAMD seed (see console)', _C.err)
    }
    _updateButtons(_selectedJob())
  })

  // Collapse this oxDNA panel and open the Molecular Dynamics panel so the new
  // seeded job is visible right away.  Expanding MD via its own heading click
  // keeps its collapse state consistent and refreshes its job list.
  function _revealMdPanel() {
    if (!_collapsed) {
      _collapsed = true
      body.style.display = 'none'
      arrow?.classList.toggle('is-collapsed', true)
      setSectionCollapsed('dynamics', 'oxdna-jobs-panel', true)
    }
    if (getSectionCollapsed('dynamics', 'md-jobs-panel', true)) {
      document.getElementById('md-jobs-panel-heading')?.click()
    }
  }

  // ── Detail actions ───────────────────────────────────────────────────────
  startBtn?.addEventListener('click', async () => {
    if (!_selectedId) return
    await api.startOxdnaJob(_selectedId)
    _fetchJobs()
  })
  stopBtn?.addEventListener('click', async () => {
    if (!_selectedId) return
    await api.stopOxdnaJob(_selectedId)
    _fetchJobs()
  })
  deleteBtn?.addEventListener('click', async () => {
    if (!_selectedId) return
    await api.deleteOxdnaJob(_selectedId)
    if (oxdnaDisplay?.activeJobId() === _selectedId) _allDisplaysOff()
    _selectedId = null
    if (detailEl) detailEl.style.display = 'none'
    _updateButtons(null)
    _fetchJobs()
  })

  // ── OxDNA display toggle ───────────────────────────────────────────────────
  async function _refreshDisplay() {
    if (!_selectedId || !oxdnaDisplay) return
    const r = await oxdnaDisplay.displayJob(_selectedId)
    _setDisplayStatus(r.ok ? `Showing relaxed positions (${r.stage || ''}, ${r.n} nt)` : (r.reason || 'no data'),
                      r.ok ? _C.ok : _C.warn)
  }
  function _setDisplayOff() {
    if (oxdnaDisplay?.mode() === 'relaxed') oxdnaDisplay.stopAndRestore()
    if (displayToggle) displayToggle.checked = false
    _setDisplayStatus('Display off', _C.dim)
  }
  // Turn off whichever overlay is active (relaxed display OR flexibility map).
  function _allDisplaysOff() {
    if (oxdnaDisplay?.mode() === 'rmsf') _setFlexOff()
    else _setDisplayOff()
    // Defensive: ensure both checkboxes are cleared and the renderer restored.
    if (oxdnaDisplay?.isActive()) oxdnaDisplay.stopAndRestore()
    if (displayToggle) displayToggle.checked = false
    if (flexToggle) flexToggle.checked = false
  }
  displayToggle?.addEventListener('change', async () => {
    if (displayToggle.checked) {
      if (!_selectedId) { displayToggle.checked = false; showToast('Select an oxDNA job first', 'warn'); return }
      if (flexToggle?.checked) _setFlexOff()   // mutually exclusive with the flexibility map
      await _refreshDisplay()
    } else {
      _setDisplayOff()
    }
  })

  // ── Pause display when leaving the Dynamics tab ───────────────────────────
  window.addEventListener('nadoc:left-tab-change', (e) => {
    if (e.detail?.activeTab !== 'dynamics') {
      if (oxdnaDisplay?.isActive()) _allDisplaysOff()
      if (_pollTimer) { clearTimeout(_pollTimer); _pollTimer = null }
    } else if (!_collapsed) {
      _onOpen()
    }
  })

  // ── Design switched/opened → re-filter the list to the new design ─────────
  // Without this the list keeps showing the previous design's jobs (and the
  // selection/display belong to the old design).  Mirrors md_jobs_panel.
  window.addEventListener('nadoc:workspace-path-change', () => {
    if (oxdnaDisplay?.isActive()) _allDisplaysOff()
    _selectedId = null
    if (detailEl) detailEl.style.display = 'none'
    _updateButtons(null)
    if (_collapsed) _renderList()   // re-filter cached jobs to the new path
    else _fetchJobs()               // fresh fetch + re-filter
  })

  // initial availability probe (cheap) so the status line is populated.
  _checkAvailable()
  if (!_collapsed) _onOpen()

  return { refresh: _fetchJobs }
}
