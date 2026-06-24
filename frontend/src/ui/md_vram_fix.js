/**
 * "Fix" affordance for failed MD relaxations.
 *
 * When a NAMD relax fails, the job list shows a "Fix" button.  Clicking it fetches
 * a server diagnosis (/api/md/jobs/{id}/fix-advice) and opens a popup that explains
 * the failure and — for foreseeable, fixable cases — offers a one-click re-run with
 * adjusted settings:
 *
 *   - vram_oom    → downsize: a water-shell carve sized to the detected GPU VRAM
 *   - instability → gentle:   re-run the whole ladder with the soft integrator
 *   - gpu_error   → retry:    resume (often a transient GPU/driver state)
 *   - other       → show the log tail; no automatic remedy
 *
 * Pure helpers (predicate + message) are unit tested; the DOM modal is exercised
 * in jsdom and the running app.
 */

// ── Pure helpers ──────────────────────────────────────────────────────────────

/** Show a "Fix" button for any failed relax we've classified. */
export function shouldShowFixButton(job) {
  return job?.status === 'failed' && !!job?.failure_kind
}

function _gb(mb) { return (Number(mb) / 1024).toFixed(1) }
function _commas(n) { return Math.round(Number(n)).toLocaleString('en-US') }

/**
 * Pure: turn a /fix-advice response into popup content.
 * Returns { title, lines, logExcerpt, canApply, applyLabel, action, shellAng }.
 *   action describes what Apply does: {type:'refit', body:{…}} or {type:'retry'}.
 *   shellAng (downsize only) seeds an editable "Water shell (Å)" input.
 */
export function fixMessage(advice) {
  const kind = advice?.failure_kind || 'other'
  const remedy = advice?.remedy || 'none'
  const logExcerpt = advice?.log_excerpt || null

  if (kind === 'vram_oom') return _vramMessage(advice, remedy, logExcerpt)

  if (kind === 'instability' && remedy === 'gentle') {
    return {
      title: 'The simulation went unstable',
      lines: [
        'An atom blew up in the first steps of dynamics — a residual strain in the '
        + 'starting model that the normal soft-start didn’t fully absorb.',
        'Re-running the whole relaxation ladder with the gentle integrator '
        + '(flexible bonds + 1 fs) usually gets past it. It’s slower, but stable.',
      ],
      logExcerpt,
      canApply: true,
      applyLabel: 'Re-run with extra-gentle relaxation',
      action: { type: 'refit', body: { force_soft: true } },
    }
  }

  if (kind === 'gpu_error' && remedy === 'retry') {
    return {
      title: 'GPU / driver error',
      lines: [
        'NAMD hit a CUDA error that isn’t out-of-memory (often a transient GPU or '
        + 'driver state, e.g. another job using the card).',
        'Resuming the run from its last checkpoint usually clears it. If it recurs, '
        + 'check the GPU is free (nvidia-smi) before retrying.',
      ],
      logExcerpt,
      canApply: true,
      applyLabel: 'Retry (resume)',
      action: { type: 'retry' },
    }
  }

  return {
    title: 'The run failed',
    lines: [
      advice?.error || 'This job failed for a reason we couldn’t classify automatically.',
      'See the log excerpt below for the NAMD error.',
    ],
    logExcerpt,
    canApply: false,
  }
}

function _vramMessage(advice, remedy, logExcerpt) {
  if (advice?.vram_detected === false) {
    return {
      title: 'Could not read GPU memory',
      lines: [
        'nvidia-smi did not report this device’s VRAM, so a downsize target can’t '
        + 'be computed automatically.',
        'You can still re-run manually with a smaller "Water shell (Å)" value.',
      ],
      logExcerpt, canApply: false,
    }
  }
  if (advice?.profile_available === false) {
    return {
      title: 'Not enough package data to recommend a fix',
      lines: ['The solvated package is missing its size profile, so a downsize can’t be estimated.'],
      logExcerpt, canApply: false,
    }
  }

  const lines = [
    `This run needs about ${_gb(advice.current_vram_mb)} GB of GPU memory, but the `
    + `card has ${_gb(advice.vram_mb)} GB.`,
    `System size: ${_commas(advice.current_atoms)} atoms `
    + `(about ${_commas(advice.max_atoms)} fit on this card).`,
  ]
  if (remedy === 'downsize' && advice.feasible) {
    const ang = Math.round(advice.recommended_shell_nm * 10)
    lines.push(
      `Keeping only water within ${ang} Å of the DNA (and running NVT) drops it to `
      + `about ${_commas(advice.estimated_atoms)} atoms (~${_gb(advice.estimated_vram_mb)} GB) — which fits.`,
    )
    return {
      title: 'Ran out of GPU memory',
      lines, logExcerpt,
      canApply: true,
      applyLabel: `Re-run with ${ang} Å water shell`,
      action: { type: 'refit', body: {} },   // water_shell_nm filled from the input
      shellAng: ang,
    }
  }
  const tight = Math.round((advice.tightest_shell_nm ?? 0) * 10)
  lines.push(
    `Even the tightest ${tight} Å shell is about ${_commas(advice.tightest_atoms)} atoms `
    + `(needs ~${_gb(advice.required_vram_mb)} GB). This system is too large for this GPU.`,
  )
  return { title: 'Ran out of GPU memory', lines, logExcerpt, canApply: false }
}

