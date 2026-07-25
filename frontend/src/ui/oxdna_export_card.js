/**
 * oxdna_export_card.js — "Export trajectory" card in the oxDNA Dynamics panel.
 *
 * Replaces the derelict single-frame "Export oxDNA ZIP" button.  Lets the user
 * pick a FRAME RANGE of the composite trajectory (relaxation stages + every
 * production run, parent + all its run children) and export just that slice for
 * high-quality video rendering in ChimeraX / oxView.
 *
 * The timeline is sourced from the SAME composite frame space the View-trajectory
 * slider uses (`getOxdnaTrajectoryMeta` → downsampled composite frames), so the
 * `[lo,hi]` the user scrubs is exactly what the backend slices and emits.  The
 * Export button posts `{jobId, lo, hi, format}` via the injected `onExport`, which
 * downloads a multi-frame PDB (ChimeraX) or an oxDNA .top+.dat zip (oxView).
 *
 * Dependency-injected (no import from oxdna_jobs_panel.js → no import cycle):
 * the panel passes `runConfig: runConfigForJob`, `getTrajectoryMeta` and `onExport`
 * so the pure builders stay decoupled and unit-testable with stubs.
 *
 * Factory: initOxdnaExportCard({ getSelectedJob, getJobs, runConfig, getTrajectoryMeta, onExport })
 */

// segment colours match the trajectory player's stage markers (house palette).
const KIND_COLOR = { production: '#3fb950', equil: '#4a9eff', md_relax: '#e0a800', mc: '#8a8a8a' }
const KIND_WORD  = { production: 'production run', equil: 'equilibration', md_relax: 'MD relax', mc: 'MC minimization' }
const RELAX_LABEL = { mc: 'MC min', md_relax: 'MD relax', equil: 'Equilibrate' }
// stage kinds that are relaxation (not a production "run") — anything else is a run.
const RELAX_KINDS = new Set(['mc', 'md_relax', 'equil', 'relax'])

const _clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v))
const _fmt = (n) => (n == null ? '?' : Number(n).toLocaleString('en-US'))
const _short = (id) => (id ? String(id).slice(0, 8) : '?')

/** Pure: dominant-axis label for a direction ([x,y,z] or a string like "+z"). */
export function dirLabel(dir) {
  if (Array.isArray(dir)) {
    const axes = [['X', +dir[0] || 0], ['Y', +dir[1] || 0], ['Z', +dir[2] || 0]]
    const dom = axes.reduce((a, b) => (Math.abs(b[1]) > Math.abs(a[1]) ? b : a))
    return `${dom[1] < 0 ? '-' : '+'}${dom[0]}`
  }
  return dir == null ? '?' : String(dir)
}

/** Pure: one-line E-field descriptor from a {field_pN, dir} record. */
export function formatField(field) {
  if (!field) return '—'
  return `${_fmt(field.field_pN)} pN/nt, ${dirLabel(field.dir)}`
}

/** Pure: one-line hard-surface descriptor from a {dir, offset_nm, stiff} record,
 *  optionally noting how many capture/immobilization strands ride on it. */
export function formatSurface(surface, surfaceStrands = null) {
  if (!surface) return '—'
  let s = `hard wall ${dirLabel(surface.dir)}`
  if (surface.offset_nm != null) s += `, offset ${surface.offset_nm} nm`
  const nCap = Array.isArray(surfaceStrands) ? surfaceStrands.length
    : (surfaceStrands && surfaceStrands.count != null ? surfaceStrands.count : 0)
  if (nCap) s += ` · ${nCap} capture strand${nCap === 1 ? '' : 's'}`
  return s
}

/** Pure: [A]/[H]/[E] element tags from a segment's meta (anchors/surface/field). */
export function metaTags(meta) {
  if (!meta) return ''
  return (meta.anchors && meta.anchors.length ? '[A]' : '') +
         (meta.surface ? '[H]' : '') +
         (meta.field ? '[E]' : '')
}

