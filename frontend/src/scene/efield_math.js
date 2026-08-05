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

// base_ref is the only import, and is itself pure (no THREE / DOM / store), so the
// "every export is unit-testable in isolation" property above still holds.
import { parseBaseKey, XB_HELIX } from './base_ref.js'

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
  if (a.kind === 'base') return `base:${a.helixId}:${a.bp}:${a.direction}`
  if (a.kind === 'extra_base') return `extra_base:${a.crossoverId}:${a.k ?? '*'}`
  if (a.kind === 'extension') return `extension:${a.extensionId}:${a.k ?? '*'}`
  return `${a.kind}:${a.id}`
}

// ── Anchor labels ────────────────────────────────────────────────────────────
//
// Labels are read in a ~230 px sidebar column, so they have to be SHORT. Raw ids are
// unusable there — a helix id is a UUID or a lattice tag like `h_XY_0_1`, and the old
// `base <uuid>.7 FORWARD` ran to 50 characters.
//
// The vocabulary is `H<n>:bp<i>`, where `<n>` is the helix NUMBER shown in the viewport
// (`helix.label ?? its index`, the same rule domain_ends.js uses for the 3D number
// sprites) — never the lattice position. Everything else hangs off that:
//
//   H2:bp23 Scaf   one nucleotide          H2:bp10-24 Stap  a domain (a bp range)
//   H2:bp23+1      extra base #1 inserted at the crossover leaving H2:bp23  (+* = all)
//   H2:bp26›2      tail base #2 beyond terminus H2:bp26                     (›* = all)
//   S3 / C1 / OH4  whole strand / cluster / overhang — these span many helices
//
// FORWARD/REVERSE is NOT shown: the two strands of a base pair are separate anchors, but
// which one is scaffold flips per helix (in a 2hb, helix 0 FORWARD is the staple while
// helix 1 FORWARD is the scaffold), so the direction word tells the user nothing. The
// suffix is the STRAND ROLE, looked up from whichever strand owns that nucleotide.

const _ROLE = { scaffold: 'Scaf', staple: 'Stap', linker: 'Link', oh_binder: 'Bind' }
const _dirUp = (d) => String(d ?? '').toUpperCase()

/**
 * Build a labeller bound to one design.  Indexes the design ONCE, then labels each anchor
 * in ~O(domains on its helix) — the card re-labels every row on each repaint, so a
 * per-row full-design scan would be quadratic in a large origami.
 *
 * PURE: design in, `(anchor) => string` out. Never reads the store or the DOM.
 */
