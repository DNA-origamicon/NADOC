// @vitest-environment jsdom
//
// U3 oracle — the CANONICAL job-list model + renderer.
//
// PARITY PIN (adapted-code rule, CLAUDE.md): the new pure model + renderer must
// reproduce the OLD oxDNA `_jobRow` / `_renderList` DOM byte-for-byte. This file
// carries a VERBATIM copy of that old row/list logic as `oldOxdnaJobRow` /
// `oldOxdnaRenderList` (transcribed from oxdna_jobs_panel.js @HEAD, lines
// 1041-1136) and drives OLD and NEW on fresh DOM fragments, asserting identical
// outerHTML. Green therefore proves behavior preservation (not green-by-luck):
// if the extraction drifted, the two DOMs would differ.
//
// It also pins the flat-list convergence (mrDNA-shaped ctx), the poll-signature
// short-circuit, and run-button enablement.

import { describe, it, expect } from 'vitest'
import {
  buildJobRowModel, buildJobListModel, jobListSignature, runButtonEnabled,
} from './jobs_panel_model.js'
import { renderJobRow, renderJobList } from './jobs_panel_render.js'
import { statusBadge, statusKeyFor, makeSpinner, makeStatusLegend } from './job_status_symbol.js'

// ── Verbatim OLD oxDNA row/list (the reference oracle) ────────────────────────
// Copied from oxdna_jobs_panel.js at the commit before U3. The oxDNA-local
// closures it referenced are passed in as params (selectedId, arJobIds,
// autorefineRunning) or reproduced faithfully (jobDisplayName, runRowLabel, etc).

const _C = { dim: '#8a8a8a', warn: '#e0a800' }

function jobDisplayName(job) {
  if (!job) return ''
  const src = job.design_source_path
  if (src) {
    const stem = String(src).split('/').pop().replace(/\.[^.]+$/, '')
    if (stem) return stem
  }
  return job.design_name || 'design'
}
function productionState(job) {
  const prods = (job?.stages || []).filter(s => s.kind === 'production')
  const prod = prods.length ? prods[prods.length - 1] : null
  if (!prod) return 'none'
  if (prod.status === 'done') return 'done'
  if (prod.status === 'failed') return 'failed'
  if (prod.status === 'running' || prod.status === 'pending') return 'running'
  return 'none'
}
function jobIsActive(job) {
  return ['queued', 'preparing', 'running'].includes(job?.status)
}
function jobOutOfDate(job) { return !!job?.out_of_date }
function runRowLabel(job, index) { return `Run ${index}` }
function runChildTitle(job) { return 'Production run' }
function formatJobTime(ts) { return `t${ts}` }
function formatBytes(n) { return `${n}B` }

// The old `_jobRow` (oxdna_jobs_panel.js:1062-1136), parameterized by the
// oxDNA-local state it closed over.
function oldOxdnaJobRow(job, { isChild = false, index = 0, depth = 0, listIndex = 0 }, S) {
  const { selectedId, arJobIds, autorefineRunning, doc } = S
  const row = doc.createElement('div')
  row.dataset.jobId = job.job_id
  row.style.cssText =
    `display:flex;align-items:center;gap:6px;padding:4px 6px;cursor:pointer;border-radius:4px;` +
    `font-size:11px;${depth ? `padding-left:${6 + depth * 14}px;` : ''}` +
    `${job.job_id === selectedId ? 'background:#2a3a4a;' : ''}`
  const badge = statusBadge(statusKeyFor('oxdna', job.status, productionState(job)))
  const idx = doc.createElement('span')
  idx.textContent = isChild ? '' : `[${listIndex}]`
  idx.style.cssText = `flex-shrink:0;color:${_C.dim};font-family:var(--font-mono)`
  const label = doc.createElement('span')
  label.style.cssText = 'flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap'
  if (isChild) {
    label.textContent = runRowLabel(job, index)
    row.title = runChildTitle(job)
  } else {
    label.textContent = jobDisplayName(job)
  }
  const ts = doc.createElement('span')
  ts.textContent = formatJobTime(job.created_at)
  ts.style.cssText = `flex-shrink:0;color:${_C.dim};font-size:10px;font-family:var(--font-mono)`
  const size = doc.createElement('span')
  size.textContent = job.size_bytes ? formatBytes(job.size_bytes) : ''
  size.style.cssText = `flex-shrink:0;color:${job.archived ? _C.warn : _C.dim};font-size:10px;font-family:var(--font-mono)`
  if (job.archived) size.title = `Archived → ${job.archive_path || ''}`
  const sym = jobIsActive(job)
    ? makeSpinner(badge.color, 10, doc)
    : Object.assign(doc.createElement('span'), { textContent: badge.symbol })
  sym.style.flexShrink = '0'
  sym.title = badge.label
  if (!jobIsActive(job)) sym.style.color = badge.color
  row.append(idx)
  if (arJobIds.has(job.job_id)) {
    const ar = Object.assign(doc.createElement('span'), { textContent: '[AR]' })
    ar.style.cssText = `flex-shrink:0;color:#e3b341;font-family:var(--font-mono);font-weight:600`
    ar.title = 'Created by Autorefine skips/loops'
    row.append(ar)
  }
  row.append(label, ts, size)
  if (job.archived) {
    const box = Object.assign(doc.createElement('span'), { textContent: '📦' })
    box.style.cssText = 'flex-shrink:0;font-size:10px'
    box.title = `Archived → ${job.archive_path || ''}`
    row.append(box)
  }
  if (jobOutOfDate(job) && !autorefineRunning) {
    const warn = Object.assign(doc.createElement('span'), { textContent: '⚠' })
    warn.className = 'oxdna-job-stale-warn'
    warn.style.cssText = `flex-shrink:0;color:${_C.warn};font-size:11px`
    warn.title = 'Design changed since this job was relaxed — run a new Relax, or roll the feature log back, before live/production.'
    row.append(warn)
  }
  row.append(sym)
  row.dataset.jobId = job.job_id
  return row
}

