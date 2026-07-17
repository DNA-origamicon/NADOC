/**
 * mrDNA jobs panel — launch + monitor a managed coarse ARBD relaxation on the
 * currently-loaded design.  Sibling of oxdna_jobs_panel.js, simplified to the
 * single-button UX: mrDNA's coarse stage starts from an energy minimisation, so
 * it IS the relaxation — one "Run mrDNA" button, one stage, no relax/production
 * split.
 *
 * REST-poll based (no WebSocket), exactly like the oxDNA panel: while a job is
 * queued/running the panel polls GET /mrdna/jobs + /mrdna/jobs/{id}/progress.
 *
 * Two display toggles, both Physical-layer / display-only:
 *   • "mrDNA display" → deform the NADOC model to the relaxed coarse positions.
 *   • "CG beads"      → draw the coarse ARBD bead cloud (5 bp/bead).
 *
 * Factory: initMrdnaJobsPanel({ mrdnaDisplay, getWorkspacePath }) → { refresh,
 * getSelectedJob }.  All cohesive logic lives here (module-first law); main.js
 * only imports + inits + does thin wiring.
 */

import { initJobsPanelBase } from './jobs_panel_base.js'
import { initForcesCard } from './forces_card.js'
import { initOxdnaAnchorsSetup } from './oxdna_anchors_setup.js'
import { initOxdnaFloorSetup } from './oxdna_floor_setup.js'
import { surfaceOpposesField } from './chain_sim_model.js'
import { showToast } from './toast.js'
import { filterJobsForPart } from './md_jobs_panel.js'
import { buildJobListModel, jobListSignature } from './jobs_panel_model.js'
import { renderJobList } from './jobs_panel_render.js'
import { formatJobTime } from '../scene/trajectory_range.js'
import { confirmNoConcurrentJob, confirmGpuNotBusy } from './job_activity.js'
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
export function mrdnaJobIsActive(job) {
  return ['queued', 'preparing', 'running'].includes(job?.status)
}

/**
 * Does an enabled E-field lack the ≥1 anchor it needs to avoid COM drift?  A uniform
 * field with no anchor streams the whole structure down-field.  Warn-only (policy
 * 2026-07-11, all engines): true here surfaces a caution — it NO LONGER blocks the
 * launch.  Mirrors oxDNA/NAMD/LAMMPS/chain-sim; the mrDNA backend also warns (never
 * 400s) server-side (routes_mrdna / mrdna_runner log a drift warning).
 *
 * Deposition case (M8): a hard surface the field presses straight INTO holds it too
 * (the plane's reaction balances the COM drift), so a field + opposing surface has no
 * drift to warn about.  The opposition test reuses the shared `surfaceOpposesField`
 * mirror — no geometry re-derived.
 */
export function fieldNeedsAnchor(fieldOn, anchors, fieldSpec = null, surfaceSpec = null) {
  if (!fieldOn) return false
  if (anchors && anchors.length) return false
  return !surfaceOpposesField(fieldSpec, surfaceSpec)
}

/**
 * Build the POST /mrdna/jobs create body (M6).  Pure: threads the shared Forces-card
 * field spec + shared Anchors-card list into the mrDNA payload under the SAME keys the
 * oxDNA/CanDo/NAMD pickers use — field: {field_pN, dir}, anchors: [scope dicts] — so
 * the mrDNA launch is byte-parity with the other engines' field/anchor requests.
 * The mrDNA field/anchors backends (M1/M2) are already implemented + tested; this
 * makes them reachable.  Three-Layer Law: these are job-request annotations, never
 * Design edits.
 */