export function makeAnchorLabeller(design) {
  const helices = design?.helices ?? []
  const strands = design?.strands ?? []
  const short = (id) => String(id ?? '').slice(0, 4)

  const helixNum = new Map(helices.map((h, i) => [h.id, h.label ?? i]))
  const strandById = new Map(strands.map((s) => [s.id, s]))
  const strandNum = new Map(strands.map((s, i) => [s.id, i]))
  const clusterNum = new Map((design?.cluster_transforms ?? []).map((c, i) => [c.id, i]))
  const overhangNum = new Map((design?.overhangs ?? []).map((o, i) => [o.id, i]))
  const xoverById = new Map((design?.crossovers ?? []).map((x) => [x.id, x]))
  const extById = new Map((design?.extensions ?? []).map((e) => [e.id, e]))

  // helix → its domains' bp ranges + owning strand role, for the Scaf/Stap suffix.
  const domainsOnHelix = new Map()
  for (const s of strands) {
    const role = _ROLE[s.strand_type?.value ?? s.strand_type] ?? null
    for (const d of s.domains ?? []) {
      if (!d?.helix_id) continue
      let arr = domainsOnHelix.get(d.helix_id)
      if (!arr) domainsOnHelix.set(d.helix_id, (arr = []))
      arr.push({                                   // REVERSE domains store start > end
        lo: Math.min(d.start_bp, d.end_bp), hi: Math.max(d.start_bp, d.end_bp),
        dir: _dirUp(d.direction), role,
      })
    }
  }

  /** `H<number>`, or `H?<id fragment>` when the design doesn't know the helix (a stale
   *  anchor whose helix was deleted) — flagged rather than silently renumbered. */
  const H = (id) => (helixNum.has(id) ? `H${helixNum.get(id)}` : `H?${short(id)}`)

  const roleAt = (helixId, bp, direction) => {
    const arr = domainsOnHelix.get(helixId)
    if (!arr) return null
    const dir = _dirUp(direction)
    for (const d of arr) if (d.dir === dir && bp >= d.lo && bp <= d.hi) return d.role
    return null
  }

  /** Scaf/Stap suffix. Falls back to Fwd/Rev when no strand covers the slot: without
   *  SOMETHING here the two strands of a base pair render as identical rows. */
  const roleSuffix = (helixId, bp, direction) => {
    const role = roleAt(helixId, bp, direction)
    if (role) return ` ${role}`
    return _dirUp(direction) === 'REVERSE' ? ' Rev' : ' Fwd'
  }

  const numbered = (map, id, prefix) =>
    map.has(id) ? `${prefix}${map.get(id)}` : `${prefix}?${short(id)}`

  return function label(a) {
    if (!a) return ''
    const kind = a.kind

    if (kind === 'base') {
      const hid = a.helixId ?? a.helix_id
      const bp = a.bp ?? a.bp_index
      return `${H(hid)}:bp${bp}${roleSuffix(hid, bp, a.direction)}`
    }

    if (kind === 'domain') {
      const sid = a.strandId ?? a.strand_id
      const di = a.domainIndex ?? a.domain_index
      const d = strandById.get(sid)?.domains?.[di]
      if (!d?.helix_id) return `${numbered(strandNum, sid, 'S')}#${di}`
      const lo = Math.min(d.start_bp, d.end_bp)
      const hi = Math.max(d.start_bp, d.end_bp)
      const role = _ROLE[strandById.get(sid)?.strand_type?.value
                         ?? strandById.get(sid)?.strand_type]
      return `${H(d.helix_id)}:bp${lo}-${hi}${role ? ` ${role}` : ''}`
    }

    // `k == null` means the whole run/tail, which the backend also accepts → '*'.
    if (kind === 'extra_base') {
      const xid = a.crossoverId ?? a.crossover_id
      const half = xoverById.get(xid)?.half_a
      const k = a.k ?? '*'
      // An extra base is INSERTED at a crossover, so it has no bp of its own — name it by
      // the bp the crossover leaves from, which is where it actually sits in the model.
      return half ? `${H(half.helix_id)}:bp${half.index}+${k}` : `XB?${short(xid)}+${k}`
    }

    if (kind === 'extension') {
      const eid = a.extensionId ?? a.extension_id
      const ext = extById.get(eid)
      const k = a.k ?? '*'
      const doms = strandById.get(ext?.strand_id)?.domains ?? []
      // A tail hangs off a strand TERMINUS: the 5′ end is the first domain's start, the
      // 3′ end the last domain's end.
      const d = ext?.end === 'five_prime' ? doms[0] : doms[doms.length - 1]
      if (!d?.helix_id) return `EX?${short(eid)}›${k}`
      const bp = ext.end === 'five_prime' ? d.start_bp : d.end_bp
      return `${H(d.helix_id)}:bp${bp}›${k}`
    }

    // These span many helices, so no H<n>:bp<i> fits them.
    if (kind === 'strand') return numbered(strandNum, a.id ?? a.strand_id ?? a.strandId, 'S')
    if (kind === 'cluster') return numbered(clusterNum, a.id ?? a.cluster_id, 'C')
    if (kind === 'overhang') return numbered(overhangNum, a.id ?? a.overhang_id, 'OH')

    return anchorKey(a)
  }
}

/** Human label for one anchor row.  `design` resolves helix numbers and the Scaf/Stap
 *  suffix; without it the label degrades to raw ids rather than lying about a number.
 *  Labelling a whole list? Build the labeller once with `makeAnchorLabeller`. */
export function anchorLabel(a, design = null) {
  return makeAnchorLabeller(design)(a)
}

/**
 * Anchor descriptors → the backend's occupancy `selection` dict.
 *
 * Same descriptors the anchor picker produces, so the scope card and the anchor cards
 * share one selection vocabulary rather than translating between two. Every kind the
 * picker can emit has a slot here — a descriptor that quietly had none would select
 * nothing and look like an empty region.
 *
 * Returns null for an empty list, which is how the caller says "whole structure".
 */