// The oxDNA ctx the panel will build (mirrors _rowCtx() in the rewired panel).
function oxdnaCtx(S) {
  return {
    engine: 'oxdna',
    selectedId: S.selectedId,
    hierarchical: true,
    displayName: jobDisplayName,
    childLabel: runRowLabel,
    childTitle: runChildTitle,
    productionState,
    isActive: jobIsActive,
    isStale: (job) => jobOutOfDate(job) && !S.autorefineRunning,
    staleClass: 'oxdna-job-stale-warn',
    staleTitle: 'Design changed since this job was relaxed — run a new Relax, or roll the feature log back, before live/production.',
    tags: (job) => S.arJobIds.has(job.job_id)
      ? [{ text: '[AR]', color: '#e3b341', title: 'Created by Autorefine skips/loops' }] : [],
    archived: (job) => !!job.archived,
    archivePath: (job) => job.archive_path || '',
    sizeBytes: (job) => job.size_bytes ?? null,
    formatTime: formatJobTime,
    formatSize: formatBytes,
    rowSig: (j) => `${j.job_id}:${j.status}:${productionState(j)}:${j.out_of_date ? 1 : 0}:${j.archived ? 1 : 0}:${j.size_bytes ?? ''}`,
    colors: { dim: _C.dim, warn: _C.warn },
  }
}

// A battery of oxDNA jobs exercising every row branch.
const OX_JOBS = [
  { job_id: 'root1', status: 'completed', created_at: 100, stages: [{ kind: 'relax', status: 'done' }], design_source_path: '/w/foo.nadoc' },
  { job_id: 'child1', parent_job_id: 'root1', status: 'completed', created_at: 110, stages: [{ kind: 'production', status: 'done' }] },
  { job_id: 'run2', status: 'running', created_at: 90, stages: [{ kind: 'relax', status: 'running' }], design_name: 'bar' },
  { job_id: 'arj', status: 'completed', created_at: 80, stages: [], design_name: 'baz' },
  { job_id: 'stalej', status: 'completed', created_at: 70, out_of_date: true, stages: [], design_name: 'old' },
  { job_id: 'arch', status: 'completed', created_at: 60, archived: true, archive_path: '/archive/x', size_bytes: 4096, stages: [], design_name: 'z' },
]

