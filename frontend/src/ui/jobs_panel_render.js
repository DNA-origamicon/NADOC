/**
 * jobs_panel_render.js — the CANONICAL job-list DOM renderer (U3). Turns the
 * pure row models from jobs_panel_model.js into the exact DOM the oxDNA jobs
 * panel produces today (indent, list index, leading tags, timestamp, size,
 * archive/stale markers, spinner-or-glyph status). Every engine's panel renders
 * through this so they all converge to the oxDNA look.
 *
 * DOM-only (no state); pinned byte-for-byte against the old oxDNA `_jobRow` /
 * `_renderList` in jobs_panel_model.test.js.
 */

import { statusBadge, makeSpinner, makeStatusLegend } from './job_status_symbol.js'

/**
 * Render one canonical row model → a `<div>` row element. `onClick(jobId)` is
 * wired to a click on the row.
 */
export function renderJobRow(m, { doc = document, onClick } = {}) {
  const row = doc.createElement('div')
  row.dataset.jobId = m.jobId
  row.style.cssText =
    `display:flex;align-items:center;gap:6px;padding:4px 6px;cursor:pointer;border-radius:4px;` +
    `font-size:11px;${m.indentPx ? `padding-left:${m.indentPx}px;` : ''}` +
    `${m.selected ? 'background:#2a3a4a;' : ''}`
  const badge = statusBadge(m.statusKey)

  const idx = doc.createElement('span')
  idx.textContent = m.indexLabel
  idx.style.cssText = `flex-shrink:0;color:${m.colors.dim};font-family:var(--font-mono)`

  const label = doc.createElement('span')
  label.style.cssText = 'flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap'
  label.textContent = m.label
  if (m.title) row.title = m.title

  const ts = doc.createElement('span')
  ts.textContent = m.timeStr
  ts.style.cssText = `flex-shrink:0;color:${m.colors.dim};font-size:10px;font-family:var(--font-mono)`

  const size = doc.createElement('span')
  size.textContent = m.sizeStr
  size.style.cssText = `flex-shrink:0;color:${m.archived ? m.colors.warn : m.colors.dim};font-size:10px;font-family:var(--font-mono)`
  if (m.archived) size.title = `Archived → ${m.archivePath}`

  // Status symbol: animated spinner while active, else the badge shape.
  const sym = m.isActive
    ? makeSpinner(badge.color, 10, doc)
    : Object.assign(doc.createElement('span'), { textContent: badge.symbol })
  sym.style.flexShrink = '0'
  sym.title = badge.label
  if (!m.isActive) sym.style.color = badge.color

  row.append(idx)
  for (const t of m.tags) {
    const tag = Object.assign(doc.createElement('span'), { textContent: t.text })
    tag.style.cssText = `flex-shrink:0;color:${t.color};font-family:var(--font-mono);font-weight:600`
    if (t.title) tag.title = t.title
    row.append(tag)
  }
  row.append(label, ts, size)
  if (m.archived) {
    const box = Object.assign(doc.createElement('span'), { textContent: '📦' })
    box.style.cssText = 'flex-shrink:0;font-size:10px'
    box.title = `Archived → ${m.archivePath}`
    row.append(box)
  }
  if (m.stale) {
    const warn = Object.assign(doc.createElement('span'), { textContent: '⚠' })
    if (m.staleClass) warn.className = m.staleClass
    warn.style.cssText = `flex-shrink:0;color:${m.colors.warn};font-size:11px`
    warn.title = m.staleTitle
    row.append(warn)
  }
  row.append(sym)
  if (onClick) row.addEventListener('click', () => onClick(m.jobId))
  return row
}

/**
 * Render a full list model into `listEl`. Empty → a dim placeholder; otherwise
 * one row per model + (once) a status legend inserted after the list.
 * `legendState` (an object `{ el:null }`) memoizes the legend element so it is
 * built once and not re-created every render.
 */
export function renderJobList(listEl, model, {
  doc = document, onClick, emptyText = 'No jobs yet.',
  dimColor = '#8a8a8a', legendState = null,
} = {}) {
  if (!listEl) return
  if (model.empty) {
    listEl.innerHTML = `<div style="color:${dimColor};padding:6px 4px;font-size:11px">${emptyText}</div>`
    return
  }
  listEl.innerHTML = ''
  for (const rm of model.rows) listEl.appendChild(renderJobRow(rm, { doc, onClick }))
  if (legendState && !legendState.el) {
    legendState.el = makeStatusLegend(doc)
    listEl.after(legendState.el)
  }
}
