/**
 * Color helpers extracted from main.js. Pure (Math only). Unit-tested in
 * color_util.test.js.
 */

// Strand-length heatmap domain (nt): clamps below 14 / above 60.
const HEATMAP_MIN = 14, HEATMAP_MAX = 60

/**
 * Packed 0xRRGGBB int → '#rrggbb' string. Masks to 24 bits so negatives /
 * over-range ints (e.g. signed colours) still produce a 6-digit hex.
 * (Deduped from two inline copies in main.js.)
 */
export function hexFromInt(value) {
  return '#' + ((value >>> 0) & 0xffffff).toString(16).padStart(6, '0')
}

// Per-base atom colours (A=green, T=red, G=yellow, C=blue), packed 0xRRGGBB.
export const BASE_HEX = { A: 0x44dd88, T: 0xff5555, G: 0xffcc00, C: 0x55aaff }

/**
 * Build the per-atom base-letter colour map keyed "strand_id:bp_index:direction".
 * `nucLetter` is the iterable of [nuc, baseLetter] pairs from buildNucLetterMap.
 * Pure — the store/geometry read stays in the caller.
 */
export function atomColorsFromLetters(nucLetter) {
  const out = new Map()
  for (const [nuc, ch] of (nucLetter ?? [])) {
    out.set(`${nuc.strand_id}:${nuc.bp_index}:${nuc.direction}`, BASE_HEX[ch])
  }
  return out
}

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
