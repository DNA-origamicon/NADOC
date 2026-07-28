/**
 * strand_sequence_pairing.js — pure helpers for the hand-edit strand-sequence dialog.
 *
 * The backend serves a `sequence-context` payload per strand
 * (GET /design/strand/{id}/sequence-context) whose `partner` string is
 * index-aligned to the strand's own 5'→3' sequence: `partner[i]` is the base that
 * position i PAIRS WITH (the antiparallel scaffold base for a duplex domain, the
 * overhang base for a binder domain, `'-'` where there is no partner at all).
 *
 * Everything here is pure input→output so it can be unit-tested without a DOM.
 * The backend remains authoritative for validation and for splicing overhang
 * bases back onto their OverhangSpec — these helpers only drive the live display.
 */

import { isComplement } from '../scene/design_queries.js'

/** Characters the backend accepts in a sequence. */
export const VALID_BASES = 'ACGTN'

/** Strip all whitespace and uppercase — mirrors backend `normalize_sequence_input`. */
export function normalizeSequence(raw) {
  return String(raw ?? '').replace(/\s+/g, '').toUpperCase()
}

/** The characters in `seq` that the backend would reject, de-duplicated + sorted. */
export function invalidBases(seq) {
  const bad = new Set()
  for (const ch of normalizeSequence(seq)) {
    if (!VALID_BASES.includes(ch)) bad.add(ch)
  }
  return [...bad].sort()
}

/**
 * Per-position mismatch flags for the typed sequence against its partners.
 *
 * Position i is a MISMATCH when it has a real partner base and the typed base is
 * not that partner's Watson-Crick complement. `N` on either side is a wildcard
 * and never counts (matching the backend's `is_watson_crick_complement(allow_n=True)`),
 * and `'-'` means "no partner here" (an ssDNA overhang tip, or a staple position
 * the scaffold does not cover) — also never a mismatch.
 *
 * Positions beyond the end of either string are not mismatches: a half-typed
 * sequence should not light up red while the user is still typing.
 *
 * @param {string} typed   the sequence being edited, 5'→3'
 * @param {string} partner the aligned partner string from the backend
 * @returns {boolean[]} one flag per character of `typed`
 */
export function mismatchFlags(typed, partner) {
  const t = normalizeSequence(typed)
  const p = String(partner ?? '').toUpperCase()
  const out = []
  for (let i = 0; i < t.length; i++) {
    const pb = p[i]
    if (pb == null || pb === '-' || pb === 'N' || t[i] === 'N') { out.push(false); continue }
    out.push(!isComplement(t[i], pb))
  }
  return out
}

/** Count of mismatched positions — the dialog's live "N mismatches" readout. */
export function mismatchCount(typed, partner) {
  return mismatchFlags(typed, partner).filter(Boolean).length
}

/**
 * Would the backend accept this sequence for a strand of `expectedLength` nt?
 *
 * Mirrors the two PATCH /design/strand/{id} rejections — invalid characters and
 * wrong length — so the dialog can block Apply before the round-trip. Mismatched
 * base pairing is deliberately NOT an error: the user is allowed to enter any
 * bases, and mismatches are only highlighted.
 *
 * @returns {{ok: boolean, error: string|null}}
 */
export function validateStrandSequence(typed, expectedLength) {
  const seq = normalizeSequence(typed)
  const bad = invalidBases(seq)
  if (bad.length) {
    return { ok: false, error: `Invalid characters: ${bad.join(', ')}. Only A, T, G, C, N are allowed.` }
  }
  if (seq.length !== expectedLength) {
    return {
      ok: false,
      error: `Need exactly ${expectedLength} bases — you have ${seq.length}.`,
    }
  }
  return { ok: true, error: null }
}

/**
 * Slice each editable overhang span out of a typed sequence.
 *
 * Used only for the optimistic UI preview; PATCH /design/strand/{id} performs the
 * authoritative write-back. Spans marked `editable: false` (an overhang whose
 * sub-domains carry their own `sequence_override`s) are skipped — those bases are
 * owned per sub-domain in the Domain Designer.
 *
 * @param {string} typed
 * @param {{start:number,length:number,kind:string,overhang_id:string|null,editable:boolean}[]} segments
 * @returns {{overhang_id: string, sequence: string}[]}
 */
export function spliceOverhangSegments(typed, segments) {
  const seq = normalizeSequence(typed)
  return (segments ?? [])
    .filter(s => s?.kind === 'overhang' && s.editable && s.overhang_id)
    .map(s => ({
      overhang_id: s.overhang_id,
      sequence: seq.slice(s.start, s.start + s.length),
    }))
}

/**
 * Split a sequence into run-length-merged spans for rendering, tagging each with
 * the segment kind it falls in and whether it is a mismatch.
 *
 * Returns `{text, kind, mismatch}[]` where `kind` is 'duplex' | 'overhang' |
 * 'binder' (from the backend segments) — so the dialog can shade overhang runs
 * and colour mismatched runs in a single pass over the string.
 *
 * @param {string} seq
 * @param {Array} segments
 * @param {boolean[]} [flags] per-position mismatch flags; omitted → all false
 */
export function decorateSequence(seq, segments, flags = []) {
  const s = String(seq ?? '')
  const kindAt = new Array(s.length).fill('duplex')
  for (const seg of segments ?? []) {
    for (let i = seg.start; i < seg.start + seg.length && i < s.length; i++) {
      kindAt[i] = seg.kind
    }
  }
  const out = []
  for (let i = 0; i < s.length; i++) {
    const kind = kindAt[i]
    const mismatch = !!flags[i]
    const prev = out[out.length - 1]
    if (prev && prev.kind === kind && prev.mismatch === mismatch) prev.text += s[i]
    else out.push({ text: s[i], kind, mismatch })
  }
  return out
}

/**
 * Overwrite only the editable spans of `next` onto `current`, keeping the bases
 * of every read-only span verbatim.
 *
 * The dialog uses this on commit so a read-only overhang region (owned by
 * sub-domain overrides) round-trips unchanged even if the textarea's contents
 * were edited across it — the user can never accidentally desync the two stores.
 */
export function preserveReadOnlySpans(next, current, segments) {
  const n = normalizeSequence(next)
  const c = normalizeSequence(current)
  if (!c || c.length !== n.length) return n
  const chars = [...n]
  for (const seg of segments ?? []) {
    if (seg?.editable !== false) continue
    for (let i = seg.start; i < seg.start + seg.length && i < chars.length; i++) {
      chars[i] = c[i]
    }
  }
  return chars.join('')
}
