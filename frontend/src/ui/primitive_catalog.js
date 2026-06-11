/**
 * DNA-origami primitive catalog — the pre-validated building blocks the
 * "Add Primitive" tool offers in the right-sidebar Primitives panel.
 *
 * Pure data + pure render helpers ONLY (no DOM, no store). The stateful panel
 * that lists these lives in `primitive_library.js`. Keep this file the single
 * source of truth for "what primitives exist"; growing the library = adding an
 * entry here, not touching the panel.
 *
 * Each entry:
 *   id          stable key (used for selection + future instantiation)
 *   name        full human name
 *   shortName   compact badge (e.g. "6HB")
 *   description 3–6 word blurb shown under the name
 *   lattice     'HONEYCOMB' | 'SQUARE'
 *   helixCount  cross-section helix count (drives the schematic thumbnail)
 */

/** @typedef {{id:string,name:string,shortName:string,description:string,lattice:string,helixCount:number}} Primitive */

/** @type {Primitive[]} */
export const PRIMITIVES = [
  {
    id: 'beam_6hb',
    name: '6-Helix Bundle',
    shortName: '6HB',
    description: 'Rigid honeycomb six-helix beam',
    lattice: 'HONEYCOMB',
    helixCount: 6,
  },
  {
    id: 'beam_18hb',
    name: '18-Helix Bundle',
    shortName: '18HB',
    description: 'Stiff eighteen-helix honeycomb beam',
    lattice: 'HONEYCOMB',
    helixCount: 18,
  },
]

/** Look up a primitive by id. Returns null if unknown. */
export function getPrimitive(id) {
  return PRIMITIVES.find((p) => p.id === id) ?? null
}

/** Short meta line, e.g. "Honeycomb · 6 helices". */
export function primitiveMeta(p) {
  const lat =
    p.lattice === 'HONEYCOMB' ? 'Honeycomb' : p.lattice === 'SQUARE' ? 'Square' : p.lattice
  return `${lat} · ${p.helixCount} helices`
}

/**
 * Inline SVG schematic of the bundle cross-section — `helixCount` circles in a
 * hex-offset grid. A lightweight stand-in for a real rendered thumbnail until
 * we have art; purely cosmetic, no exact lattice geometry implied.
 * @param {number} helixCount
 * @param {{size?:number}} [opts]
 * @returns {string} self-contained <svg> string
 */
export function primitiveThumbSvg(helixCount, { size = 48 } = {}) {
  const n = Math.max(1, helixCount | 0)
  const cols = Math.ceil(Math.sqrt(n))
  const r = 0.42 // circle radius in cell units
  const dx = 1.0 // horizontal cell spacing
  const dy = 0.88 // rows packed slightly closer (hex feel)

  const pts = []
  for (let i = 0; i < n; i++) {
    const row = Math.floor(i / cols)
    const col = i % cols
    const offset = (row % 2) * 0.5 // honeycomb half-step on odd rows
    pts.push([col * dx + offset, row * dy])
  }

  const xs = pts.map((p) => p[0])
  const ys = pts.map((p) => p[1])
  const minX = Math.min(...xs) - r
  const minY = Math.min(...ys) - r
  const w = Math.max(...xs) + r - minX
  const h = Math.max(...ys) + r - minY

  const circles = pts
    .map(
      ([x, y]) =>
        `<circle cx="${(x - minX).toFixed(3)}" cy="${(y - minY).toFixed(3)}" r="${r}" ` +
        `fill="#1f6feb" fill-opacity="0.28" stroke="#58a6ff" stroke-width="0.07"/>`,
    )
    .join('')

  return (
    `<svg viewBox="0 0 ${w.toFixed(3)} ${h.toFixed(3)}" width="${size}" height="${size}" ` +
    `preserveAspectRatio="xMidYMid meet" xmlns="http://www.w3.org/2000/svg">${circles}</svg>`
  )
}
