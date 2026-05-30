/**
 * Straight-line "ladder + traveling fork" geometry for the strand-animation
 * playground, in the ball-and-slab representation. DISPLAY-ONLY — no Design,
 * no topology, no backend.
 *
 * Reaction coordinate φ ∈ [0,1] = fraction of base pairs still HYBRIDIZED.
 *   φ = 1 → fully paired duplex (closed ladder of base-pair slabs, no fork)
 *   φ = 0 → fully unzipped (both strands forked to full length, bases splayed)
 *
 * The duplex lies in the XY plane at Z = 0, axis along +X. Every nucleotide is
 * emitted with a backbone position (the "ball"), a unit base-normal `bn`
 * (cross-strand direction the base "slab" points toward) and a unit tangent
 * along the strand. Two paired backbones run parallel at y = ±W/2; their slabs
 * point inward and nearly meet to read as a base pair. As φ drops, a fork
 * junction at xJ = (nPaired/N)·L travels along the axis and the freed strands
 * splay apart — one pulled UP (+Y), one pulled DOWN (−Y).
 *
 * Beads sit on a fixed lattice in the zipped region (spacing L/N, independent
 * of φ), so the junction sweeps PAST beads rather than sliding them around.
 * Every nucleotide always exists (N per strand) — only its rail-vs-arm role
 * changes with φ — so the instanced bead/slab counts are constant for a given N.
 */

import { meltFraction, lerp } from './melt.js'

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v))

/**
 * Number of nucleotides per strand (= constant instanced bead/slab count per
 * strand). Beads/slabs are reallocated only when N changes.
 * @param {number} N
 */
export function nucsPerStrand(N) { return Math.max(2, Math.round(N)) }

/**
 * Build per-nucleotide ball-and-slab data for a given parameter set and φ.
 *
 * @param {object} params - see params.js DEFAULTS
 * @param {number} phi    - reaction coordinate [0,1]
 * @returns {{
 *   posA:Float32Array, tanA:Float32Array, bnA:Float32Array,   // strand A (up),   3·N each
 *   posB:Float32Array, tanB:Float32Array, bnB:Float32Array,   // strand B (down), 3·N each
 *   meta:{ N:number, nPaired:number, nOpen:number, xJ:number, L:number }
 * }}
 */
export function buildStraightLineGeometry(params, phi) {
  const N = nucsPerStrand(params.N)
  const rise = params.rise
  const W = params.W
  const theta = (params.thetaDeg * Math.PI) / 180
  const ssStretch = params.armPull          // contour scale of freed ssDNA arms
  const forkToCenter = !!params.forkToCenter
  const endFrom = params.endFrom === 'left' ? 'left' : 'right'

  const f = clamp(phi, 0, 1)
  const L = (N - 1) * rise                   // full duplex contour length

  const nPaired = clamp(Math.round(f * N), 0, N)
  const nOpen = N - nPaired

  const xJ = N > 1 ? (nPaired / N) * L : 0    // fork junction X (nominal, for readout)
  const beadSpacing = L / N                   // fixed lattice in the zipped region
  const armStep = rise * ssStretch
  const cos = Math.cos(theta)
  const sin = Math.sin(theta)

  // Continuous fork index + melt width: each base eases from rail to arm over
  // `meltBp` bp centered on the fork, instead of snapping at the integer step.
  const jIdx = f * N - 1
  const xFork = (jIdx + 0.5) * beadSpacing
  const meltBp = params.meltBp ?? 0

  // Build one strand. sign = +1 → strand A (splays UP), −1 → strand B (DOWN).
  function buildStrand(sign) {
    const pos = new Float32Array(N * 3)
    const tan = new Float32Array(N * 3)
    const bn = new Float32Array(N * 3)
    const yRail = sign * W * 0.5
    const armOriginY = forkToCenter ? 0 : yRail
    const dirx = cos, diry = sign * sin            // arm direction
    const abx = sin, aby = -sign * cos             // arm base-slab ⟂, toward centerline

    for (let i = 0; i < N; i++) {
      const w = meltFraction(i, jIdx, meltBp)
      // paired (rail) candidate H
      const hx = (i + 0.5) * beadSpacing, hy = yRail
      // unzipped (arm) candidate A — arc length past the fork, continuous in φ
      const s = (i - jIdx) * armStep
      const ax = xFork + s * dirx, ay = armOriginY + s * diry
      // blend
      const px = lerp(hx, ax, w), py = lerp(hy, ay, w)
      let tx = lerp(1, dirx, w), ty = lerp(0, diry, w)
      const tl = Math.hypot(tx, ty) || 1; tx /= tl; ty /= tl
      let bx = lerp(0, abx, w), by = lerp(-sign, aby, w)
      const bl = Math.hypot(bx, by) || 1; bx /= bl; by /= bl
      const o = i * 3
      pos[o] = px; pos[o + 1] = py; pos[o + 2] = 0
      tan[o] = tx; tan[o + 1] = ty; tan[o + 2] = 0
      bn[o] = bx; bn[o + 1] = by; bn[o + 2] = 0
    }
    return { pos, tan, bn }
  }

  const A = buildStrand(+1)
  const B = buildStrand(-1)

  // endFrom='left' → mirror horizontally so unzipping starts at the low-X end.
  if (endFrom === 'left') {
    for (const s of [A, B]) {
      for (let i = 0; i < N; i++) {
        const o = i * 3
        s.pos[o] = L - s.pos[o]
        s.tan[o] = -s.tan[o]
        s.bn[o] = -s.bn[o]
      }
    }
  }

  return {
    strands: [
      { pos: A.pos, tan: A.tan, bn: A.bn, role: 'A' },
      { pos: B.pos, tan: B.tan, bn: B.bn, role: 'B' },
    ],
    meta: {
      N, nPaired, nOpen, xJ, L,
      readout: `paired = ${nPaired} bp   open = ${nOpen} bp   junction x = ${xJ.toFixed(2)} nm`,
    },
  }
}
