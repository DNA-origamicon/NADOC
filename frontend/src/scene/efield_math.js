/**
 * Electric-field setup math (pure) — the automatable core of the oxDNA E-field
 * feature.  No THREE, no DOM, no store: every export is a plain input→output
 * function so it can be unit-tested directly (see efield_math.test.js).
 *
 * Physics recap (full rationale in memory/project_oxdna_efield.md):
 *  - oxDNA has no native E-field force; a uniform field becomes an equal constant
 *    `string` force on every nucleotide.  We store the FORCE PER NUCLEOTIDE in pN
 *    as the canonical value (honest about what oxDNA applies); a V/m helper fills
 *    it via an editable effective-charge constant.
 *  - 1 oxDNA force unit ≈ 48.63 pN.
 *  - F = q_eff · e · E  (q_eff ≈ 0.25 e/phosphate after Manning condensation).
 *
 * Three-Layer Law: this is all display/Physical-layer setup — nothing here mutates
 * topology.
 */

// ── Physical constants ──────────────────────────────────────────────────────
export const OXDNA_FORCE_PN = 48.63           // 1 oxDNA force unit in pN
export const ELEM_CHARGE_C  = 1.602176634e-19 // electron charge (Coulombs)
export const DEFAULT_Q_EFF  = 0.25            // Manning-condensed effective backbone charge (e/phosphate)

// ── Force-unit conversions ──────────────────────────────────────────────────
const _num = (x, d = 0) => (Number.isFinite(Number(x)) ? Number(x) : d)

/** Force per nucleotide: pN → oxDNA simulation force units. */
export function pnToOxdna(pN) { return _num(pN) / OXDNA_FORCE_PN }
/** Force per nucleotide: oxDNA simulation force units → pN. */
export function oxdnaToPn(f)  { return _num(f) * OXDNA_FORCE_PN }

/**
 * Uniform field (V/m) → force per nucleotide (pN).  F = q_eff·e·E, then N→pN.
 * q_eff defaults to the Manning value but is meant to be user-editable (the
 * effective charge is genuinely uncertain — see the plan's GOTCHA 3).
 */
export function fieldVpmToPn(E_Vpm, qEff = DEFAULT_Q_EFF) {
  return _num(qEff, DEFAULT_Q_EFF) * ELEM_CHARGE_C * _num(E_Vpm) * 1e12
}
/** Inverse of fieldVpmToPn: force per nucleotide (pN) → field (V/m). */
export function pnToFieldVpm(pN, qEff = DEFAULT_Q_EFF) {
  const q = _num(qEff, DEFAULT_Q_EFF)
  if (q === 0) return 0
  return _num(pN) / (q * ELEM_CHARGE_C * 1e12)
}

// ── Plain [x,y,z] vector helpers ─────────────────────────────────────────────
export function vecLen(v)    { return Math.hypot(_num(v?.[0]), _num(v?.[1]), _num(v?.[2])) }
export function scaleVec(v, s) { return [_num(v?.[0]) * s, _num(v?.[1]) * s, _num(v?.[2]) * s] }
export function normalize(v) {
  const l = vecLen(v)
  return l > 1e-12 ? [_num(v[0]) / l, _num(v[1]) / l, _num(v[2]) / l] : [0, 0, 0]
}

/**
 * Intersect a ray with the plane through `planePoint` with normal `planeNormal`,
 * and return the world vector from `planePoint` to the hit (i.e. the new field
 * vector when the plane passes through the gizmo origin).  Returns null when the
 * ray is parallel to the plane or the hit is behind the camera.  Pure — the gizmo
 * supplies ray origin/dir from a THREE.Raycaster.
 */
