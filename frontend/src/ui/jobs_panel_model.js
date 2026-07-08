/**
 * jobs_panel_model.js — the CANONICAL job-list row model (U3, "unified panel"
 * track). PURE, no DOM, no I/O — trivially unit-testable and shared verbatim by
 * every engine's jobs panel.
 *
 * The oxDNA jobs panel is the reference: correct parent/child indent, status
 * icons, list index, naming conventions. Historically each engine's panel
 * re-implemented its own row rendering (mrDNA/cando/lammps were flat lists with
 * ad-hoc markup, only oxDNA/md had the tree). This module lifts oxDNA's row/list
 * SHAPE into an engine-agnostic model so every panel converges to it: a panel
 * supplies a small `ctx` of per-engine data + pure callbacks (display name,
 * child label, status flags, tag list) and gets back the same row descriptors
 * oxDNA produces today. `jobs_panel_render.js` turns a model into the canonical
 * DOM; `jobs_panel_model.test.js` pins it byte-for-byte against the old oxDNA
 * `_jobRow`/`_renderList`.
 *
 * ctx fields (all optional except `engine`):
 *   engine          engine key for statusKeyFor ('oxdna'|'mrdna'|…)
 *   selectedId      currently-selected job id (drives the row highlight)
 *   hierarchical    true → parent/child tree via flattenJobTree; false → flat list
 *   collapsedIds    Set of collapsed parent ids (hierarchical only)
 *   displayName(job)        → root-row label
 *   childLabel(job, index)  → child-row label (hierarchical only)
 *   childTitle(job)         → child-row hover title (hierarchical only)
 *   productionState(job)    → oxDNA production sub-state for statusKeyFor (else null)
 *   isActive(job)           → spinner vs static glyph (default: queued/preparing/running)
 *   isStale(job)            → ⚠ marker
 *   staleClass, staleTitle  → ⚠ marker className + hover title
 *   tags(job)               → [{ text, color, title }] leading tags (e.g. [AR])
 *   archived(job)           → 📦 marker (default: job.archived)
 *   archivePath(job)        → archive location for the 📦 title
 *   sizeBytes(job)          → on-disk size (default: job.size_bytes)
 *   formatTime(ts)          → timestamp string
 *   formatSize(bytes)       → size string
 *   rowSig(job)             → per-row render signature (drives the poll short-circuit)
 *   rowAction(job)          → optional trailing per-row control {text, title?, styleText}
 *                            or null (e.g. LAMMPS's inline Stop button); oxDNA/mrDNA/
 *                            cando omit it → null → no button (oxDNA parity preserved)
 *   chevron                 → truthy → every row gets a leading expand/collapse chevron
 *                            span (empty spacer for leaves, ▸/▾ for parents), toggling
 *                            the tree; absent → no span (NAMD only; oxDNA parity preserved)
 *   postLabelMarkers(job,{childCount,collapsed}) → [{ text, title?, css? }] spans rendered
 *                            after the label, before the timestamp (e.g. NAMD's collapsed-
 *                            ensemble summary + oxDNA/mrDNA-seeded + Alpine badges); default []
 *   symbolOverride(job)     → { glyph, color?, title?, dataset? } to REPLACE the
 *                            spinner/badge status symbol (e.g. NAMD's ⧗ remote-queued
 *                            hourglass with a live-refresh dataset), or null
 *   colors                  → { dim, warn } row colors
 *   indentBase, indentStep  → child indent px (default 6 + depth*14, oxDNA's values)
 */

import { flattenJobTree } from './job_tree.js'
import { statusKeyFor } from './job_status_symbol.js'

const _DEFAULT_ACTIVE = (job) => ['queued', 'preparing', 'running'].includes(job?.status)
const _DEFAULT_COLORS = { dim: '#8a8a8a', warn: '#e0a800' }

/**
 * Pure: one job → a canonical row descriptor. `pos` carries the tree position
 * ({ depth, index, listIndex }) computed by buildJobListModel.
 */
