/**
 * "Gate A" — pre-flight water-box SIZE decisions, shown when the user presses Relax,
 * BEFORE anything is built. Driven by POST /md/jobs/preflight-vram → {tier, …advice}:
 *
 *   ok → no gate (full box fits)
 *   unknown / skipped / missing → requirements must be established
 *   headroom → insufficient reserve; current envelopes block launch
 *   a3 → the fully solvated system exceeds capacity → hard-stop modal
 *
 * Pure `gateAMessage` is unit tested; the DOM modal is exercised in jsdom + the app.
 * Mirrors md_vram_fix.js / md_gate_b.js chrome.
 */

import { openChoiceModal } from './md_modal.js'

function _gb(mb, digits = 1) { return (Number(mb) / 1024).toFixed(digits) }
function _commas(n) { return Math.round(Number(n)).toLocaleString('en-US') }

// ── Pure message builder ────────────────────────────────────────────────────────

/**
 * Pure: a preflight advice → gate content, or null when the estimate fits.
 * Returns { tier, isNotice?, notice?, title?, lines?, canProceed?, proceedLabel? }.
 */
export function gateAMessage(advice) {
  const tier = !advice || advice.skipped || !advice.tier ? 'unknown' : advice.tier
  if (tier === 'ok') return null
  if (tier === 'unknown') {
    return { tier, canProceed: false, title: 'Memory requirements need verification',
      lines: [advice?.reason || 'A reliable memory budget is unavailable.',
        'Recheck the configuration or use a compute target with a verified resource budget.'] }
  }

  const need = advice.current_vram_mb || advice.required_vram_mb || advice.estimated_vram_mb
  const hostBound = advice.bound === 'host RAM'
  const resource = hostBound ? 'Host RAM' : 'GPU memory'
  const lines = [advice.atom_estimate_kind === 'upper_bound'
    ? `The complete periodic water box is budgeted for up to ${_commas(advice.current_atoms)} atoms.`
    : `The complete periodic water box is approximately ${_commas(advice.current_atoms)} atoms.`]
  if (Number.isFinite(advice.preparation_ram_mb)) {
    lines.push(`Preparation budget: ${_gb(advice.preparation_ram_mb)} GB host RAM.`)
  }
  if (advice.vram_mb != null && need != null) {
    lines.push(`Estimated GPU memory: ${_gb(need)} GB; GPU capacity: ${_gb(advice.vram_mb)} GB.`)
  }
  if (advice.host_mb != null) {
    lines.push(`${advice.current_host_mb != null ? `Estimated host RAM: ${_gb(advice.current_host_mb)} GB; ` : ''}`
      + `currently available host RAM: ${_gb(advice.host_mb)} GB.`)
  }
  const offload = advice.execution_modes?.offload
  if (offload?.supported && Number.isFinite(offload.ram_mib) && Number.isFinite(offload.gpu_mib)) {
    lines.push(`CUDA offload estimate: ${_gb(offload.ram_mib + (offload.health_ram_mib || 0))} GB host RAM including health analysis, `
      + `${_gb(offload.gpu_mib)} GB GPU memory. Select GPU-resident mode off to use this lower-memory option; throughput may be lower.`)
  }
  if (tier === 'headroom') {
    const budget = hostBound ? advice.host_budget_mb : advice.vram_budget_mb
    const estimated = hostBound ? advice.current_host_mb : need
    lines.push(`${resource} is the limiting resource: the ${_gb(estimated, 2)} GB estimate exceeds `
      + `the recommended ${_gb(budget, 2)} GB budget, which reserves memory for other applications and runtime overhead.`)
    if (advice.require_reserved_budget) {
      lines.push('Free memory, select CUDA offload, or choose a larger compute target before launching.')
      return { tier, canProceed: false, title: `${resource} reserve is insufficient`, lines }
    }
    lines.push('The estimate is within capacity. You can continue with the current box, or free memory first. '
      + 'Actual memory use may be higher than estimated.')
    return { tier, canProceed: true, title: `${resource} headroom is limited`, lines,
      proceedLabel: 'Continue with current box' }
  }
  lines.push(`${resource} is the limiting resource. `
    + (hostBound ? 'Free host RAM, select a machine with more RAM, or reduce the system size.'
      : 'Select CUDA offload, a GPU with more memory, Alpine, or RunPod.'))
  return { tier, canProceed: false, title: 'The fully solvated system does not fit', lines }
}

// ── DOM modal ─────────────────────────────────────────────────────────────────────

/**
 * Open the Gate A modal for an oversized full-box estimate and resolve the decision:
 *   true  → no gate, or the user accepts reduced headroom
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