export function anchorsToSelection(anchors) {
  const sel = { cluster_ids: [], helix_ids: [], strand_ids: [], overhang_ids: [],
                domains: [], bases: [], extra_bases: [], extensions: [] }
  let n = 0
  for (const a of anchors ?? []) {
    if (!a?.kind) continue
    if (a.kind === 'cluster') sel.cluster_ids.push(a.id)
    else if (a.kind === 'strand') sel.strand_ids.push(a.id)
    else if (a.kind === 'overhang') sel.overhang_ids.push(a.id)
    else if (a.kind === 'domain') sel.domains.push([a.strandId, a.domainIndex])
    else if (a.kind === 'base') sel.bases.push([a.helixId, a.bp, a.direction])
    // A missing index means the whole run/tail; the backend reads a 1-element entry
    // that way, so don't pad it with null.
    else if (a.kind === 'extra_base') {
      sel.extra_bases.push(a.k == null ? [a.crossoverId] : [a.crossoverId, a.k])
    } else if (a.kind === 'extension') {
      sel.extensions.push(a.k == null ? [a.extensionId] : [a.extensionId, a.k])
    } else continue
    n++
  }
  return n ? sel : null
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

// ── Per-anchor atom holds (NAMD) ─────────────────────────────────────────────
// Which ATOMS of each anchored base a given anchor holds.  The choice rides on the
// descriptor itself (`atoms`), not beside the list, because descriptors already
// round-trip through the job manifest (`anchors.requested`) → GET /forces →
// applyConfig — so per-anchor read-back is free and nothing else had to learn a new
// field.  `anchorKey` ignores it, so adding it never changes identity or dedupe.
//
// THE SENTINEL, and it is the subtle part:  `atoms` PRESENT (even as null) is that
// anchor's own decision; ABSENT means "no opinion" and falls back to the job-level
// `anchor_atoms`.  `null` ≡ all heavy atoms — the same meaning `anchor_atoms=None`
// already carries on the backend.  Collapsing present-null into absent would leak the
// job default into a row that explicitly asked for all-heavy.

const _ATOMS_KEYS = ['atoms', 'atom_names', 'atomNames']

/** Pure: a "Hold atoms" select value → an atom-name list, or null.
 *  '' (All heavy atoms) → null, the backend's "no filter" sentinel; anything else is a
 *  comma-separated PDB atom-name list. Returning [] instead of null would ask the
 *  backend to anchor NOTHING, which it rejects rather than running unanchored. */
export function atomNamesFromValue(value) {
  const names = String(value ?? '').split(',').map(s => s.trim()).filter(Boolean)
  return names.length ? names : null
}

/** Pure: one descriptor's held atom names, or null (= all heavy atoms).  Accepts the
 *  three spellings a descriptor can arrive with (our own `atoms`, the backend's
 *  `atom_names`, a camelCase caller) and a raw "P,C1'" string, mirroring the alias
 *  tolerance `resolveAnchorEntries` already has for scope keys. */
export function anchorAtoms(a) {
  if (!a) return null
  for (const k of _ATOMS_KEYS) {
    if (!(k in a)) continue
    const v = a[k]
    if (v == null) return null
    if (typeof v === 'string') return atomNamesFromValue(v)
    const names = (Array.isArray(v) ? v : []).map(s => String(s).trim()).filter(Boolean)
    return names.length ? names : null
  }
  return null
}

/** Pure: does this descriptor state an opinion about its atoms?  Key PRESENCE, not
 *  truthiness — `{atoms: null}` (all heavy, deliberately) is an opinion; a descriptor
 *  with no `atoms` key at all is not. */
export function hasAnchorAtoms(a) {
  return !!a && _ATOMS_KEYS.some(k => k in a)
}

/** Pure: order-insensitive canonical key for an atom set, so "P,C1'" and "C1',P" are
 *  the same choice.  '' is all-heavy-atoms (matching the select's '' option value). */
export function anchorAtomsKey(a) {
  const names = anchorAtoms(a)
  return names ? names.slice().sort().join(',') : ''
}

/** Pure: set one row's atoms, by anchor key.  Returns a NEW list; untouched rows keep
 *  their identity so a re-render can diff cheaply. */
export function withAnchorAtoms(anchors, key, names) {
  return (anchors || []).map(a => (anchorKey(a) === key ? _withAtoms(a, names) : a))
}

/** Pure: set every row's atoms — the "Apply hold to all" write. */
export function withAllAnchorAtoms(anchors, names) {
  return (anchors || []).map(a => _withAtoms(a, names))
}

function _withAtoms(a, names) {
  const list = Array.isArray(names) ? names.map(s => String(s).trim()).filter(Boolean) : null
  const out = { ...a, atoms: list && list.length ? list : null }
  // Drop the alias spellings so a descriptor can never carry two disagreeing answers.
  delete out.atom_names
  delete out.atomNames
  return out
}

/** Pure: THE blank-when-mixed rule for "Apply hold to all".  Returns the canonical key
 *  every row agrees on, or null when they disagree (→ the select renders blank).
 *  An empty card returns '' — there is nothing to disagree about, and all-heavy is the
 *  historical default a fresh card starts from. */
export function commonAnchorAtomsKey(anchors) {
  const list = anchors || []
  if (!list.length) return ''
  const first = anchorAtomsKey(list[0])
  return list.every(a => anchorAtomsKey(a) === first) ? first : null
}

/** Pure: canonical atom-set key → the <option> value that represents it.  Built from
 *  the LIVE option list (the four presets live once, in index.html) so the card never
 *  duplicates the enum.  A set no option offers — a headless caller's custom names —
 *  simply has no entry, and the select renders blank rather than lying. */
export function atomOptionByKey(options) {
  const map = new Map()
  for (const o of options || []) {
    const value = typeof o === 'string' ? o : o?.value
    if (value == null) continue
    const key = anchorAtomsKey({ atoms: atomNamesFromValue(value) })
    if (!map.has(key)) map.set(key, value)
  }
  return map
}

/**
 * Which anchors are highlighted (purple) right now — drives BOTH the 3D halo and the
 * chip styling, so the list and the scene can never disagree.  The rule:
 *   • one entry focused (clicked) → ONLY that one, whatever the toggle says. An explicit
 *     click is an explicit "show me this one".
 *   • nothing focused → the "Highlight all anchors" toggle decides: all, or none.
 * A focusKey that matches no anchor (e.g. the focused chip was just removed) falls back to
 * the toggle rather than going dark.
 * PURE.
 */
export function highlightedAnchors(anchors, { glowAll = true, focusKey = null } = {}) {
  const list = anchors || []
  if (focusKey) {
    const only = list.filter(a => anchorKey(a) === focusKey)
    if (only.length) return only
  }
  return glowAll ? list.slice() : []
}

/**
 * Build the selection snapshot an Anchors card resolves "Add" against.  The raw store
 * state isn't enough for two of the ways you can multi-select:
 *  • END BEADS (Ctrl/Alt-picked termini) are owned by selection_manager, not the store —
 *    the caller passes their nuc records in as `ctrlBeadNucs`.
 *  • CLUSTERS mirror their member strands into `multiSelectedStrandIds` for the highlight.
 *    Left in, each cluster would yield one cluster anchor PLUS a redundant strand anchor
 *    per member — the same nucleotides trapped twice, i.e. double the trap stiffness. So
 *    subtract the mirrored members. Independently multi-selected strands aren't members
 *    of a selected cluster, so they survive.
 * Pure: `clusterMemberStrandIds` is injected because membership resolves through the live
 * renderer (bead entries / cylinder records), which this module must not reach into.
 */
export function anchorSelectionState({ state, ctrlBeadNucs = [], clusterMemberStrandIds = null } = {}) {
  const s = state || {}
  const clusterIds = s.multiSelectedClusterIds ?? []
  if (!clusterIds.length) return { ...s, ctrlBeadNucs }
  const members = new Set(clusterIds.flatMap(id => clusterMemberStrandIds?.(id) || []))
  return {
    ...s,
    multiSelectedStrandIds: (s.multiSelectedStrandIds ?? []).filter(id => !members.has(id)),
    ctrlBeadNucs,
  }
}

/**
 * Turn the base-level pool (`multiSelectedBaseKeys`) into anchor descriptors.
 *
 * The five bead families the `base` selection level can pick need three different
 * descriptor kinds, because the backend addresses them three different ways:
 *
 *  - real nucleotides (backbone, extension-adjacent duplex, flexible ssDNA, ss-linker
 *    bridge) → `kind:'base'`, matched on `(helix_id, bp, direction)` provenance;
 *  - crossover extra-base inserts → `kind:'extra_base'`, matched on the key tuple
 *    `("__xb__", crossover_id, k)` — these have NO helix/bp/direction at all;
 *  - strand-extension tail beads → `kind:'extension'`, matched on `("__ext_<id>", k, …)`.
 *
 * Each kind's owner is checked against the live design, because the backend resolves a
 * stale descriptor to zero particles SILENTLY — a deleted helix, a deleted crossover and
 * a deleted extension all produce an anchor that looks added and holds nothing. Omitting
 * an id set means "can't tell", which keeps the key rather than dropping it.
 *
 * @param {string[]} keys   app-wide base keys (scene/base_ref.js)
 * @param {{helixIds?:Set<string>, crossoverIds?:Set<string>, extensionIds?:Set<string>}} live
 * @returns {{anchors: object[], unsupported: string[]}}
 */
export function partitionBaseKeys(keys, live = {}) {
  const { helixIds, crossoverIds, extensionIds } = live
  const anchors = []
  const unsupported = []
  for (const key of keys || []) {
    const p = parseBaseKey(key)
    if (!p) { unsupported.push(key); continue }
    if (p.helix_id === XB_HELIX) {
      if (crossoverIds && !crossoverIds.has(p.crossover_id)) { unsupported.push(key); continue }
      anchors.push({ kind: 'extra_base', crossoverId: p.crossover_id, k: p.k })
      continue
    }
    if (p.helix_id.startsWith('__ext_')) {
      const extId = p.helix_id.slice('__ext_'.length)
      if (extensionIds && !extensionIds.has(extId)) { unsupported.push(key); continue }
      anchors.push({ kind: 'extension', extensionId: extId, k: p.bp_index })
      continue
    }
    if (p.bp_index == null) { unsupported.push(key); continue }
    if (helixIds && !helixIds.has(p.helix_id)) { unsupported.push(key); continue }
    anchors.push({ kind: 'base', helixId: p.helix_id, bp: p.bp_index, direction: p.direction })
  }
  return { anchors, unsupported }
}

/** The live owner-id sets a selection snapshot's design provides. */
function _liveIds(state) {
  const d = state?.currentDesign
  return {
    helixIds:     new Set((d?.helices ?? []).map(h => h.id)),
    crossoverIds: new Set((d?.crossovers ?? []).map(x => x.id)),
    extensionIds: new Set((d?.extensions ?? []).map(e => e.id)),
  }
}

/**
 * The base keys in a selection snapshot that no anchor can address.
 *
 * Every bead family is addressable now, so this is only STALE keys — one whose helix,
 * crossover or extension is gone from the design, or an unparseable string. Normally
 * empty; the anchor card reports it rather than dropping silently, because the backend
 * would resolve such a descriptor to zero particles without complaint.
 */
export function unsupportedBaseKeys(state) {
  const s = state || {}
  return partitionBaseKeys(s.multiSelectedBaseKeys ?? [], _liveIds(s)).unsupported
}

/**
 * Collect anchor descriptors from a store state snapshot.  Reads the multi-select
 * arrays (lasso) + the single `selectedObject`, restricted to the anchorable
 * scopes: overhang / domain / cluster / whole strand (e.g. an overhang-binding
 * oligo) / individual base.  Pure: takes the state object, returns descriptors;
 * the UI passes anchorSelectionState(...) (store.getState() + the bits it can't see).
 */
export function resolveSelectionAnchors(state) {
  const s = state || {}
  const out = []
  for (const id of s.multiSelectedOverhangIds || []) out.push({ kind: 'overhang', id })
  // Cluster-level multi-select mirrors each cluster's member strands into
  // multiSelectedStrandIds too; the caller strips those so a cluster yields ONE cluster
  // anchor rather than a redundant per-member-strand trap over the same nucleotides.
  for (const id of s.multiSelectedClusterIds || []) {
    if (id != null) out.push({ kind: 'cluster', id })
  }
  for (const id of s.multiSelectedStrandIds || []) {
    if (id != null) out.push({ kind: 'strand', id })
  }
  for (const d of s.multiSelectedDomainIds || []) {
    if (d) out.push({ kind: 'domain', strandId: d.strandId, domainIndex: d.domainIndex })
  }
  // Ctrl/Alt-picked end beads are owned by selection_manager, not the store — the caller
  // passes their nuc records through so multi-picked bases resolve like any other anchor.
  for (const n of s.ctrlBeadNucs || []) {
    if (n) out.push({ kind: 'base', helixId: n.helix_id, bp: n.bp_index, direction: n.direction })
  }
  // The `base` selection level's pool. Unlike ctrlBeadNucs these are KEY strings spanning
  // five bead renderers, so partitionBaseKeys picks the right descriptor kind per family
  // (base / extra_base / extension) and drops stale ones. `unsupportedBaseKeys` reports
  // what it dropped.
  out.push(...partitionBaseKeys(s.multiSelectedBaseKeys ?? [], _liveIds(s)).anchors)
  const sel = s.selectedObject
  if (sel) {
    if (sel.type === 'overhang') out.push({ kind: 'overhang', id: sel.id })
    else if (sel.type === 'cluster') out.push({ kind: 'cluster', id: sel.id })
    else if (sel.type === 'strand') out.push({ kind: 'strand', id: sel.id ?? sel.data?.strand_id })
    else if (sel.type === 'domain' && sel.data) {
      out.push({ kind: 'domain', strandId: sel.data.strand_id, domainIndex: sel.data.domain_index })
    } else if (sel.type === 'nucleotide' && sel.data) {
      out.push({ kind: 'base', helixId: sel.data.helix_id,
                bp: sel.data.bp_index, direction: sel.data.direction })
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
