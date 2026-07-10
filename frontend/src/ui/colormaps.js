/**
 * Shared colormap registry for every scalar-coloured simulation output (oxDNA /
 * MD flexibility-RMSF maps, deviation maps, CanDo RMSF / deviation / cylinder heat
 * maps).  ONE source of truth so the on-structure colours, the legend gradient, and
 * the colormap-picker swatches can never drift apart.
 *
 * Each colormap is a short list of RGB anchor stops (0-255); `colormapHex` /
 * `colormapRGB` piecewise-linearly interpolate a t∈[0,1] across them.  Display-state
 * only — nothing here touches topology.
 *
 * Pure module (no DOM) apart from the tiny localStorage persistence helpers, which
 * fail closed so unit tests / SSR never throw.
 */

// Anchor stops (0-255).  Perceptual maps (viridis…cividis) sampled from matplotlib;
// turbo from Google's Turbo; jet kept as the simplified 5-stop ramp the CanDo
// cylinders already drew with (so the shared registry doesn't shift existing tubes);
// devramp is the green→amber→red "deviation" ramp; gray avoids pure black so dark
// beads stay visible.
export const COLORMAPS = {
  viridis:  { label: 'Viridis',   lut: [[68, 1, 84], [59, 82, 139], [33, 144, 140], [93, 201, 99], [253, 231, 37]] },
  magma:    { label: 'Magma',     lut: [[0, 0, 4], [81, 18, 124], [183, 55, 121], [252, 137, 97], [252, 253, 191]] },
  plasma:   { label: 'Plasma',    lut: [[13, 8, 135], [126, 3, 168], [204, 71, 120], [248, 149, 64], [240, 249, 33]] },
  inferno:  { label: 'Inferno',   lut: [[0, 0, 4], [87, 16, 110], [188, 55, 84], [249, 142, 8], [252, 255, 164]] },
  cividis:  { label: 'Cividis',   lut: [[0, 32, 76], [0, 66, 89], [122, 122, 120], [187, 177, 101], [255, 234, 70]] },
  turbo:    { label: 'Turbo',     lut: [[48, 18, 59], [50, 102, 229], [26, 199, 194], [132, 228, 72], [236, 203, 40], [241, 96, 26], [122, 4, 3]] },
  jet:      { label: 'Jet',       lut: [[0, 0, 255], [0, 255, 255], [0, 255, 0], [255, 255, 0], [255, 0, 0]] },
  coolwarm: { label: 'Cool–Warm', lut: [[59, 76, 192], [144, 178, 254], [221, 221, 221], [246, 158, 131], [180, 4, 38]] },
  devramp:  { label: 'Green→Red', lut: [[63, 185, 80], [210, 153, 34], [248, 81, 73]] },
  gray:     { label: 'Grayscale', lut: [[30, 30, 30], [240, 240, 240]] },
}

/** Ordered [{ name, label }] for the picker popup (registry order). */
export const COLORMAP_LIST = Object.keys(COLORMAPS).map((name) => ({ name, label: COLORMAPS[name].label }))

/** Per map-type default colormap (each map keeps its "respective colours"). */
export const DEFAULT_COLORMAP_FOR = { flex: 'viridis', deviation: 'devramp', cando: 'jet' }

/** Pure: resolve a colormap name to a valid registry key (falls back to viridis). */
export function normalizeColormap(name) {
  return Object.prototype.hasOwnProperty.call(COLORMAPS, name) ? name : 'viridis'
}

/** Pure: default colormap for a map-type (flex/deviation/cando), viridis otherwise. */
export function defaultColormapFor(mapType) {
  return DEFAULT_COLORMAP_FOR[mapType] || 'viridis'
}

/** Pure: [r,g,b] (0-255, rounded) for colormap `name` at t∈[0,1] (clamped). */
export function colormapRGB255(name, t) {
  const lut = (COLORMAPS[normalizeColormap(name)]).lut
  const x = Math.max(0, Math.min(1, Number.isFinite(t) ? t : 0))
  const seg = x * (lut.length - 1)
  const i = Math.min(lut.length - 2, Math.floor(seg))
  const f = seg - i
  const a = lut[i], b = lut[i + 1]
  return [
    Math.round(a[0] + (b[0] - a[0]) * f),
    Math.round(a[1] + (b[1] - a[1]) * f),
    Math.round(a[2] + (b[2] - a[2]) * f),
  ]
}

/** Pure: 0xRRGGBB int for colormap `name` at t∈[0,1]. */
export function colormapHex(name, t) {
  const [r, g, b] = colormapRGB255(name, t)
  return (r << 16) | (g << 8) | b
}

/** Pure: [r,g,b] floats in 0..1 (for InstancedMesh / vertex colours). */
export function colormapRGB(name, t) {
  const [r, g, b] = colormapRGB255(name, t)
  return [r / 255, g / 255, b / 255]
}

/** Pure: sample a colormap into a CSS linear-gradient (t=0 at the given start edge). */
export function colormapGradientCss(name, { stops = 8, dir = 'to top' } = {}) {
  const parts = []
  for (let i = 0; i < stops; i++) {
    const h = (colormapHex(name, i / (stops - 1)) >>> 0) & 0xffffff
    parts.push('#' + h.toString(16).padStart(6, '0'))
  }
  return `linear-gradient(${dir}, ${parts.join(', ')})`
}

// ── Per map-type persistence (remember the user's pick for each map) ─────────────
const _KEY = (mapType) => `nadoc:flexscale-cmap:${mapType || 'flex'}`

/** Load the remembered colormap for a map-type, or its default.  Fails closed. */
export function loadColormap(mapType) {
  try {
    const v = window?.localStorage?.getItem(_KEY(mapType))
    if (v && Object.prototype.hasOwnProperty.call(COLORMAPS, v)) return v
  } catch { /* no storage (tests / SSR) */ }
  return defaultColormapFor(mapType)
}

/** Persist the colormap pick for a map-type.  Fails closed. */
export function saveColormap(mapType, name) {
  try { window?.localStorage?.setItem(_KEY(mapType), normalizeColormap(name)) } catch { /* ignore */ }
}
