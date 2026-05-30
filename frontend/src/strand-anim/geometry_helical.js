/**
 * Helical double-helix un/zipping geometry.
 *
 * The HYBRIDIZED region is a real B-DNA double helix, built with the SAME
 * conventions as the rest of NADOC (backend/core/geometry.py nucleotide_positions):
 *   - backbones on the helix at HELIX_RADIUS (= W/2), forward at angle
 *     phase + bp·twist, reverse offset by the MINOR GROOVE (150°);
 *   - base-slab "base_normal" = the cross-strand chord normalize(rev−fwd)
 *     (negated on the reverse strand), NOT a radial-to-axis vector;
 *   - base-slab "axis_tangent" = the helix axis direction, shared by both
 *     strands, NOT the local backbone spiral tangent.
 * So a base-pair slab here is oriented exactly as `slabQuaternion(base_normal,
 * axis_tangent)` produces it in scene/helix_renderer.js.
 *
 * The UNZIPPING region stays straight — the freed single strands keep a fixed
 * pull direction (strand A up +Y, strand B down −Y, at splay half-angle θ) and
 * do NOT spiral. As φ drops, the helix shrinks from the fork end and the
 * straight splayed arms grow. (Freed bases are ssDNA, which NADOC renders as
 * arcs rather than slabs; here we keep a slab per freed base to show the
 * exposed base, oriented ⟂ to the strand.)
 *
 * Phase is anchored at the FORK (not the fixed end), at anchorAngle =
 * (π − groove)/2, so the fork base pair straddles the pull plane symmetrically
 * (forward up, reverse down, base-pair vector vertical, both at equal depth).
 * The freed strands therefore peel cleanly without crossing, and the
 * consequence — the far/closed end rotates as φ changes — is the hybridized
 * helix "twisting" as the ends are pulled apart. jIdx is continuous so the spin
 * is smooth during playback.
 *
 * Emits the SAME per-nucleotide output contract (posX/tanX/bnX, 3·N each) as the
 * straight-line form, so the ball-and-slab renderer in app.js is shared.
 *
 * DISPLAY-ONLY — no Design, no topology, no backend.
 */

import { nucsPerStrand } from './geometry_straight.js'
import { meltFraction, lerp } from './melt.js'

export { nucsPerStrand }

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v))

// B-DNA minor groove — matches backend/core/constants.py BDNA_MINOR_GROOVE_ANGLE_DEG.
const MINOR_GROOVE_RAD = (150.0 * Math.PI) / 180

/**
 * @param {object} params - see params.js DEFAULTS (uses twistDeg; R = W/2)
 * @param {number} phi
 * @returns {{
 *   posA:Float32Array, tanA:Float32Array, bnA:Float32Array,
 *   posB:Float32Array, tanB:Float32Array, bnB:Float32Array,
 *   meta:{ N:number, nPaired:number, nOpen:number, xJ:number, L:number }
 * }}
 */
