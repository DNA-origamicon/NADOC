/**
 * Smooth "melt" of a base from its paired placement (helix / rail) to its
 * unzipped placement (straight arm), so a base eases out of the duplex over a
 * few bp instead of snapping when the fork passes it.
 *
 * Shared by both the straight-line and helical forms: each computes a paired
 * candidate H and an arm candidate A per base, then lerps by meltFraction().
 */

const clamp01 = (v) => Math.max(0, Math.min(1, v))

/** Hermite smoothstep on [0,1]. */
export function smoothstep(t) {
  t = clamp01(t)
  return t * t * (3 - 2 * t)
}

/**
 * Melt fraction for base `i` (0 = fully paired, 1 = fully unzipped), smoothed
 * over `meltBp` base pairs centered on the continuous fork index `jIdx`.
 * Higher i opens first (the un-mirrored 'right' frame). meltBp ≤ 0 → hard step
 * (the old sudden transition).
 */
export function meltFraction(i, jIdx, meltBp) {
  if (meltBp <= 1e-6) return i > jIdx ? 1 : 0
  return smoothstep((i - jIdx) / meltBp + 0.5)
}

/** Scalar lerp. */
export function lerp(a, b, t) { return a + (b - a) * t }
