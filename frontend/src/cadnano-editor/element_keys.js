/**
 * Cadnano editor element-key codec — the single source of truth for the string
 * keys that identify selectable elements in `_selectedElements` (domain bodies
 * and ends, crossovers, forced ligations, loop/skip markers).
 *
 * CRITICAL: bp indices CAN BE NEGATIVE. Helices start as low as bp -17, so a
 * domain/end/crossover/loop-skip can sit entirely in the negative region. Every
 * parser therefore matches an OPTIONAL leading '-' (`-?\d+`). A `\d+`-only parser
 * silently fails to match a negative key — which made negative-bp scaffold stubs
 * undeletable in the 2D editor (the delete path collected no selectors → no-op).
 * See issues_ledger.md ISSUE-7 and LESSONS.md.
 *
 * Builders and parsers live together here so the emitted format and the regex
 * that reads it back can never drift apart (the round-trip is unit-tested).
 */

// ── Builders ────────────────────────────────────────────────────────────────

/** `line:{helix_id}_{lo}_{hi}_{direction}` — a domain body. lo/hi may be < 0. */
export function domainLineKey(dom) {
  const lo = Math.min(dom.start_bp, dom.end_bp)
  const hi = Math.max(dom.start_bp, dom.end_bp)
  return `line:${dom.helix_id}_${lo}_${hi}_${dom.direction}`
}

/** `end:{helix_id}_{bp}_{direction}` — a 5′/3′ domain end cap. bp may be < 0. */
export function domainEndKey(dom, which) {   // which = '5p' | '3p'
  const lo = Math.min(dom.start_bp, dom.end_bp)
  const hi = Math.max(dom.start_bp, dom.end_bp)
  const isFwd = dom.direction === 'FORWARD'
  const bp = which === '5p' ? (isFwd ? lo : hi) : (isFwd ? hi : lo)
  return `end:${dom.helix_id}_${bp}_${dom.direction}`
}

/** `xo:{helix_id}_{index}_{strand}` — a crossover (keyed on half_a). index may be < 0. */
export function xoverKey(xo) {
  return `xo:${xo.half_a.helix_id}_${xo.half_a.index}_${xo.half_a.strand}`
}

/** `fl:{id}` — a forced ligation (no bp index). */
export function forcedLigKey(fl) {
  return `fl:${fl.id}`
}

/** `ls:{helix_id}_{bpIndex}_{loop|skip}` — a loop/skip marker. bpIndex may be < 0. */
export function loopSkipKey(helixId, bpIndex, delta) {
  return `ls:${helixId}_${bpIndex}_${delta > 0 ? 'loop' : 'skip'}`
}

// ── Parsers (negative-bp safe) ───────────────────────────────────────────────
// `(.+)` is greedy; with backtracking it correctly assigns the helix_id even
// though helix ids contain underscores and digits (e.g. `h_XY_0_0`). The only
// difference from the historical regexes is `-?` on each numeric group.

const LINE_RE = /^line:(.+)_(-?\d+)_(-?\d+)_(FORWARD|REVERSE)$/
const END_RE  = /^end:(.+)_(-?\d+)_(FORWARD|REVERSE)$/
const XO_RE   = /^xo:(.+)_(-?\d+)_(FORWARD|REVERSE)$/
const LS_RE   = /^ls:(.+)_(-?\d+)_(loop|skip)$/

/** → { helix_id, lo, hi, direction } | null */
export function parseLineKey(key) {
  const m = key.match(LINE_RE)
  return m ? { helix_id: m[1], lo: parseInt(m[2]), hi: parseInt(m[3]), direction: m[4] } : null
}

/** → { helix_id, bp, direction } | null */
export function parseEndKey(key) {
  const m = key.match(END_RE)
  return m ? { helix_id: m[1], bp: parseInt(m[2]), direction: m[3] } : null
}

/** → { helix_id, index, strand } | null */
export function parseXoverKey(key) {
  const m = key.match(XO_RE)
  return m ? { helix_id: m[1], index: parseInt(m[2]), strand: m[3] } : null
}

/** → { helix_id, bp, kind } | null  (kind = 'loop' | 'skip') */
export function parseLoopSkipKey(key) {
  const m = key.match(LS_RE)
  return m ? { helix_id: m[1], bp: parseInt(m[2]), kind: m[3] } : null
}

/** → { id } | null */
export function parseForcedLigKey(key) {
  return key.startsWith('fl:') ? { id: key.slice(3) } : null
}
