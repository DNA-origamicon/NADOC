// cpd_geometry.js — reaction coordinates for a designed extra-base UV weld.
//
// At an antiparallel reciprocal crossover pair carrying extra bases, the inserted
// thymines are the intended UV point-weld partners.  Two numbers say how close that pair
// is to the [2+2] cycloaddition geometry:
//
//   dMid — distance between the two C5=C6 BOND MIDPOINTS.  (The KIMMDY expression
//          0.5*((C5b-C5a) + (C6b-C6a)) simplifies to exactly that.)  Note this is NOT
//          the C5-C5 distance; when one base is flipped the two differ substantially.
//   eta  — the dihedral C5a-C6a-C6b-C5b: the twist between the two C5=C6 double bonds.
//
// k is the KIMMDY geometric propensity in [0,1], 1.0 at the product geometry.  It is a
// weighting factor, not an Arrhenius rate.  D0 = 0.157 nm is a cyclobutane C-C bond —
// the product — which a classical force field cannot reach; the sampled range bottoms
// out at van der Waals contact, ~0.34 nm.
//
// THIS COMPUTES FROM THE COORDINATES ALREADY ON SCREEN.  The MD display affine is handed
// over rather than re-derived (see memory/project_md_viz_tools.md), so a second
// coordinate pipeline would draw the markers off the atoms.  The backend sends only atom
// SERIALS (GET /api/md/jobs/{id}/cpd-pairs); positions come from the rendered frame.
//
// Mirrored by backend/core/cpd_metrics.py.  Both are pinned to
// tests/fixtures/cpd_reference_cases.json — change one without the other and the tests
// go red rather than putting a different number on screen than in the analysis.
//
// All positions are in NANOMETRES.

/** KIMMDY geometric rate parameters (kimmdy-dimerization schema, GPL-3.0). */
export const K1 = 2.017017017017017 // 1/nm
export const K2 = 0.03003003003003003 // 1/deg
export const D0 = 0.157177 // nm  — product midpoint distance
export const N0 = 16.743651884789273 // deg — product dihedral

/** Pair is "in contact" for display purposes below this [nm]. */
export const REACTIVE_D_NM = 0.45
/** Angular tolerance of the reactive corner [deg]. */
export const REACTIVE_ETA_DEG = 45
/** vdW contact — the floor a classical force field can sample [nm]. */
export const VDW_FLOOR_NM = 0.34

const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]]
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
const cross = (a, b) => [
  a[1] * b[2] - a[2] * b[1],
  a[2] * b[0] - a[0] * b[2],
  a[0] * b[1] - a[1] * b[0],
]
const norm = (a) => Math.sqrt(dot(a, a))

/**
 * |eta - N0| taken the short way round the circle.
 * PURE.  The upstream KIMMDY model uses a plain abs(eta - N0), which at eta = -175 deg
 * returns 191.7 where the true separation is 168.3 — underestimating k ~2x.  Not inherited.
 */
export function angularSeparationDeg (etaDeg) {
  const d = Math.abs(etaDeg - N0)
  return Math.min(d, 360 - d)
}

/** KIMMDY geometric propensity in [0,1]. PURE. */
export function kimmdyRate (dNm, etaDeg) {
  return Math.exp(-(K1 * Math.abs(dNm - D0) + K2 * angularSeparationDeg(etaDeg)))
}

/** Signed dihedral p0-p1-p2-p3 in degrees. PURE. */
export function dihedralDeg (p0, p1, p2, p3) {
  const b0 = sub(p0, p1)
  const b1 = sub(p2, p1)
  const b2 = sub(p3, p2)
  const len = norm(b1)
  if (len === 0) return 0
  const b1n = [b1[0] / len, b1[1] / len, b1[2] / len]
  const vd = dot(b0, b1n)
  const wd = dot(b2, b1n)
  const v = [b0[0] - vd * b1n[0], b0[1] - vd * b1n[1], b0[2] - vd * b1n[2]]
  const w = [b2[0] - wd * b1n[0], b2[1] - wd * b1n[1], b2[2] - wd * b1n[2]]
  return (Math.atan2(dot(cross(b1n, v), w), dot(v, w)) * 180) / Math.PI
}

/** Midpoint of a C5=C6 bond — the site dMid is measured between. PURE. */
export function bondMidpoint (c5, c6) {
  return [(c5[0] + c6[0]) / 2, (c5[1] + c6[1]) / 2, (c5[2] + c6[2]) / 2]
}

