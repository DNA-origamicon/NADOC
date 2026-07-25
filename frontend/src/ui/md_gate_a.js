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
  return new Promise((resolve) => {
    if (!msg || msg.isNotice) { resolve(true); return }

    let done = false
    const finish = (v) => { if (done) return; done = true; close(); resolve(v) }

    const overlay = document.createElement('div')
    overlay.setAttribute('data-testid', 'gate-a-modal')
    overlay.dataset.tier = msg.tier
    overlay.style.cssText =
      'position:fixed;inset:0;background:rgba(0,0,0,0.6);z-index:10000;'
      + 'display:flex;align-items:center;justify-content:center'

    const box = document.createElement('div')
    box.style.cssText =
      'background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:18px 20px;'
      + 'max-width:460px;width:90%;color:#c9d1d9;font-size:13px;box-shadow:0 8px 30px rgba(0,0,0,0.5)'
    overlay.appendChild(box)

    const h = document.createElement('div')
    h.textContent = msg.title
    h.style.cssText = 'font-size:15px;font-weight:600;margin-bottom:10px;color:#f0f6fc'
    box.appendChild(h)

    msg.lines.forEach((t) => {
      const p = document.createElement('p')
      p.textContent = t
      p.style.cssText = 'margin:0 0 8px;line-height:1.45;color:#c9d1d9'
      box.appendChild(p)
    })

    const btnRow = document.createElement('div')
    btnRow.style.cssText = 'display:flex;justify-content:flex-end;gap:8px;margin-top:14px'
    box.appendChild(btnRow)

    function close() { overlay.remove(); document.removeEventListener('keydown', onKey) }
    function onKey(e) { if (e.key === 'Escape') finish(false) }
    document.addEventListener('keydown', onKey)
    overlay.addEventListener('click', (e) => { if (e.target === overlay) finish(false) })

    const cancel = document.createElement('button')
    cancel.textContent = msg.canProceed ? 'Cancel' : 'Close'
    cancel.setAttribute('data-choice', 'cancel')
    cancel.style.cssText =
      'background:#21262d;border:1px solid #30363d;color:#c9d1d9;border-radius:4px;'
      + 'padding:5px 12px;cursor:pointer;font-size:12px'
    cancel.addEventListener('click', () => finish(false))
    btnRow.appendChild(cancel)

    if (msg.canProceed) {
      const go = document.createElement('button')
      go.textContent = msg.proceedLabel
      go.setAttribute('data-choice', 'proceed')
      go.style.cssText =
        'background:#238636;border:1px solid #2ea043;color:#fff;border-radius:4px;'
        + 'padding:5px 12px;cursor:pointer;font-size:12px;font-weight:600'
      go.addEventListener('click', () => finish(true))
      btnRow.appendChild(go)
    }

    document.body.appendChild(overlay)
  })
}
