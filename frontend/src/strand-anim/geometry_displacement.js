/**
 * Toehold-mediated strand displacement (TMSD) geometry.
 *
 * Three strands:
 *   - SUBSTRATE — the template spine, fully duplexed over its whole length
 *     (N bp = toehold t + branch-migration domain m). Always present.
 *   - INVADER — complementary to the whole substrate (N bases). Bound over the
 *     toehold + the already-displaced region [0, p); its un-bound leading tail
 *     dangles from the branch point.
 *   - INCUMBENT — complementary to the branch domain only (m bases). Bound over
 *     the not-yet-displaced region [p, N); its displaced tail dangles.
 *
 * Reaction coordinate φ = FRACTION OF THE INVADER BOUND ∈ [0,1], so the single
 * sweep covers the WHOLE process: the invader's binding front advances over all
 * N bp = first ZIPPING THE TOEHOLD [0,t) (φ ∈ [0, t/N]), then BRANCH-MIGRATING
 * to displace the incumbent [t,N) (φ ∈ [t/N, 1]).
 *   φ = 0   → invader unbound (free tail), substrate toehold exposed ss,
 *             incumbent fully bound.
 *   φ = t/N → toehold fully hybridized (the classic initial toehold complex).
 *   φ = 1   → invader fully bound; incumbent released.
 * Binding front b = round(φ·N). The substrate toehold region between the front
 * and t carries no partner → it reads as the exposed ss toehold.
 *
 * The duplex (substrate + bound partner) is built with the SAME NADOC
 * conventions as geometry_helical.js (150° minor groove, base_normal = chord,
 * axis_tangent = helix axis; or a flat ladder when form='straight'). The two
 * free ssDNA tails splay up from the branch point in a Λ (invader up-right,
 * toward where it will bind; incumbent up-left, the released segment). The
 * helix phase is anchored at the branch point so the tails always peel up
 * cleanly — the consequence is the duplex rotating as the branch migrates.
 * Per-base melt (melt.js) smooths bound↔free at the branch point.
 *
 * Emits the shared strand-list contract { strands:[{pos,tan,bn,role}], meta }.
 * DISPLAY-ONLY — no Design, no topology, no backend.
 */

import { nucsPerStrand } from './geometry_straight.js'
import { meltFraction, lerp } from './melt.js'

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v))
const MINOR_GROOVE_RAD = (150.0 * Math.PI) / 180

// Blend one base between a bound candidate (H / Ht / Hbn) and a free-tail
// candidate (A / At / Abn) by melt weight w, writing into pos/tan/bn at offset o.
function blendInto(pos, tan, bn, o, H, Ht, Hbn, A, At, Abn, w) {
  pos[o] = lerp(H[0], A[0], w); pos[o + 1] = lerp(H[1], A[1], w); pos[o + 2] = lerp(H[2], A[2], w)
  let tx = lerp(Ht[0], At[0], w), ty = lerp(Ht[1], At[1], w), tz = lerp(Ht[2], At[2], w)
  const tl = Math.hypot(tx, ty, tz) || 1
  tan[o] = tx / tl; tan[o + 1] = ty / tl; tan[o + 2] = tz / tl
  let bx = lerp(Hbn[0], Abn[0], w), by = lerp(Hbn[1], Abn[1], w), bz = lerp(Hbn[2], Abn[2], w)
  const bl = Math.hypot(bx, by, bz) || 1
  bn[o] = bx / bl; bn[o + 1] = by / bl; bn[o + 2] = bz / bl
}