/**
 * Full weld geometry from four carbon positions (nm).
 * PURE.  → { dNm, etaDeg, k, reactive, midA, midB }
 */
export function weldGeometry (c5a, c6a, c5b, c6b) {
  const midA = bondMidpoint(c5a, c6a)
  const midB = bondMidpoint(c5b, c6b)
  const dNm = norm(sub(midB, midA))
  const etaDeg = dihedralDeg(c5a, c6a, c6b, c5b)
  return {
    dNm,
    etaDeg,
    k: kimmdyRate(dNm, etaDeg),
    reactive: dNm < REACTIVE_D_NM && angularSeparationDeg(etaDeg) < REACTIVE_ETA_DEG,
    midA,
    midB,
  }
}

/**
 * Read one atom's xyz out of a serial-indexed flat position array.
 * PURE.  Returns null when the serial is outside the array — an unresolved pair must
 * degrade to "not drawable", never to NaN geometry rendered as a marker at the origin.
 */
export function readSerial (positions, serial) {
  if (!positions || !Number.isInteger(serial) || serial < 0) return null
  const i = serial * 3
  if (i + 2 >= positions.length) return null
  const x = positions[i]; const y = positions[i + 1]; const z = positions[i + 2]
  if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(z)) return null
  return [x, y, z]
}

/**
 * Weld geometry for one pair descriptor against a rendered frame.
 * PURE.  `pair` is a /cpd-pairs entry ({ c5_a, c6_a, c5_b, c6_b, ... }); `positions` is
 * the serial-indexed flat array the atomistic display already holds.
 * Returns null if the pair is unresolved or any atom is missing from this frame.
 */
export function readWeldGeometry (pair, positions) {
  return readWeldGeometryFrom(pair, (s) => readSerial(positions, s))
}

/**
 * Weld geometry from an arbitrary position resolver.
 * PURE.  `getPos(serial)` must return [x,y,z] in nm, or null/undefined if that atom is
 * not currently placed.  This is the form the renderer hook uses: it hands over the SAME
 * lerp that positions the atom instances, so the markers cannot drift off the atoms.
 * Returns null if the pair is unresolved or any of the four atoms is unavailable.
 */
export function readWeldGeometryFrom (pair, getPos) {
  if (!pair || pair.serials_resolved === false || typeof getPos !== 'function') return null
  const c5a = getPos(pair.c5_a)
  const c6a = getPos(pair.c6_a)
  const c5b = getPos(pair.c5_b)
  const c6b = getPos(pair.c6_b)
  if (!c5a || !c6a || !c5b || !c6b) return null
  if (![...c5a, ...c6a, ...c5b, ...c6b].every(Number.isFinite)) return null
  return { id: pair.id, label: pair.label, ...weldGeometry(c5a, c6a, c5b, c6b) }
}

/**
 * Colour for a weld marker from its propensity: red (far) → amber → green (reactive).
 * PURE.  Returns a 0xRRGGBB integer so callers can hand it straight to three.js.
 */
export function weldColor (k) {
  const t = Math.max(0, Math.min(1, k))
  // red (0.85,0.15,0.15) → amber (0.95,0.65,0.10) at t=0.5 → green (0.15,0.80,0.30)
  const lerp = (a, b, u) => a + (b - a) * u
  let r, g, b
  if (t < 0.5) {
    const u = t / 0.5
    r = lerp(0.85, 0.95, u); g = lerp(0.15, 0.65, u); b = lerp(0.15, 0.10, u)
  } else {
    const u = (t - 0.5) / 0.5
    r = lerp(0.95, 0.15, u); g = lerp(0.65, 0.80, u); b = lerp(0.10, 0.30, u)
  }
  const q = (v) => Math.round(Math.max(0, Math.min(1, v)) * 255)
  return (q(r) << 16) | (q(g) << 8) | q(b)
}

/** One-line readout for the HUD. PURE. */
export function formatWeldReadout (geom) {
  if (!geom) return 'weld: —'
  const ang = Math.round(geom.etaDeg)
  return `d ${(geom.dNm * 10).toFixed(2)} Å   η ${ang >= 0 ? '+' : ''}${ang}°   `
    + `k ${geom.k.toFixed(3)}${geom.reactive ? '  ⚡ reactive' : ''}`
}
