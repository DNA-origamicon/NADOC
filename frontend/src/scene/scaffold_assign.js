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
