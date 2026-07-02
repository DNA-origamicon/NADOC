/**
 * Pure design-graph lookups extracted from main.js — operate on a plain `design`
 * object (overhangs / strands / domains / representation_overrides /
 * flexible_connections) with no scene/store/renderer access. Unit-tested in
 * design_queries.test.js.
 */

/** Flatten representation_overrides to the list of 'surface'-rep segments. */
export function surfaceSegments(design) {
  const segs = []
  for (const ov of design?.representation_overrides ?? []) {
    if (ov.representation === 'surface') for (const s of ov.segments ?? []) segs.push(s)
  }
  return segs
}

/** True if the overhang lives on its own helix (no scaffold domain on it) — i.e.
 *  an extrude-style overhang rather than an inline one. */
export function isExtrudeOverhang(ovhgId, design) {
  const o = design?.overhangs?.find(x => x.id === ovhgId)
  if (!o?.helix_id) return false
  return !design?.strands?.some(
    s => s.strand_type === 'scaffold' && s.domains?.some(d => d.helix_id === o.helix_id)
  )
}

// Returns domain ID objects for the overhang's strand — used to filter captureClusterBase
// and applyClusterTransform so that unselected overhangs sharing the same child helix are
// not affected by the live preview transform.
export function ovhgDomainIds(ovhgId, design) {
  const o = design?.overhangs?.find(x => x.id === ovhgId)
  if (!o) return null
  const strand = design?.strands?.find(s => s.id === o.strand_id)
  if (!strand?.domains?.length) return null
  return strand.domains.map((_, i) => ({ strand_id: strand.id, domain_index: i }))
}

// Returns {strand_id, domain_index} for every domain in the design that BINDS the
// given overhang (Domain.binds_overhang_id === ovhgId) — strand-type-agnostic, so it
// covers standalone OH_BINDER strands, LINKER complements, AND end-to-root binders
// spliced into a STAPLE strand. Used so the orientation-edit live preview rotates the
// binder (and any toehold extending past the overhang on the same helix) with the
// overhang. The per-overhang filter keeps OTHER overhangs' binders out.
export function ovhgBinderDomainIds(ovhgId, design) {
  if (!ovhgId) return []
  const out = []
  for (const s of design?.strands ?? []) {
    s.domains?.forEach((d, i) => {
      if (d.binds_overhang_id === ovhgId) out.push({ strand_id: s.id, domain_index: i })
    })
  }
  return out
}

/** Geometry key "helix:bp:dir" for a flexible-connection anchor, or null. */
export function flexAnchorKey(anc, design) {
  const s = design?.strands?.find(s => s.id === anc.strand_id)
  const d = s?.domains?.[anc.domain_index]
  return d ? `${d.helix_id}:${anc.bp_index}:${anc.direction}` : null
}

/**
 * Flexible ssDNA segments: the contiguous run of UNPAIRED beads containing the
 * clicked bead, within its strand (5'→3' order). Returns a list of mark bodies
 * {strand_id, domain_index, bp_index, direction}. Falls back to the single bead
 * if the run can't be resolved. Used to mark/unmark a whole tether at once.
 * `geometry` is the per-nucleotide list carrying `is_unpaired`.
 */
export function flexibleRunForBead(design, geometry, nuc) {
  const single = [{ strand_id: nuc.strand_id, domain_index: nuc.domain_index,
                    bp_index: nuc.bp_index, direction: nuc.direction }]
  const strand = design?.strands?.find(s => s.id === nuc.strand_id)
  if (!strand) return single
  // Build the strand's 5'→3' bead order with (domain_index, helix, bp, direction).
  const order = []
  strand.domains.forEach((d, di) => {
    const step = d.end_bp >= d.start_bp ? 1 : -1
    for (let bp = d.start_bp; ; bp += step) {
      order.push({ helix_id: d.helix_id, bp, direction: d.direction, domain_index: di })
      if (bp === d.end_bp) break
    }
  })
  const k = o => `${o.helix_id}:${o.bp}:${o.direction}`
  const unpaired = new Set((geometry ?? [])
    .filter(n => n.is_unpaired)
    .map(n => `${n.helix_id}:${n.bp_index}:${n.direction}`))
  const idx = order.findIndex(o =>
    o.helix_id === nuc.helix_id && o.bp === nuc.bp_index && o.direction === nuc.direction)
  if (idx < 0 || !unpaired.has(k(order[idx]))) return single
  let lo = idx, hi = idx
  while (lo - 1 >= 0 && unpaired.has(k(order[lo - 1]))) lo--
  while (hi + 1 < order.length && unpaired.has(k(order[hi + 1]))) hi++
  return order.slice(lo, hi + 1).map(o => ({
    strand_id: nuc.strand_id, domain_index: o.domain_index,
    bp_index: o.bp, direction: o.direction,
  }))
}

