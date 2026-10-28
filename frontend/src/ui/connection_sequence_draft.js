import { capSequenceToLength, overhangDomainLength } from '../scene/design_queries.js'
import { reverseComplement } from './reverse_complement.js'

/** Existing A-drives-B sequence policy, prepared without changing the part. */
export async function connectionSequenceDraft(design, aId, bId, generate) {
  const a = design.overhangs.find(o => o.id === aId)
  const b = design.overhangs.find(o => o.id === bId)
  if (!a || !b || aId === bId) throw new Error('Select two current overhangs.')
  const length = id => overhangDomainLength(design, id) ?? undefined
  const rc = (sequence, id) => capSequenceToLength(reverseComplement(sequence), length(id))
  let aSeq = a.sequence || null, bSeq = b.sequence || null
  if (!aSeq && !bSeq) aSeq = await generate(aId)
  if (!aSeq && bSeq) aSeq = rc(bSeq, aId)
  else if (!bSeq || reverseComplement(aSeq) !== bSeq.toUpperCase()) bSeq = rc(aSeq, bId)
  return { overhang_a_seq: aSeq, overhang_b_seq: bSeq }
}
