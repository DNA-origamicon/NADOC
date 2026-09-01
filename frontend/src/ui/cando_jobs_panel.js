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

import { initJobsPanelBase } from './jobs_panel_base.js'
import { selectionUpdatesVisualization } from './visualization_selection_policy.js'
import { showToast } from './toast.js'
import { filterJobsForPart } from './md_jobs_panel.js'
import { buildJobListModel, jobListSignature } from './jobs_panel_model.js'
import { renderJobList } from './jobs_panel_render.js'
import { formatJobTime } from '../scene/trajectory_range.js'
import { confirmNoConcurrentJob } from './job_activity.js'
import { initCandoMetricsCard } from './cando_metrics_card.js'

const CANDO_DISPLAY_PHASE_LABELS = {
  thermal: 'Load representative thermal conformation',
  'thermal-download': 'Download representative conformation',
  'thermal-decode': 'Decode representative conformation',
  snapshot: 'Build snapshot geometry',
  'display-data': 'Load predicted positions',
  rmsf: 'Load flexibility values',
  deviation: 'Compute deviation map',
  cylinders: 'Build CanDo cylinders',
  transform: 'Transform display data',
  'render-snapshot': 'Build snapshot scene',
  'reuse-scene': 'Reuse matching live scene',
  apply: 'Apply visualization',
  error: 'Visualization failed',
}

/** Render retained, labelled progress rows for a CanDo visualization selection. */
export function renderCandoDisplayProgress(el, phases) {
  if (!el) return
  el.replaceChildren()
  for (const [phase, p] of phases) {
    const row = document.createElement('div')
    row.dataset.candoDisplayPhase = phase
    row.style.marginTop = el.childElementCount ? '4px' : '0'
    const track = document.createElement('div')
    track.style.cssText = 'height:4px;background:#21262d;border-radius:3px;overflow:hidden'
    const fill = document.createElement('div')
    fill.style.cssText = 'height:100%;background:#4a9eff;transition:width .15s'
    const pct = p.total ? Math.max(0, Math.min(100, (100 * p.done) / p.total)) : 0
    fill.style.width = `${pct}%`
    track.appendChild(fill)
    const label = document.createElement('div')
    label.style.cssText = 'margin-top:3px;color:#8b949e;font-size:10px'
    const count = p.total ? `${Math.min(p.done, p.total)} of ${p.total}` : 'working…'
    label.textContent = `${CANDO_DISPLAY_PHASE_LABELS[phase] || phase} · ${count}`
    row.append(track, label)
    el.appendChild(row)
  }
}

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
  // Older assembly jobs recorded the internal materialization label as
  // "Flattened:_Name". Flattening is an implementation detail, not the user's
  // design name; keep those persisted jobs readable too.
  return String(job.design_name || 'design').replace(/^Flattened:\s*_?/i, '') || 'design'
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
/**
 * Total loop/skip marks in a converged mark set ``{helix:{bp:delta}}`` (pure).  The autorefine's
 * work lands here — the SQUARE density sweep writes the whole skip pattern to ``converged_marks``
 * (NOT ``edits_kept``, which only counts the greedy hotspot pass) — so a summary keyed on this is
 * the one that shows a density-driven refinement.
 */
export function refineMarkCounts(result) {
  const marks = result?.converged_marks || {}
  let skips = 0, loops = 0
  for (const bps of Object.values(marks)) {
    for (const dl of Object.values(bps)) {
      if (dl < 0) skips += 1
      else if (dl > 0) loops += 1
    }
  }
  return { skips, loops, total: skips + loops }
}

/**
 * Did the refine actually improve the design vs as-loaded (pure)?  True when the deviation RMSD
 * dropped — this catches BOTH the density sweep (which can lower RMSD with zero greedy edits) and
 * the greedy pass.  The old gate keyed on ``edits_kept.length`` and so reported a large
 * density-driven improvement (e.g. RMSD 1.73→0.46 on a square strut) as "no improving edit found".
 */
export function refineImproved(result) {
  if (!result) return false
  const before = result.before?.rmsd
  const after = result.after?.rmsd
  if (typeof before === 'number' && typeof after === 'number') return after < before - 1e-4
  return (result.edits_kept?.length ?? 0) > 0
}