/** Find the flexible connection whose marked run contains this bead, or null. */
export function connIdForBead(nuc, design) {
  for (const c of (design?.flexible_connections ?? [])) {
    for (const k of (c.segment_bead_keys ?? [])) {
      if (k.strand_id === nuc.strand_id && k.domain_index === nuc.domain_index &&
          k.bp_index === nuc.bp_index && k.direction === nuc.direction) return c.id
    }
  }
  return null
}

/**
 * Pure: the bp length of an overhang's backing domain — the domain whose
 * `overhang_id` names this overhang. Mirrors the backend's
 * `abs(domain.end_bp - domain.start_bp) + 1`. This is the AUTHORITATIVE current
 * length: when the user drags an overhang end to resize it, the backing domain
 * grows while the stored `ovhg.sequence` / sub-domains stay short, so passing
 * this to `assembleOverhangSequence` makes the now-undefined 3' bases show as N.
 *
 * @param {object} design — Design with .strands[].domains
 * @param {string} ovhgId
 * @returns {number|null} domain length in bp, or null when no backing domain found
 */
export function overhangDomainLength(design, ovhgId) {
  for (const s of design?.strands ?? []) {
    for (const d of s.domains ?? []) {
      if (d.overhang_id === ovhgId) return Math.abs(d.end_bp - d.start_bp) + 1
    }
  }
  return null
}

/**
 * Pure JS mirror of backend `sequences._assemble_overhang_5to3`: assemble an
 * overhang's bases 5'→3' from its sub-domains (sequence_override → parent
 * `ovhg.sequence` slice → 'N'), padded/trimmed to `domainLen`. When `domainLen`
 * is omitted it defaults to the overhang's nominal length (Σ sub-domain length_bp,
 * else parent-sequence length). Used so the sidebar + 3D sequence overlay show the
 * REAL overhang sequence even when it lives in split sub-domain overrides rather
 * than the top-level field.
 *
 * @param {object} ovhg — OverhangSpec ({ sequence, sub_domains })
 * @param {number} [domainLen]
 * @returns {string} assembled bases (length === domainLen), '' for a null overhang
 */
export function assembleOverhangSequence(ovhg, domainLen) {
  if (!ovhg) return ''
  const parent = ovhg.sequence ? String(ovhg.sequence).toUpperCase() : null
  const subs = [...(ovhg.sub_domains ?? [])].sort((a, b) => (a.start_bp_offset ?? 0) - (b.start_bp_offset ?? 0))
  const nominal = subs.length
    ? subs.reduce((n, sd) => n + (sd.length_bp ?? 0), 0)
    : (parent?.length ?? 0)
  const len = domainLen ?? nominal
  const slot = (s, n) => {
    s = (s ?? '').toUpperCase()
    return (s.length >= n ? s.slice(0, n) : s + 'N'.repeat(n - s.length))
  }
  let out
  if (!subs.length) {
    out = parent !== null ? slot(parent, len) : 'N'.repeat(len)
  } else {
    out = ''
    for (const sd of subs) {
      const n = sd.length_bp ?? 0
      if (sd.sequence_override) out += slot(sd.sequence_override, n)
      else if (parent !== null) out += slot(parent.slice(sd.start_bp_offset ?? 0, (sd.start_bp_offset ?? 0) + n), n)
      else out += 'N'.repeat(n)
    }
  }
  return out.length >= len ? out.slice(0, len) : out + 'N'.repeat(len - out.length)
}

/** True if any of the overhang's sub-domains carries a per-sub-domain
 *  `sequence_override` — i.e. its sequence is authored per sub-domain (via the
 *  Domain Designer), so the sidebar's single Sequence field is read-only. */
export function overhangHasSequenceOverride(ovhg) {
  return (ovhg?.sub_domains ?? []).some(sd => !!sd.sequence_override)
}

