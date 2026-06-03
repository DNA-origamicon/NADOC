/**
 * Color helpers extracted from main.js. Pure (Math only). Unit-tested in
 * color_util.test.js.
 */

// Strand-length heatmap domain (nt): clamps below 14 / above 60.
const HEATMAP_MIN = 14, HEATMAP_MAX = 60

/** Map an nt count to a blue→red heatmap colour (packed 0xRRGGBB int). */
export function heatmapHex(ntCount) {
  const t = Math.max(0, Math.min(1, (ntCount - HEATMAP_MIN) / (HEATMAP_MAX - HEATMAP_MIN)))
  const hue = Math.round(240 * (1 - t))
  // HSL → hex
  const s = 0.9, l = 0.5
  const k = n => (n + hue / 30) % 12
  const a = s * Math.min(l, 1 - l)
  const ch = n => Math.round((l - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1)))) * 255)
  return (ch(0) << 16) | (ch(8) << 8) | ch(4)
}