export function autorefineStatusText(run) {
  if (!run) return ''
  if (run.state === 'error') return `Failed: ${run.error || 'autorefine error'}`
  if (run.state === 'stopped') return 'Stopped.'
  if (run.state === 'done') {
    const m = run.result?.metrics
    const { total } = refineMarkCounts(run.result)
    const n = total || (run.result?.edits_kept?.length ?? 0)
    const editStr = `${n} mark${n === 1 ? '' : 's'}`
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
  const { skips, loops } = refineMarkCounts(result)
  const kept = result.edits_kept?.length ?? 0
  const density = result.density
  // Headline: what the refine landed.  For a SQUARE density sweep, the marks come as a uniform
  // skip period; otherwise report the skip/loop mix + any local greedy edits.
  const parts = []
  if (density && density.best_period != null) {
    parts.push(`skip density: period ${density.best_period} → ${skips} deletion${skips === 1 ? '' : 's'}`)
    if (kept) parts.push(`${kept} local edit${kept === 1 ? '' : 's'}`)
  } else {
    const bits = []
    if (skips) bits.push(`${skips} skip${skips === 1 ? '' : 's'}`)
    if (loops) bits.push(`${loops} loop${loops === 1 ? '' : 's'}`)
    parts.push(`${bits.join(' + ') || 'no marks'} kept`)
  }
  const rows = [
    `deviation ${_fmtNm(m.before?.deviation)} → <b>${_fmtNm(m.after?.deviation)}</b> (target 0)`,
    `curvature ${_fmtDeg(m.before?.bend_deg)} → <b>${_fmtDeg(m.after?.bend_deg)}</b> (target ${_fmtDeg(m.target?.bend_deg)})`,
    `twist ${_fmtDeg(m.before?.twist_deg)} → <b>${_fmtDeg(m.after?.twist_deg)}</b> (target ${_fmtDeg(m.target?.twist_deg)})`,
  ]
  return `<div style="font-size:11px;color:#8b949e;line-height:1.5">`
    + `<div>${parts.join(' · ')}</div>`
    + rows.map((r) => `<div>${r}</div>`).join('') + `</div>`
}

// ── Autorefine JOB status/result (the auto-applying job flow; pure, unit-tested) ─────────────
/** Live status line for an autorefine JOB poll payload (uses the server-built ``refine_note``). */
export function autorefineJobStatusText(job) {
  if (!job) return ''
  if (job.status === 'failed') return `Failed: ${job.error || 'autorefine error'}`
  if (job.status === 'stopped') return job.refine_note || 'Stopped.'
  if (job.status === 'completed') return job.refine_note || 'Done.'
  return job.refine_note || 'Autorefining…'
}

/** Result summary HTML for a COMPLETED autorefine job: what it auto-applied (or that nothing
 *  improved) + a pointer that the job's displays are ready.  No Apply button — the job already
 *  applied the marks to the design as a reversible feature-log entry. */
export function autorefineJobResultHtml(job) {
  if (!job || job.status !== 'completed') return ''
  const b = job.refine_before_rmsd, a = job.refine_after_rmsd
  if (!job.refine_applied) {
    return `<div style="font-size:11px;color:#8b949e;line-height:1.5">`
      + `<div>No improving loop/skip program found — deviation ${_fmtNm(b)} is already as low as `
      + `the marks allow. Nothing applied.</div></div>`
  }
  const per = job.refine_period != null ? ` · period ${job.refine_period}` : ''
  const n = job.refine_n_marks ?? 0
  return `<div style="font-size:11px;color:#8b949e;line-height:1.5">`
    + `<div><b>Applied ${n} loop/skip mark${n === 1 ? '' : 's'}</b>${per} — reversible in the Feature Log</div>`
    + `<div>deviation ${_fmtNm(b)} → <b>${_fmtNm(a)}</b> (target 0)</div>`
    + `<div>Select this job below to view its predicted shape / flexibility / deviation / cylinder displays.</div>`
    + `</div>`
}

// ── Factory ───────────────────────────────────────────────────────────────────

export function initCandoJobsPanel({ candoDisplay = null, getWorkspacePath = null, getSelection = null } = {}) {
  const $ = (id) => document.getElementById(id)
  const panel = $('cando-jobs-panel')
  const heading = $('cando-jobs-heading')
  const body = $('cando-jobs-body')
  if (!panel || !body) return { refresh: () => {}, getSelectedJob: () => null }   // heading optional (removed; tab names the engine)

  const arrow = $('cando-jobs-arrow')
  const coarseBtn = $('cando-jobs-coarse-btn')
  const fineBtn = $('cando-jobs-fine-btn')
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
  const summaryEl = $('cando-jobs-summary')
  const detailError = $('cando-jobs-detail-error')
  const stopBtn = $('cando-jobs-stop-btn')
  const displayStatus = $('cando-jobs-display-status')
  const modeRadios = () => Array.from(panel.querySelectorAll('.cando-display-mode'))
  const checkedMode = () => modeRadios().find((r) => r.checked)?.value || 'off'
  const setMode = (value) => modeRadios().forEach((r) => { r.checked = r.value === value })

  let _jobs = []
  let _selectedId = null
  let _progress = null
  let _launching = false   // re-entrancy guard: a launch is between click and job-registered
  let _listSig = null            // last-rendered list signature (avoids spinner-restart churn)
  const _legend = { el: null }   // status-symbol legend, inserted once after the list

  const _selectedJob = () => _jobs.find((j) => j.job_id === _selectedId) || null

  // Canonical job-list model + renderer (U3): CanDo converges to the oxDNA look
  // (list index, status glyph/spinner, legend). CanDo jobs are flat (no
  // parent/child tree, no archive/size); the Coarse/Fine solver mode rides the
  // canonical leading-tag slot (the [AR] tag's slot on oxDNA).
  function _rowCtx() {
    return {
      engine: 'cando',
      selectedId: _selectedId,
      hierarchical: false,
      displayName: jobDisplayName,
      isActive: candoJobIsActive,
      formatTime: formatJobTime,
      tags: (job) => [{
        text: job.nonlinear ? 'Fine' : 'Coarse', color: _C.dim,
        title: job.nonlinear ? 'Fine (nonlinear)' : 'Coarse (linear)',
      }],
      rowSig: (j) => `${j.job_id}:${j.status}:${j.nonlinear ? 1 : 0}`,
      colors: { dim: _C.dim, warn: _C.warn },
    }
  }

  // Graphs & Metrics card — a child module reading the panel's job selection.
  const _metricsCard = initCandoMetricsCard({ getSelectedJob: _selectedJob })

  // Anchors + Electric-field cards — mimics of the oxDNA panel's, feeding the FEM solve
  // (C1/C2).  The anchors card shares the exact oxDNA scope resolver (parameterised ids);
  // the field card is numeric-only (the oxDNA panel owns the one in-scene arrow gizmo).
  const _anchorsCard = initOxdnaAnchorsSetup({
    engine: 'cando',
    getSelection: () => (getSelection ? getSelection() : null),
    ids: {
      toggle: 'cando-anchors-toggle', arrow: 'cando-anchors-arrow', body: 'cando-anchors-body',
      add: 'cando-anchors-add', clear: 'cando-anchors-clear', list: 'cando-anchors-list',
      status: 'cando-anchors-status', glow: 'cando-anchors-glow',
    },
  })
  const _efieldCard = initForcesCard({
    engine: 'cando',
    getAnchorCount: () => _anchorsCard?.getAnchors?.()?.length || 0,
  })

  // ── Shared scaffold: collapse + advanced drawer + poll loop (U3 base) ─────────
  const _base = initJobsPanelBase({
    section: 'cando-jobs-panel',
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
      const anchors = _anchorsCard.getAnchors()
      const fieldSpec = _efieldCard.getFieldSpec()
      const fieldOn = _efieldCard.isEnabled()
      // A uniform field with no anchor just streams the whole structure (COM drift) —
      // the E-field card shows a warning notice, but the solve is allowed (not blocked).
      const body_ = {
        nonlinear,
        n_steps:   Math.max(1, parseInt(stepsInput?.value, 10) || 20),
        with_rmsf: rmsfInput ? !!rmsfInput.checked : true,
        with_thermal_fluctuations: rmsfInput ? !!rmsfInput.checked : true,
        autostart: true,
        design_source_path: getWorkspacePath?.() || null,
        anchors: anchors.length ? anchors : null,
        field:   fieldOn ? { field_pN: fieldSpec.field_pN, dir: fieldSpec.dir } : null,
      }
      // Assembly materialization happens before POST /cando/jobs inside the shared API
      // client. Put a real-looking temporary row on screen before that potentially long
      // request so the click is acknowledged immediately and its current process is clear.
      const optimisticId = `preparing-${Date.now()}`
      const optimistic = {
        job_id: optimisticId, design_name: getWorkspacePath?.() || 'assembly',
        design_source_path: getWorkspacePath?.() || null, nonlinear,
        status: 'preparing', created_at: Date.now() / 1000,
        stages: [{ name: nonlinear ? 'nonlinear' : 'linear', status: 'pending' }],
      }
      _jobs = [optimistic, ..._jobs]
      _selectedId = optimisticId
      _progress = { overall: 0, phases: [
        { name: 'materialize', label: 'Materialize complete assembly', fraction: 0 },
        { name: 'register', label: 'Register CanDo job', fraction: 0 },
      ] }
      _renderList()
      _renderDetail()
      window.dispatchEvent(new CustomEvent('nadoc:sim-jobs-changed', { detail: {
        node: { ...optimistic, engine: 'cando', progress_fraction: 0 }, select: true,
      } }))
      const job = await api.createCandoJob(body_)
      if (!job) {
        _jobs = _jobs.filter(j => j.job_id !== optimisticId)
        _selectedId = null
        _progress = null
        _renderList(); _renderDetail()
        showToast(api.lastErrorMessage() || 'Failed to start CanDo FEM prediction', { severity: 'error' })
        return
      }
      _selectedId = job.job_id
      await _fetchJobs()
      window.dispatchEvent(new CustomEvent('nadoc:sim-jobs-changed'))
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
  let _arJobId = null
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
  function _updateArButton() {
    if (!arBtn) return
    arBtn.disabled = _arRunning
    arBtn.style.cursor = _arRunning ? 'not-allowed' : 'pointer'
    arBtn.style.opacity = _arRunning ? '0.5' : '1'
    if (arStopBtn) arStopBtn.style.display = _arRunning ? '' : 'none'
  }

  function _renderArJobResult(job) {
    if (!arResult) return
    arResult.innerHTML = autorefineJobResultHtml(job)
  }

  async function _pollAutorefineJob(jobId) {
    let job
    try { job = await api.getCandoJob(jobId) } catch { job = null }
    if (!job) { _arPollTimer = setTimeout(() => _pollAutorefineJob(jobId), 1200); return }
    if (['queued', 'preparing', 'running'].includes(job.status)) {
      _setArStatus(autorefineJobStatusText(job), _C.warn, true)
      _arPollTimer = setTimeout(() => _pollAutorefineJob(jobId), 1000)
      return
    }
    // terminal (completed / stopped / failed)
    _arRunning = false
    _updateArButton()
    const color = job.status === 'failed' ? _C.err : job.status === 'stopped' ? _C.dim : _C.ok
    _setArStatus(autorefineJobStatusText(job), color, false)
    _renderArJobResult(job)
    // The refine auto-APPLIED its marks server-side (feature log) → pull the updated design so the
    // editor + feature log reflect it; refresh the jobs list + select the job so its display modes
    // (predicted shape / flex / deviation / cylinders) are immediately available.
    if (job.status === 'completed') {
      if (job.refine_applied) {
        await api.getDesign()
        showToast('Autorefine applied loop/skips to the design (see Feature Log)', { severity: 'info' })
      }
      _selectedId = jobId
    }
    await _fetchJobs()
  }

  async function _startAutorefine() {
    if (_arRunning) return
    if (!(await confirmNoConcurrentJob())) return
    _arRunning = true; _arJobId = null
    if (arResult) arResult.innerHTML = ''
    _updateArButton()
    _setArStatus('Starting autorefine…', _C.warn, true)
    // An autorefine JOB: Coarse (linear) FEM oracle per trial (fast), auto-applies the best
    // loop/skip program as a reversible feature-log entry, then caches the FEM analysis of the
    // refined design so all display modes work on the job.
    const job = await api.createCandoJob({
      kind: 'autorefine', nonlinear: false, autostart: true,
      design_source_path: getWorkspacePath?.() || null,
    })
    if (!job || !job.job_id) {
      _arRunning = false; _updateArButton()
      _setArStatus('Failed to start: ' + (api.lastErrorMessage() || 'could not create autorefine job'), _C.err, false)
      return
    }
    _arJobId = job.job_id
    _pollAutorefineJob(_arJobId)
  }
  arBtn?.addEventListener('click', _startAutorefine)
  arStopBtn?.addEventListener('click', async () => {
    if (!_arJobId) return
    if (arStopBtn) arStopBtn.disabled = true
    _setArStatus('Stopping…', _C.dim, true)
    await api.stopCandoJob(_arJobId)
    if (arStopBtn) arStopBtn.disabled = false
  })

  // ── Jobs list + poll ────────────────────────────────────────────────────────
  async function _fetchJobs() {
    const all = await api.listCandoJobs()
    if (!Array.isArray(all)) return
    _jobs = filterJobsForPart(all, getWorkspacePath?.() || null, showAll?.checked)
    // A freshly launched assembly job may have no source path because its input is a
    // transient flattened projection. Never let the part-path filter hide the job the
    // user just launched while it is running (or after it completes).
    const selected = all.find(j => j.job_id === _selectedId)
    if (selected && !_jobs.some(j => j.job_id === selected.job_id)) _jobs.unshift(selected)
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
    _notifyIfJobsChanged()
    _base.schedulePoll()
  }

  // Wake the master job list + progress bar (simulate_jobs.js, the VISIBLE list) whenever
  // THIS panel's job set/statuses change — a launch, autorefine, stop, or completion. The
  // master self-polls only while it already holds an active node, so a run launched while
  // it's idle would otherwise not surface until a manual page refresh.
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
      emptyText: 'No CanDo FEM jobs for this design yet.',
      dimColor: _C.dim,
      legendState: _legend,
    })
  }

  async function _selectJob(jobId) {
    _selectedId = jobId
    _progress = await api.getCandoProgress(jobId)
    _renderList()
    _renderDetail()
    if (selectionUpdatesVisualization(_selectedJob())) await _retargetDisplayToSelection()
    _base.schedulePoll()
  }

  /** Clicking the ALREADY-selected row deselects it: the row highlight and the detail
   *  block clear, but nothing cached is thrown away — the predicted-shape / flexibility /
   *  deviation overlay stays on screen and candoDisplay keeps the data it loaded, so
   *  re-selecting the same job costs nothing.  Only picking a DIFFERENT job retargets
   *  (and therefore drops) the cached visualization — that's `_retargetDisplayToSelection`,
   *  deliberately NOT called here. */
  function _deselectJob() {
    _selectedId = null
    _progress = null
    _renderList()
    _renderDetail()
    _base.schedulePoll()
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
    _syncDisplayModes()
    if (!detail) return
    if (!job) { detail.style.display = 'none'; _syncDisplayStatus(); return }
    detail.style.display = ''
    if (summaryEl) {
      const html = formatSummary(job)
      summaryEl.style.display = html ? '' : 'none'
      summaryEl.innerHTML = html
    }
    if (detailError) {
      detailError.style.display = job.status === 'failed' ? '' : 'none'
      detailError.textContent = job.status === 'failed' ? (job.error || 'Solve failed.') : ''
    }
    if (stopBtn) stopBtn.style.display = job.status === 'running' ? '' : 'none'
    _syncDisplayStatus()
    _metricsCard?.sync()
  }

  /** Gate the always-visible Display card's radios: enabled only for a completed job
   *  (+ the candoDisplay dep); the Flexibility map additionally needs computed RMSF.
   *  No selection / an unfinished job leaves every radio locked. */
  function _syncDisplayModes() {
    const job = _selectedJob()
    const ready = job?.status === 'completed'
    // Deselecting leaves the previous job's overlay on screen (it's cached, not cleared),
    // so "Off" has to stay clickable with nothing selected — otherwise the only way to
    // take that overlay down would be to re-select the job first.
    const overlayUp = !!candoDisplay?.deformActive?.()
    modeRadios().forEach((r) => {
      if (r.value === 'off') { r.disabled = !candoDisplay || (!ready && !overlayUp); return }
      const needsRmsf = r.value === 'flex'
      r.disabled = !ready || !candoDisplay || (needsRmsf && !job?.rmsf_max_nm)
    })
  }

  /** Readout under the radios: the active mode + its scalar range / RMSD. */
  const _displayLoadPhases = new Map()
  function _showDisplayProgress(p) {
    if (!p || !displayStatus) return
    if (p.reset) _displayLoadPhases.clear()
    if (p.phase) _displayLoadPhases.set(p.phase, {
      done: Math.max(0, Number(p.done) || 0), total: Math.max(0, Number(p.total) || 0),
    })
    renderCandoDisplayProgress(displayStatus, _displayLoadPhases)
  }
  function _syncDisplayStatus() {
    if (!displayStatus) return
    _displayLoadPhases.clear()
    const mode = candoDisplay?.mode?.()
    if (!mode) { displayStatus.textContent = ''; return }
    const s = candoDisplay?.lastStats?.()
    if (mode === 'flex' && s?.kind === 'flex') {
      displayStatus.textContent = `Flexibility (RMSF) ${s.min.toFixed(2)}–${s.max.toFixed(2)} nm` +
        (s.thermal ? ` · representative 298 K conformation` : '')
    } else if (mode === 'deviation' && s?.kind === 'deviation') {
      displayStatus.textContent =
        `Deviation from design — RMSD ${s.rmsd.toFixed(2)} nm (max ${s.max.toFixed(2)} nm)` +
        (s.thermal ? ` · representative 298 K conformation` : '')
    } else if (mode === 'cando' && s?.kind === 'cando') {
      displayStatus.textContent =
        `CanDo-style cylinders — ${s.helices} helix tubes, ${s.joints} crossover joints` +
        (s.thermal ? ` · representative 298 K conformation` : '')
    } else if (mode === 'deform' && s?.kind === 'deform' && s.thermal) {
      displayStatus.textContent = `Predicted solution shape · representative 298 K thermal conformation`
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
  // Delete the selected CanDo job. Invoked by the consolidated #simulate-job-actions
  // Delete button (dispatched by the master card on the selected node). Returns true if
  // the delete went through.
  async function deleteSelected() {
    if (!_selectedId) return false
    const r = await api.deleteCandoJob(_selectedId)
    if (r?.ok) {
      if (candoDisplay?.deformJobId?.() === _selectedId) candoDisplay.stopDeform?.()
      _selectedId = null
      detail && (detail.style.display = 'none')
      await _fetchJobs()
      return true
    }
    showToast(api.lastErrorMessage() || 'Delete failed', { severity: 'error' })
    return false
  }

  // ── Display-mode radios (Off / Predicted shape / Flexibility / Deviation) ─────
  // Mutually exclusive; each supersedes the shared FEM overlay + scalar-colour channel.
  const _MODE_FNS = { deform: 'showDeform', flex: 'showFlex', deviation: 'showDeviation', cando: 'showCandoStyle' }
  async function _onModeChange() {
    if (!candoDisplay) { setMode('off'); return }
    const mode = checkedMode()
    candoDisplay.stopThermal?.()
    if (mode === 'off') { candoDisplay.stopDeform?.(); _syncDisplayStatus(); return }
    if (!_selectedId) { setMode('off'); return }
    _showDisplayProgress({ reset: true })
    let r
    try {
      r = await candoDisplay[_MODE_FNS[mode]]?.(
        _selectedId, _showDisplayProgress,
        { reuseLiveGeometry: _selectedJob()?.out_of_date === false },
      )
    } catch (err) {
      r = { ok: false, reason: err?.message || 'load failed' }
    }
    if (!r?.ok) {
      setMode('off'); candoDisplay.stopDeform?.()
      _showDisplayProgress({ phase: 'error', done: 1, total: 1 })
      showToast(mode === 'flex' ? 'RMSF not available for this job'
        : 'Predicted positions not ready', { severity: 'warn' })
      return
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

  _base.initCollapsed(true)

  // selectJob: highlight + populate this panel's detail as a row click does — used by
  // the unified Simulate list to route a CanDo node's selection here. Refetches if the
  // job isn't listed yet.
  async function selectJob(jobId) {
    if (!jobId) return
    // Mark the requested job before refetching. Assembly CanDo jobs are built from a
    // transient flattened projection and therefore have no design_source_path; the
    // normal workspace-path filter would otherwise discard the job before
    // _selectJob() can populate the Display card, leaving every mode disabled.
    _selectedId = jobId
    if (!_jobs.find((j) => j.job_id === jobId)) await _fetchJobs()
    return _selectJob(jobId)
  }
  return { refresh: _fetchJobs, getSelectedJob: _selectedJob, selectJob, deleteSelected,
           // Drop the selection without touching the display (the unified Simulate list
           // routes its own click-the-selected-row-to-deselect here).
           deselectJob: _deselectJob }
}
