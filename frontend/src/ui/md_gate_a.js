/**
 * "Gate A" — pre-flight water-box SIZE decisions, shown when the user presses Relax,
 * BEFORE anything is built. Driven by POST /md/jobs/preflight-vram → {tier, …advice}:
 *
 *   ok / skipped → no gate (full box fits, or sizing couldn't run)
 *   a1 → a comfortable thinner shell fits → auto-apply + a non-blocking NOTICE (a toast,
 *        handled by the caller — gateAMessage returns { isNotice, notice })
 *   a2 → only a TIGHT shell fits (accuracy trade-off) → a modal: use tight padding / cancel
 *   a3 → won't fit even at the tightest shell → a hard-stop modal (no proceed)
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

  // The chosen protocol may FORBID a carve — the `literature` preset locks it off, because
  // a carved cell has no bulk phase for the published ionic condition to be defined in, no
  // barostat (so no settle stage and no box-size trace), and a vacuum far field. Every
  // fitting tier below exists to APPLY a carve, so when carving is off the only question
  // left is whether the full box fits.
  //
  // The answer is a WARNING, not a refusal. Whether a system fits is a property of today's
  // hardware and the pre-flight is an estimate — the user is entitled to attempt the full
  // box and let NAMD answer. So: say plainly what is likely to happen, name the
  // alternatives, and offer Cancel / Run anyway.
  if (advice.carve_allowed === false && tier !== 'ok') {
    const need = advice.required_vram_mb || advice.estimated_vram_mb
    return {
      tier, canProceed: true, proceedLabel: 'Run anyway',
      title: 'This design may not fit — and this protocol will not shrink the water',
      lines: [
        need
          ? `The full water box needs roughly ${_gb(need)} GB of GPU memory; your card has `
            + `${_gb(advice.vram_mb)} GB.`
          : `The full water box is unlikely to fit your ${_gb(advice.vram_mb)} GB GPU.`,
        'This protocol reproduces a published recipe, so it will NOT trim the water to fit: '
        + 'a carved cell has no bulk phase for its ionic condition to be defined in, no '
        + 'barostat, and therefore neither the settle stage nor the box-size trace the '
        + 'reference uses to judge equilibration.',
        'You can run it anyway — the estimate is not a measurement, and NAMD will tell you '
        + 'for certain. If it does run out of memory it fails at the first segment, before '
        + 'any real compute is spent.',
        'Alternatives: lower the water padding; seed from an oxDNA or mrDNA relaxation so '
        + 'the all-atom leg is short; run it on RunPod or the cluster; or pick a protocol '
        + 'that permits a carve.',
      ],
    }
  }

  if (tier === 'a1') {
    const ang = Math.round((advice.recommended_shell_nm || 0) * 10)
    return {
      tier, isNotice: true,
      notice: `Large design — using a ${ang} Å water jacket to fit your ${_gb(advice.vram_mb)} GB GPU. `
        + `This is normal and doesn’t affect accuracy.`,
    }
  }
  if (tier === 'a2') {
    const ang = Math.round((advice.recommended_shell_nm || 0) * 10)
    return {
      tier, canProceed: true, proceedLabel: `Use ${ang} Å padding`,
      title: 'Fitting your design to the GPU',
      lines: [
        `To fit your ${_gb(advice.vram_mb)} GB GPU, the water padding must drop to ${ang} Å — `
        + `tighter than the usual 15 Å.`,
        `The structure still runs (≈${_commas(advice.estimated_atoms)} atoms); the very edges `
        + `may be slightly affected.`,
      ],
    }
  }
  // a3 — hard stop
  const tight = Math.round((advice.tightest_shell_nm || 0) * 10)
  return {
    tier, canProceed: false, title: 'Too large for this GPU',
    lines: [
      `This design needs about ${_gb(advice.required_vram_mb)} GB of GPU memory — more than your `
      + `${_gb(advice.vram_mb)} GB card, even with minimal water (${tight} Å, `
      + `≈${_commas(advice.tightest_atoms)} atoms).`,
      'It can’t run locally as-is. A smaller design, or a GPU with more memory, would run it.',
    ],
  }
}

// ── DOM modal ─────────────────────────────────────────────────────────────────────

/**
 * Open the Gate A modal for an A2/A3 advice and resolve to the launch decision:
 *   true  → proceed (A2 accepted — caller applies the recommended shell)
 *   false → cancel / hard-stop (A3, or A2 cancelled, or dismissed)
 * ok/skipped/A1 need no modal → resolves true immediately (A1's notice is the caller's toast).
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