describe('U3 parity pin — canonical row matches old oxDNA _jobRow byte-for-byte', () => {
  const S = () => ({
    selectedId: 'child1',
    arJobIds: new Set(['arj']),
    autorefineRunning: false,
    doc: document,
  })

  it('every row branch (root/child/running/AR/stale/archived+size) is byte-identical', () => {
    const s = S()
    const ctx = oxdnaCtx(s)
    // Drive the SAME flattened positions through both paths.
    const listModel = buildJobListModel(OX_JOBS, ctx)
    // Reconstruct positions the old code would have used from the flattened order.
    // buildJobListModel already applied flattenJobTree; walk its rows and rebuild
    // the old-row inputs from each model's depth/label to prove equivalence.
    for (const rm of listModel.rows) {
      const job = OX_JOBS.find(j => j.job_id === rm.jobId)
      const isChild = rm.depth > 0
      // recover index/listIndex from the model's own indexLabel + child label
      const listIndex = isChild ? 0 : Number(rm.indexLabel.replace(/[[\]]/g, ''))
      const index = isChild ? Number(rm.label.replace('Run ', '')) : 0
      const oldRow = oldOxdnaJobRow(job, { isChild, index, depth: rm.depth, listIndex }, s)
      const newRow = renderJobRow(rm, { doc: document })
      expect(newRow.outerHTML).toBe(oldRow.outerHTML)
    }
  })

  it('a selected root highlights and an unselected one does not', () => {
    const sel = renderJobRow(buildJobRowModel(OX_JOBS[0], oxdnaCtx({ ...S(), selectedId: 'root1' }), { depth: 0, listIndex: 1 }))
    const unsel = renderJobRow(buildJobRowModel(OX_JOBS[0], oxdnaCtx(S()), { depth: 0, listIndex: 1 }))
    expect(sel.style.background).toBeTruthy()
    expect(unsel.style.background).toBeFalsy()
  })
})

describe('U3 parity pin — renderJobList matches old oxDNA _renderList', () => {
  function oldRenderList(container, jobs, S) {
    const doc = S.doc
    const sorted = jobs.slice().sort((a, b) => b.created_at - a.created_at)
    if (!sorted.length) {
      container.innerHTML = `<div style="color:${_C.dim};padding:6px 4px;font-size:11px">No oxDNA jobs for this design yet.</div>`
      return
    }
    container.innerHTML = ''
    // flatten via the same helper the panel uses
    const { flattenJobTree } = require('./job_tree.js')
    let rootNo = 0
    for (const { job, depth, index } of flattenJobTree(sorted)) {
      if (depth === 0) rootNo += 1
      container.appendChild(oldOxdnaJobRow(job, { isChild: depth > 0, index, depth, listIndex: rootNo }, S))
    }
  }

  it('non-empty list innerHTML is identical', async () => {
    const { flattenJobTree } = await import('./job_tree.js')
    void flattenJobTree
    const s = { selectedId: 'child1', arJobIds: new Set(['arj']), autorefineRunning: false, doc: document }
    const oldEl = document.createElement('div')
    // inline old render (avoid require in ESM)
    const sorted = OX_JOBS.slice().sort((a, b) => b.created_at - a.created_at)
    oldEl.innerHTML = ''
    let rootNo = 0
    for (const { job, depth, index } of flattenJobTree(sorted)) {
      if (depth === 0) rootNo += 1
      oldEl.appendChild(oldOxdnaJobRow(job, { isChild: depth > 0, index, depth, listIndex: rootNo }, s))
    }

    const newEl = document.createElement('div')
    renderJobList(newEl, buildJobListModel(OX_JOBS, oxdnaCtx(s)), {
      onClick: () => {}, emptyText: 'No oxDNA jobs for this design yet.', dimColor: _C.dim,
    })
    expect(newEl.innerHTML).toBe(oldEl.innerHTML)
  })

  it('empty list placeholder is identical', () => {
    const oldEl = document.createElement('div')
    oldEl.innerHTML = `<div style="color:${_C.dim};padding:6px 4px;font-size:11px">No oxDNA jobs for this design yet.</div>`
    const newEl = document.createElement('div')
    renderJobList(newEl, buildJobListModel([], oxdnaCtx({ selectedId: null, arJobIds: new Set(), autorefineRunning: false, doc: document })), {
      emptyText: 'No oxDNA jobs for this design yet.', dimColor: _C.dim,
    })
    expect(newEl.innerHTML).toBe(oldEl.innerHTML)
  })
})