export function buildDisplacementGeometry(params, phi) {
  const N = nucsPerStrand(params.N)
  const t = clamp(Math.round(params.toeholdBp ?? 0), 0, N - 1)  // toehold length
  const m = N - t                                                // branch domain
  const rise = params.rise
  const R = params.W * 0.5
  const theta = (params.thetaDeg * Math.PI) / 180
  const twist = ((params.twistDeg ?? 34.3) * Math.PI) / 180
  const ssStretch = params.armPull
  const meltBp = params.meltBp ?? 0
  const helical = params.form === 'helical'

  // φ now drives the invader binding front over the WHOLE substrate (N bp), so
  // the single sweep is: zip the toehold [0,t) FIRST, then branch-migrate [t,N).
  const fd = clamp(phi, 0, 1)
  const bIdx = fd * N                              // continuous binding front
  const b = clamp(Math.round(bIdx), 0, N)          // invader-bound bp
  const toeBound = Math.min(b, t)                  // toehold bp hybridized
  const displaced = Math.max(0, b - t)             // incumbent bp displaced
  const armStep = rise * ssStretch
  const cosT = Math.cos(theta), sinT = Math.sin(theta)
  const anchorAngle = (Math.PI - MINOR_GROOVE_RAD) / 2

  // Partner(top) angle, anchored at the binding front so the partner is "up"
  // there → tails peel up cleanly; the duplex rotates as the front advances.
  const partnerAngle = (i) => (i - bIdx) * twist + anchorAngle

  // Duplex backbone at bp i: substrate (bottom) + bound partner (top), with
  // NADOC base-normal (chord) and axis_tangent (+X).
  function duplexAt(i) {
    const x = i * rise
    if (!helical) {
      return { par: [x, R, 0], sub: [x, -R, 0], parBn: [0, -1, 0], subBn: [0, 1, 0] }
    }
    const ap = partnerAngle(i), as = ap + MINOR_GROOVE_RAD
    const par = [x, R * Math.cos(ap), R * Math.sin(ap)]
    const sub = [x, R * Math.cos(as), R * Math.sin(as)]
    let by = sub[1] - par[1], bz = sub[2] - par[2]
    const bl = Math.hypot(by, bz) || 1; by /= bl; bz /= bl
    return { par, sub, parBn: [0, by, bz], subBn: [0, -by, -bz] }
  }

  // Fork origin = partner position at the (continuous) binding front.
  const xBr = bIdx * rise
  const Obr = helical
    ? [xBr, R * Math.cos(anchorAngle), R * Math.sin(anchorAngle)]
    : [xBr, R, 0]

  // ── substrate: the spine, N beads. The toehold region [b,t) carries NO
  //    partner (invader hasn't reached it, incumbent only covers [t,N)) → it
  //    reads as the exposed ss toehold before/while the invader zips on. ──
  const subPos = new Float32Array(N * 3), subTan = new Float32Array(N * 3), subBn = new Float32Array(N * 3)
  for (let i = 0; i < N; i++) {
    const o = i * 3, D = duplexAt(i)
    subPos[o] = D.sub[0]; subPos[o + 1] = D.sub[1]; subPos[o + 2] = D.sub[2]
    subTan[o] = 1; subTan[o + 1] = 0; subTan[o + 2] = 0
    subBn[o] = D.subBn[0]; subBn[o + 1] = D.subBn[1]; subBn[o + 2] = D.subBn[2]
  }

  // ── invader: bp [0,b) bound (toehold first, then displaced region),
  //    [b,N) free leading tail (up-right). Front advances 0→N over the sweep. ──
  const invPos = new Float32Array(N * 3), invTan = new Float32Array(N * 3), invBn = new Float32Array(N * 3)
  for (let k = 0; k < N; k++) {
    const o = k * 3, D = duplexAt(k)
    const w = meltFraction(k, bIdx, meltBp)        // 0 bound (k<front), 1 free (k>front)
    const s = (k - bIdx) * armStep
    blendInto(invPos, invTan, invBn, o,
      D.par, [1, 0, 0], D.parBn,
      [Obr[0] + s * cosT, Obr[1] + s * sinT, Obr[2]], [cosT, sinT, 0], [sinT, -cosT, 0], w)
  }

  // ── incumbent: bead j ↔ bp (t+j). Bound while the front is in the toehold;
  //    once the front passes t, the displaced bp [t,b) peel off as a tail
  //    (up-left). ──
  const incPos = new Float32Array(m * 3), incTan = new Float32Array(m * 3), incBn = new Float32Array(m * 3)
  for (let j = 0; j < m; j++) {
    const o = j * 3, bp = t + j, D = duplexAt(bp)
    // free when bp < front → mirror of meltFraction about the front index
    const w = meltFraction(2 * bIdx - bp, bIdx, meltBp)
    const s = (bIdx - bp) * armStep
    blendInto(incPos, incTan, incBn, o,
      D.par, [1, 0, 0], D.parBn,
      [Obr[0] - s * cosT, Obr[1] + s * sinT, Obr[2]], [-cosT, sinT, 0], [sinT, cosT, 0], w)
  }

  return {
    strands: [
      { pos: subPos, tan: subTan, bn: subBn, role: 'substrate' },
      { pos: invPos, tan: invTan, bn: invBn, role: 'invader' },
      { pos: incPos, tan: incTan, bn: incBn, role: 'incumbent' },
    ],
    meta: {
      N, t, m, b, toeBound, displaced,
      readout: `toehold ${toeBound}/${t} bp   displaced ${displaced}/${m} bp   front x = ${xBr.toFixed(2)} nm`,
    },
  }
}