/** Pure: the ordered ANCESTOR CHAIN for a selected job — [root, …, selectedJob].
 *  Runs form a multi-level chain (each `appendOxdnaRun` seeds from the
 *  previously-selected run, so parent_job_id points at the immediately-preceding
 *  run, to any depth).  We walk UP `parent_job_id` from the selected job all the
 *  way to the root, collecting every ancestor, then reverse to root-first.  This is
 *  "all runs leading up to and including the selected run" — and it mirrors the
 *  backend's `_lineage_jobs` / `_composite_inputs`, so the slider's runs match the
 *  frames the export actually slices (runs AFTER the selected one aren't part of
 *  its composite trajectory and are intentionally excluded). Cycle-guarded. */
export function lineageForJob(job, jobs) {
  if (!job) return []
  const list = Array.isArray(jobs) ? jobs : []
  const byId = new Map(list.map((j) => [j.job_id, j]))
  const chain = []
  let cur = byId.get(job.job_id) || job
  const seen = new Set()
  while (cur && !seen.has(cur.job_id)) {
    seen.add(cur.job_id)
    chain.push(cur)
    cur = cur.parent_job_id ? byId.get(cur.parent_job_id) : null
  }
  return chain.reverse()   // root-first
}

/** Pure: which lineage jobs are production "runs" — i.e. contribute a run stage
 *  (not pure relaxation).  Ordered by the lineage (root-first).  A relaxation-only
 *  root is excluded, so run segments map correctly to the runs that produced them. */
export function runJobsOf(lineage) {
  return (lineage || []).filter((j) => (j.stages || []).some((s) => !RELAX_KINDS.has(s.kind)))
}

/** Pure: build the export timeline model from the composite trajectory META
 *  (`metaStages` = [{name, kind, n_frames, field}] from getOxdnaTrajectoryMeta) and
 *  the job `lineage` (ancestor chain).  Frame counts/boundaries come from the meta
 *  (the real, downsampled composite frame space the slider lives in); anchors/surface
 *  per run come from `runConfigFn(job)` by zipping run stages to the lineage's run
 *  jobs in order.  Each stage becomes a segment with a cumulative [start,end) span;
 *  run segments carry per-run meta.  Returns {segments, total, unit:'frame'}. */
export function buildExportModel(metaStages, lineage, runConfigFn) {
  const rc = typeof runConfigFn === 'function' ? runConfigFn : () => ({})
  const runJobs = runJobsOf(lineage)
  const segments = []
  let runIndex = 0

  for (const st of metaStages || []) {
    const weight = st.n_frames | 0
    if (RELAX_KINDS.has(st.kind)) {
      segments.push({
        kind: st.kind, label: RELAX_LABEL[st.kind] || st.kind,
        jobId: null, status: null, isChild: false, weight, meta: null,
      })
    } else {
      const job = runJobs[runIndex] || null
      runIndex += 1
      const cfg = (job && rc(job)) || {}
      segments.push({
        kind: 'production',
        label: `Run ${runIndex}`,
        jobId: job?.job_id || null,
        status: job?.status || null,
        isChild: runIndex > 1,
        weight,
        meta: {
          anchors: cfg.anchors || [],
          surface: cfg.surface || null,
          surfaceStrands: cfg.surfaceStrands || null,
          field: st.field || cfg.field || null,   // prefer the meta stage's field
        },
      })
    }
  }

  // assign cumulative [start,end) spans
  let cursor = 0
  for (const s of segments) { s.start = cursor; s.end = cursor + s.weight; cursor += s.weight }
  return { segments, total: cursor, unit: 'frame' }
}

/** Pure: per-lineage-job detail rows for the "for each job and its children"
 *  breakdown.  Reuses the same runConfigFn as the model. */