export function buildJobRowModel(job, ctx, { depth = 0, index = 0, listIndex = 0, childCount = 0 } = {}) {
  const isChild = depth > 0
  const colors = ctx.colors || _DEFAULT_COLORS
  const collapsed = !!(ctx.collapsedIds && ctx.collapsedIds.has(job.job_id))
  const prodState = ctx.productionState ? ctx.productionState(job) : null
  const statusKey = statusKeyFor(ctx.engine, job.status, prodState)
  const isActive = ctx.isActive ? !!ctx.isActive(job) : _DEFAULT_ACTIVE(job)
  const archived = ctx.archived ? !!ctx.archived(job) : !!job?.archived
  const sizeBytes = ctx.sizeBytes ? ctx.sizeBytes(job) : (job?.size_bytes ?? null)
  const archivePath = archived ? (ctx.archivePath ? ctx.archivePath(job) : (job?.archive_path || '')) : ''
  const label = isChild && ctx.childLabel
    ? ctx.childLabel(job, index)
    : (ctx.displayName ? ctx.displayName(job) : '')
  const indentBase = ctx.indentBase ?? 6
  const indentStep = ctx.indentStep ?? 14
  return {
    jobId: job.job_id,
    depth,
    indentPx: depth ? indentBase + depth * indentStep : 0,
    selected: job.job_id === ctx.selectedId,
    statusKey,
    isActive,
    indexLabel: isChild ? '' : `[${listIndex}]`,
    label,
    title: isChild && ctx.childTitle ? ctx.childTitle(job) : null,
    timeStr: ctx.formatTime ? ctx.formatTime(job.created_at) : '',
    sizeStr: sizeBytes && ctx.formatSize ? ctx.formatSize(sizeBytes) : '',
    archived,
    archivePath,
    stale: ctx.isStale ? !!ctx.isStale(job) : false,
    staleClass: ctx.staleClass || null,
    staleTitle: ctx.staleTitle || '',
    tags: ctx.tags ? (ctx.tags(job) || []) : [],
    action: ctx.rowAction ? (ctx.rowAction(job) || null) : null,
    chevron: ctx.chevron
      ? {
          childCount,
          collapsed,
          title: childCount > 0
            ? (collapsed ? `Expand ${childCount} child job${childCount === 1 ? '' : 's'}` : 'Collapse')
            : '',
        }
      : null,
    postLabelMarkers: ctx.postLabelMarkers ? (ctx.postLabelMarkers(job, { childCount, collapsed }) || []) : [],
    symbolOverride: ctx.symbolOverride ? (ctx.symbolOverride(job) || null) : null,
    colors,
  }
}

/**
 * Pure: the full ordered list model. Roots newest-first; children in run order
 * (flattenJobTree). Flat engines (hierarchical=false) number rows [1..N] in the
 * same newest-first order. Returns { empty, rows:[rowModel] }.
 */
export function buildJobListModel(jobs, ctx) {
  const sorted = (jobs || []).slice().sort((a, b) => (b.created_at || 0) - (a.created_at || 0))
  if (!sorted.length) return { empty: true, rows: [] }
  const rows = []
  if (ctx.hierarchical) {
    let rootNo = 0
    for (const { job, depth, index, childCount } of flattenJobTree(sorted, { collapsedIds: ctx.collapsedIds || null })) {
      if (depth === 0) rootNo += 1
      rows.push(buildJobRowModel(job, ctx, { depth, index, listIndex: rootNo, childCount }))
    }
  } else {
    sorted.forEach((job, i) => rows.push(buildJobRowModel(job, ctx, { depth: 0, index: 0, listIndex: i + 1 })))
  }
  return { empty: false, rows }
}

/**
 * Pure: the render signature of what the list actually shows (id + status +
 * per-engine row fields + selection). A running job's health/progress changing
 * must NOT re-render the list, or the row spinners restart every poll. Sorted
 * newest-first to match buildJobListModel.
 */
export function jobListSignature(jobs, ctx) {
  const sorted = (jobs || []).slice().sort((a, b) => (b.created_at || 0) - (a.created_at || 0))
  const per = ctx.rowSig || ((j) => `${j.job_id}:${j.status}`)
  return sorted.map(per).join(',') + `|sel=${ctx.selectedId ?? ''}`
}

/**
 * Pure: canonical run-button enablement. A run is offered when the engine is
 * available, nothing is mid-launch, and no per-engine blocking job state applies
 * (a job already running, a stale prerequisite). Every panel's predicate is a
 * specialization of this — `blocked` is the per-engine part.
 */
export function runButtonEnabled({ available = false, launching = false, blocked = false } = {}) {
  return !!available && !launching && !blocked
}
