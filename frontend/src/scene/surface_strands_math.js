/**
 * Surface capture-strand placement math (oxDNA immobilization feature) — PURE.
 *
 * The "Hard surface" card can disperse ssDNA capture strands (complementary to the
 * origami overhangs) across a coverage patch so the origami hybridizes and immobilizes.
 * This module turns the user's coverage spec (shape / size / density / seed / offset)
 * into a deterministic set of in-plane (u,v) placement points, plus a normalized spec.
 *
 * DECISION-FREE by design (Phase 1): no DNA topology / geometry decisions live here —
 * only 2D placement in the surface plane and count-from-density. The 3D lift (mapping
 * (u,v) → world via the surface normal basis) and the actual nucleotide build are Phase 2.
 *
 * The PRNG is mulberry32 specifically so the eventual Python backend generator can
 * re-implement it verbatim: the same seed reproduces the identical dispersion, which is
 * the whole point of the user-facing "seed" field.
 */

export const NM2_PER_UM2 = 1e6

// B-form seed geometry — MUST match backend/physics/oxdna_surface_strands.py (the locked
// B-DNA constants) so the preview shows exactly what the build seeds.
export const BFORM_RISE_NM = 0.334                 // BDNA_RISE_PER_BP
export const BFORM_TWIST_RAD = 34.3 * Math.PI / 180 // BDNA_TWIST_PER_BP_RAD
export const BFORM_RADIUS_NM = 1.0                 // HELIX_RADIUS
const BFORM_PHASE0 = Math.PI / 2 + BFORM_TWIST_RAD / 2   // native HC FORWARD phase

/**
 * Local bead offsets for one B-form capture strand standing along the surface normal,
 * as {axial, du, dv} in nm: axial = distance up the normal, (du,dv) = in-plane radial
 * offset (the helix backbone at radius 1 nm).  Bead 0 is at the plane.  The caller maps
 * to world: bead = anchor + axial·dHat + du·u + dv·v.  Both attach ends occupy the same
 * physical stack (only which end is pinned differs), so this is orientation-agnostic.
 */
export function captureStrandLocalBeads(nBeads) {
  const n = Math.max(0, nBeads | 0)
  const out = []
  for (let m = 0; m < n; m++) {
    const fa = BFORM_PHASE0 + m * BFORM_TWIST_RAD
    out.push({ axial: m * BFORM_RISE_NM, du: BFORM_RADIUS_NM * Math.cos(fa), dv: BFORM_RADIUS_NM * Math.sin(fa) })
  }
  return out
}

// Minimum centre-to-centre spacing between capture strands (nm). Baked into placement
// so a dense patch can't overlap strands; the density target is capped by this. A user
// decision (Phase 2), not a physical constant.
export const MIN_SPACING_NM = 2

// Default coverage extent (nm): circle DIAMETER / square WIDTH. ~100 nm ≈ an origami
// footprint's worth of surface.
export const DEFAULT_COVERAGE_NM = 100

const VALID_SHAPES = new Set(['circle', 'square'])
const VALID_ENDS = new Set(["5'", "3'"])

/** Deterministic PRNG in [0,1). Portable (mulberry32) so JS and a future Python
 *  generator agree bit-for-bit given the same 32-bit seed. */