export function rayPlaneVector(rayOrigin, rayDir, planeNormal, planePoint) {
  const n = planeNormal, ro = rayOrigin, rd = rayDir
  const denom = n[0] * rd[0] + n[1] * rd[1] + n[2] * rd[2]
  if (Math.abs(denom) < 1e-9) return null
  const diff = [planePoint[0] - ro[0], planePoint[1] - ro[1], planePoint[2] - ro[2]]
  const t = (n[0] * diff[0] + n[1] * diff[1] + n[2] * diff[2]) / denom
  if (t < 0) return null
  return [
    ro[0] + rd[0] * t - planePoint[0],
    ro[1] + rd[1] * t - planePoint[1],
    ro[2] + rd[2] * t - planePoint[2],
  ]
}

// ── Anchor-bond tension (the ACTUAL destructive axis) ────────────────────────
// A uniform field puts force `f` on every one of the n_total nucleotides; the
// anchors are the only thing reacting it, so the whole NET force (n_total·f)
// funnels through the held bonds — peak tension ≈ net / n_anchored (a hanging-
// chain effect: every base pulls, the load concentrates at the held region).
// This is what blew up a real field run, and it scales WITH n_total (not 1/n_total
// — that would be the local per-base stress, a different, non-fatal failure mode).
//
// Thresholds are on tension at the worst anchor bond (pN):
//   < SAFE     : elastic, below the dsDNA B→S overstretch (~65 pN) — green
//   SAFE..DISRUPT : straining the anchor (green → red)
//   >= DISRUPT : past the 5-oxDNA-unit relaxation backbone cap (243 pN); the
//                uncapped field-stage FENE diverges here → the structure explodes
export const EFIELD_ANCHOR_SAFE_PN    = 50    // anchor-bond tension stays elastic below this
export const EFIELD_ANCHOR_DISRUPT_PN = 243   // 5 oxDNA force units; beyond → FENE divergence / blow-up

/** True when we know enough to grade tension: a real structure size + ≥1 anchor. */
function _ctxKnown(ctx) {
  return !!ctx && _num(ctx.nTotal) > 0 && _num(ctx.nAnchored) >= 1
}
/** Load amplification: net field force / anchor bonds = n_total / n_anchored. */
export function anchorAmplification(nTotal, nAnchored) {
  const N = _num(nTotal), n = Math.max(1, _num(nAnchored))
  return N > 0 ? N / n : 1
}
/** Peak anchor-bond tension (pN) for a per-nt force `pN` on this structure. */
export function anchorTensionPn(pN, nTotal, nAnchored) {
  return Math.max(0, _num(pN)) * anchorAmplification(nTotal, nAnchored)
}
/** Per-nt force (pN) whose anchor tension just reaches `tensionPn`. */
function _pnForTension(tensionPn, ctx) {
  const A = anchorAmplification(ctx?.nTotal, ctx?.nAnchored)
  return A > 0 ? tensionPn / A : tensionPn
}
/** Per-nt force (pN) at the elastic/strong boundary for this structure. */
export function safePnFor(ctx)    { return _pnForTension(EFIELD_ANCHOR_SAFE_PN, ctx) }
/** Per-nt force (pN) at the disrupt (blow-up) boundary for this structure. */
export function disruptPnFor(ctx) { return _pnForTension(EFIELD_ANCHOR_DISRUPT_PN, ctx) }

// ── Display length ⇄ magnitude mapping ───────────────────────────────────────
// The gizmo arrow's world length encodes magnitude on a coarse linear scale (the
// numeric input is the precise control).  A minimum length keeps the direction
// arrow visible at zero field.  These are DISPLAY-only constants (nm of arrow).
export const EFIELD_NM_PER_PN  = 4    // world nm of arrow per pN (structure-blind fallback)
export const EFIELD_MIN_LEN_NM = 2    // floor so direction stays visible at 0 pN
export const EFIELD_MAX_LEN_NM = 60   // cap so a huge field doesn't fill the scene
// Base count at which the arrow keeps its structure-blind feel (full drag ≈ the
// flat ~14.5 pN/nt). A PROPORTIONALITY ANCHOR, not a floor: nm-per-pN scales ∝ N
// about this point, so a design 10× bigger gives 10× finer per-nt control — the
// arrow encodes the TOTAL push on the structure (per-nt force ∝ 1/N). The precise
// per-nt value is always set in the numeric box; this only shapes the drag feel.
export const EFIELD_REF_NT = 1000