export function buildJobRows(lineage, runConfigFn) {
  const rc = typeof runConfigFn === 'function' ? runConfigFn : () => ({})
  let runIndex = 0
  return lineage.map((job, li) => {
    const isChild = li !== 0
    const cfg = rc(job) || {}
    const hasProd = isChild || (job.stages || []).some((s) => s.kind === 'production')
    if (hasProd) runIndex += 1
    const meta = { anchors: cfg.anchors || [], surface: cfg.surface || null, field: cfg.field || null }
    const relax = !isChild && cfg.advanced
      ? `Relax: MC ${_fmt(cfg.advanced.mcSteps)}, MD ${_fmt(cfg.advanced.mdSteps)}, equil ${_fmt(cfg.advanced.equilSteps)}`
      : null
    const bits = []
    if (meta.anchors.length) bits.push(`${meta.anchors.length} anchor${meta.anchors.length === 1 ? '' : 's'}`)
    if (meta.surface) bits.push(formatSurface(meta.surface, cfg.surfaceStrands))
    if (meta.field) bits.push(`E-field ${formatField(meta.field)}`)
    return {
      jobId: job.job_id,
      shortId: _short(job.job_id),
      status: job.status || '—',
      isChild,
      runLabel: hasProd ? `Run ${runIndex}` : 'Relaxation only',
      tags: metaTags(meta),
      relax,
      summary: bits.length ? bits.join(' · ') : 'plain production run',
    }
  })
}

/** Pure: multi-line native-title tooltip text for one timeline segment. */
export function segmentTooltip(seg, unit = 'frame') {
  const word = KIND_WORD[seg.kind] || seg.kind
  const head = seg.weight
    ? `${seg.label} — ${word} · ${_fmt(seg.weight)} ${unit}${seg.weight === 1 ? '' : 's'}`
    : `${seg.label} — ${word}`
  const lines = [head]
  if (seg.meta) {
    const m = seg.meta
    const a = m.anchors ? m.anchors.length : 0
    if (a) lines.push(`Anchors: ${a}`)
    if (m.surface) lines.push(`Surface: ${formatSurface(m.surface, m.surfaceStrands)}`)
    if (m.field) lines.push(`E-field: ${formatField(m.field)}`)
    if (!a && !m.surface && !m.field) lines.push('No anchors / surface / E-field')
  } else {
    lines.push('Relaxation stage (not exported unless included in the range)')
  }
  return lines.join('\n')
}

/** Pure: human label for an export progress phase from the backend
 *  (`_TRAJ_PROGRESS.phase`): "align" = PBC-unwrap/Kabsch pass, "atoms" = per-frame all-atom
 *  rebuild, "write" = per-frame PDB build. Anything else falls back to a neutral "Building". */
export function exportPhaseLabel(phase) {
  if (phase === 'align') return 'Aligning frames'
  if (phase === 'frames') return 'Building frames'
  if (phase === 'atoms') return 'Rebuilding atoms'
  if (phase === 'write') return 'Writing PDB'
  return 'Building'
}

/** Pure: bar state for the export progress bar from a progress payload ({done,total,phase}).
 *  Returns { pct, text, indeterminate } — pct clamped to [0,100].
 *
 *  The "align" phase (PBC-unwrap + Kabsch fit over the whole composite trajectory) reports NO
 *  per-frame counter — `done` sits at 0 for its entire duration, which used to render as a bar
 *  frozen at "0/51 frames · 0%" and read as a hung export. So align is reported as
 *  INDETERMINATE: the caller shows a moving barber-pole instead of a stalled 0%, and the label
 *  says what the pass is doing rather than quoting a counter that cannot move. */
export function exportProgressView(p) {
  const total = p && p.total > 0 ? p.total : 0
  const done = p ? (p.done || 0) : 0
  const pct = total > 0 ? Math.max(0, Math.min(100, Math.round((100 * done) / total))) : 0
  if (p && p.phase === 'align') {
    const scope = total > 0 ? `${_fmt(total)} frames` : 'the trajectory'
    return { pct: 100, indeterminate: true,
             text: `Aligning ${scope} — unwrapping + fitting, no per-frame count (can take several minutes)` }
  }
  const text = total > 0
    ? `${exportPhaseLabel(p.phase)} — ${_fmt(done)}/${_fmt(total)} frames · ${pct}%`
    : 'Preparing…'
  return { pct, text, indeterminate: false }
}

/** Pure: the ChimeraX command that opens a multi-MODEL PDB as a trajectory.
 *  `coordsets true` reads the MODEL records as frames of ONE structure (not N separate
 *  models); `slider true` opens the frame player.  `filename` is the name your browser
 *  saved from the PDB export; when unknown we emit an obvious placeholder to edit.  The
 *  name is quoted (and any embedded quote escaped) so paths with spaces survive the paste. */