export function mulberry32(seed) {
  let a = (Number(seed) >>> 0)
  return function () {
    a |= 0; a = (a + 0x6D2B79F5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

/** Keep only A/C/G/T (upper-cased). Empty string if nothing valid. */
export function sanitizeSequence(seq) {
  return String(seq || '').toUpperCase().replace(/[^ACGT]/g, '')
}

/** Coverage-patch area in nm². `sizeNm` is the circle DIAMETER / square WIDTH.
 *  Circle: π·(d/2)²; square: side². 0 for a bad size. */
export function surfaceStrandArea({ shape, sizeNm } = {}) {
  const s = Number(sizeNm)
  if (!(s > 0)) return 0
  if (shape === 'square') return s * s
  const r = s / 2
  return Math.PI * r * r
}

/** Expected strand count = round(density[/µm²] · area[nm²] / 1e6). 0 if either ≤ 0. */
export function surfaceStrandCount({ shape, sizeNm, densityPerUm2 } = {}) {
  const area = surfaceStrandArea({ shape, sizeNm })
  const d = Number(densityPerUm2)
  if (!(area > 0) || !(d > 0)) return 0
  return Math.round((d * area) / NM2_PER_UM2)
}

/**
 * Deterministic in-plane placement points {x,y} in nm, centred on (offsetXNm, offsetYNm).
 * `sizeNm` is the circle DIAMETER / square WIDTH.
 *   circle → area-uniform polar sampling (r = (d/2)·√U, θ = 2πU)
 *   square → uniform in [-side/2, side/2]²
 * A `minSpacingNm` minimum centre-to-centre distance is enforced by rejection: the
 * target count is best-effort — if the patch saturates before the count is reached
 * (density too high for the area), fewer points are returned. Deterministic given seed.
 * `count` overrides the density-derived count (for previews / tests). Returns [] when
 * there is nothing to place.
 */
export function surfaceStrandPlacements({
  shape, sizeNm, densityPerUm2, seed,
  offsetXNm = 0, offsetYNm = 0, count = null, minSpacingNm = MIN_SPACING_NM,
} = {}) {
  const target = count == null ? surfaceStrandCount({ shape, sizeNm, densityPerUm2 }) : Math.max(0, count | 0)
  const s = Number(sizeNm)
  if (!(target > 0) || !(s > 0)) return []
  const cx = Number(offsetXNm) || 0
  const cy = Number(offsetYNm) || 0
  const half = s / 2
  const min2 = Math.max(0, Number(minSpacingNm) || 0) ** 2
  const rnd = mulberry32(seed)
  const placed = []   // {u,v} in patch-local coords
  const MAX_CONSEC = 80   // consecutive rejections ⇒ patch is saturated, stop
  let consec = 0
  while (placed.length < target && consec < MAX_CONSEC) {
    let u, v
    if (shape === 'square') {
      u = (rnd() - 0.5) * s
      v = (rnd() - 0.5) * s
    } else {
      const r = half * Math.sqrt(rnd())
      const th = 2 * Math.PI * rnd()
      u = r * Math.cos(th)
      v = r * Math.sin(th)
    }
    let ok = true
    if (min2 > 0) {
      for (const p of placed) {
        const dx = p.u - u, dy = p.v - v
        if (dx * dx + dy * dy < min2) { ok = false; break }
      }
    }
    if (!ok) { consec++; continue }
    consec = 0
    placed.push({ u, v })
  }
  return placed.map(p => ({ x: p.u + cx, y: p.v + cy }))
}

// Capture nucleotides keyed above any real origami bp_index so their base-pair slab
// bucket never collides with an origami nucleotide (which would draw a bogus slab).
const _CAP_BP_BASE = 1_000_000

function _unit(x, y, z) {
  const n = Math.hypot(x, y, z) || 1
  return [x / n, y / n, z / n]
}

/**
 * Convert world-nm strand bead lists into plain nucleotide dicts the CG renderer consumes —
 * so capture strands render natively in every rep (beads/slab/cylinders/hull) and move with
 * `applyFemPositions`.  Synthetic `cap<i>` helix/strand ids (no `__` prefix → not filtered),
 * unique high bp_index, FORWARD-only (ssDNA → no paired slabs).
 *
 * Each bead is EITHER `{p:[x,y,z], a1:[…], a3:[…]}` (frame supplied — B-form base plate for
 * a preview, chain-tangent for a relaxed strand) OR a bare `[x,y,z]` (frame derived from the
 * chain). a1 = base_normal (backbone→base; drives slab orientation), a3 = axis_tangent.
 */
export function captureNucleotidesFromChains(chains) {
  const out = []
  if (!Array.isArray(chains)) return out
  for (let si = 0; si < chains.length; si++) {
    const beads = chains[si]
    if (!beads || beads.length === 0) continue
    const L = beads.length
    for (let k = 0; k < L; k++) {
      const bd = beads[k]
      const framed = bd && !Array.isArray(bd)
      const p = framed ? bd.p : bd
      let a1, a3
      if (framed && bd.a1 && bd.a3) {
        a1 = bd.a1; a3 = bd.a3
      } else {
        const ref = (framed ? (beads[k + 1]?.p || beads[k - 1]?.p) : (beads[k + 1] || beads[k - 1])) || p
        let tx = ref[0] - p[0], ty = ref[1] - p[1], tz = ref[2] - p[2]
        if (k === L - 1 && L > 1) { tx = -tx; ty = -ty; tz = -tz }
        a3 = _unit(tx, ty, tz)
        const rz = Math.abs(a3[2]) > 0.9 ? 0 : 1, rx = Math.abs(a3[2]) > 0.9 ? 1 : 0
        a1 = _unit(a3[1] * rz, a3[2] * rx - a3[0] * rz, -a3[1] * rx)
      }
      out.push({
        helix_id: 'cap' + si, strand_id: 'cap' + si,
        bp_index: _CAP_BP_BASE + si * 1000 + k, direction: 'FORWARD',
        backbone_position: [p[0], p[1], p[2]],
        base_normal: [a1[0], a1[1], a1[2]], axis_tangent: [a3[0], a3[1], a3[2]],
        is_five_prime: k === 0, is_three_prime: k === L - 1,
      })
    }
  }
  return out
}

/**
 * Normalize raw UI fields into a clean capture-strand spec, or null when disabled.
 * Clamps/validates every field and attaches the derived `count`. `subjectToField`
 * defaults to true (strands feel the E-field unless the user unticks it).
 */
export function surfaceStrandsSpec(raw = {}) {
  if (!raw || !raw.enabled) return null
  const shape = VALID_SHAPES.has(raw.shape) ? raw.shape : 'circle'
  const attachEnd = VALID_ENDS.has(raw.attachEnd) ? raw.attachEnd : "5'"
  const sizeNm = Math.max(0, Number(raw.sizeNm) || 0)
  const densityPerUm2 = Math.max(0, Number(raw.densityPerUm2) || 0)
  const spec = {
    enabled: true,
    sequence: sanitizeSequence(raw.sequence),
    attachEnd,
    shape,
    sizeNm,
    densityPerUm2,
    offsetXNm: Number(raw.offsetXNm) || 0,
    offsetYNm: Number(raw.offsetYNm) || 0,
    seed: (Number(raw.seed) >>> 0),
    subjectToField: raw.subjectToField !== false,
  }
  spec.count = surfaceStrandCount(spec)
  return spec
}
