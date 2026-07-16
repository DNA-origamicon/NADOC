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
 * Selecting any node drives the master card: a status line + one status-coloured progress
 * bar (with the full stage/segment detail as its hover tooltip) + the selected engine's
 * stage timeline at the card bottom + one context Run/Stop/Resume button (via the pure
 * `job_run_control.runControlState`). Detail dispatches by engine — oxDNA/mrDNA/CanDo/NAMD
 * each light up their own panel via `selectJob(id)`; a LAMMPS run (oxDNA's CPU fallback,
 * same oxDNA2 bead model) shows in the oxDNA panel's OWN viz card via `selectLammpsJob(node)`,
 * with its Stop / re-Run on the master button.
 *
 * Factory: initSimulateJobs({ api, getWorkspacePath, oxdnaPanel, mrdnaPanel, candoPanel,
 * mdPanel, engineSelector }) → { refresh, selectJob, setActiveEngine, getSelected }.
 * Module-first: cohesive logic lives here / in the pure helpers below; main.js only inits.
 * Physical-layer / display-state only (topology is never touched).
 */

import { buildJobListModel, jobListSignature } from './jobs_panel_model.js'
import { mountDirectoryButton } from './run_location.js'
import { renderJobList } from './jobs_panel_render.js'
import { runControlState, RUN_ACTION } from './job_run_control.js'
import { jobDisplayName as oxDisplayName, runRowLabel, runChildTitle } from './oxdna_jobs_panel.js'
import { jobDisplayName as mrdnaDisplayName } from './mrdna_jobs_panel.js'
import { jobDisplayName as candoDisplayName } from './cando_jobs_panel.js'
import { jobDisplayName as snupiDisplayName } from './snupi_jobs_panel.js'
import { mdJobRowCtx } from './md_jobs_panel.js'
import { buildCreatePayload } from './lammps_jobs_logic.js'
import { getSectionCollapsed, setSectionCollapsed } from './section_collapse_state.js'
import { formatJobTime } from '../scene/trajectory_range.js'
import { formatBytes } from './format_bytes.js'
import { showToast } from './toast.js'

const POLL_MS = 1500
const _C = { ok: '#5cb85c', warn: '#e0a800', err: '#d9534f', accent: '#4a9eff', dim: '#8a8a8a' }
const _ACTIVE = ['queued', 'preparing', 'running']

// Per-engine badge shown on rows only in "Show all job types" mode, so a mixed list
// stays legible about which engine each run came from. LAMMPS keeps its own [L] badge
// (it's oxDNA's CPU fallback, grouped under the oxDNA tab) and is omitted here.
const _ENGINE_BADGE = {
  oxdna: { text: '[ox]', color: '#4a9eff', title: 'oxDNA' },
  mrdna: { text: '[mr]', color: '#9e6bff', title: 'mrDNA' },
  cando: { text: '[CD]', color: '#39c5cf', title: 'CanDo FEM' },
  snupi: { text: '[SN]', color: '#d29bff', title: 'SNUPI FEM' },
  namd:  { text: '[MD]', color: '#3fb950', title: 'NAMD (Molecular Dynamics)' },
}

/** The engine TAB a node belongs to. LAMMPS is oxDNA's transparent CPU fallback, so its
 *  runs live under the oxDNA tab (the auto-policy picks GPU-oxDNA ⇄ CPU-LAMMPS). */
function engineGroup(node) {
  return node?.engine === 'lammps' ? 'oxdna' : node?.engine
}

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

/** Coarse progress % for the ONE master bar (no extra fetch): completed → 100; LAMMPS
 *  from current_step/steps; NAMD from segments done/total; oxDNA from stages done/total;
 *  mrDNA/CanDo have no granular signal → 0 while running (the bar COLOR conveys state). */