describe('U3 — flat-list convergence (mrDNA-shaped ctx)', () => {
  const MR_JOBS = [
    { job_id: 'm1', status: 'completed', created_at: 10, design_name: 'a' },
    { job_id: 'm2', status: 'running', created_at: 20, design_name: 'b' },
  ]
  const mrCtx = {
    engine: 'mrdna',
    selectedId: 'm2',
    hierarchical: false,
    displayName: jobDisplayName,
    formatTime: formatJobTime,
    rowSig: (j) => `${j.job_id}:${j.status}`,
    colors: { dim: _C.dim, warn: _C.warn },
  }

  it('numbers rows newest-first and maps the mrDNA status key', () => {
    const model = buildJobListModel(MR_JOBS, mrCtx)
    expect(model.rows.map(r => r.jobId)).toEqual(['m2', 'm1'])   // newest first
    expect(model.rows.map(r => r.indexLabel)).toEqual(['[1]', '[2]'])
    expect(model.rows[0].statusKey).toBe(statusKeyFor('mrdna', 'running'))
    expect(model.rows[0].isActive).toBe(true)       // running → spinner
    expect(model.rows[1].isActive).toBe(false)      // completed → glyph
  })

  it('renders the canonical structure (index + name + spinner-or-glyph)', () => {
    const model = buildJobListModel(MR_JOBS, mrCtx)
    const el = document.createElement('div')
    renderJobList(el, model, { onClick: () => {}, emptyText: 'No mrDNA jobs for this design yet.', dimColor: _C.dim })
    const rows = el.querySelectorAll('[data-job-id]')
    expect(rows.length).toBe(2)
    // active row → spinner; completed row → badge glyph
    expect(rows[0].querySelector('.nadoc-spinner')).toBeTruthy()
    expect(rows[1].querySelector('.nadoc-spinner')).toBeFalsy()
    expect(rows[1].textContent).toContain(statusBadge(statusKeyFor('mrdna', 'completed')).symbol)
  })
})

describe('U3 slice 2a — cando flat convergence (mode as a leading tag)', () => {
  const CANDO_JOBS = [
    { job_id: 'c1', status: 'completed', created_at: 10, design_name: 'a', nonlinear: false },
    { job_id: 'c2', status: 'running', created_at: 20, design_name: 'b', nonlinear: true },
  ]
  const candoCtx = {
    engine: 'cando',
    selectedId: 'c2',
    hierarchical: false,
    displayName: jobDisplayName,
    isActive: jobIsActive,
    formatTime: formatJobTime,
    tags: (job) => [{ text: job.nonlinear ? 'Fine' : 'Coarse', color: _C.dim,
      title: job.nonlinear ? 'Fine (nonlinear)' : 'Coarse (linear)' }],
    rowSig: (j) => `${j.job_id}:${j.status}:${j.nonlinear ? 1 : 0}`,
    colors: { dim: _C.dim, warn: _C.warn },
  }

  it('numbers rows newest-first, maps the cando status key, spinner while active', () => {
    const model = buildJobListModel(CANDO_JOBS, candoCtx)
    expect(model.rows.map(r => r.jobId)).toEqual(['c2', 'c1'])       // newest first
    expect(model.rows.map(r => r.indexLabel)).toEqual(['[1]', '[2]'])
    expect(model.rows[0].statusKey).toBe(statusKeyFor('cando', 'running'))
    expect(model.rows[0].isActive).toBe(true)
    expect(model.rows[1].isActive).toBe(false)
  })

  it('renders the Coarse/Fine mode as a leading tag (canonical tag slot, not a bespoke column)', () => {
    const model = buildJobListModel(CANDO_JOBS, candoCtx)
    const el = document.createElement('div')
    renderJobList(el, model, { onClick: () => {}, emptyText: 'No CanDo FEM jobs for this design yet.', dimColor: _C.dim })
    const rows = el.querySelectorAll('[data-job-id]')
    // row[0] is c2 (running, nonlinear) → 'Fine' tag + spinner
    expect(rows[0].textContent).toContain('Fine')
    expect(rows[0].querySelector('.nadoc-spinner')).toBeTruthy()
    // row[1] is c1 (completed, linear) → 'Coarse' tag + static glyph
    expect(rows[1].textContent).toContain('Coarse')
    expect(rows[1].querySelector('.nadoc-spinner')).toBeFalsy()
    // no per-row action button (cando has no rowAction)
    expect(el.querySelector('button')).toBeFalsy()
  })
})