const _clamp = (x, lo, hi) => Math.max(lo, Math.min(hi, x))

/**
 * nm-of-arrow per pN for a given structure context.  Scales the drag so the FULL
 * arrow length corresponds to the disrupt force FOR THIS DESIGN — i.e. a moderate
 * arrow is a moderate fraction of "enough to destroy it", instead of a fixed
 * (structure-blind) 4 nm/pN where 2 pN looks tame on a 14 k-nt structure it rips.
 * Falls back to the flat constant when context is unknown.
 */
export function nmPerPnFor(ctx) {
  if (!_ctxKnown(ctx)) return EFIELD_NM_PER_PN
  const dPn = disruptPnFor(ctx)
  if (!(dPn > 0)) return EFIELD_NM_PER_PN
  return _clamp((EFIELD_MAX_LEN_NM - EFIELD_MIN_LEN_NM) / dPn, 0.02, 1e6)
}

/**
 * nm-of-arrow per pN scaled by the design's TOTAL base count `nTotal` — so the
 * arrow encodes total force and the per-nt force for a given arrow length shrinks
 * ∝ 1/N.  This is what gives fine per-nt control on large origami: at the
 * reference size `EFIELD_REF_NT` it equals the flat constant; 10× the bases → 10×
 * the nm/pN → 1/10 the per-nt force for the same drag.  No floor (scales at all
 * sizes, per the design choice); falls back to the flat constant when `nTotal` is
 * unknown (no geometry loaded).  Only base count is needed — the anchored-nt count
 * (which `nmPerPnFor` uses) isn't known in the browser until a run is created.
 */
export function nmPerPnForN(nTotal) {
  const N = _num(nTotal)
  if (!(N > 0)) return EFIELD_NM_PER_PN
  return _clamp(EFIELD_NM_PER_PN * (N / EFIELD_REF_NT), 0.02, 1e6)
}

/** Arrow world length (nm) for a force-per-nucleotide (pN). `nmPerPn` defaults to
 *  the structure-blind constant; pass nmPerPnFor(ctx) for structure-aware scaling. */
export function arrowLenForPn(pN, nmPerPn = EFIELD_NM_PER_PN) {
  return _clamp(EFIELD_MIN_LEN_NM + _num(nmPerPn, EFIELD_NM_PER_PN) * Math.abs(_num(pN)), EFIELD_MIN_LEN_NM, EFIELD_MAX_LEN_NM)
}
/** Inverse: force-per-nucleotide (pN) implied by an arrow world length (nm). */
export function pnForArrowLen(lenNm, nmPerPn = EFIELD_NM_PER_PN) {
  const s = _num(nmPerPn, EFIELD_NM_PER_PN)
  return s > 0 ? Math.max(0, (_num(lenNm) - EFIELD_MIN_LEN_NM) / s) : 0
}

// ── Magnitude → colour grading (gizmo arrow feedback) ────────────────────────
// Per-nucleotide force thresholds (pN).  Heuristic, tunable: a base pair ruptures
// around ~10–20 pN and the B→S overstretch transition is ~65 pN, so a per-nt force
// approaching tens of pN will locally disrupt the duplex.
//   < LOW       : too small (blue) — negligible effect
//   LOW..GOOD   : working range (blue → green)
//   GOOD..DISRUPT: getting strong (green → red)
//   >= DISRUPT  : large enough to disrupt the DNA (red)
export const EFIELD_PN_LOW     = 0.5
export const EFIELD_PN_GOOD    = 10
export const EFIELD_PN_DISRUPT = 40

