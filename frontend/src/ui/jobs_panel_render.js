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
export function renderJobRow(m, { doc = document, onClick, onAction, onChevron,
  onContextMenu } = {}) {
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

  const info = doc.createElement('span')
  info.style.cssText = 'display:block;flex:1;min-width:0;overflow:hidden;white-space:nowrap'
  const infoTrack = doc.createElement('span')
  infoTrack.style.cssText = 'display:inline-flex;align-items:center;gap:6px;white-space:nowrap'

  const label = doc.createElement('span')
  label.style.cssText = m.compactColumns
    ? 'flex-shrink:0;white-space:nowrap'
    : 'flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap'
  label.textContent = m.label
  if (m.title) row.title = m.title

  const ts = doc.createElement('span')
  ts.textContent = m.timeStr
  ts.style.cssText = `flex-shrink:0;color:${m.colors.dim};font-size:10px;font-family:var(--font-mono)`

  const size = doc.createElement('span')
  size.textContent = m.sizeStr
  size.style.cssText = `flex-shrink:0;color:${m.archived ? m.colors.warn : m.colors.dim};font-size:10px;font-family:var(--font-mono)`
  if (m.archived) size.title = `Archived → ${m.archivePath}`

  // Status symbol: an explicit override (e.g. NAMD's ⧗ remote-queued hourglass) wins;
  // else an animated spinner while active, else the badge shape.
  let sym
  if (m.symbolOverride) {
    sym = Object.assign(doc.createElement('span'), { textContent: m.symbolOverride.glyph })
    sym.style.flexShrink = '0'
    if (m.symbolOverride.color) sym.style.color = m.symbolOverride.color
    sym.title = m.symbolOverride.title || ''
    if (m.symbolOverride.dataset) {
      for (const [k, v] of Object.entries(m.symbolOverride.dataset)) sym.dataset[k] = v
    }
  } else {
    sym = m.isActive
      ? makeSpinner(badge.color, 10, doc)
      : Object.assign(doc.createElement('span'), { textContent: badge.symbol })
    sym.style.flexShrink = '0'
    sym.title = badge.label
    if (!m.isActive) sym.style.color = badge.color
  }

  // Optional leading expand/collapse chevron (NAMD tree): every row gets the span
  // (empty spacer for leaves) so indentation lines up; parents get the ▸/▾ toggle.
  if (m.chevron) {
    const chev = doc.createElement('span')
    chev.style.cssText = `flex-shrink:0;width:10px;font-size:9px;color:${m.colors.dim};cursor:pointer;user-select:none`
    if (m.chevron.childCount > 0) {
      chev.textContent = m.chevron.collapsed ? '▸' : '▾'
      chev.title = m.chevron.title
      chev.addEventListener('click', (e) => { e.stopPropagation(); onChevron?.(m.jobId) })
    }
    row.append(chev)
  }
  row.append(idx)
  for (const t of m.tags) {
    const tag = Object.assign(doc.createElement('span'), { textContent: t.text })
    tag.style.cssText = `flex-shrink:0;color:${t.color};font-family:var(--font-mono);font-weight:600`
    if (t.title) tag.title = t.title
    row.append(tag)
  }
  const infoTarget = m.compactColumns ? infoTrack : row
  infoTarget.append(label)
  // Optional post-label markers (NAMD's collapsed-ensemble summary + CG-seed / Alpine
  // badges) sit between the label and the timestamp. Empty for oxDNA/mrDNA/cando/lammps.
  for (const pm of m.postLabelMarkers) {
    const s = Object.assign(doc.createElement('span'), { textContent: pm.text })
    if (pm.css) s.style.cssText = pm.css
    if (pm.title) s.title = pm.title
    infoTarget.append(s)
  }
  infoTarget.append(ts, size)
  if (m.compactColumns) {
    info.append(infoTrack)
    row.append(info)
  }

  // Archive and status are stable columns: every row reserves the same space even
  // when it is not archived or active. This stops the important state glyphs from
  // wandering as variable-width job information changes.
  if (!m.compactColumns && m.archived) {
    const box = Object.assign(doc.createElement('span'), { textContent: '📦' })
    box.style.cssText = 'flex-shrink:0;font-size:10px'
    box.title = `Archived → ${m.archivePath}`
    row.append(box)
  }
  const warningCol = m.compactColumns ? doc.createElement('span') : row
  if (m.compactColumns) warningCol.style.cssText = 'flex:0 0 12px;width:12px;text-align:center'
  if (m.stale) {
    const warn = Object.assign(doc.createElement('span'), { textContent: '⚠' })
    if (m.staleClass) warn.className = m.staleClass
    warn.style.cssText = `flex-shrink:0;color:${m.colors.warn};font-size:11px`
    warn.title = m.staleTitle
    warningCol.append(warn)
  }
  if (m.compactColumns) row.append(warningCol)
  if (m.compactColumns) {
    const box = Object.assign(doc.createElement('span'), { textContent: m.archived ? '📦' : '' })
    box.style.cssText = 'flex:0 0 10px;width:10px;text-align:center;font-size:10px'
    box.setAttribute('aria-label', m.archived ? 'Archived' : 'Not archived')
    if (m.archived) box.title = `Archived → ${m.archivePath}`
    row.append(box)

    const statusCol = doc.createElement('span')
    statusCol.style.cssText = 'display:flex;align-items:center;justify-content:center;flex:0 0 14px;width:14px'
    statusCol.append(sym)
    row.append(statusCol)
  } else {
    row.append(sym)
  }
  // Optional trailing per-row control (e.g. LAMMPS Stop). Absent for oxDNA/mrDNA/
  // cando (m.action === null) → nothing appended, so their DOM is unchanged.
  if (m.action) {
    const btn = doc.createElement('button')
    btn.textContent = m.action.text
    if (m.action.title) btn.title = m.action.title
    btn.style.cssText = m.action.styleText || ''
    btn.addEventListener('click', (e) => { e.stopPropagation(); onAction?.(m.jobId) })
    row.append(btn)
  }
  if (onClick) row.addEventListener('click', () => onClick(m.jobId))
  // A clipped information strip makes one smooth side-to-side pass on hover, then
  // returns to its starting point on leave. No animation is started when it fits.
  let hoverAnimation = null
  row.addEventListener('mouseenter', () => {
    if (!m.compactColumns) return
    const overflow = Math.max(0, infoTrack.scrollWidth - info.clientWidth)
    if (overflow <= 0 || typeof infoTrack.animate !== 'function') return
    hoverAnimation?.cancel()
    hoverAnimation = infoTrack.animate(
      [{ transform: 'translateX(0)' }, { transform: `translateX(-${overflow}px)` }],
      { duration: Math.max(700, overflow * 18), easing: 'linear', fill: 'forwards' },
    )
  })
  row.addEventListener('mouseleave', () => {
    if (!m.compactColumns) return
    hoverAnimation?.cancel()
    hoverAnimation = null
    infoTrack.style.transform = ''
  })
  // Opt-in per-panel right-click. The HANDLER calls preventDefault, not this: the unified
  // Simulate list mixes engines and only offers a menu on some of them, so suppressing the
  // browser's here would leave the rest with no menu at all.
  if (onContextMenu) row.addEventListener('contextmenu', (e) => onContextMenu(m.jobId, e))
  return row
}

/**
 * Render a full list model into `listEl`. Empty → a dim placeholder; otherwise
 * one row per model + (once) a status legend inserted after the list.
 * `legendState` (an object `{ el:null }`) memoizes the legend element so it is
 * built once and not re-created every render.
 */
export function renderJobList(listEl, model, {
  doc = document, onClick, onAction, onChevron, onContextMenu, emptyText = 'No jobs yet.',
  dimColor = '#8a8a8a', legendState = null,
} = {}) {
  if (!listEl) return
  if (model.empty) {
    listEl.innerHTML = `<div style="color:${dimColor};padding:6px 4px;font-size:11px">${emptyText}</div>`
    return
  }
  listEl.innerHTML = ''
  for (const rm of model.rows) {
    listEl.appendChild(renderJobRow(rm, { doc, onClick, onAction, onChevron, onContextMenu }))
  }
  if (legendState && !legendState.el) {
    legendState.el = makeStatusLegend(doc)
    listEl.after(legendState.el)
  }
}
