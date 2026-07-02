/**
 * Shared "Gen" (generate overhang sequence) flow — used by BOTH the Overhang
 * Connections panel per-side Gen buttons and the Overhangs sidebar row Gen buttons.
 *
 * Behaviour:
 *   • No connected partner, or the partner has no sequence → generate a fresh
 *     random (Johnson) sequence for THIS overhang.
 *   • Partner has a sequence but THIS one doesn't → fill THIS one with the reverse
 *     complement of the partner (they pair).
 *   • BOTH already have a sequence → ASK (3-way choice):
 *       'pair'     — new random for this + set the partner to its reverse complement
 *       'override' — new random for this overhang only (leave the partner)
 *       'rc'       — set this = reverse complement of the partner (leave the partner)
 *
 * Every "set to reverse complement" write goes through the injected `rcOfPartner`
 * effect, which is REGISTER-AWARE in the panels (see design_queries
 * `overhangRcOfPartner`): it overwrites only the paired-window bases of the target
 * with the WC complement of the register-aligned partner bases and PRESERVES the
 * toehold, so the target keeps its own length. The default fallback (tests) is a
 * plain reverse complement of the partner's full sequence.
 */
import { showChoice as _defaultShowChoice } from './primitives/choice.js'
import { showToast } from './toast.js'

const JOHNSON = 'Using the Johnson et al. overhang algorithm — DOI: 10.1021/acs.nanolett.9b02786'
const _WC = { A: 'T', T: 'A', C: 'G', G: 'C', N: 'N' }

/** Reverse complement (ACGTN, uppercased). */
export function reverseComplement(seq) {
  const s = String(seq ?? '').toUpperCase()
  let out = ''
  for (let i = s.length - 1; i >= 0; i--) out += _WC[s[i]] ?? s[i]
  return out
}

/**
 * Run the Gen flow for `thisId`, coordinating with the connected `otherId`
 * (may be null). Pure orchestration over injected effects — `showChoice` is
 * injectable so the 3-way branch is unit-testable without a real modal.
 *
 * @param {string} thisId
 * @param {string|null} otherId
 * @param {object} deps
 * @param {object} deps.api        — generateOverhangRandomSequence(id) / patchOverhang(id, {sequence})
 * @param {(id: string) => string|null} deps.getSeq  — current sequence (read fresh from the store)
 * @param {(targetId: string, sourceId: string) => string|null} [deps.rcOfPartner]  — the new
 *        FULL sequence for `targetId` making it the reverse complement of `sourceId`. Panels inject
 *        the REGISTER-AWARE `overhangRcOfPartner` (paired window RC'd, toehold + length preserved).
 *        Returns null when it can't compute (→ that write is skipped). Default: plain RC of source.
 * @param {typeof _defaultShowChoice} [deps.showChoice]
 * @returns {Promise<void>}
 */
/** A real (non-empty, not all-N placeholder) sequence, or null. */
function _real(seq) {
  const s = String(seq ?? '').trim()
  return (s && !/^n+$/i.test(s)) ? s : null
}

export async function runOverhangGen(thisId, otherId, {
  api, getSeq,
  rcOfPartner = (_targetId, sourceId) => reverseComplement(_real(getSeq(sourceId)) ?? ''),
  showChoice = _defaultShowChoice,
}) {
  if (!thisId) return
  const thisSeq  = _real(getSeq(thisId))
  const otherSeq = otherId ? _real(getSeq(otherId)) : null

  // Set `targetId` to the (register-aware) reverse complement of `sourceId`.
  const setRc = async (targetId, sourceId) => {
    const seq = rcOfPartner(targetId, sourceId)
    if (seq != null) await api.patchOverhang(targetId, { sequence: seq })
  }

  // No partner sequence to pair against → plain random for this overhang.
  if (!otherSeq) {
    showToast(JOHNSON)
    await api.generateOverhangRandomSequence(thisId)
    return
  }

  // Partner sequenced, this one empty → fill this with RC(partner).
  if (!thisSeq) {
    await setRc(thisId, otherId)
    return
  }

  // Both already have a sequence → ask the user which they want.
  const pick = await showChoice({
    title: 'Generate overhang sequence',
    message: 'Both overhangs already have a sequence. What would you like to do?',
    options: [
      { value: 'pair',     label: 'New pair',
        tooltip: 'Generate a new random sequence for this overhang and set the partner to its reverse complement.' },
      { value: 'override', label: 'New (this only)',
        tooltip: 'Generate a new random sequence for this overhang only — leave the partner unchanged.' },
      { value: 'rc',       label: 'RC of partner',
        tooltip: "Set this overhang's paired window to the reverse complement of the partner (toehold preserved)." },
    ],
  })
  if (!pick) return

  if (pick === 'pair') {
    showToast(JOHNSON)
    await api.generateOverhangRandomSequence(thisId)
    if (_real(getSeq(thisId))) await setRc(otherId, thisId)   // partner ← RC of the freshly-generated this
  } else if (pick === 'override') {
    showToast(JOHNSON)
    await api.generateOverhangRandomSequence(thisId)
  } else if (pick === 'rc') {
    await setRc(thisId, otherId)
  }
}