/**
 * Cap a sequence to exactly `length` bases (truncate if longer, N-pad if shorter)
 * — mirrors backend `_cv_sequence_for_live_overhang`. Used so a complementary-
 * sequence write during Connect can NEVER resize the target overhang's backing
 * domain (a `patchOverhang` sequence write resizes to `len(sequence)`; capping to
 * the overhang's CURRENT length keeps a shorter overhang from being grown to match
 * a longer partner — the length-preservation invariant).
 */
export function capSequenceToLength(seq, length) {
  const s = String(seq ?? '').toUpperCase()
  if (!length || length <= 0) return s
  if (s.length === length) return s
  return s.length > length ? s.slice(0, length) : s + 'N'.repeat(length - s.length)
}

const _WC = { A: 'T', T: 'A', C: 'G', G: 'C' }
/** Watson-Crick complement test (case-insensitive; N never pairs). */
export function isComplement(x, y) {
  const a = String(x ?? '').toUpperCase()
  return _WC[a] != null && _WC[a] === String(y ?? '').toUpperCase()
}

/**
 * Pure: classify each base of two paired overhang sides for display coloring.
 *
 * `aBases` / `bBases` are each side's full assembled bases 5'→3' (already
 * N-padded to the backing-domain length via `assembleOverhangSequence`). The
 * duplex is ANCHORED at the bound region — `[aStart, aStart+pairLen)` on A and
 * `[bStart, bStart+pairLen)` on B — which the caller takes from the binding's
 * stored sub-domains (or the connection-type attach sub-domain). Pairing is
 * antiparallel: `aBases[aStart+i]` pairs with `bBases[bStart+pairLen-1-i]`.
 *
 * Returns `{ a, b }`, each a run-length-merged array of `{ text, kind }` where
 * kind is:
 *   'paired'   — inside the bound region AND Watson-Crick complementary
 *   'unpaired' — inside the bound region but a mismatch (or N) — not pairing
 *   'excess'   — outside the bound region: length beyond the partner, or the
 *                undefined N tail left when an overhang was dragged longer
 *
 * @returns {{a: {text:string,kind:string}[], b: {text:string,kind:string}[]}}
 */
export function pairingSegments(aBases, bBases, aStart, bStart, pairLen) {
  const a = String(aBases ?? '')
  const b = String(bBases ?? '')
  const len = Math.max(0, pairLen | 0)
  const classify = (bases, start, partner, partnerStart) => {
    const out = []
    for (let i = 0; i < bases.length; i++) {
      let kind
      if (i < start || i >= start + len) {
        kind = 'excess'
      } else {
        const partnerIdx = partnerStart + (len - 1 - (i - start))   // antiparallel
        kind = isComplement(bases[i], partner[partnerIdx]) ? 'paired' : 'unpaired'
      }
      const prev = out[out.length - 1]
      if (prev && prev.kind === kind) prev.text += bases[i]
      else out.push({ text: bases[i], kind })
    }
    return out
  }
  return {
    a: classify(a, aStart | 0, b, bStart | 0),
    b: classify(b, bStart | 0, a, aStart | 0),
  }
}

// ── Proposal-B Duplex graph: pure JS mirror of backend core/duplex.py ──────────
// Reads design.duplexes (register-bearing edges over helix bp intervals) so the
// sidebar / connections display can colour by the STORED register — multivalency,
// derived toeholds, mismatches — instead of the attach-anchored heuristic above.
// See memory/project_overhang_duplex_foundation.md.

/** The backing domain (the domain whose `overhang_id` names this overhang), or
 *  null. Carries the helix bp span the duplex intervals live in. */
export function overhangBackingDomain(design, ovhgId) {
  for (const s of design?.strands ?? []) {
    for (const d of s.domains ?? []) {
      if (d.overhang_id === ovhgId) return d
    }
  }
  return null
}

// bp ↔ 5'→3' offset (mirrors backend offset_to_bp / bp_to_offset).
const _step = (dom) => (dom.end_bp >= dom.start_bp ? 1 : -1)
function _offsetToBp(dom, off) { return dom.start_bp + off * _step(dom) }
function _bpToOffset(dom, bp) { return (bp - dom.start_bp) * _step(dom) }

function _wcBase(a, b, allowN) {
  if (allowN && (a === 'N' || b === 'N')) return true
  return isComplement(a, b)
}

