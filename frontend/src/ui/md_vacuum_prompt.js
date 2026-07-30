/**
 * The "skip the vacuum shape step?" prompt.  DORMANT — nothing imports this.
 *
 * The vacuum pre-stage was retired on 2026-07-30 (see backend/core/namd_vacuum.py for
 * why), so the panel no longer asks.  Kept alongside the dormant builder so reviving the
 * stage is one import rather than a rewrite; its tests still run.
 *
 * The published protocol (Yoo et al., Methods Mol Biol 1811 §3.2) relaxes an origami's
 * SHAPE in vacuum before solvating, and NADOC now does too. But exp48 measured the step
 * to be useless-to-harmful on very small structures: a 2-helix bundle has no global shape
 * to relax, so it only pivots about its single junction and ends up needing a 6.8% BIGGER
 * water box. From 6 helices up it genuinely compacts the structure (−7 to −9%).
 *
 * So the step runs by default and this asks first when the design is below the threshold.
 * Answering is required — dismissing cancels the launch rather than silently picking.
 */

import { openChoiceModal } from './md_modal.js'

/** Designs with fewer helices than this get asked (backend: namd_vacuum.VACUUM_MIN_HELICES). */
export const VACUUM_MIN_HELICES = 4

/** Resolution values, so callers never compare bare booleans. */
export const VACUUM_RUN = 'run'
export const VACUUM_SKIP = 'skip'
export const VACUUM_CANCEL = 'cancel'

/**
 * Pure: does this design need the prompt?
 * @param {number} helixCount
 */
export function needsVacuumPrompt(helixCount) {
  return Number.isFinite(helixCount) && helixCount > 0 && helixCount < VACUUM_MIN_HELICES
}

/**
 * Pure: the prompt's content for a given helix count (null when no prompt is needed).
 */
export function vacuumPromptMessage(helixCount) {
  if (!needsVacuumPrompt(helixCount)) return null
  const n = Math.round(helixCount)
  return {
    title: 'Skip the vacuum shape step?',
    lines: [
      `The standard protocol relaxes the shape in vacuum before adding water. That step `
      + `is what turns the idealised, perfectly parallel helices into the real structure.`,
      `Your design has ${n} ${n === 1 ? 'helix' : 'helices'}, which has no overall shape to `
      + `relax — measured on a 2-helix bundle, the step made the water box 6.8% BIGGER `
      + `rather than smaller, so it costs time and gains nothing.`,
      'Skipping goes straight to the water simulation. Running it anyway is harmless, just slower.',
    ],
  }
}

/**
 * Ask, and resolve to VACUUM_SKIP / VACUUM_RUN / VACUUM_CANCEL.
 * Resolves VACUUM_RUN immediately when the design is big enough to need no prompt.
 */
export function openVacuumPromptModal(helixCount) {
  const msg = vacuumPromptMessage(helixCount)
  if (!msg) return Promise.resolve(VACUUM_RUN)
  return openChoiceModal({
    testid: 'vacuum-prestage-modal',
    dataset: { helices: String(Math.round(helixCount)) },
    title: msg.title,
    lines: msg.lines,
    choices: [
      { label: 'Run it anyway', value: VACUUM_RUN, choice: 'run' },
      { label: 'Skip it', value: VACUUM_SKIP, choice: 'skip', primary: true },
    ],
    dismissValue: VACUUM_CANCEL,
  })
}