export function chimeraxOpenCommand(filename) {
  const f = String(filename || 'PATH_TO_YOUR_EXPORT.pdb').replace(/"/g, '\\"')
  return `open "${f}" coordsets true slider true`
}

/** Pure: the two-line ChimeraX command for a PDB+DCD pair (the `dcd` export format).
 *  A DCD holds coordinates only — no bonding — so the topology PDB must be opened FIRST and
 *  the trajectory attached to it via `structureModel #1`. `stem` is the shared basename of
 *  the two unzipped files; unknown until an export has run, so we emit an editable placeholder. */
export function chimeraxOpenDcdCommand(stem) {
  const s = String(stem || 'PATH_TO_YOUR_EXPORT').replace(/"/g, '\\"')
  return `open "${s}.pdb"\nopen "${s}.dcd" structureModel #1`
}

/** Pure: strip the archive suffix an export download carries, giving the shared basename of
 *  the .pdb/.dcd inside it. `foo_frames0-50_chimerax.zip` -> `foo_frames0-50`. */
export function dcdStemFromZipName(filename) {
  if (!filename) return null
  return String(filename).replace(/\.zip$/i, '').replace(/_chimerax$/i, '')
}

/** Human names for the export formats, shared by the status line and the ChimeraX popup. */
export const FORMAT_LABEL = {
  dcd: 'PDB + DCD zip (ChimeraX)',
  pdb: 'multi-frame PDB (ChimeraX)',
  oxdna: 'oxDNA .top + .dat (oxView)',
}

/** Pure: order + clamp a [lo,hi] frame range into [0,total]. */
export function clampRange(lo, hi, total) {
  let a = _clamp(Math.round(lo), 0, total)
  let b = _clamp(Math.round(hi), 0, total)
  if (a > b) [a, b] = [b, a]
  return { lo: a, hi: b }
}

export function frameToPct(frame, total) {
  return total > 0 ? _clamp((frame / total) * 100, 0, 100) : 0
}
export function pctToFrame(pct, total) {
  return Math.round((_clamp(pct, 0, 100) / 100) * total)
}

/** Pure: segments that intersect the half-open range [lo,hi). */
export function segmentsSpanned(segments, lo, hi) {
  return (segments || []).filter((s) => s.start < hi && s.end > lo)
}

/** Pure: one-line readout of the current selection (unit-aware, lists the runs
 *  the range spans). */
export function rangeSummary(model, lo, hi) {
  const { segments, total, unit } = model
  if (!total) return 'No production frames yet — run a production job first.'
  const runs = segmentsSpanned(segments, lo, hi).filter((s) => s.kind === 'production').map((s) => s.label)
  const cap = unit.charAt(0).toUpperCase() + unit.slice(1)
  const base = `${cap}s ${_fmt(lo)}–${_fmt(hi)} · ${_fmt(hi - lo)} of ${_fmt(total)}`
  return runs.length ? `${base} · spans ${runs.join(', ')}` : base
}

/** Pure: sorted, de-duped snap targets — the start/end frame of every run/stage
 *  (plus 0 and the total). These are the points the interval sliders snap to. */
export function runBoundaries(model) {
  const set = new Set([0, model.total | 0])
  for (const s of model.segments || []) { set.add(s.start); set.add(s.end) }
  return [...set].sort((a, b) => a - b)
}

/** Pure: snap `v` to the nearest boundary within `threshold`, else leave it free.
 *  Gives magnetic run-boundary snapping without losing sub-run precision. */
export function snapValue(v, boundaries, threshold) {
  let best = v, bestD = threshold
  for (const b of boundaries || []) {
    const d = Math.abs(v - b)
    if (d <= bestD) { bestD = d; best = b }
  }
  return best
}

// ── Stateful renderer ────────────────────────────────────────────────────────

export function initOxdnaExportCard({
  getSelectedJob = null, getJobs = null, runConfig = null,
  getTrajectoryMeta = null, onExport = null, getExportProgress = null,
} = {}) {
  const toggle  = document.getElementById('oxdna-export-toggle')
  const arrow   = document.getElementById('oxdna-export-arrow')
  const bodyEl  = document.getElementById('oxdna-export-card')
  const wrap    = document.getElementById('oxdna-export-timeline-wrap')
  const segsEl  = document.getElementById('oxdna-export-segments')
  const dimLo   = document.getElementById('oxdna-export-dim-lo')
  const dimHi   = document.getElementById('oxdna-export-dim-hi')
  const markersEl = document.getElementById('oxdna-export-markers')
  const rangeLo = document.getElementById('oxdna-export-range-lo')
  const rangeHi = document.getElementById('oxdna-export-range-hi')
  const readout = document.getElementById('oxdna-export-readout')
  const detail  = document.getElementById('oxdna-export-detail')
  const runBtn  = document.getElementById('oxdna-export-run-btn')
  const statusEl = document.getElementById('oxdna-export-status')
  const fmtPdb  = document.getElementById('oxdna-export-fmt-pdb')
  const fmtDcd  = document.getElementById('oxdna-export-fmt-dcd')
  const cxBtn   = document.getElementById('oxdna-chimerax-btn')
  const progWrap  = document.getElementById('oxdna-export-progress')
  const progFill  = document.getElementById('oxdna-export-progress-fill')
  const progLabel = document.getElementById('oxdna-export-progress-label')
  if (!bodyEl) return { rebuild: () => {}, api: null }

  let _model = { segments: [], total: 0, unit: 'frame' }
  let _boundaries = [0]
  let _lo = 0, _hi = 0
  let _rebuildToken = 0   // guards against races between rapid job selections
  // Filename + range of the last PDB the user exported, so the "Direct to ChimeraX"
  // popup can name the exact file to open (the export stem isn't reconstructable here).
  let _lastPdb = null

  function _renderSegments() {
    if (!segsEl) return
    segsEl.innerHTML = ''
    const segs = _model.segments
    for (const s of segs) {
      const cell = document.createElement('div')
      cell.title = segmentTooltip(s, _model.unit)
      const grow = Math.max(1, s.weight || 0)
      cell.style.cssText =
        `flex:${grow} 1 0;min-width:2px;height:100%;background:${KIND_COLOR[s.kind] || '#484f58'};` +
        `border-right:1px solid #0d1117;cursor:help;opacity:${s.kind === 'production' ? '1' : '0.55'}`
      segsEl.appendChild(cell)
    }
  }

  // Colour ticks at every run/stage boundary — same visual language as the
  // View-trajectory slider's stage-transition markers.
  function _renderMarkers() {
    if (!markersEl) return
    markersEl.innerHTML = ''
    for (const s of _model.segments) {
      if (s.start === 0) continue   // no tick at the very start
      const pct = frameToPct(s.start, _model.total)
      const tick = document.createElement('div')
      tick.style.cssText =
        `position:absolute;top:0;left:${pct}%;width:2px;height:100%;transform:translateX(-1px);` +
        `background:${KIND_COLOR[s.kind] || '#cdd9e5'}`
      markersEl.appendChild(tick)
    }
  }

  function _renderRange() {
    const total = _model.total
    const loPct = frameToPct(_lo, total)
    const hiPct = frameToPct(_hi, total)
    if (rangeLo) rangeLo.value = String(_lo)
    if (rangeHi) rangeHi.value = String(_hi)
    if (dimLo) dimLo.style.width = `${loPct}%`
    if (dimHi) dimHi.style.width = `${100 - hiPct}%`
    if (readout) readout.textContent = rangeSummary(_model, _lo, _hi)
    const disabled = total <= 0
    if (rangeLo) rangeLo.disabled = disabled
    if (rangeHi) rangeHi.disabled = disabled
    if (runBtn) { runBtn.disabled = disabled; runBtn.style.opacity = disabled ? '0.5' : '1'; runBtn.style.cursor = disabled ? 'not-allowed' : 'pointer' }
    if (cxBtn)  { cxBtn.disabled  = disabled; cxBtn.style.opacity  = disabled ? '0.5' : '1'; cxBtn.style.cursor  = disabled ? 'not-allowed' : 'pointer' }
  }

  function _renderDetail(lineage) {
    if (!detail) return
    const rows = buildJobRows(lineage || lineageForJob(getSelectedJob?.(), getJobs?.() || []), runConfig)
    if (!rows.length) { detail.innerHTML = '<span style="color:#8b949e">Select an oxDNA job to see its runs.</span>'; return }
    detail.innerHTML = ''
    const head = document.createElement('div')
    head.style.cssText = 'color:#c9d1d9;margin-bottom:3px'
    head.textContent = `Jobs in this trajectory (${rows.length})`
    detail.appendChild(head)
    rows.forEach((r) => {
      const line = document.createElement('div')
      line.style.cssText = 'margin:2px 0 2px 4px;line-height:1.35'
      const kind = r.isChild ? 'child' : 'parent'
      line.innerHTML =
        `<span style="color:#c9d1d9">${r.runLabel}</span> ` +
        `<span style="color:#8b949e">${r.tags ? r.tags + ' ' : ''}· ${kind} ${r.shortId} · ${r.status}</span>` +
        (r.relax ? `<div style="color:#6e7681;margin-left:8px">${r.relax}</div>` : '') +
        `<div style="color:#8b949e;margin-left:8px">${r.summary}</div>`
      detail.appendChild(line)
    })
  }

  function _setModel(model) {
    _model = model
    _boundaries = runBoundaries(_model)
    _lo = 0
    _hi = _model.total
    const max = String(Math.max(0, _model.total))
    if (rangeLo) { rangeLo.max = max; rangeLo.value = '0' }
    if (rangeHi) { rangeHi.max = max; rangeHi.value = max }
    _renderSegments()
    _renderMarkers()
    _renderRange()
  }

  // Empty/placeholder state: no timeline, a message in the readout, controls off.
  function _setEmpty(msg) {
    _setModel({ segments: [], total: 0, unit: 'frame' })
    if (readout) readout.textContent = msg
  }

  // Rebuild from the composite trajectory META (the real, downsampled composite
  // frame space).  Async: the per-job detail renders instantly from the lineage,
  // then the timeline populates once the meta arrives.  Race-guarded so a rapid
  // job re-selection can't let a stale response overwrite a newer one.
  async function rebuild() {
    const token = ++_rebuildToken
    const job = getSelectedJob?.()
    const lineage = lineageForJob(job, getJobs?.() || [])
    _renderDetail(lineage)                       // instant, from the lineage
    if (statusEl) statusEl.textContent = ''
    if (!job) { _setEmpty('Select an oxDNA job to export its trajectory.'); return }
    if (typeof getTrajectoryMeta !== 'function') { _setEmpty('Trajectory export unavailable.'); return }
    _setEmpty('Loading composite trajectory…')
    let meta = null
    try { meta = await getTrajectoryMeta(job.job_id) } catch { meta = null }
    if (token !== _rebuildToken) return          // superseded by a newer selection
    if (!meta || !meta.ready || !(meta.n_frames > 0)) {
      _setEmpty('No trajectory yet — run a production job first.')
      return
    }
    _setModel(buildExportModel(meta.stages || [], lineage, runConfig))
  }

  // ── the two range sliders (snap to run boundaries, can't cross) ──────────
  const _snapThreshold = () => Math.max(1, Math.round(_model.total * 0.04))
  rangeLo?.addEventListener('input', () => {
    const v = snapValue(parseInt(rangeLo.value, 10) || 0, _boundaries, _snapThreshold())
    _lo = Math.min(Math.max(0, v), _hi)     // start can't pass end
    _renderRange()
  })
  rangeHi?.addEventListener('input', () => {
    const v = snapValue(parseInt(rangeHi.value, 10) || 0, _boundaries, _snapThreshold())
    _hi = Math.max(Math.min(_model.total, v), _lo)   // end can't pass start
    _renderRange()
  })
  // Raise whichever thumb is nearer the cursor so both stay grabbable even when
  // they sit close together (the two inputs fully overlap).
  wrap?.addEventListener('pointermove', (e) => {
    if (!_model.total) return
    const rect = wrap.getBoundingClientRect()
    const px = ((e.clientX - rect.left) / Math.max(1, rect.width)) * _model.total
    const loNearer = Math.abs(px - _lo) <= Math.abs(px - _hi)
    if (rangeLo) rangeLo.style.zIndex = loNearer ? '3' : '2'
    if (rangeHi) rangeHi.style.zIndex = loNearer ? '2' : '3'
  })

  // ── collapse toggle (mirrors the Graphs-and-Metrics card) ────────────────
  toggle?.addEventListener('click', () => {
    const open = bodyEl.style.display === 'none'
    bodyEl.style.display = open ? '' : 'none'
    if (arrow) arrow.style.transform = open ? 'rotate(90deg)' : ''
    if (open) rebuild()
  })

  // ── live export progress bar ─────────────────────────────────────────────
  // While the (blocking) export POST runs, poll the backend build's frames-processed
  // counter and drive the bar below the button — same _TRAJ_PROGRESS the View-trajectory
  // loader polls. Self-hides when there's no active build (e.g. the oxDNA .zip path,
  // which doesn't report frames).
  let _exportPoll = null
  function _paintProgress(p) {
    const { pct, text, indeterminate } = exportProgressView(p)
    if (progWrap) progWrap.style.display = ''
    if (progFill) {
      progFill.style.width = `${pct}%`
      progFill.classList.toggle('ox-export-bar--indeterminate', !!indeterminate)
    }
    if (progLabel) progLabel.textContent = text
  }
  function _stopExportPoll() {
    if (_exportPoll) { clearInterval(_exportPoll); _exportPoll = null }
    if (progWrap) progWrap.style.display = 'none'
    if (progFill) progFill.classList.remove('ox-export-bar--indeterminate')
  }
  function _startExportPoll(jobId) {
    _stopExportPoll()
    if (typeof getExportProgress !== 'function' || !jobId) return
    // Paint immediately: the first poll is 250 ms away and the backend's first phase can run
    // for minutes, so an un-painted bar here is exactly the "nothing is happening" symptom.
    _paintProgress(null)
    _exportPoll = setInterval(async () => {
      let p = null
      try { p = await getExportProgress(jobId) } catch { p = null }
      // An inactive/absent payload means the build hasn't registered yet (or reports no
      // frames at all, e.g. the oxDNA .zip path) — hold the last painted state rather than
      // blanking the bar; _stopExportPoll hides it when the POST resolves.
      if (!p || !p.active) return
      _paintProgress(p)
    }, 250)
  }

  // ── export the selected frame range ──────────────────────────────────────
  runBtn?.addEventListener('click', async () => {
    if (_model.total <= 0 || runBtn.disabled) return
    const jobId = getSelectedJob?.()?.job_id
    if (!jobId) return
    const format = fmtDcd?.checked ? 'dcd' : (fmtPdb?.checked ? 'pdb' : 'oxdna')
    const sel = { jobId, lo: _lo, hi: _hi, format }
    if (typeof onExport !== 'function') { if (statusEl) statusEl.textContent = 'Export unavailable.'; return }
    const fmtName = FORMAT_LABEL[format] || format
    runBtn.disabled = true
    if (statusEl) statusEl.textContent = `Exporting frames ${_fmt(_lo)}–${_fmt(_hi)} as ${fmtName}…${format === 'pdb' ? ' (PDB rebuild can take a while)' : ''}`
    _startExportPoll(jobId)
    let result = false
    try { result = await onExport(sel) } catch { result = false } finally { _stopExportPoll() }
    // Remember the exact download name so the ChimeraX popup can name the file(s).
    if (result && (format === 'pdb' || format === 'dcd')) {
      _lastPdb = { filename: typeof result === 'string' ? result : null, lo: _lo, hi: _hi, format }
    }
    if (statusEl) statusEl.textContent = result ? `Downloaded ${fmtName}, frames ${_fmt(_lo)}–${_fmt(_hi)}.` : 'Export failed — see console.'
    runBtn.disabled = false
  })

  // ── Direct to ChimeraX: a popup with the paste-ready `open` command ───────────
  // No server call and no rebuild — it just names the PDB you exported above. The
  // filename is filled in once you've exported this exact range; otherwise it shows
  // an obvious placeholder to edit (ChimeraX opens the file from YOUR machine).
  function _pdbFilenameForRange() {
    return (_lastPdb && _lastPdb.lo === _lo && _lastPdb.hi === _hi) ? _lastPdb.filename : null
  }

  function _showChimeraxModal() {
    const filename = _pdbFilenameForRange()
    // A DCD export downloads a zip holding <stem>.pdb + <stem>.dcd, which need the two-line
    // open (topology first, trajectory attached to it). A multi-frame PDB is the one-liner.
    const isDcd = !!(_lastPdb && _lastPdb.format === 'dcd' && filename)
    const stem = isDcd ? dcdStemFromZipName(filename) : null
    const overlay = document.createElement('div')
    overlay.className = 'modal-overlay'
    overlay.style.cssText = 'position:fixed;inset:0;z-index:10002;background:rgba(0,0,0,.65);display:flex;align-items:center;justify-content:center;padding:24px'
    const box = document.createElement('div')
    box.style.cssText = 'width:min(620px,100%);background:#1a2530;border:1px solid #455a64;border-radius:10px;padding:20px;color:#cfd8dc;box-shadow:0 12px 48px rgba(0,0,0,.7)'
    const h = document.createElement('h2'); h.textContent = 'Open trajectory in ChimeraX'
    h.style.cssText = 'font-size:16px;margin:0 0 10px;color:#eceff1'
    const p = document.createElement('p')
    p.innerHTML = isDcd
      ? `Unzip <b>${filename}</b> first, then paste this into the ChimeraX command line. Both files must sit in the same folder — give full paths, or <code>cd</code> there first.`
      : (filename
        ? `Paste into the ChimeraX command line. Point it at where your browser saved <b>${filename}</b> — give the full path, or <code>cd</code> to that folder first.`
        : 'Export the range first (“Export selected range”), then paste this into ChimeraX with the path to your saved file.')
    p.style.cssText = 'font-size:13px;line-height:1.45;margin:0 0 10px'
    const pre = document.createElement('textarea'); pre.readOnly = true; pre.spellcheck = false
    pre.value = isDcd ? chimeraxOpenDcdCommand(stem) : chimeraxOpenCommand(filename)
    pre.style.cssText = `box-sizing:border-box;width:100%;height:${isDcd ? 68 : 52}px;padding:10px;background:#111c24;color:#b0bec5;border:1px solid #37474f;border-radius:5px;font:12px monospace;resize:none`
    const note = document.createElement('div')
    note.textContent = isDcd
      ? 'The PDB carries the topology (bonds); the DCD carries every frame · structureModel #1 attaches the trajectory to it'
      : 'coordsets true = read the models as one trajectory · slider true = open the frame player'
    note.style.cssText = 'font-size:11px;color:#78909c;margin-top:6px'
    const row = document.createElement('div'); row.style.cssText = 'display:flex;justify-content:flex-end;gap:8px;margin-top:12px'
    const copy = document.createElement('button'); copy.textContent = 'Copy'
    const close = document.createElement('button'); close.textContent = 'Close'
    for (const b of [copy, close]) b.style.cssText = 'padding:7px 14px;border-radius:5px;border:1px solid #546e7a;background:#263238;color:#fff;cursor:pointer'
    const done = () => { document.removeEventListener('keydown', onKey); overlay.remove() }
    const onKey = (e) => { if (e.key === 'Escape') done() }
    close.onclick = done
    overlay.onclick = (e) => { if (e.target === overlay) done() }
    document.addEventListener('keydown', onKey)
    copy.onclick = async () => { try { await navigator.clipboard?.writeText(pre.value); copy.textContent = 'Copied!' } catch { pre.select() } }
    row.append(copy, close); box.append(h, p, pre, note, row); overlay.appendChild(box); document.body.appendChild(overlay)
  }
  cxBtn?.addEventListener('click', () => { if (!cxBtn.disabled) _showChimeraxModal() })

  // rebuild whenever the panel's selection changes.
  window.addEventListener('nadoc:oxdna-job-selected', rebuild)
  rebuild()

  return { rebuild, api: { getRange: () => ({ lo: _lo, hi: _hi, unit: _model.unit }) } }
}