/**
 * Pure: per-base classification of ONE duplex, `left` walked 5'→3' against
 * `right` walked 3'→5' (antiparallel). Mirror of backend `classify_duplex_pairing`.
 * @returns {{length:number, positions:{offset:number,left_bp:number,right_bp:number,left_base:string,right_base:string,complementary:boolean}[]}}
 */
export function classifyDuplex(design, duplex) {
  const leftDom = overhangBackingDomain(design, duplex.left.overhang_id)
  const rightDom = overhangBackingDomain(design, duplex.right.overhang_id)
  const L = Math.abs(duplex.left.end_bp - duplex.left.start_bp) + 1
  const positions = []
  if (leftDom && rightDom) {
    const leftOv = (design.overhangs ?? []).find(o => o.id === duplex.left.overhang_id)
    const rightOv = (design.overhangs ?? []).find(o => o.id === duplex.right.overhang_id)
    const leftBases = assembleOverhangSequence(leftOv, overhangDomainLength(design, duplex.left.overhang_id) ?? undefined)
    const rightBases = assembleOverhangSequence(rightOv, overhangDomainLength(design, duplex.right.overhang_id) ?? undefined)
    const allowN = duplex.allow_n_wildcard !== false
    const lOff0 = _bpToOffset(leftDom, duplex.left.start_bp)
    const rOff0 = _bpToOffset(rightDom, duplex.right.start_bp)
    for (let i = 0; i < L; i++) {
      const lOff = lOff0 + i
      const rOff = rOff0 + (L - 1 - i)   // antiparallel: left 5' ↔ right 3'
      const lBase = (lOff >= 0 && lOff < leftBases.length) ? leftBases[lOff] : 'N'
      const rBase = (rOff >= 0 && rOff < rightBases.length) ? rightBases[rOff] : 'N'
      positions.push({
        offset: i,
        left_bp: _offsetToBp(leftDom, lOff),
        right_bp: _offsetToBp(rightDom, rOff),
        left_base: lBase,
        right_base: rBase,
        complementary: _wcBase(lBase, rBase, allowN),
      })
    }
  }
  return { length: L, positions }
}

/**
 * Register-aware "reverse complement of the partner" for `targetId` paired with
 * `sourceId`. Returns `targetId`'s assembled sequence with ONLY its paired-window
 * bases (per the connecting duplex register) overwritten by the Watson–Crick
 * complement of the register-aligned `sourceId` bases — antiparallel, reusing the
 * exact offset walk of `classifyDuplex` (left 5'→3' vs right 3'→5'). The non-paired
 * region (toehold) keeps its current bases, so the returned string is always
 * `targetId`'s own length (never a resize).
 *
 * When no duplex connects the two overhangs, falls back to aligning their 5' roots
 * antiparallel over the shorter overhang's length.
 *
 * Returns null when either overhang has no backing domain (caller should skip the write).
 */
export function overhangRcOfPartner(design, targetId, sourceId) {
  const targetDom = overhangBackingDomain(design, targetId)
  const sourceDom = overhangBackingDomain(design, sourceId)
  if (!targetDom || !sourceDom) return null
  const targetOv = (design?.overhangs ?? []).find(o => o.id === targetId)
  const sourceOv = (design?.overhangs ?? []).find(o => o.id === sourceId)
  const targetBases = assembleOverhangSequence(targetOv, overhangDomainLength(design, targetId) ?? undefined).split('')
  const sourceBases = assembleOverhangSequence(sourceOv, overhangDomainLength(design, sourceId) ?? undefined)
  const comp = (b) => _WC[String(b ?? '').toUpperCase()] ?? 'N'

  const dxs = (design?.duplexes ?? []).filter(d => {
    const ids = [d.left.overhang_id, d.right.overhang_id]
    return ids.includes(targetId) && ids.includes(sourceId)
  })

  if (dxs.length) {
    for (const dx of dxs) {
      const leftDom = overhangBackingDomain(design, dx.left.overhang_id)
      const rightDom = overhangBackingDomain(design, dx.right.overhang_id)
      if (!leftDom || !rightDom) continue
      const L = Math.abs(dx.left.end_bp - dx.left.start_bp) + 1
      const lOff0 = _bpToOffset(leftDom, dx.left.start_bp)
      const rOff0 = _bpToOffset(rightDom, dx.right.start_bp)
      const targetIsLeft = dx.left.overhang_id === targetId
      for (let i = 0; i < L; i++) {
        const lOff = lOff0 + i
        const rOff = rOff0 + (L - 1 - i)   // antiparallel: left 5' ↔ right 3'
        const tOff = targetIsLeft ? lOff : rOff
        const sOff = targetIsLeft ? rOff : lOff
        if (tOff < 0 || tOff >= targetBases.length) continue
        const sBase = (sOff >= 0 && sOff < sourceBases.length) ? sourceBases[sOff] : 'N'
        targetBases[tOff] = comp(sBase)
      }
    }
  } else {
    // No duplex: align the two 5' roots antiparallel over the shorter length.
    const L = Math.min(targetBases.length, sourceBases.length)
    for (let i = 0; i < L; i++) targetBases[i] = comp(sourceBases[L - 1 - i] ?? 'N')
  }
  return targetBases.join('')
}