export function masterProgressPct(node) {
  if (!node) return 0
  if (node.status === 'completed' || node.production_state === 'done') return 100
  if (node.engine === 'lammps') {
    const total = Number(node.steps) || 0
    const cur = Number(node.current_step) || 0
    return total > 0 ? Math.max(0, Math.min(100, Math.round((cur / total) * 100))) : 0
  }
  if (node.engine === 'namd') {
    // Prefer the live within-segment fraction the backend stamps on a RUNNING NAMD job
    // (so a single-segment production child advances instead of sitting at 0 % until its
    // one segment flips to done). Fall back to the done/total segment count otherwise.
    if (node.progress_fraction != null) {
      return Math.max(0, Math.min(100, Math.round(Number(node.progress_fraction) * 100)))
    }
    const seg = node.segments || []
    if (!seg.length) return 0
    return Math.round((seg.filter((s) => s.status === 'done').length / seg.length) * 100)
  }
  // oxDNA: prefer the live within-stage fraction the backend stamps on a running job
  // (so a SINGLE-stage run — e-field / surface / production child — advances smoothly
  // instead of sitting at 0 % until its one stage flips to done). Fall back to the
  // completed-stage count for jobs without it (queued / older list payloads).
  if (node.progress_fraction != null) {
    return Math.max(0, Math.min(100, Math.round(Number(node.progress_fraction) * 100)))
  }
  const st = node.stages || []
  if (!st.length) return 0
  return Math.round((st.filter((s) => s.status === 'done').length / st.length) * 100)
}

/** Fill colour of the master bar, by status: green done · red failed · orange WARNING
 *  (design changed since the run — stale/out-of-date) · grey stopped/queued · blue active. */
export function masterProgressColor(node) {
  if (!node) return _C.accent
  if (node.out_of_date) return _C.warn                                   // orange — stale
  if (node.status === 'failed' || node.production_state === 'failed') return _C.err
  if (node.status === 'completed' || node.production_state === 'done') return _C.ok
  if (node.status === 'stopped' || node.status === 'queued') return _C.dim
  return _C.accent                                                        // running / preparing
}

/** The full progress detail (stage / segments / % / status) — shown as the master bar's
 *  hover TOOLTIP (what used to sit inline in each engine's #*-jobs-progress). */
export function masterProgressTooltip(node) {
  if (!node) return ''
  const pct = masterProgressPct(node)
  const stale = node.out_of_date ? '\n⚠ design changed since this run' : ''
  if (node.engine === 'lammps') {
    return `LAMMPS (CPU) · ${node.status}${node.status === 'running' ? ` · ${pct}%` : ''}${stale}`
  }
  if (node.engine === 'namd') {
    const seg = node.segments || []
    const done = seg.filter((s) => s.status === 'done').length
    const run = seg.find((s) => s.status === 'running')
    const lines = [`NAMD · ${node.status}`]
    if (seg.length) lines.push(`${done}/${seg.length} segments · ${pct}% overall`)
    if (run) lines.push(`Current: ${run.name || run.stage || 'running'}${run.percent != null ? ` · ${run.percent}%` : ''}`)
    return lines.join('\n') + stale
  }
  const eng = engineLabel(node)
  const state = node.production_state && node.production_state !== 'none'
    ? `production ${node.production_state}` : node.status
  const st = node.stages || []
  const parts = [`${eng} · ${state}`]
  if (st.length) parts.push(`${st.filter((s) => s.status === 'done').length}/${st.length} stages · ${pct}%`)
  return parts.join('\n') + stale
}

/** Human engine label for a node — used by the status line + tooltip so a NAMD/mrDNA/
 *  CanDo run isn't mislabeled "oxDNA". */
export function engineLabel(node) {
  switch (node?.engine) {
    case 'lammps': return 'LAMMPS (CPU)'
    case 'namd':   return 'NAMD'
    case 'mrdna':  return 'mrDNA'
    case 'cando':  return 'CanDo'
    case 'snupi':  return 'SNUPI'
    case 'oxdna':  return 'oxDNA'
    default:       return node?.engine || 'run'
  }
}

function _stepTotal(node) {
  const direct = Number(node?.steps ?? node?.total_steps ?? node?.n_steps)
  if (Number.isFinite(direct) && direct > 0) return direct
  const parts = node?.engine === 'namd' ? (node.segments || []) : (node.stages || [])
  const values = parts.map(p => Number(p.steps ?? p.total_steps ?? p.num_steps ?? p.n_steps) || 0)
  const sum = values.reduce((a, b) => a + b, 0)
  if (sum > 0) return sum
  if (node?.engine === 'mrdna') return (Number(node.coarse_steps) || 0) + (Number(node.fine_steps) || 0)
  // Linear FEM solves are one solve step; nonlinear CanDo/SNUPI normally expose n_steps.
  if (node?.engine === 'cando' || node?.engine === 'snupi') return 1
  return 0
}

