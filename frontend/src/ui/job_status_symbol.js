/**
 * Shared status symbol + legend for the oxDNA and MD job lists (and the animation
 * trajectory dropdown). Each status maps to a distinct SHAPE + colour so a list row
 * reads at a glance, with a legend explaining the key.
 *
 * Pure (no DOM imports beyond the optional legend builder), so the key→badge
 * mapping is unit-testable and shared verbatim across both engines.
 */

const C = {
  green: '#5cb85c', blue: '#4a9eff', cyan: '#39c5cf',
  amber: '#e0a800', red: '#d9534f', grey: '#8a8a8a',
}

// status key → { symbol, color, label }. Active states (running/preparing) render
// as an animated spinner in the row; their badge here is the legend fallback glyph.
export const STATUS_BADGE = {
  'running':           { symbol: '⟳', color: C.amber, label: 'Running' },
  'preparing':         { symbol: '⟳', color: C.amber, label: 'Preparing' },
  'queued':            { symbol: '○', color: C.grey,  label: 'Queued' },
  'completed':         { symbol: '◆', color: C.cyan,  label: 'Completed' },
  'production-ready':  { symbol: '▲', color: C.green, label: 'Production ready' },
  'production-done':   { symbol: '■', color: C.blue,  label: 'Production done' },
  'production-failed': { symbol: '✕', color: C.red,   label: 'Production failed' },
  'paused':            { symbol: '⏸', color: C.amber, label: 'Paused' },
  'stopped':           { symbol: '◼', color: C.grey,  label: 'Stopped' },
  'failed':            { symbol: '✕', color: C.red,   label: 'Failed' },
  'unknown':           { symbol: '·', color: C.grey,  label: 'Unknown' },
}

/** Badge ({symbol,color,label}) for a status key (falls back to 'unknown'). */
export function statusBadge(key) {
  return STATUS_BADGE[key] || STATUS_BADGE.unknown
}

/** A spinning circular activity indicator (CSS class .nadoc-spinner). Shared by
 *  every job list for the "active" row glyph. */
export function makeSpinner(color = 'currentColor', size = 11, doc = document) {
  const s = doc.createElement('span')
  s.className = 'nadoc-spinner'
  s.style.width = s.style.height = `${size}px`
  if (color) s.style.color = color
  s.setAttribute('aria-hidden', 'true')
  return s
}

/**
 * Normalize an engine + raw job status (+ oxDNA production state) to a badge key.
 * ``prodState`` is oxDNA's productionState(job) ('none'|'running'|'done'|'failed');
 * MD callers omit it. Production distinctions only apply to oxDNA.
 */
export function statusKeyFor(engine, status, prodState = null) {
  if (engine === 'oxdna') {
    if (status === 'completed' && prodState === 'none') return 'production-ready'
    if (prodState === 'done')   return 'production-done'
    if (prodState === 'failed') return 'production-failed'
  }
  switch (status) {
    case 'completed': return 'completed'
    case 'running':   return 'running'
    case 'preparing': return 'preparing'
    case 'queued':    return 'queued'
    case 'paused':    return 'paused'
    case 'stopped':   return 'stopped'
    case 'failed':    return 'failed'
    default:          return 'unknown'
  }
}

// Curated, ordered legend (the keys that actually appear on rows).
export const JOB_STATUS_LEGEND = [
  'running', 'queued', 'completed', 'production-ready',
  'production-done', 'failed', 'stopped', 'paused',
].map(k => STATUS_BADGE[k])

/**
 * Build a compact wrapped legend element (symbol + label pairs). Stateless DOM —
 * call once and insert under a job list.
 */
export function makeStatusLegend(doc = document) {
  const wrap = doc.createElement('div')
  wrap.style.cssText =
    'display:flex;flex-wrap:wrap;gap:6px 10px;padding:5px 4px 2px;' +
    'font-size:10px;color:#8a8a8a;line-height:1.4'
  for (const b of JOB_STATUS_LEGEND) {
    const item = doc.createElement('span')
    item.style.cssText = 'display:inline-flex;align-items:center;gap:3px;white-space:nowrap'
    const sym = doc.createElement('span')
    sym.textContent = b.symbol
    sym.style.cssText = `color:${b.color};font-size:11px`
    const txt = doc.createElement('span')
    txt.textContent = b.label
    item.append(sym, txt)
    wrap.appendChild(item)
  }
  return wrap
}