/**
 * Pure: bp → 'paired' | 'mismatch' | 'unpaired' for every bp of an overhang's
 * backing domain, aggregating ALL duplexes that touch it (multivalency). Uncovered
 * bp are 'unpaired' — a maximal unpaired run is a toehold. Mirror of backend
 * `overhang_pairing_map`. Returns {} when the overhang has no backing domain.
 */
export function overhangDuplexCoverage(design, overhangId) {
  const dom = overhangBackingDomain(design, overhangId)
  if (!dom) return {}
  const lo = Math.min(dom.start_bp, dom.end_bp)
  const hi = Math.max(dom.start_bp, dom.end_bp)
  const out = {}
  for (let bp = lo; bp <= hi; bp++) out[bp] = 'unpaired'
  for (const dx of design?.duplexes ?? []) {
    if (dx.left.overhang_id !== overhangId && dx.right.overhang_id !== overhangId) continue
    for (const p of classifyDuplex(design, dx).positions) {
      for (const [sideId, bp] of [[dx.left.overhang_id, p.left_bp], [dx.right.overhang_id, p.right_bp]]) {
        if (sideId === overhangId && bp in out) out[bp] = p.complementary ? 'paired' : 'mismatch'
      }
    }
  }
  return out
}

/** True if any duplex references this overhang. */
export function overhangHasDuplex(design, overhangId) {
  return (design?.duplexes ?? []).some(
    dx => dx.left.overhang_id === overhangId || dx.right.overhang_id === overhangId,
  )
}

/** The duplex CLUSTER this overhang participates in (as driver OR driven), or null. A duplex
 *  cluster carries `overhang_duplex_driver_id`; the driven overhang's domain is in its
 *  `domain_ids`. Used to route a duplex-backed overhang's orientation edit to the cluster
 *  gizmo instead of the standalone orientation panel. [[overhang-duplex-cluster]] P4. */
export function duplexClusterForOverhang(design, overhangId) {
  const strandById = new Map((design?.strands ?? []).map(s => [s.id, s]))
  for (const c of (design?.cluster_transforms ?? [])) {
    if (!c.overhang_duplex_driver_id) continue
    if (c.overhang_duplex_driver_id === overhangId) return c
    for (const dr of (c.domain_ids ?? [])) {
      const s = strandById.get(dr.strand_id)
      if (s?.domains?.[dr.domain_index]?.overhang_id === overhangId) return c
    }
  }
  return null
}

/**
 * Pure: colored run-segments for an overhang's assembled bases (5'→3'), colored by
 * its duplex coverage. kind ∈ 'paired' | 'mismatch' | 'toehold' (uncovered). This
 * is what the sidebar renders once the overhang participates in a duplex.
 * @returns {{text:string,kind:string}[]}
 */
export function overhangDuplexSegments(design, overhangId) {
  const dom = overhangBackingDomain(design, overhangId)
  const ov = (design?.overhangs ?? []).find(o => o.id === overhangId)
  if (!dom || !ov) return []
  const bases = assembleOverhangSequence(ov, overhangDomainLength(design, overhangId) ?? undefined)
  const cov = overhangDuplexCoverage(design, overhangId)
  const out = []
  for (let off = 0; off < bases.length; off++) {
    const bp = _offsetToBp(dom, off)
    const status = cov[bp] ?? 'unpaired'
    const kind = status === 'unpaired' ? 'toehold' : status   // paired | mismatch | toehold
    const prev = out[out.length - 1]
    if (prev && prev.kind === kind) prev.text += bases[off]
    else out.push({ text: bases[off], kind })
  }
  return out
}
