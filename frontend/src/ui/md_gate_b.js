/**
 * "Gate B" — GPU-resident fallback decision modal.
 *
 * When the fastest GPU mode can't start, the backend PAUSES the job and sets
 * `job.decision` (a {gate:'gpu_resident', title, message, checks, options, …} payload).
 * This renders that decision and lets the user choose an option — "Run in slower GPU
 * mode" (offload) or "Cancel" — via POST /md/jobs/{id}/gpu-decision. The default policy
 * is to ask (a capable GPU is assumed wanted); this is the UI for that choice.
 *
 * Pure helpers (predicate + message) are unit tested; the DOM modal is exercised in
 * jsdom and the running app. Mirrors md_vram_fix.js.
 */

// ── Pure helpers ──────────────────────────────────────────────────────────────

/** True when a paused job is waiting on the GPU-resident fallback decision. */
/** The gates that pause a job to ASK rather than substituting something quietly.
 *  `gpu_resident` — the fastest GPU mode could not start.
 *  `cpu_reroute`  — NAMD's CUDA build hits its tile-list bug on this geometry; the CPU
 *                   build is ~12x slower. This used to reroute silently. */
const DECISION_GATES = new Set(['gpu_resident', 'cpu_reroute'])

export function hasPendingGpuDecision(job) {
  return job?.status === 'paused' && DECISION_GATES.has(job?.decision?.gate)
}

/**
 * Pure: turn a `job.decision` payload into modal content.
 * Returns { title, lines, checks, technicalReason, options }.
 * `retry_hint` adds a line about a newer NAMD build; options always fall back to a
 * single Close so a malformed payload still renders a dismissable modal.
 */
export function gateBMessage(decision) {
  const d = decision || {}
  const lines = []
  if (d.message) lines.push(d.message)
  if (d.retry_hint) {
    lines.push('A newer NAMD build usually fixes this — installing one keeps full speed.')
  }
  const options = Array.isArray(d.options) && d.options.length
    ? d.options
    : [{ id: 'cancel', label: 'Close', primary: false }]
  return {
    title: d.title || 'A decision is needed',
    lines,
    checks: Array.isArray(d.checks) ? d.checks : [],
    technicalReason: d.technical_reason || null,
    options,
  }
}

// ── DOM modal ─────────────────────────────────────────────────────────────────

/**
 * Open the Gate B decision modal. `onChoose(optionId)` runs the choice (the panel maps
 * it to POST /gpu-decision) and may throw to show an inline error. `onDismiss` fires
 * only on Escape / click-outside (hide without choosing — the job stays paused).
 * Returns a `close()` teardown fn (does not fire onDismiss).
 */
export function openGpuDecisionModal({ decision, onChoose, onDismiss } = {}) {
  const msg = gateBMessage(decision)

  const overlay = document.createElement('div')
  overlay.setAttribute('data-testid', 'gpu-decision-modal')
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

  // Check-trail: what NADOC tried, ending on the failed step.
  if (msg.checks.length) {
    const list = document.createElement('div')
    list.style.cssText = 'margin:4px 0 10px;display:flex;flex-direction:column;gap:3px'
    msg.checks.forEach((c) => {
      const row = document.createElement('div')
      row.style.cssText = 'display:flex;align-items:baseline;gap:8px;font-size:12.5px'
      const mark = document.createElement('span')
      mark.textContent = c.ok ? '✓' : '✗'
      mark.style.cssText = `color:${c.ok ? '#3fb950' : '#d29922'};font-weight:700`
      const lbl = document.createElement('span')
      lbl.textContent = c.label
      lbl.style.color = c.ok ? '#8b949e' : '#c9d1d9'
      row.appendChild(mark)
      row.appendChild(lbl)
      list.appendChild(row)
    })
    box.appendChild(list)
  }

  if (msg.technicalReason) {
    const det = document.createElement('details')
    det.style.cssText = 'margin-top:4px'
    const sum = document.createElement('summary')
    sum.textContent = 'Technical detail'
    sum.style.cssText = 'cursor:pointer;color:#8b949e;font-size:12px'
    det.appendChild(sum)
    const pre = document.createElement('pre')
    pre.textContent = msg.technicalReason
    pre.style.cssText =
      'margin:6px 0 0;max-height:140px;overflow:auto;background:#010409;border:1px solid #30363d;'
      + 'border-radius:4px;padding:6px 8px;font-size:11px;color:#8b949e;white-space:pre-wrap'
    det.appendChild(pre)
    box.appendChild(det)
  }

  const btnRow = document.createElement('div')
  btnRow.style.cssText = 'display:flex;justify-content:flex-end;gap:8px;margin-top:14px'
  box.appendChild(btnRow)

  const errEl = document.createElement('div')
  errEl.style.cssText = 'color:#f85149;font-size:12px;margin-top:8px;display:none'
  box.appendChild(errEl)

  function close() {
    overlay.remove()
    document.removeEventListener('keydown', onKey)
  }
  function dismiss() { close(); onDismiss?.() }
  function onKey(e) { if (e.key === 'Escape') dismiss() }
  document.addEventListener('keydown', onKey)
  overlay.addEventListener('click', (e) => { if (e.target === overlay) dismiss() })

  msg.options.forEach((opt) => {
    const b = document.createElement('button')
    b.textContent = opt.label
    b.setAttribute('data-choice', opt.id)
    b.style.cssText = opt.primary
      ? 'background:#238636;border:1px solid #2ea043;color:#fff;border-radius:4px;'
        + 'padding:5px 12px;cursor:pointer;font-size:12px;font-weight:600'
      : 'background:#21262d;border:1px solid #30363d;color:#c9d1d9;border-radius:4px;'
        + 'padding:5px 12px;cursor:pointer;font-size:12px'
    b.addEventListener('click', async () => {
      const label = b.textContent
      b.disabled = true
      b.textContent = 'Working…'
      errEl.style.display = 'none'
      try {
        await onChoose?.(opt.id)
        close()
      } catch (err) {
        b.disabled = false
        b.textContent = label
        errEl.textContent = `Couldn't apply that choice: ${err?.message || err}`
        errEl.style.display = ''
      }
    })
    btnRow.appendChild(b)
  })

  document.body.appendChild(overlay)
  return close
}