export function buildMrdnaLaunchBody({
  coarseSteps, fineSteps, outputPeriod, device, sourcePath = null,
  anchors = [], fieldSpec = null, fieldOn = false,
  surfaceSpec = null, surfaceOn = false,
} = {}) {
  // Hard surface (M8): the shared floor card emits camelCase {dir, offsetNm, stiff};
  // the backend takes the cross-engine snake_case {dir, offset_nm, stiff} form (same as
  // oxDNA production).  Only threaded when enabled AND stiff — a bare/zero-stiff surface
  // is a no-op.
  const surface = (surfaceOn && surfaceSpec && surfaceSpec.stiff > 0)
    ? { dir: surfaceSpec.dir, offset_nm: surfaceSpec.offsetNm, stiff: surfaceSpec.stiff }
    : null
  return {
    coarse_steps:  Math.max(1000, parseInt(coarseSteps, 10) || 100000),
    fine_steps:    fineSteps,
    output_period: Math.max(100, parseInt(outputPeriod, 10) || 10000),
    device:        (String(device ?? '0').trim() || '0'),
    autostart:     true,
    design_source_path: sourcePath || null,
    anchors: (anchors && anchors.length) ? anchors : null,
    field:   (fieldOn && fieldSpec) ? { field_pN: fieldSpec.field_pN, dir: fieldSpec.dir } : null,
    surface,
  }
}

/** Human status line for the detail block. */
export function detailStatusText(job, progress) {
  if (!job) return ''
  switch (job.status) {
    case 'queued':    return 'Queued — preparing to run.'
    case 'preparing': return 'Writing the design snapshot…'
    case 'running': {
      const pct = formatProgress(job, progress)
      const eta = progress?.eta_seconds
      const etaStr = (typeof eta === 'number' && eta > 0) ? ` · ~${Math.ceil(eta)}s left` : ''
      return `Relaxing (coarse ARBD) ${pct}${etaStr}`
    }
    case 'completed': {
      const s = job.sim_seconds ? ` in ${job.sim_seconds}s` : ''
      const b = job.n_beads ? ` · ${job.n_beads} CG beads` : ''
      return `Relaxed${s}${b}. Toggle a display below.`
    }
    case 'stopped': return 'Stopped.'
    case 'failed':  return `Failed: ${job.error || 'see error log'}`
    default:        return job.status || ''
  }
}

/** Timeline glyphs for the job's stages (coarse, and fine when present). */
/** Pure: a job that can seed a NAMD run — its FINE stage must have completed (the
 * seed reconstruction needs the 1-bead/bp fine structure; a coarse-only job can't). */
export function seedReady(job) {
  return job?.status === 'completed' && (job?.fine_steps || 0) > 0
}

export function coarseStageChip(job) {
  const glyph = (st) => st === 'done' ? '●' : st === 'failed' ? '✗' : st === 'running' ? '◐' : '○'
  const stages = job?.stages?.length ? job.stages : [{ name: 'coarse', status: undefined }]
  return stages.map((s) => `${glyph(s.status)} ${s.name}`).join('  ')
}

/**
 * Designed-vs-simulated curvature readout HTML for the panel.  Curvature is a
 * twist-coupled effect only the FINE stage develops, so a coarse run shows the
 * designed value + a nudge to run Fine.  Pure (unit-tested); returns an HTML
 * string the panel drops into the readout div.
 */
export function formatCurvature(report) {
  const a = report?.analytic
  if (!a || !a.has_marks) {
    return '<span style="color:#8b949e">No loop/skip curvature marks — nothing to bend.</span>'
  }
  const fmtR = (r) => (typeof r === 'number' && isFinite(r)) ? `${r.toFixed(0)} nm` : '∞ (straight)'
  const designed =
    `<b>Designed</b> (Dietz): R=${fmtR(a.radius_nm)} · κ=${a.kappa_deg_per_nm.toFixed(2)}°/nm · bend ${a.bend_deg.toFixed(0)}°`
  const m = report?.measured
  if (!m) return designed
  if (!report.fine) {
    return designed +
      '<br><span style="color:#e0a800">Coarse run — curvature not simulated. Run <b>Fine</b> to check the bend.</span>'
  }
  const sim = `<b>Simulated</b> (mrDNA fine): R=${fmtR(m.radius_nm)} · bend ${m.bend_deg.toFixed(0)}°`
  let verdict = ''
  if (typeof report.ratio === 'number') {
    const pct = Math.round(report.ratio * 100)
    if (report.ratio < 0.5) {
      // Known limitation: the CG model (T0 crossover potentials) under-develops the
      // Dietz bend — surface it honestly rather than implying the design is wrong.
      verdict = `<br><span style="color:#e0a800">simulated ≈ ${pct}% of designed — the CG model ` +
        `under-reproduces loop/skip curvature (experimental); trust the designed value.</span>`
    } else {
      const col = report.ratio <= 1.7 ? '#3fb950' : '#e0a800'
      verdict = `<br><span style="color:${col}">simulated ≈ ${pct}% of designed curvature</span>`
    }
  }
  return `${designed}<br>${sim}${verdict}`
}

