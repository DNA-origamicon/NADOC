// Shared selected-end forced-ligation rules and action.
//
// End polarity is topology supplied by the backend.  Both the keyboard shortcut
// and the 3D context menu route through this module so they cannot disagree about
// which selected pair is legal or how the endpoint ids map onto the API.

/** Strand-end polarity: '3p' | '5p' | null. */
export function endRole(nuc) {
  if (!nuc) return null
  const three = !!nuc.is_three_prime
  const five = !!nuc.is_five_prime
  if (three === five) return null
  return three ? '3p' : '5p'
}

/** A legal forced ligation joins opposite-polarity ends on different strands. */
export function isValidPair(firstNuc, secondNuc) {
  const firstRole = endRole(firstNuc)
  const secondRole = endRole(secondNuc)
  return !!firstRole && !!secondRole && firstRole !== secondRole &&
    firstNuc.strand_id !== secondNuc.strand_id
}

/** Map a validated pair to the backend fields, independent of selection order. */
export function ligationArgs(firstNuc, secondNuc) {
  const firstIsThree = endRole(firstNuc) === '3p'
  const three = firstIsThree ? firstNuc : secondNuc
  const five = firstIsThree ? secondNuc : firstNuc
  return { three_prime_strand_id: three.strand_id, five_prime_strand_id: five.strand_id }
}

/** Return backend args only when the canonical End selection is exactly one 3' + one 5'. */
export function selectedEndLigationArgs(selectedEnds) {
  if (!Array.isArray(selectedEnds) || selectedEnds.length !== 2) return null
  const [first, second] = selectedEnds
  if (!isValidPair(first?.nuc, second?.nuc)) return null
  return ligationArgs(first.nuc, second.nuc)
}

/** True when the raycast nucleotide is one of the selected canonical ends. */
export function selectedEndsIncludeNuc(selectedEnds, hitNuc) {
  if (!hitNuc) return false
  return selectedEnds.some(({ nuc } = {}) => nuc &&
    nuc.helix_id === hitNuc.helix_id &&
    nuc.bp_index === hitNuc.bp_index &&
    nuc.direction === hitNuc.direction)
}

/** Commit the currently selected End pair. Invalid selections are a safe no-op. */
export async function forceLigateSelectedEnds({ store, selectionManager, api }) {
  if (store.getState().assemblyActive) return false
  const args = selectedEndLigationArgs(selectionManager.getSelectedEndBeads?.())
  if (!args) return false

  // Clear before the topology response rebuilds the scene, avoiding stale glow
  // being projected onto whichever strand inherits an old id.
  selectionManager.clearEndSelection?.()
  const ok = await api.forcedLigation(args.three_prime_strand_id, args.five_prime_strand_id)
  if (!ok) {
    const err = store.getState().lastError
    console.error('[force-ligation] forced ligation failed:', err?.message)
  }
  return !!ok
}
