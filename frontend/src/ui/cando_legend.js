/**
 * Floating colour-ramp legend for the CanDo FEM colour-mapped displays.
 *
 * Pinned to the middle-right of the 3D workspace — the SAME slot as the oxDNA
 * flexibility (RMSF) scale (`#flex-scale`) — so every colour-mapped output in the
 * app reads its legend from one place.  Shown only while a CanDo Flexibility (RMSF)
 * or Deviation-from-design map is active; the other CanDo modes (predicted shape,
 * CanDo cylinders) are not colour-mapped, so the legend stays hidden for them.
 *
 * Display-state only.  The ramps are sampled from cando_display's own viridis /
 * green→red hex ramps, so the legend can never drift from the on-structure colours.
 *
 * Factory: initCandoLegend() → { show(mode, min, max), hide(), isVisible() }.
 */

import { viridisHex, deviationHex } from './cando_display.js'
import { jetRGB, JET_BRIGHTNESS } from '../scene/cando_cylinders.js'

/** viridis / green→red come from cando_display; the CanDo-cylinder RMSF heat map uses
 *  the scene overlay's jet ramp, dimmed by the SAME brightness the tubes are drawn with,
 *  so the legend can't drift from the on-structure colours. */
function jetHex(t) {
  const [r, g, b] = jetRGB(t)
  const q = (c) => Math.round(Math.max(0, Math.min(1, c * JET_BRIGHTNESS)) * 255)
  return (q(r) << 16) | (q(g) << 8) | q(b)
}

/** Pure: (min, max) → two fixed-decimal label strings ('—' when non-finite). */
export function legendLabels(min, max, decimals = 2) {
  const f = (v) => (Number.isFinite(v) ? v.toFixed(decimals) : '—')
  return { min: f(min), max: f(max) }
}

/** Pure: sample a hex-ramp fn (t∈[0,1]) into a bottom→top CSS linear-gradient
 *  (t=0 at the bottom of the bar, t=1 at the top). */
export function gradientCss(hexFn, stops = 6) {
  const parts = []
  for (let i = 0; i < stops; i++) {
    const h = (hexFn(i / (stops - 1)) >>> 0) & 0xffffff
    parts.push('#' + h.toString(16).padStart(6, '0'))
  }
  return `linear-gradient(to top, ${parts.join(', ')})`
}

const _MODES = {
  flex:      { title: 'RMSF (nm)',      hexFn: viridisHex },
  deviation: { title: 'Deviation (nm)', hexFn: deviationHex },
  // The CanDo-cylinder output is an RMSF heat map on the jet ramp (bluest = min →
  // reddest = 95th percentile, clamped above) — same ramp as the tubes.
  cando:     { title: 'RMSF (nm)',      hexFn: jetHex },
}

/** Pure: a display mode → { title, gradient }, or null when the mode is not a
 *  colour-mapped one (off / deform → no legend). */
export function legendConfig(mode) {
  const m = _MODES[mode]
  return m ? { title: m.title, gradient: gradientCss(m.hexFn) } : null
}

export function initCandoLegend() {
  const root = document.getElementById('cando-legend')
  const titleEl = document.getElementById('cando-legend-title')
  const barEl = document.getElementById('cando-legend-bar')
  const maxEl = document.getElementById('cando-legend-max')
  const minEl = document.getElementById('cando-legend-min')
  if (!root) return { show: () => {}, hide: () => {}, isVisible: () => false }

  function show(mode, min, max) {
    const cfg = legendConfig(mode)
    if (!cfg) { hide(); return }
    if (titleEl) titleEl.textContent = cfg.title
    if (barEl) barEl.style.background = cfg.gradient
    const { min: lo, max: hi } = legendLabels(min, max)
    if (maxEl) maxEl.textContent = hi
    if (minEl) minEl.textContent = lo
    root.style.display = 'block'
  }
  function hide() { root.style.display = 'none' }

  return { show, hide, isVisible: () => root.style.display !== 'none' }
}