/** Engine-symmetric numeric progress appended beneath the unified Jobs bar. */
export function masterStepText(node) {
  if (!node) return ''
  const pct = masterProgressPct(node)
  const total = _stepTotal(node)
  if (!(total > 0)) return `${pct}%`
  const explicit = Number(node.current_step ?? node.completed_steps ?? node.steps_completed)
  const completed = Number.isFinite(explicit)
    ? Math.max(0, Math.min(total, Math.round(explicit)))
    : Math.max(0, Math.min(total, Math.round(total * pct / 100)))
  const left = Math.max(0, total - completed)
  return `${pct}% · ${completed.toLocaleString()} / ${total.toLocaleString()} steps · ${left.toLocaleString()} left`
}

/** One-line master status text for the selected node (engine-symmetric). */
export function masterStatusText(node) {
  if (!node) return 'Select a run above, or press ▶ Relax to start one.'
  const eng = engineLabel(node)
  if (node.engine === 'lammps') {
    return `${eng} · ${node.status} · ${masterStepText(node)}`
  }
  if (node.production_state === 'running') return `${eng} · production running · ${masterStepText(node)}`
  if (node.production_state === 'done') return `${eng} · production done · ${masterStepText(node)}`
  if (node.production_state === 'failed') return `${eng} · production failed · ${masterStepText(node)}`
  // NAMD (and any engine with a live/segment fraction) shows overall % while running so a
  // single-segment production reads as progress, not a bare "running".
  if (node.engine === 'namd' && node.status === 'running') return `${eng} · running · ${masterStepText(node)}`
  // SNUPI reports a REAL fraction (a fixed GJF step count) + an ETA measured from the observed rate,
  // plus the current phase — building the hydrodynamic friction is a slow, step-less phase, so name it
  // or the bar looks stuck. This line sits directly under the master bar.
  if (node.engine === 'snupi' && node.status === 'running') {
    const parts = [`${eng} · running · ${masterStepText(node)}`]
    const eta = Number(node.eta_seconds)
    if (Number.isFinite(eta) && eta > 0) parts.push(`~${formatEta(eta)} left`)
    if (node.phase) parts.push(node.phase)
    return parts.join(' · ')
  }
  const stages = node.stages || node.segments || []
  const stageText = stages.length
    ? `${stages.filter(s => s.status === 'done').length}/${stages.length} ${node.engine === 'namd' ? 'segments' : 'stages'}`
    : ''
  return [`${eng} · ${node.status}`, stageText, masterStepText(node)].filter(Boolean).join(' · ')
}

/** Compact ETA: seconds under a minute, else m:ss — a multi-minute RPY solve reads badly as "412s". */
export function formatEta(seconds) {
  const s = Math.max(0, Math.ceil(Number(seconds) || 0))
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  return `${m}m ${String(s % 60).padStart(2, '0')}s`
}

/**
 * The expandable detail note under the master bar. This note is oxDNA-SPECIFIC: an oxDNA run gets a
 * brief size line (its rich detail lives in the oxDNA panel), and a LAMMPS run explains why it fell
 * back to CPU (LAMMPS runs are oxDNA's CPU fallback and group under the oxDNA tab).
 *
 * ``activeEngine`` is the engine TAB currently selected. The note only renders on the oxDNA tab: with
 * "Show all job types" on you can select an oxDNA run from any tab, and an oxDNA-flavoured line has no
 * business appearing under, say, the SNUPI panel.
 *
 * It also returns '' for every other engine. It used to FALL THROUGH — any non-LAMMPS node with
 * ``n_units`` was labelled "oxDNA (GPU) · N nucleotides", so selecting a SNUPI / mrDNA / CanDo / NAMD
 * run claimed it had run on oxDNA. Engines other than oxDNA have no detail note here; theirs lives in
 * their own panel.
 */
