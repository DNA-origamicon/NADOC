/**
 * Scaffold-assignment helpers extracted from main.js. Pure (no DOM/store).
 * Unit-tested in scaffold_assign.test.js.
 */

/** Known scaffold sequence lengths (nt). */
export const SCAFFOLD_LENGTHS = { M13mp18: 7249, p7560: 7560, p8064: 8064 }

/**
 * Warning line for the assign-scaffold modal, or null if no warning applies.
 * - With a custom sequence: warn when it's shorter than the scaffold (rest → 'N').
 * - Otherwise: warn when the scaffold exceeds the chosen reference sequence.
 * (Was the branch logic inside _ascUpdateWarning.)
 */
export function ascWarningText({ customRaw = '', totalNt = 0, scaffoldName = 'M13mp18', scaffoldLen = 0 } = {}) {
  if (customRaw) {
    if (customRaw.length < totalNt) {
      return `⚠ Custom sequence (${customRaw.length} nt) is shorter than scaffold (${totalNt} nt). `
        + `${totalNt - customRaw.length} bases will be assigned 'N'.`
    }
    return null
  }
  if (totalNt > scaffoldLen) {
    return `⚠ Scaffold (${totalNt} nt) exceeds ${scaffoldName} (${scaffoldLen} nt). `
      + `${totalNt - scaffoldLen} bases will be assigned 'N'.`
  }
  return null
}

/**
 * Count scaffold nucleotides for a design, honouring loop/skip deltas:
 * skip (delta=-1 → 0 nt) and loop (delta=+1 → 2 nt). Mirrors the backend
 * _strand_nt_with_skips logic. Returns 0 if there is no scaffold strand.
 * (Was the lsMap-build + domain-walk inside _openScaffoldModal.)
 *
 * `strandId` targets one specific scaffold strand (the right-click "Assign
 * sequence…" path); omit it for the first scaffold in the design. A strandId
 * that is missing or not a scaffold counts 0.
 */
export function countScaffoldNt(currentDesign, strandId = null) {
  // Build (helixId + ':' + bpIndex) → delta map from helix loop_skips.
  const lsMap = new Map()
  for (const helix of currentDesign?.helices ?? []) {
    for (const ls of helix.loop_skips ?? []) {
      lsMap.set(`${helix.id}:${ls.bp_index}`, ls.delta)
    }
  }
  const scaffold = strandId != null
    ? currentDesign?.strands?.find(s => s.id === strandId && s.strand_type === 'scaffold')
    : currentDesign?.strands?.find(s => s.strand_type === 'scaffold')
  let totalNt = 0
  if (scaffold) {
    for (const d of scaffold.domains) {
      const isForward = d.direction === 'FORWARD'
      const step = isForward ? 1 : -1
      for (let bp = d.start_bp; isForward ? bp <= d.end_bp : bp >= d.end_bp; bp += step) {
        const delta = lsMap.get(`${d.helix_id}:${bp}`) ?? 0
        if (delta <= -1) continue
        totalNt += delta + 1
      }
    }
  }
  return totalNt
}