const _BLUE  = [59, 130, 246]
const _GREEN = [40, 200, 90]
const _RED   = [220, 60, 50]
const _lerp = (a, b, t) => Math.round(a + (b - a) * Math.max(0, Math.min(1, t)))
const _mix  = (c1, c2, t) => (_lerp(c1[0], c2[0], t) << 16) | (_lerp(c1[1], c2[1], t) << 8) | _lerp(c1[2], c2[2], t)

/** Colour (0xRRGGBB) for a force-per-nucleotide (pN): blue (too small) → green
 *  (good) → red (disrupts DNA).  Used to recolour the field gizmo arrow. */
export function fieldColorHex(pN) {
  const f = Math.max(0, _num(pN))
  if (f <= EFIELD_PN_LOW) return _mix(_BLUE, _BLUE, 0)
  if (f <= EFIELD_PN_GOOD) return _mix(_BLUE, _GREEN, (f - EFIELD_PN_LOW) / (EFIELD_PN_GOOD - EFIELD_PN_LOW))
  if (f <= EFIELD_PN_DISRUPT) return _mix(_GREEN, _RED, (f - EFIELD_PN_GOOD) / (EFIELD_PN_DISRUPT - EFIELD_PN_GOOD))
  return _mix(_RED, _RED, 0)
}

/** Zone label for a force-per-nucleotide: 'low' | 'good' | 'strong' | 'disrupt'.
 *  Drives the warning shown when a field is large enough to disrupt the DNA. */
export function fieldZone(pN) {
  const f = Math.max(0, _num(pN))
  if (f < EFIELD_PN_LOW) return 'low'
  if (f <= EFIELD_PN_GOOD) return 'good'
  if (f < EFIELD_PN_DISRUPT) return 'strong'
  return 'disrupt'
}

// ── Structure-aware grading (anchor-bond tension) ────────────────────────────
// Same blue→green→red feedback, but graded on anchor-bond tension (∝ n_total /
// n_anchored) instead of raw per-nt force, so a "moderate" arrow on a big, lightly
// anchored structure correctly reads red.  `ctx = {nTotal, nAnchored}`.  When ctx
// is unknown (no anchors yet / no job), these fall back to the per-nt heuristic.

/** Zone for a per-nt force given structure context: 'low'|'good'|'strong'|'disrupt'.
 *  'low' stays intensive (per-nt too weak to deflect anything); the destructive
 *  boundaries are on anchor-bond tension. */
export function fieldZoneFor(pN, ctx) {
  const f = Math.max(0, _num(pN))
  if (!_ctxKnown(ctx)) return fieldZone(f)
  // Destructive grading FIRST: with amplification a "negligible" per-nt force can
  // already strain the anchor (e.g. 0.1 pN/nt on VoltronCore = 92 pN/bond), so the
  // tension verdict outranks the intensive too-weak floor.
  const T = anchorTensionPn(f, ctx.nTotal, ctx.nAnchored)
  if (T >= EFIELD_ANCHOR_DISRUPT_PN) return 'disrupt'
  if (T >= EFIELD_ANCHOR_SAFE_PN) return 'strong'
  if (f < EFIELD_PN_LOW) return 'low'        // safe AND too weak to deflect anything
  return 'good'
}

/** Gizmo colour (0xRRGGBB) graded on anchor-bond tension for this structure.
 *  blue (negligible) → green (elastic) → red (will blow the run up). */
export function fieldColorForHex(pN, ctx) {
  const f = Math.max(0, _num(pN))
  if (!_ctxKnown(ctx)) return fieldColorHex(f)
  const T = anchorTensionPn(f, ctx.nTotal, ctx.nAnchored)
  if (T >= EFIELD_ANCHOR_DISRUPT_PN) return _mix(_RED, _RED, 0)
  if (T >= EFIELD_ANCHOR_SAFE_PN) {
    return _mix(_GREEN, _RED, (T - EFIELD_ANCHOR_SAFE_PN) / (EFIELD_ANCHOR_DISRUPT_PN - EFIELD_ANCHOR_SAFE_PN))
  }
  if (f <= EFIELD_PN_LOW) return _mix(_BLUE, _BLUE, 0)  // safe AND negligible
  return _mix(_GREEN, _GREEN, 0)
}