export function nodeDetailText(node, activeEngine = 'oxdna') {
  if (!node) return ''
  if (activeEngine !== 'oxdna') return ''            // not the oxDNA tab → no oxDNA note
  if (node.engine === 'lammps') {
    const cores = Number(node.ranks) || 1
    return `Ran on CPU (LAMMPS, ${cores} core${cores === 1 ? '' : 's'}) because the GPU was busy — ` +
           'the same oxDNA2 force field, multi-core, faster than single-core.'
  }
  if (node.engine !== 'oxdna') return ''             // never label another engine's run "oxDNA"
  const n = Number(node.n_units) || 0
  return n ? `oxDNA (GPU) · ${n.toLocaleString()} nucleotides` : ''
}

// ── Stateful factory ──────────────────────────────────────────────────────────

export function initSimulateJobs({
  api,
  getWorkspacePath = null,
  oxdnaPanel = null,
  mrdnaPanel = null,
  candoPanel = null,
  snupiPanel = null,
  mdPanel = null,
  engineSelector = null,
} = {}) {
  const $ = (id) => document.getElementById(id)
  const root = $('simulate-jobs')
  const listEl = $('simulate-jobs-list')
  const statusEl = $('simulate-jobs-status')
  const progressBar = root?.querySelector('#simulate-jobs-progress .bar')
  const progressWrap = $('simulate-jobs-progress')
  const runBtn = $('simulate-jobs-run-btn')
  const detailEl = $('simulate-jobs-detail')
  // The one stage-timeline block at the bottom of the jobs card + each engine's timeline
  // element (relocated here from its panel by main.js); the selected engine's is shown.
  const timelineBlock = $('simulate-jobs-timeline')
  const _timelineEls = {
    oxdna: $('oxdna-jobs-timeline'), namd: $('md-jobs-timeline'),
    mrdna: $('mrdna-jobs-timeline'), cando: $('cando-jobs-timeline'),
    snupi: $('snupi-jobs-timeline'),
  }
  if (!root || !listEl) return { refresh: () => {}, selectJob: () => {}, getSelected: () => null, setActiveEngine: () => {} }

  // collapsible "Jobs" card (header/body/chevron) + "Show all job types" toggle + the
  // engine-scope label in the header.
  const cardHeader = $('simulate-jobs-toggle')
  const cardBody = $('simulate-jobs-body')
  const cardArrow = $('simulate-jobs-arrow')
  const engineLabel = $('simulate-jobs-engine-label')
  const showAllToggle = $('simulate-jobs-show-all-types')

  // Consolidated Archive/Delete (one pair for all engines, above the jobs card). Acts on
  // the selected run by dispatching to that run's engine panel; hidden until a deletable
  // run is selected. Archive shows only for engines that support it (oxDNA / NAMD).
  const actionsHost = $('simulate-job-actions')
  const archiveActionBtn = $('simulate-jobs-archive-btn')
  const deleteActionBtn = $('simulate-jobs-delete-btn')
  const archiveProgress = $('simulate-jobs-archive-progress')

  // The ONE shared "📁 Directory" button, above the jobs list — sets where new runs (any
  // engine) write their large trajectories. Each engine's create reads getRunDir().
  mountDirectoryButton($('simulate-run-dir'), { api })

  let _nodes = []
  let _sel = { engine: null, id: null }
  let _listSig = null
  let _busy = false
  let _dynamicsActive = true
  let _pollTimer = null
  let _activeEngine = engineSelector?.getSelected?.() || 'oxdna'
  let _showAllTypes = false
  const _legend = { el: null }

  // Nodes shown for the current view: the active engine tab's runs (LAMMPS grouped under
  // oxDNA), or every engine's when "Show all job types" is on.
  const _visibleNodes = () =>
    _showAllTypes ? _nodes : _nodes.filter((n) => engineGroup(n) === _activeEngine)

  const _currentPath = () => (getWorkspacePath ? getWorkspacePath() : null) || null
  const _selectedNode = () => _nodes.find((n) => n.engine === _sel.engine && n.job_id === _sel.id) || null
  const _setStatus = (el, text, color = _C.dim) => { if (el) { el.textContent = text; el.style.color = color } }
  // The engine panel owning a node's Archive/Delete (LAMMPS has no panel — its runs are
  // oxDNA's CPU fallback and carry no per-job delete UI).
  const _panelFor = (node) =>
    ({ oxdna: oxdnaPanel, mrdna: mrdnaPanel, cando: candoPanel, snupi: snupiPanel, namd: mdPanel }[node?.engine]) || null

  // ── list ─────────────────────────────────────────────────────────────────
  // Per-engine row labels: each engine's own display/child-label fns render its rows
  // in the shared list. NAMD reuses its canonical row ctx (mdJobRowCtx) so its
  // production/replica labels, seeded/remote badges + hourglass override stay identical
  // to the NAMD tab; oxDNA/mrDNA/CanDo use their exported label fns.
  function _mdCtx(nodes) {
    return mdJobRowCtx({ jobs: nodes.filter((n) => n.engine === 'namd'),
                         selectedId: _sel.id, formatTime: formatJobTime })
  }
  function _displayName(n, md) {
    switch (n.engine) {
      case 'oxdna': case 'lammps': return oxDisplayName(n)
      case 'mrdna': return mrdnaDisplayName(n)
      case 'cando': return candoDisplayName(n)
      case 'snupi': return snupiDisplayName(n)
      case 'namd':  return md.displayName(n)
      default:      return n.job_id
    }
  }
  function _childLabel(n, i, md) {
    if (n.engine === 'oxdna') return runRowLabel(n, i)
    if (n.engine === 'namd') return md.childLabel(n, i)
    return ''
  }
  function _childTitle(n, md) {
    if (n.engine === 'oxdna') return runChildTitle(n)
    if (n.engine === 'namd') return md.childTitle(n)
    return null
  }
  function _tags(n) {
    const out = []
    if (_showAllTypes && n.engine !== 'lammps' && _ENGINE_BADGE[n.engine]) {
      const b = _ENGINE_BADGE[n.engine]
      out.push({ text: b.text, color: b.color, title: b.title })
    }
    if (n.engine === 'lammps') {
      out.push({ text: '[L]', color: '#9e6bff', title: 'Ran on CPU (LAMMPS) — the GPU was busy' })
    } else if (n.engine === 'oxdna' && (oxdnaPanel?.autorefineJobIds?.() || new Set()).has(n.job_id)) {
      out.push({ text: '[AR]', color: '#e3b341', title: 'Created by Autorefine skips/loops' })
    }
    return out
  }

  function _rowCtx(nodes) {
    const md = _mdCtx(nodes)
    return {
      engine: 'oxdna',                       // fallback; engineOf resolves per row
      engineOf: (n) => (n.engine === 'lammps' ? 'lammps' : n.engine),
      selectedId: _sel.id,
      hierarchical: true,
      displayName: (n) => _displayName(n, md),
      childLabel: (n, i) => _childLabel(n, i, md),
      childTitle: (n) => _childTitle(n, md),
      productionState: (n) => (n.engine === 'oxdna' ? n.production_state : null),
      isActive: nodeIsActive,
      isStale: (n) => !!n.out_of_date,
      staleClass: 'oxdna-job-stale-warn',
      staleTitle: 'Design changed since this job was relaxed — run a new Relax, or roll the feature log back, before live/production.',
      tags: _tags,
      postLabelMarkers: (n, meta) => (n.engine === 'namd' ? md.postLabelMarkers(n, meta) : []),
      symbolOverride: (n) => (n.engine === 'namd' ? md.symbolOverride(n) : null),
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
    const nodes = _visibleNodes()
    const ctx = _rowCtx(nodes)
    const sig = `${_activeEngine}:${_showAllTypes ? 1 : 0}|` + jobListSignature(nodes, ctx)
    if (sig === _listSig && listEl.childElementCount > 0) return
    _listSig = sig
    renderJobList(listEl, buildJobListModel(nodes, ctx), {
      onClick: (jobId) => _select(jobId),
      emptyText: _showAllTypes
        ? 'No simulation runs for this design yet — press ▶ Relax to start one.'
        : `No ${_activeEngine === 'namd' ? 'NAMD' : _activeEngine} runs for this design yet. Toggle “Show all job types” to see every engine’s runs.`,
      dimColor: _C.dim,
      legendState: _legend,
    })
  }

  function _renderMaster() {
    const node = _selectedNode()
    _setStatus(statusEl, masterStatusText(node),
      node?.status === 'failed' ? _C.err : node && nodeIsActive(node) ? _C.warn : _C.dim)
    // ONE progress bar (below the list): width from the node, colour by status, and the
    // detailed stage/segment text as a hover tooltip.
    if (progressBar) {
      progressBar.style.width = `${node ? masterProgressPct(node) : 0}%`
      progressBar.style.background = node ? masterProgressColor(node) : _C.accent
    }
    if (progressWrap) progressWrap.title = node ? masterProgressTooltip(node) : ''
    if (detailEl) {
      // oxDNA-only note, gated to the oxDNA tab. Collapse the element when there's nothing to say,
      // so other engines don't get a blank gap under the bar.
      const text = nodeDetailText(node, _activeEngine)
      detailEl.textContent = text
      detailEl.style.display = text ? '' : 'none'
    }
    _renderTimeline(node)
    _renderRunButton()
    _renderActions(node)
  }

  // ── consolidated Archive / Delete (above the jobs card) ────────────────────
  // Show the pair only when a deletable run is selected (any engine except LAMMPS, and
  // not while it is running). Archive is offered only for engines that support it
  // (oxDNA / NAMD); its label tracks the selected run's archived state.
  function _renderActions(node = _selectedNode()) {
    const eng = node?.engine
    const canDelete = !!node && eng !== 'lammps' && node.status !== 'running'
    const canArchive = canDelete && (eng === 'oxdna' || eng === 'namd')
    if (actionsHost) actionsHost.style.display = canDelete ? '' : 'none'
    if (deleteActionBtn) deleteActionBtn.style.display = canDelete ? '' : 'none'
    if (archiveActionBtn) {
      archiveActionBtn.style.display = canArchive ? '' : 'none'
      archiveActionBtn.textContent = node?.archived ? 'Unarchive' : 'Archive'
    }
  }

  // Byte-move progress for an archive/unarchive (rendered here, driven by the engine panel).
  function _setArchiveProgress(st) {
    if (!archiveProgress) return
    if (!st) { archiveProgress.style.display = 'none'; archiveProgress.textContent = ''; return }
    const pct = st.total_bytes ? Math.round((st.moved_bytes / st.total_bytes) * 100) : 0
    archiveProgress.style.display = ''
    archiveProgress.textContent =
      `${formatBytes(st.moved_bytes || 0)} / ${formatBytes(st.total_bytes || 0)} (${pct}%)`
  }

  async function _onArchive() {
    const node = _selectedNode()
    const panel = _panelFor(node)
    if (!panel?.archiveSelected) return
    if (archiveActionBtn) archiveActionBtn.disabled = true
    if (deleteActionBtn) deleteActionBtn.disabled = true
    try {
      await panel.archiveSelected({ onProgress: _setArchiveProgress })
    } finally {
      if (archiveActionBtn) archiveActionBtn.disabled = false
      if (deleteActionBtn) deleteActionBtn.disabled = false
      _setArchiveProgress(null)
      await _fetch()
    }
  }
  async function _onDelete() {
    const node = _selectedNode()
    const panel = _panelFor(node)
    if (!panel?.deleteSelected) return
    const ok = await panel.deleteSelected()
    if (ok) { _sel = { engine: null, id: null }; await _fetch() }
  }
  archiveActionBtn?.addEventListener('click', _onArchive)
  deleteActionBtn?.addEventListener('click', _onDelete)

  // Show the selected engine's stage timeline (relocated to the bottom of the jobs card);
  // hide the others. LAMMPS has no stage timeline.
  function _renderTimeline(node) {
    const eng = node && node.engine !== 'lammps' ? node.engine : null
    let anyShown = false
    for (const [k, el] of Object.entries(_timelineEls)) {
      if (!el) continue
      const show = k === eng
      el.style.display = show ? '' : 'none'
      if (show) anyShown = true
    }
    if (timelineBlock) timelineBlock.style.display = anyShown ? '' : 'none'
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
    _renderList()
    _renderMaster()
    _dispatchDetail(node)
  }

  // Rich detail dispatch by engine: reveal the selected job's engine tab and light up
  // that panel's own detail/viz via selectJob (identical to a row click on that tab).
  // A LAMMPS run is the CPU fallback for oxDNA (same oxDNA2 bead model), so it shows in
  // the oxDNA panel's OWN viz card via selectLammpsJob — same display/RMSF/deviation/
  // trajectory tools, just a different loader.
  function _dispatchDetail(node) {
    if (node.engine === 'lammps') {
      engineSelector?.select?.('oxdna')
      oxdnaPanel?.selectLammpsJob?.(node)
      return
    }
    const panel = { oxdna: oxdnaPanel, mrdna: mrdnaPanel, cando: candoPanel, snupi: snupiPanel, namd: mdPanel }[node.engine]
    if (!panel) return
    engineSelector?.select?.(node.engine)     // reveal that engine's detail host
    panel?.selectJob?.(node.job_id)
  }

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
    _fetch()
  })
  // A job launched / stopped / resumed from an engine panel (each polls its OWN hidden
  // list) must WAKE the master: its poll re-arms only while it already has an active
  // node, so a launch made while the master is idle would otherwise not surface until a
  // manual refresh. _fetch() picks up the new job AND re-arms the poll from there.
  window.addEventListener('nadoc:sim-jobs-changed', () => _fetch())

  // ── engine scope: filter to the active tab + "Show all job types" toggle ───
  function _engineTabName() {
    return { oxdna: 'oxDNA', mrdna: 'mrDNA', cando: 'CanDo', snupi: 'SNUPI', namd: 'NAMD' }[_activeEngine] || _activeEngine
  }
  function _updateEngineLabel() {
    if (engineLabel) engineLabel.textContent = _showAllTypes ? '· all engines' : `· ${_engineTabName()}`
  }
  /** Called by the engine selector's onSelect (main.js): the list re-scopes to the
   *  newly-active tab. No-op refetch — the same design's nodes are re-filtered client-side.
   *  Switching to a different engine tab also drops a selection that belongs to the OLD
   *  engine (a NAMD job selected, then the SNUPI tab clicked): the master card — status,
   *  progress bar, stage timeline, detail, run/archive buttons — is shared across engines,
   *  so clearing the selection + re-rendering it prevents the previous engine's stages from
   *  lingering under the new tab. In "show all job types" mode every run stays visible, so
   *  the selection (still highlighted in the list) is preserved. */
  function setActiveEngine(engine) {
    if (!engine || engine === _activeEngine) return
    _activeEngine = engine
    _updateEngineLabel()
    if (_sel.id && !_visibleNodes().some((n) => n.engine === _sel.engine && n.job_id === _sel.id)) {
      _sel = { engine: null, id: null }
    }
    // ALWAYS re-render the master block on a tab switch, not only when the selection was cleared:
    // in "show all job types" mode the selection SURVIVES the switch, and the detail note is gated on
    // the active tab (oxDNA-only) — without this it would linger under another engine's panel.
    _renderMaster()
    _renderList()
  }
  showAllToggle?.addEventListener('change', () => {
    _showAllTypes = !!showAllToggle.checked
    _updateEngineLabel()
    _renderList()
  })

  // ── collapsible "Jobs" card (persisted per Dynamics tab) ───────────────────
  function _applyCollapsed(collapsed) {
    if (cardBody) cardBody.style.display = collapsed ? 'none' : ''
    if (cardArrow) cardArrow.classList.toggle('is-collapsed', collapsed)
  }
  let _collapsed = getSectionCollapsed('dynamics', 'simulate-jobs', false)
  _applyCollapsed(_collapsed)
  _updateEngineLabel()
  cardHeader?.addEventListener('click', () => {
    _collapsed = !_collapsed
    setSectionCollapsed('dynamics', 'simulate-jobs', _collapsed)
    _applyCollapsed(_collapsed)
  })

  function refresh() { return _fetch() }
  function selectJob(jobId) { return _select(jobId) }

  // Initial populate deferred a tick so late-declared main.js deps (workspace path) exist.
  queueMicrotask(_fetch)

  return { refresh, selectJob, setActiveEngine, getSelected: () => ({ ..._sel }) }
}