describe('U3 slice 2a — per-row action button (LAMMPS inline Stop)', () => {
  const LAMMPS_JOBS = [
    { job_id: 'l1', status: 'running', created_at: 20, design_name: 'live' },
    { job_id: 'l2', status: 'completed', created_at: 10, design_name: 'done' },
  ]
  const STOP_STYLE = 'flex:0 0 auto;padding:1px 6px'
  const lammpsCtx = {
    engine: 'lammps',
    selectedId: null,
    hierarchical: false,
    displayName: jobDisplayName,
    isActive: jobIsActive,
    formatTime: formatJobTime,
    rowAction: (job) => jobIsActive(job) ? { text: 'Stop', title: 'Stop this run', styleText: STOP_STYLE } : null,
    rowSig: (j) => `${j.job_id}:${j.status}`,
    colors: { dim: _C.dim, warn: _C.warn },
  }

  it('models the action only for active jobs', () => {
    const model = buildJobListModel(LAMMPS_JOBS, lammpsCtx)
    const running = model.rows.find(r => r.jobId === 'l1')
    const done = model.rows.find(r => r.jobId === 'l2')
    expect(running.action).toEqual({ text: 'Stop', title: 'Stop this run', styleText: STOP_STYLE })
    expect(done.action).toBe(null)
  })

  it('renders a Stop button on active rows; clicking it fires onAction and NOT the row onClick', () => {
    const model = buildJobListModel(LAMMPS_JOBS, lammpsCtx)
    const el = document.createElement('div')
    const clicks = []
    const actions = []
    renderJobList(el, model, {
      onClick: (id) => clicks.push(id),
      onAction: (id) => actions.push(id),
      emptyText: 'none', dimColor: _C.dim,
    })
    const rows = el.querySelectorAll('[data-job-id]')
    const runningRow = [...rows].find(r => r.dataset.jobId === 'l1')
    const doneRow = [...rows].find(r => r.dataset.jobId === 'l2')
    const stopBtn = runningRow.querySelector('button')
    expect(stopBtn).toBeTruthy()
    expect(stopBtn.textContent).toBe('Stop')
    expect(doneRow.querySelector('button')).toBeFalsy()   // completed → no Stop
    stopBtn.click()
    expect(actions).toEqual(['l1'])   // action fired
    expect(clicks).toEqual([])        // stopPropagation → row select did NOT fire
  })

  it('a ctx WITHOUT rowAction renders no button (oxDNA-parity guard)', () => {
    const noActionCtx = { ...lammpsCtx, rowAction: undefined }
    const model = buildJobListModel(LAMMPS_JOBS, noActionCtx)
    expect(model.rows.every(r => r.action === null)).toBe(true)
    const el = document.createElement('div')
    renderJobList(el, model, { onClick: () => {}, emptyText: 'none', dimColor: _C.dim })
    expect(el.querySelector('button')).toBeFalsy()
  })
})

describe('U3 — poll signature short-circuit', () => {
  const ctx = { selectedId: 's', rowSig: (j) => `${j.job_id}:${j.status}` }
  it('is stable across a health-only change and flips on status/selection change', () => {
    const a = [{ job_id: 'x', status: 'running', created_at: 1, health: 0.2 }]
    const b = [{ job_id: 'x', status: 'running', created_at: 1, health: 0.9 }]  // health changed only
    expect(jobListSignature(a, ctx)).toBe(jobListSignature(b, ctx))
    const c = [{ job_id: 'x', status: 'completed', created_at: 1 }]
    expect(jobListSignature(a, ctx)).not.toBe(jobListSignature(c, ctx))
    expect(jobListSignature(a, ctx)).not.toBe(jobListSignature(a, { ...ctx, selectedId: 'other' }))
  })
})

describe('U3 — runButtonEnabled', () => {
  it('is the canonical available && !launching && !blocked predicate', () => {
    expect(runButtonEnabled({ available: true, launching: false, blocked: false })).toBe(true)
    expect(runButtonEnabled({ available: false })).toBe(false)
    expect(runButtonEnabled({ available: true, launching: true })).toBe(false)
    expect(runButtonEnabled({ available: true, blocked: true })).toBe(false)
    expect(runButtonEnabled()).toBe(false)
  })
})

// makeStatusLegend is DOM-built once by renderJobList; sanity that it exists.
describe('U3 — legend memoization hook', () => {
  it('builds the legend once and inserts it after the list', () => {
    const parent = document.createElement('div')
    const listEl = document.createElement('div')
    parent.appendChild(listEl)
    const legendState = { el: null }
    const model = buildJobListModel([{ job_id: 'x', status: 'completed', created_at: 1, design_name: 'd' }], {
      engine: 'oxdna', hierarchical: false, displayName: jobDisplayName, formatTime: formatJobTime, colors: { dim: _C.dim, warn: _C.warn },
    })
    renderJobList(listEl, model, { legendState })
    expect(legendState.el).toBeTruthy()
    expect(listEl.nextSibling).toBe(legendState.el)
    const first = legendState.el
    renderJobList(listEl, model, { legendState })   // second render must not rebuild
    expect(legendState.el).toBe(first)
    void makeStatusLegend
  })
})