// ── Anchor descriptors (clusters / domains / overhangs) ──────────────────────
// An anchor descriptor is a plain object the backend will later resolve to oxDNA
// particle indices.  Kinds: 'overhang' {id} | 'cluster' {id} | 'domain' {strandId, domainIndex}.

/** Stable key for an anchor descriptor (used for dedupe + chip removal). */
export function anchorKey(a) {
  if (!a) return ''
  if (a.kind === 'domain') return `domain:${a.strandId}:${a.domainIndex}`
  return `${a.kind}:${a.id}`
}

/** Human label for an anchor chip. */
export function anchorLabel(a) {
  if (!a) return ''
  if (a.kind === 'domain') return `domain ${a.strandId}#${a.domainIndex}`
  if (a.kind === 'overhang') return `overhang ${a.id}`
  if (a.kind === 'cluster') return `cluster ${a.id}`
  return anchorKey(a)
}

/** Dedupe a list of anchor descriptors, preserving first-seen order. */
export function dedupeAnchors(list) {
  const seen = new Set()
  const out = []
  for (const a of list || []) {
    const k = anchorKey(a)
    if (k && !seen.has(k)) { seen.add(k); out.push(a) }
  }
  return out
}

export function addAnchors(existing, more) {
  return dedupeAnchors([...(existing || []), ...(more || [])])
}
export function removeAnchor(existing, key) {
  return (existing || []).filter(a => anchorKey(a) !== key)
}

/**
 * Collect anchor descriptors from a store state snapshot.  Reads the multi-select
 * arrays (lasso) + the single `selectedObject`, restricted to the three allowed
 * scopes (overhang / domain / cluster — overhang being the recommended path).
 * Pure: takes the state object, returns descriptors; the UI passes store.getState().
 */
export function resolveSelectionAnchors(state) {
  const s = state || {}
  const out = []
  for (const id of s.multiSelectedOverhangIds || []) out.push({ kind: 'overhang', id })
  for (const d of s.multiSelectedDomainIds || []) {
    if (d) out.push({ kind: 'domain', strandId: d.strandId, domainIndex: d.domainIndex })
  }
  const sel = s.selectedObject
  if (sel) {
    if (sel.type === 'overhang') out.push({ kind: 'overhang', id: sel.id })
    else if (sel.type === 'cluster') out.push({ kind: 'cluster', id: sel.id })
    else if (sel.type === 'domain' && sel.data) {
      out.push({ kind: 'domain', strandId: sel.data.strand_id, domainIndex: sel.data.domain_index })
    }
  }
  return dedupeAnchors(out)
}

// ── Field spec (the payload the run-wiring phase will POST) ───────────────────
/**
 * Build the canonical field spec from the UI state.  `pN` is force per nucleotide
 * (canonical); `dir` is any world vector (normalized here); `anchors` is the chip
 * list.  Also carries the oxDNA-unit force so the backend needn't re-derive it.
 */
export function buildFieldSpec({ pN, dir, anchors } = {}) {
  const fpn = Math.max(0, _num(pN))
  return {
    field_pN: fpn,
    field_oxdna: pnToOxdna(fpn),
    dir: normalize(dir || [0, 0, 0]),
    anchors: dedupeAnchors(anchors || []),
  }
}

/**
 * Is a field spec runnable?  Requires a positive force, a real direction, and ≥1
 * anchor — the anchor requirement is physical, not cosmetic: without it the equal
 * per-nucleotide force nets a COM drift and the structure streams across the box
 * (plan GOTCHA 1).
 */
export function fieldSpecReady(spec) {
  return !!spec && spec.field_pN > 0 && vecLen(spec.dir) > 0.5 && (spec.anchors?.length || 0) >= 1
}
