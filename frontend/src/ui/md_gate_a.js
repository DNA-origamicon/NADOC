/**
 * "Gate A" — pre-flight water-box SIZE decisions, shown when the user presses Relax,
 * BEFORE anything is built. Driven by POST /md/jobs/preflight-vram → {tier, …advice}:
 *
 *   ok / skipped → no gate (full box fits, or sizing couldn't run)
 *   a3 → the fully solvated system does not fit → hard-stop modal
 *
 * Pure `gateAMessage` is unit tested; the DOM modal is exercised in jsdom + the app.
 * Mirrors md_vram_fix.js / md_gate_b.js chrome.
 */

import { openChoiceModal } from './md_modal.js'

function _gb(mb) { return (Number(mb) / 1024).toFixed(1) }
function _commas(n) { return Math.round(Number(n)).toLocaleString('en-US') }

// ── Pure message builder ────────────────────────────────────────────────────────

/**
 * Pure: a preflight advice → gate content, or null when there's no gate (ok/skipped).
 * Returns { tier, isNotice?, notice?, title?, lines?, canProceed?, proceedLabel? }.
 */
export function gateAMessage(advice) {
  const tier = advice?.tier
  if (!advice || advice.skipped || !tier || tier === 'ok') return null

  const need = advice.current_vram_mb || advice.required_vram_mb || advice.estimated_vram_mb
  return {
    tier, canProceed: false, title: 'The fully solvated system does not fit',
    lines: [
      `The complete periodic water box is approximately ${_commas(advice.current_atoms)} atoms `
      + `and needs about ${_gb(need)} GB; this target has ${_gb(advice.vram_mb)} GB.`,
      'Explicit-solvent jobs are not reduced to a finite water shell. Select hardware with '
      + 'more memory, reduce the design size, or use an available implicit-solvent protocol.',
    ],
  }
}

// ── DOM modal ─────────────────────────────────────────────────────────────────────

/**
 * Open the Gate A modal for an oversized full-box estimate and resolve the decision:
 *   true  → no gate
 *   false → cancel / hard-stop
 */
export function openGateAModal(advice) {
  const msg = gateAMessage(advice)
  if (!msg || msg.isNotice) return Promise.resolve(true)

  const choices = [{ label: msg.canProceed ? 'Cancel' : 'Close', value: false, choice: 'cancel' }]
  if (msg.canProceed) {
    choices.push({ label: msg.proceedLabel, value: true, choice: 'proceed', primary: true })
  }
  return openChoiceModal({
    testid: 'gate-a-modal',
    dataset: { tier: msg.tier },
    title: msg.title,
    lines: msg.lines,
    choices,
    dismissValue: false,
  })
}