// ── Factory ───────────────────────────────────────────────────────────────────

export function initMrdnaJobsPanel({ mrdnaDisplay = null, getWorkspacePath = null, getSelection = null } = {}) {
  const $ = (id) => document.getElementById(id)
  const panel = $('mrdna-jobs-panel')
  const heading = $('mrdna-jobs-heading')
  const body = $('mrdna-jobs-body')
  if (!panel || !body) return { refresh: () => {}, getSelectedJob: () => null }   // heading optional (removed; tab names the engine)

  const arrow = $('mrdna-jobs-arrow')
  const statusEl = $('mrdna-jobs-status')
  const coarseBtn = $('mrdna-jobs-coarse-btn')
  const fineBtn = $('mrdna-jobs-fine-btn')
  const progressEl = $('mrdna-jobs-progress')
  const advToggle = $('mrdna-jobs-adv-toggle')
  const advArrow = $('mrdna-jobs-adv-arrow')
  const advBody = $('mrdna-jobs-adv-body')
  const stepsInput = $('mrdna-jobs-coarse-steps')
  const outputInput = $('mrdna-jobs-output-period')
  const deviceInput = $('mrdna-jobs-device')
  const showAll = $('mrdna-jobs-show-all')
  const listEl = $('mrdna-jobs-list')
  const detail = $('mrdna-jobs-detail')
  const detailStatus = $('mrdna-jobs-detail-status')
  const timeline = $('mrdna-jobs-timeline')
  const curvatureEl = $('mrdna-jobs-curvature')
  const detailError = $('mrdna-jobs-detail-error')
  const stopBtn = $('mrdna-jobs-stop-btn')
  const seedBtn = $('mrdna-jobs-seed-btn')
  const seedStatus = $('mrdna-jobs-seed-status')
  let _seeding = false
  const displayToggle = $('mrdna-jobs-display-toggle')
  const beadsToggle = $('mrdna-jobs-beads-toggle')
  const displayStatus = $('mrdna-jobs-display-status')

  let _jobs = []
  let _selectedId = null
  let _progress = null
  let _available = null
  let _listSig = null            // last-rendered list signature (avoids spinner-restart churn)
  const _legend = { el: null }   // status-symbol legend, inserted once after the list

  const _selectedJob = () => _jobs.find((j) => j.job_id === _selectedId) || null

  // Canonical job-list model + renderer (U3): mrDNA converges to the oxDNA look
  // (list index, status glyph/spinner, legend). mrDNA relaxations are flat (no
  // parent/child tree, no archive/size), so the ctx omits those callbacks.
  function _rowCtx() {
    return {
      engine: 'mrdna',
      selectedId: _selectedId,
      hierarchical: false,
      displayName: jobDisplayName,
      isActive: mrdnaJobIsActive,
      formatTime: formatJobTime,
      rowSig: (j) => `${j.job_id}:${j.status}`,
      colors: { dim: _C.dim, warn: _C.warn },
    }
  }

  // ── Shared scaffold: collapse + advanced drawer + poll loop (U3 base) ─────────
  const _base = initJobsPanelBase({
    section: 'mrdna-jobs-panel',
    els: { heading, body, arrow, advToggle, advArrow, advBody },
    pollMs: POLL_MS,
    collapsible: false,   // engine header is a static label; Simulate owns the collapse
    hasActive: () => _hasActiveJob(),
    tick: () => _fetchJobs(),
    onOpen: () => _onOpen(),
  })

  // ── Anchors + Electric-field cards (M6) ──────────────────────────────────────
  // Mount the SHARED cards (same as CanDo/NAMD) so mrDNA's already-implemented M1/M2
  // field/anchor backends are reachable.  Numeric field card (no gizmo — oxDNA owns the
  // one in-scene arrow); the anchors card shares the exact scope resolver via ids.
  const _anchorsCard = initOxdnaAnchorsSetup({
    engine: 'mrdna',
    getSelection: () => (getSelection ? getSelection() : null),
    ids: {
      toggle: 'mrdna-anchors-toggle', arrow: 'mrdna-anchors-arrow', body: 'mrdna-anchors-body',
      add: 'mrdna-anchors-add', clear: 'mrdna-anchors-clear', list: 'mrdna-anchors-list',
      status: 'mrdna-anchors-status', glow: 'mrdna-anchors-glow',
    },
  })
  const _efieldCard = initForcesCard({ engine: 'mrdna' })

  // ── Hard surface card (M8) ────────────────────────────────────────────────────
  // Mount the SHARED oxDNA floor card onto mrDNA's own DOM ids so the M7 ARBD
  // repulsion-plane backend is reachable.  Same {dir, offset_nm, stiff} descriptor;
  // no in-scene grid (that's oxDNA's floor render — omit setSurfaceGrid).
  const _surfaceCard = initOxdnaFloorSetup({
    ids: {
      toggle: 'mrdna-surface-toggle', arrow: 'mrdna-surface-arrow', body: 'mrdna-surface-body',
      enable: 'mrdna-surface-enable', controls: 'mrdna-surface-controls', axis: 'mrdna-surface-axis',
      offset: 'mrdna-surface-offset', offsetLabel: 'mrdna-surface-offset-label',
      stiff: 'mrdna-surface-stiff', ready: 'mrdna-surface-ready',
    },
  })

  // ── Availability ──────────────────────────────────────────────────────────────
  async function _checkAvailable() {
    _available = await api.mrdnaAvailable()
    const ok = !!_available?.available
    const missing = !_available?.mrdna ? 'mrDNA' : 'ARBD'
    window.dispatchEvent(new CustomEvent('nadoc:engine-availability', { detail: {
      engine: 'mrdna', ok, reason: `${missing} not installed.` } }))
    if (coarseBtn) coarseBtn.disabled = !ok
    if (fineBtn) fineBtn.disabled = !ok
    if (!statusEl) return
    if (ok) {
      statusEl.textContent = 'mrDNA + ARBD ready (GPU).'
      statusEl.style.color = _C.ok
    } else {
      statusEl.textContent = `${missing} not installed — open Help ▸ MD Engines to set up.`
      statusEl.style.color = _C.warn
    }
  }

  // ── Run (Coarse = fast/global shape; Fine = curvature via twist) ───────────────
  const FINE_DEFAULT_STEPS = 200000
  async function _launch(fineSteps) {
    if (!(await confirmNoConcurrentJob())) return
    if (!(await confirmGpuNotBusy())) return
    const anchors = _anchorsCard.getAnchors()
    const fieldSpec = _efieldCard.getFieldSpec()
    const fieldOn = _efieldCard.isEnabled()
    const surfaceSpec = _surfaceCard.getSurfaceSpec()
    const surfaceOn = _surfaceCard.isEnabled()
    if (fieldNeedsAnchor(fieldOn, anchors, fieldSpec, surfaceOn ? surfaceSpec : null)) {
      // Warn-only (policy 2026-07-11, all engines): an unanchored field streams the
      // whole structure down-field (COM drift), but the run is NO LONGER blocked —
      // the user may want the drift (or will add an anchor / opposing surface). We
      // surface the caution and proceed, matching oxDNA / NAMD / LAMMPS / chain-sim.
      showToast('Heads up: this electric field has no anchor and no opposing surface, so the whole '
        + 'structure will drift down-field (COM drift). Add a fixed strand in the Anchors card, '
        + 'or a hard surface it presses into (deposition), if you want it held.', { severity: 'warn' })
    }
    const body_ = buildMrdnaLaunchBody({
      coarseSteps: stepsInput?.value, fineSteps, outputPeriod: outputInput?.value,
      device: deviceInput?.value, sourcePath: getWorkspacePath?.() || null,
      anchors, fieldSpec, fieldOn, surfaceSpec, surfaceOn,
    })
    if (coarseBtn) coarseBtn.disabled = true
    if (fineBtn) fineBtn.disabled = true
    const job = await api.createMrdnaJob(body_)
    if (coarseBtn) coarseBtn.disabled = false
    if (fineBtn) fineBtn.disabled = false
    if (!job) {
      showToast(api.lastErrorMessage() || 'Failed to start mrDNA relaxation', { severity: 'error' })
      return
    }
    _selectedId = job.job_id
    await _fetchJobs()
  }
  coarseBtn?.addEventListener('click', () => _launch(0))
  fineBtn?.addEventListener('click', () => _launch(FINE_DEFAULT_STEPS))

  // ── Jobs list + poll ────────────────────────────────────────────────────────
  async function _fetchJobs() {
    const all = await api.listMrdnaJobs()
    if (!Array.isArray(all)) return
    _jobs = filterJobsForPart(all, getWorkspacePath?.() || null, showAll?.checked)
    _renderList()
    if (_selectedId) {
      _progress = await api.getMrdnaProgress(_selectedId)
      const job = _selectedJob()
      // Live-follow: refresh the deformed display when a running job completes.
      if (job && job.status === 'completed' && mrdnaDisplay?.deformActive?.()
          && mrdnaDisplay.deformJobId?.() === _selectedId) {
        await mrdnaDisplay.showDeform(_selectedId)
      }
      _renderDetail()
    }
    _notifyIfJobsChanged()
    _base.schedulePoll()
  }

  // Wake the master job list + progress bar (simulate_jobs.js, the VISIBLE list) whenever
  // THIS panel's job set/statuses change — a launch, stop, or completion. The master
  // self-polls only while it already holds an active node, so a run launched while it's
  // idle would otherwise not surface until a manual page refresh.
  let _prevJobsSig = null
  function _notifyIfJobsChanged() {
    const sig = _jobs.map(j => `${j.job_id}:${j.status}`).sort().join('|')
    if (_prevJobsSig !== null && sig !== _prevJobsSig) {
      window.dispatchEvent(new CustomEvent('nadoc:sim-jobs-changed'))
    }
    _prevJobsSig = sig
  }

  function _hasActiveJob() {
    if (_jobs.some(mrdnaJobIsActive)) return true
    const job = _selectedJob()
    return job ? mrdnaJobIsActive(job) : false
  }

  function _renderList() {
    if (!listEl) return
    const ctx = _rowCtx()
    const sig = jobListSignature(_jobs, ctx)
    if (sig === _listSig && listEl.childElementCount > 0) return
    _listSig = sig
    renderJobList(listEl, buildJobListModel(_jobs, ctx), {
      onClick: (jobId) => _selectJob(jobId),
      emptyText: 'No mrDNA jobs for this design yet.',
      dimColor: _C.dim,
      legendState: _legend,
    })
  }

  async function _selectJob(jobId) {
    _selectedId = jobId
    _progress = await api.getMrdnaProgress(jobId)
    _renderList()
    _renderDetail()
    _base.schedulePoll()
  }

  function _renderDetail() {
    const job = _selectedJob()
    if (!detail) return
    if (!job) { detail.style.display = 'none'; return }
    detail.style.display = ''
    if (detailStatus) detailStatus.textContent = detailStatusText(job, _progress)
    if (timeline) timeline.textContent = coarseStageChip(job)
    if (progressEl) {
      const pct = _progress?.overall != null ? Math.round(_progress.overall * 100) : 0
      progressEl.style.display = job.status === 'running' ? '' : 'none'
      progressEl.querySelector('.bar')?.style.setProperty('width', `${pct}%`)
    }
    if (detailError) {
      detailError.style.display = job.status === 'failed' ? '' : 'none'
      detailError.textContent = job.status === 'failed' ? (job.error || 'Run failed.') : ''
    }
    if (stopBtn) stopBtn.style.display = job.status === 'running' ? '' : 'none'
    const ready = job.status === 'completed'
    if (displayToggle) displayToggle.disabled = !ready
    if (beadsToggle) beadsToggle.disabled = !ready
    if (seedBtn && !_seeding) {
      const ok = seedReady(job)
      seedBtn.disabled = !ok
      seedBtn.style.cursor = ok ? 'pointer' : 'not-allowed'
      seedBtn.style.background = ok ? '#21262d' : '#122117'
      seedBtn.style.color = ok ? '#c9d1d9' : '#484f58'
    }
    _renderCurvature(job)
    _syncDisplayStatus()
  }

  async function _renderCurvature(job) {
    if (!curvatureEl) return
    if (!job || job.status !== 'completed') { curvatureEl.style.display = 'none'; return }
    const jid = job.job_id
    const rep = await api.getMrdnaCurvature(jid)
    if (!rep || _selectedId !== jid) return   // stale (job switched) — drop
    curvatureEl.innerHTML = formatCurvature(rep)
    curvatureEl.style.display = ''
  }

  function _syncDisplayStatus() {
    if (!displayStatus) return
    const bits = []
    if (mrdnaDisplay?.deformActive?.()) bits.push('model deformed')
    if (mrdnaDisplay?.beadsActive?.()) bits.push('CG beads')
    displayStatus.textContent = bits.length ? `Showing: ${bits.join(' + ')}` : ''
  }

  // ── Control buttons ───────────────────────────────────────────────────────────
  if (stopBtn) {
    stopBtn.addEventListener('click', async () => {
      if (!_selectedId) return
      await api.stopMrdnaJob(_selectedId)
      await _fetchJobs()
    })
  }
  // ── Use as NAMD seed — only once a FINE-stage relaxation has completed ──────────
  function _setSeedStatus(text, color = _C.dim) {
    if (seedStatus) { seedStatus.textContent = text; seedStatus.style.color = color }
  }
  if (seedBtn) {
    seedBtn.addEventListener('click', async () => {
      if (!_selectedId || seedBtn.disabled || _seeding) return
      _seeding = true
      seedBtn.disabled = true
      _setSeedStatus('Creating NAMD draft…', _C.accent)
      // Draft (deferred solvation): appears in the NAMD list unstarted so the user can
      // set advanced options, then press "Relax from mrDNA" to solvate + run.
      const job = await api.createMdJob({
        mrdna_job_id: _selectedId,
        design_source_path: getWorkspacePath?.() || null,
        draft: true,
        autostart: true,   // remembered on the draft → "Relax from mrDNA" runs it (standard relax)
      })
      _seeding = false
      if (job && job.job_id) {
        _setSeedStatus('NAMD draft created — set options + "Relax from mrDNA" in the NAMD tab.', _C.ok)
        showToast('NAMD draft created — configure it, then Relax from mrDNA', { severity: 'ok' })
        window.dispatchEvent(new CustomEvent('nadoc:md-job-created'))
        window.dispatchEvent(new CustomEvent('nadoc:sim-jobs-changed'))   // wake master (new NAMD job)
      } else {
        _setSeedStatus(api.lastErrorMessage() || 'Failed to create NAMD seed (see console)', _C.err)
      }
      _renderDetail()
    })
  }
  // Delete the selected mrDNA job. Invoked by the consolidated #simulate-job-actions
  // Delete button (dispatched by the master card on the selected node). Returns true if
  // the delete went through.
  async function deleteSelected() {
    if (!_selectedId) return false
    const r = await api.deleteMrdnaJob(_selectedId)
    if (r?.ok) {
      // Drop any display tied to this job.
      if (mrdnaDisplay?.deformJobId?.() === _selectedId) mrdnaDisplay.stopDeform()
      if (mrdnaDisplay?.beadsJobId?.() === _selectedId) mrdnaDisplay.hideBeads()
      _selectedId = null
      detail && (detail.style.display = 'none')
      await _fetchJobs()
      return true
    }
    showToast(api.lastErrorMessage() || 'Delete failed', { severity: 'error' })
    return false
  }

  // ── Display toggles ───────────────────────────────────────────────────────────
  if (displayToggle) {
    displayToggle.addEventListener('change', async () => {
      if (!_selectedId || !mrdnaDisplay) return
      if (displayToggle.checked) {
        const r = await mrdnaDisplay.showDeform(_selectedId)
        if (!r?.ok) { displayToggle.checked = false; showToast('Relaxed positions not ready', { severity: 'warn' }) }
      } else {
        mrdnaDisplay.stopDeform()
      }
      _syncDisplayStatus()
    })
  }
  if (beadsToggle) {
    beadsToggle.addEventListener('change', async () => {
      if (!_selectedId || !mrdnaDisplay) return
      if (beadsToggle.checked) {
        const r = await mrdnaDisplay.showBeads(_selectedId)
        if (!r?.ok) { beadsToggle.checked = false; showToast('CG beads not ready', { severity: 'warn' }) }
      } else {
        mrdnaDisplay.hideBeads()
      }
      _syncDisplayStatus()
    })
  }
  if (showAll) showAll.addEventListener('change', _fetchJobs)

  // ── Cross-panel coordination ──────────────────────────────────────────────────
  function _stopDisplays() {
    mrdnaDisplay?.stopAndRestore?.()
    if (displayToggle) displayToggle.checked = false
    if (beadsToggle) beadsToggle.checked = false
    _syncDisplayStatus()
  }
  // NOTE: `e.detail` is `{ activeTab, collapsed }` (main.js setActiveTab) — it has no
  // `from`, so this guard never fires and the mrDNA overlay currently survives EVERY
  // tab change, editing tabs included. Left as-is deliberately: it already satisfies
  // "the overlay must survive the Photo tab" (display_tab_policy.js), and making the
  // guard live would newly drop the overlay on Design/Assembly — a behaviour change
  // beyond the Photo fix. Fix it with `shouldTearDownDisplays(e.detail?.activeTab)`
  // if that teardown is actually wanted.
  window.addEventListener('nadoc:left-tab-change', (e) => {
    if (e.detail?.from === 'dynamics') _stopDisplays()
  })
  window.addEventListener('nadoc:design-changed', () => { _stopDisplays() })
  window.addEventListener('nadoc:workspace-path-change', () => { _selectedId = null; _fetchJobs() })

  // ── Open ──────────────────────────────────────────────────────────────────────
  function _onOpen() {
    _checkAvailable()
    _fetchJobs()
  }

  _base.initCollapsed(true)

  // selectJob: highlight + populate this panel's detail as a row click does — used by
  // the unified Simulate list to route an mrDNA node's selection here. Refetches if the
  // job isn't listed yet.
  async function selectJob(jobId) {
    if (!jobId) return
    if (!_jobs.find((j) => j.job_id === jobId)) await _fetchJobs()
    return _selectJob(jobId)
  }
  return { refresh: _fetchJobs, getSelectedJob: _selectedJob, selectJob, deleteSelected }
}