// ── DOM modal ─────────────────────────────────────────────────────────────────

/**
 * Open the Fix popup.  `advice` is a /fix-advice response; `onApply(action)` runs
 * the chosen remedy (the panel maps action → /refit or /start).  Returns close fn.
 */
export function openVramFixModal({ advice, onApply, onClose } = {}) {
  const msg = fixMessage(advice)

  const overlay = document.createElement('div')
  overlay.setAttribute('data-testid', 'vram-fix-modal')
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

  let shellInput = null
  if (msg.canApply && msg.shellAng != null) {
    const row = document.createElement('label')
    row.style.cssText = 'display:flex;align-items:center;gap:8px;margin:12px 0 4px;color:#8b949e'
    row.appendChild(document.createTextNode('Water shell (Å)'))
    shellInput = document.createElement('input')
    shellInput.type = 'number'
    shellInput.min = '6'
    shellInput.step = '1'
    shellInput.value = String(msg.shellAng)
    shellInput.style.cssText =
      'width:80px;background:#161b22;border:1px solid #30363d;color:#c9d1d9;'
      + 'border-radius:3px;padding:3px 6px;font-size:13px'
    row.appendChild(shellInput)
    box.appendChild(row)
    const hint = document.createElement('div')
    hint.textContent = 'Smaller = fewer atoms (more headroom); ≥6 Å keeps the simulation valid.'
    hint.style.cssText = 'font-size:11px;color:#6e7681;margin-bottom:6px'
    box.appendChild(hint)
  }

  if (msg.logExcerpt) {
    const det = document.createElement('details')
    det.style.cssText = 'margin-top:8px'
    const sum = document.createElement('summary')
    sum.textContent = 'NAMD log (tail)'
    sum.style.cssText = 'cursor:pointer;color:#8b949e;font-size:12px'
    det.appendChild(sum)
    const pre = document.createElement('pre')
    pre.textContent = msg.logExcerpt
    pre.style.cssText =
      'margin:6px 0 0;max-height:160px;overflow:auto;background:#010409;border:1px solid #30363d;'
      + 'border-radius:4px;padding:6px 8px;font-size:11px;color:#8b949e;white-space:pre-wrap'
    det.appendChild(pre)
    box.appendChild(det)
  }

  const btnRow = document.createElement('div')
  btnRow.style.cssText = 'display:flex;justify-content:flex-end;gap:8px;margin-top:14px'
  box.appendChild(btnRow)

  function close() {
    overlay.remove()
    document.removeEventListener('keydown', onKey)
    onClose?.()
  }
  function onKey(e) { if (e.key === 'Escape') close() }
  document.addEventListener('keydown', onKey)
  overlay.addEventListener('click', (e) => { if (e.target === overlay) close() })

  const cancel = document.createElement('button')
  cancel.textContent = msg.canApply ? 'Cancel' : 'Close'
  cancel.style.cssText =
    'background:#21262d;border:1px solid #30363d;color:#c9d1d9;border-radius:4px;'
    + 'padding:5px 12px;cursor:pointer;font-size:12px'
  cancel.addEventListener('click', close)
  btnRow.appendChild(cancel)

  if (msg.canApply) {
    const apply = document.createElement('button')
    apply.textContent = msg.applyLabel
    apply.style.cssText =
      'background:#238636;border:1px solid #2ea043;color:#fff;border-radius:4px;'
      + 'padding:5px 12px;cursor:pointer;font-size:12px;font-weight:600'
    apply.addEventListener('click', async () => {
      const action = JSON.parse(JSON.stringify(msg.action))
      if (shellInput) {
        const ang = parseFloat(shellInput.value || String(msg.shellAng))
        action.body.water_shell_nm = (Number.isFinite(ang) ? ang : msg.shellAng) / 10
      }
      apply.disabled = true
      apply.textContent = 'Starting…'
      try {
        await onApply?.(action)
        close()
      } catch (err) {
        apply.disabled = false
        apply.textContent = msg.applyLabel
        const e = document.createElement('div')
        e.textContent = `Could not start re-run: ${err?.message || err}`
        e.style.cssText = 'color:#f85149;font-size:12px;margin-top:8px'
        box.appendChild(e)
      }
    })
    btnRow.appendChild(apply)
  }

  document.body.appendChild(overlay)
  return close
}
