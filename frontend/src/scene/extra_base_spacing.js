/**
 * Extra-base lattice spacing — the MD-measured interhelical distance a design
 * actually relaxes to, as a function of how many bases its crossovers carry.
 *
 * Pure lookup + design query.  No THREE, no store, no DOM: the display side
 * lives in `expanded_spacing.js`, which owns the offset channel.
 *
 * ── Where the numbers come from ────────────────────────────────────────────
 * Measured 2026-08-05 from archived unrestrained NAMD production trajectories
 * of two matched-control series — designs identical apart from the inserted
 * bases (24hb: 24 helices / 384 crossovers, 338 carrying T or TT; 6hbx100:
 * 6 helices / 66 crossovers, 60 carrying them).  Mean nearest-neighbour C1'
 * centroid distance, measured per axial slab against the duplex core only
 * (inserts excluded from the centroids so they cannot drag it), end slabs
 * dropped, on the matched MGHH-only stage:
 *
 *      extra bases │ 6hbx100 │  24hb  │  Δ vs 0
 *      ────────────┼─────────┼────────┼─────────
 *           0      │  24.02  │ 23.58  │    —
 *           1 (T)  │  24.95  │ 24.14  │  +0.93 / +0.56
 *           2 (TT) │  25.34  │ 24.32  │  +1.32 / +0.74
 *
 * The response is strongly SUB-LINEAR — a second inserted base adds roughly a
 * third of what the first one does, because the slack absorbs into the loop
 * conformation rather than pushing the helices apart.  Do not extrapolate
 * linearly past 2; `spacingForExtraBases` clamps instead (see below).
 *
 * The 0-base row is the other half of the story and the reason this is a
 * spacing TABLE and not a delta: even with no inserts at all, a relaxed bundle
 * sits ~2 Å wider than the 2.25 nm caDNAno lattice the design is built on.
 * That baseline offset is larger than the extra-base effect itself.
 */

/** caDNAno lattice pitch the design is built on — honeycomb and square alike. */
export const NATURAL_SPACING_NM = 2.25

/**
 * MD-relaxed centre-to-centre spacing, indexed by extra bases per crossover.
 * Index 0 is the no-insert baseline; see the header for provenance.
 */
export const RELAXED_SPACING_NM = [2.45, 2.53, 2.55]

/**
 * Relaxed spacing for `n` extra bases per crossover.
 *
 * Counts above the measured range clamp to the last entry rather than
 * extrapolating: the trend is saturating, so a linear continuation would
 * overstate a 3- or 4-base insert badly.
 *
 * @param {number} n  extra bases per crossover (the design's maximum)
 * @returns {number}  centre-to-centre spacing in nm
 */
export function spacingForExtraBases(n) {
  if (!Number.isFinite(n) || n <= 0) return RELAXED_SPACING_NM[0]
  const i = Math.min(Math.floor(n), RELAXED_SPACING_NM.length - 1)
  return RELAXED_SPACING_NM[i]
}

/**
 * Largest extra-base count on any crossover in the design.
 *
 * A design mixing 1- and 2-base crossovers is adjusted as if every crossover
 * carried 2: the lattice is one rigid frame, so the widest junction sets the
 * pitch the whole bundle has to accommodate.
 *
 * `extra_bases` is a STRING on the wire ("T", "TT") and its length is the
 * count; a falsy value means a plain crossover.  `forced_ligations` carry the
 * same field and are counted too — `crossover_connections.js` already draws
 * them through the same path.
 *
 * @param {object} design  Design model
 * @returns {number}  0 when nothing carries inserts
 */
export function maxExtraBaseCount(design) {
  let max = 0
  for (const list of [design?.crossovers, design?.forced_ligations]) {
    if (!Array.isArray(list)) continue
    for (const xo of list) {
      const n = xo?.extra_bases?.length ?? 0
      if (n > max) max = n
    }
  }
  return max
}

/**
 * Target spacing for a design under the "adjust for extra bases" view.
 *
 * @param {object} design  Design model
 * @returns {number}  centre-to-centre spacing in nm
 */
export function adjustedSpacingForDesign(design) {
  return spacingForExtraBases(maxExtraBaseCount(design))
}