export function buildHelicalGeometry(params, phi) {
  const N = nucsPerStrand(params.N)
  const rise = params.rise
  const R = params.W * 0.5                    // helix radius (backbone-to-axis)
  const theta = (params.thetaDeg * Math.PI) / 180
  const twist = ((params.twistDeg ?? 34.3) * Math.PI) / 180
  const ssStretch = params.armPull
  const endFrom = params.endFrom === 'left' ? 'left' : 'right'

  const f = clamp(phi, 0, 1)
  const L = (N - 1) * rise
  const nPaired = clamp(Math.round(f * N), 0, N)
  const nOpen = N - nPaired
  const beadSpacing = L / N
  const xJ = N > 1 ? (nPaired / N) * L : 0
  const armStep = rise * ssStretch
  const cosT = Math.cos(theta)
  const sinT = Math.sin(theta)

  // Fork-anchored, continuous phase. anchorAngle straddles the pull plane so
  // the fork base pair is vertical (fwd up, rev down) and the freed strands
  // peel cleanly; the far end then rotates with f → the helix twists.
  const jIdx = f * N - 1
  const anchorAngle = (Math.PI - MINOR_GROOVE_RAD) / 2
  const meltBp = params.meltBp ?? 0

  const posA = new Float32Array(N * 3), tanA = new Float32Array(N * 3), bnA = new Float32Array(N * 3)
  const posB = new Float32Array(N * 3), tanB = new Float32Array(N * 3), bnB = new Float32Array(N * 3)

  // Arm origin = where the strands leave the helix at the fork (continuous in φ).
  const xFork = (jIdx + 0.5) * beadSpacing
  const afFork = anchorAngle, arFork = anchorAngle + MINOR_GROOVE_RAD
  const oAy = R * Math.cos(afFork), oAz = R * Math.sin(afFork)   // strand A (up)
  const oBy = R * Math.cos(arFork), oBz = R * Math.sin(arFork)   // strand B (down)

  // Each base blends from its helical placement H to its straight-arm placement
  // A over `meltBp` bp around the fork, instead of snapping at the integer step.
  function blend(out, o, Hx, Hy, Hz, Htx, Hty, Htz, Hbx, Hby, Hbz,
                 Ax, Ay, Az, Atx, Aty, Hb_armx, Hb_army, w) {
    out.pos[o] = lerp(Hx, Ax, w); out.pos[o + 1] = lerp(Hy, Ay, w); out.pos[o + 2] = lerp(Hz, Az, w)
    let tx = lerp(Htx, Atx, w), ty = lerp(Hty, Aty, w), tz = lerp(Htz, 0, w)
    const tl = Math.hypot(tx, ty, tz) || 1
    out.tan[o] = tx / tl; out.tan[o + 1] = ty / tl; out.tan[o + 2] = tz / tl
    let bx = lerp(Hbx, Hb_armx, w), by = lerp(Hby, Hb_army, w), bz = lerp(Hbz, 0, w)
    const bl = Math.hypot(bx, by, bz) || 1
    out.bn[o] = bx / bl; out.bn[o + 1] = by / bl; out.bn[o + 2] = bz / bl
  }

  for (let i = 0; i < N; i++) {
    const o = i * 3
    const w = meltFraction(i, jIdx, meltBp)

    // Helical placement (paired): both strands, axis_tangent = +X.
    const af = (i - jIdx) * twist + anchorAngle, ar = af + MINOR_GROOVE_RAD
    const xH = (i + 0.5) * beadSpacing
    const fy = R * Math.cos(af), fz = R * Math.sin(af)
    const ry = R * Math.cos(ar), rz = R * Math.sin(ar)
    let cy = ry - fy, cz = rz - fz                 // base_normal chord (rev − fwd)
    const cl = Math.hypot(cy, cz) || 1; cy /= cl; cz /= cl

    // Arm placement (unzipped): arc length past the fork from the fork origin.
    const s = (i - jIdx) * armStep
    const xA = xFork + s * cosT

    // forward / strand A (pull up): arm dir (cosT,+sinT,0), arm bn (sinT,−cosT,0)
    blend({ pos: posA, tan: tanA, bn: bnA }, o,
      xH, fy, fz, 1, 0, 0, 0, cy, cz,
      xA, oAy + s * sinT, oAz, cosT, sinT, sinT, -cosT, w)
    // reverse / strand B (pull down): arm dir (cosT,−sinT,0), arm bn (sinT,+cosT,0)
    blend({ pos: posB, tan: tanB, bn: bnB }, o,
      xH, ry, rz, 1, 0, 0, 0, -cy, -cz,
      xA, oBy - s * sinT, oBz, cosT, -sinT, sinT, cosT, w)
  }

  // endFrom='left' → mirror horizontally so unzipping starts at the low-X end.
  if (endFrom === 'left') {
    for (const arr of [posA, posB]) for (let i = 0; i < N; i++) arr[i * 3] = L - arr[i * 3]
    for (const arr of [tanA, tanB, bnA, bnB]) for (let i = 0; i < N; i++) arr[i * 3] = -arr[i * 3]
  }

  return {
    strands: [
      { pos: posA, tan: tanA, bn: bnA, role: 'A' },
      { pos: posB, tan: tanB, bn: bnB, role: 'B' },
    ],
    meta: {
      N, nPaired, nOpen, xJ, L,
      readout: `paired = ${nPaired} bp   open = ${nOpen} bp   junction x = ${xJ.toFixed(2)} nm`,
    },
  }
}
