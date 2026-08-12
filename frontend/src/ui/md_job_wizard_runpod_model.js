/**
 * Pure logic for the Job Wizard's RunPod card — money, storage, and the gate.
 *
 * Its own module rather than more of `md_job_wizard_target_model.js` because renting hardware
 * is a different concern from picking a partition: everything here is about not spending money
 * by accident, and every function is written so a wrong answer is the EXPENSIVE-side wrong
 * answer rather than the reassuring one.
 *
 * Two rules from the runbook are encoded here rather than left to the renderer:
 *
 *   1. **Never re-rank.** The backend already applied the two-axis rule (within 0.6x of the
 *      fastest card's ns/day, then cheapest $/ns). A client-side "cheapest first" would
 *      resurrect the A6000 trap — a fallback that was 4x worse value and silently degraded a
 *      whole run. Nothing in this file sorts.
 *   2. **The cap is per-POD.** Every string about the budget has to survive the fact that a
 *      resume gets the cap afresh, so N reclaims can cost N x it.
 *
 * No DOM, no fetch — `md_job_wizard_runpod.js` owns both.
 */

import { balanceStatus } from './runpod_setup.js'

/** Matches `runpod_script.MIN_LIFETIME_S` — the pod's kill-switch never goes below 15 min. */
const MIN_LIFETIME_S = 900

/** Matches `runpod_script.DEFAULT_BUDGET_USD`. */
export const DEFAULT_BUDGET_USD = 15

/**
 * The `/runpod/job-preview` request body, derived from the wizard's live plan.
 *
 * The interesting part is the TIMESTEP. A relaxation ladder is not one timestep: minimisation,
 * a soft 1-2 fs first chunk and the 4 fs ladder all sit in the same phase. What the backend
 * needs is a per-phase `(ns, timestep_fs)` pair that is mutually consistent with the true step
 * count, because wall-clock is `steps x ms_step` and the timestep cancels out:
 *
 *     hours = ns / ns_day * 24  and  ns_day = 86.4 * ts / ms_step   =>   hours = steps * ms_step / 3.6e6
 *
 * So we hand over the step-weighted MEAN timestep (`1e6 * ns / steps`) and the hours come out
 * exact for a mixed-timestep ladder. Quoting a single nominal 4 fs instead would under-report
 * the ladder — which is the direction that costs money.
 */
export function runpodPlanShape(plan, { productionNsIntent = null } = {}) {
  const stages = Array.isArray(plan?.stages) ? plan.stages : []
  const acc = { relax: { ns: 0, steps: 0 }, production: { ns: 0, steps: 0 } }
  const segments = []
  for (const s of stages) {
    const steps = Number(s?.steps) || 0
    const ns = Number(s?.ns) || 0
    const bucket = s?.role === 'production' ? acc.production : acc.relax
    bucket.ns += ns
    bucket.steps += steps
    segments.push({
      steps,
      // A stage with no dcdfreq writes no trajectory; 0 would divide by zero downstream, and
      // the backend clamps to >= 1 anyway.
      dcd_freq: Math.max(1, Number(s?.params?.dcdfreq) || 1),
    })
  }

  // In relaxation mode there are no production stages at all, but the user has still told us
  // how long they intend to produce — it is the cell-sizing decision (`production_ns_intent`),
  // and it is the honest basis for "what will this whole thing cost". Flagged as an intent so
  // the UI can caption it rather than passing it off as planned.
  let productionSource = acc.production.steps > 0 ? 'plan' : 'none'
  let productionNs = acc.production.ns
  let productionDt = _meanTimestep(acc.production, 4.0)
  if (productionSource === 'none' && Number(productionNsIntent) > 0) {
    productionSource = 'intent'
    productionNs = Number(productionNsIntent)
    productionDt = 4.0                 // the only production timestep NADOC runs
  }

  return {
    n_atoms: null,                     // sized server-side from the active design
    relax_ns: Number(acc.relax.ns.toFixed(4)),
    relax_steps: acc.relax.steps,
    relax_timestep_fs: _meanTimestep(acc.relax, 4.0),
    production_ns: Number(Number(productionNs).toFixed(4)),
    production_steps: acc.production.steps,
    production_timestep_fs: productionDt,
    production_source: productionSource,
    stages: segments,
  }
}

function _meanTimestep({ ns, steps }, fallback) {
  if (!(steps > 0) || !(ns > 0)) return fallback
  return Number((1e6 * ns / steps).toFixed(4))
}

/**
 * The cache key behind the refresh no-op guard.
 *
 * In it: everything that changes an hour, a dollar or a byte. Out of it, deliberately:
 *   - **the budget** — it moves no hour and no rate, and `budgetState` re-gates purely, so
 *     typing in the cap must never cost a round trip.
 *   - **the selected GPU** — every card's numbers are already in the response.
 *   - **n_atoms** — sized server-side from the design, which cannot change while the wizard is
 *     open. This is what protects the ~26 s cold solvation estimate behind it.
 *
 * `dcd_freq` IS in it even though it changes no cost: it moves the storage forecast, and a run
 * that silently overflows the volume dies mid-segment and is paid for twice.
 */
export function runpodEstimateKey(shape, { connected = false } = {}) {
  if (!shape) return ''
  return [
    shape.relax_steps,
    shape.relax_timestep_fs,
    shape.production_steps,
    shape.production_ns,
    shape.production_timestep_fs,
    (shape.stages || []).map(s => `${s.steps}x${s.dcd_freq}`).join(','),
    connected ? 1 : 0,                 // live prices vs indicative ones are different answers
  ].join('|')
}

/** The row the user picked, else the best-value one the backend ranked first. */
export function selectedRow(preview, gpuKey) {
  const rows = preview?.gpus || []
  return rows.find(r => r.key === gpuKey && r.eligible !== false)
    || rows.find(r => r.eligible !== false) || null
}

/**
 * How long the cap buys on a given card. Mirrors `runpod_script.lifetime_for_budget`,
 * **including its 15-minute floor** — promising a shorter kill-switch than the pod will
 * actually get would be a safety claim the backend does not honour.
 */
export function budgetHours(budgetUsd, usdPerHour) {
  const b = Number(budgetUsd)
  const rate = Number(usdPerHour)
  if (!(b > 0) || !(rate > 0)) return null
  return Math.max(MIN_LIFETIME_S / 3600, b / rate)
}

/** Pretty hours: minutes under 1 h, hours under 2 days, else days. */
export function formatHours(hours) {
  if (hours == null || !isFinite(hours)) return '—'
  if (hours < 1) return `${Math.round(hours * 60)} min`
  if (hours < 48) return `${hours.toFixed(1)} h`
  return `${(hours / 24).toFixed(1)} d`
}

export function formatUsd(usd) {
  if (usd == null || !isFinite(usd)) return '—'
  return usd < 10 ? `$${usd.toFixed(2)}` : `$${Math.round(usd)}`
}

export function formatBytes(bytes) {
  if (bytes == null || !isFinite(bytes)) return '—'
  const gb = bytes / 1024 ** 3
  if (gb >= 1) return `${gb.toFixed(1)} GB`
  return `${Math.max(1, Math.round(bytes / 1024 ** 2))} MB`
}

/**
 * The estimate table: relaxation and production as separate lines plus a total.
 *
 * Split because they are different KINDS of cost. The ladder is a fixed entry fee for getting
 * a usable structure; production is the part the user is actually choosing the length of. One
 * merged number hides which of the two a change just moved.
 */
export function estimateRows(row, shape) {
  if (!row) return []
  const rows = []
  if (row.relax_hours != null || row.relax_cost != null) {
    rows.push(['Relaxation ladder',
      `${formatHours(row.relax_hours)} · ${formatUsd(row.relax_cost)}`,
      `${shape?.relax_ns ?? '?'} ns at ${shape?.relax_timestep_fs ?? '?'} fs`])
  }
  if (row.production_hours != null || row.production_cost != null) {
    rows.push(['Production',
      `${formatHours(row.production_hours)} · ${formatUsd(row.production_cost)}`,
      shape?.production_source === 'intent'
        ? `${shape.production_ns} ns intended (not planned yet)`
        : `${shape?.production_ns ?? '?'} ns at ${shape?.production_timestep_fs ?? '?'} fs`])
  } else if (shape?.production_source === 'none') {
    rows.push(['Production', 'not set',
      'Set an intended production length to see what the whole run costs.'])
  }
  rows.push(['Total', `${formatHours(row.total_hours)} · ${formatUsd(row.total_cost)}`,
    `${row.ns_day ?? '?'} ns/day on this card`])
  return rows
}

/** Capacity vs forecast, as label/value/note triples. */
export function storageRows(storage) {
  if (!storage) return []
  const rows = [['Trajectories + restarts', formatBytes(storage.output_bytes), '']]
  if (storage.package_bytes) {
    const st = storage.staging || {}
    rows.push(['Upload before it starts', formatBytes(storage.package_bytes),
      st.minutes != null
        ? `${st.minutes} min of pod time${st.usd != null ? ` (${formatUsd(st.usd)})` : ''}`
        : ''])
  }
  if (storage.volume_size_gb != null) {
    rows.push(['Network volume', `${storage.volume_size_gb} GB`,
      storage.used_known
        ? `${formatBytes(storage.free_bytes)} free`
        : 'RunPod reports a volume’s size but not its free space — the patched NAMD, the '
          + 'packages and every earlier checkpoint already live on it.'])
  }
  return rows
}

/**
 * Budget verdict. `over` is the gate; the rest is context.
 *
 * The estimate compared here already includes the staging upload, because that bills before
 * NAMD runs a step — leaving it out is how a "just under budget" run goes over.
 */
export function budgetState({ budget, balance, livePods = [] } = {}) {
  const cap = Number(budget?.budget_usd)
  const est = budget?.estimated_usd
  const over = !!budget?.over_budget
  const bal = balanceStatus(balance)
  const billing = livePods.reduce((a, p) => a + (Number(p.cost_per_hr) || 0), 0)
  return {
    over,
    estimated: est,
    cap,
    message: over
      ? `Estimated ${formatUsd(est)} against a ${formatUsd(cap)} cap.`
      : (est != null ? `Estimated ${formatUsd(est)} of a ${formatUsd(cap)} cap.` : ''),
    balance: bal,
    // The raw number as well as the sentence: the gate compares it against the estimate, and
    // `balanceStatus` only formats.
    balanceUsd: balance?.available === true ? Number(balance.balance) : null,
    // Not a gate: a legitimate second run is a normal thing to want. But an unnoticed pod is
    // the most expensive bug in this subsystem, so it is always on screen.
    livePods: livePods.length,
    billingPerHour: billing,
    billingMessage: livePods.length
      ? `${livePods.length} pod${livePods.length === 1 ? '' : 's'} already billing`
        + `${billing ? ` at ${formatUsd(billing)}/hr` : ''}.`
      : '',
  }
}

/**
 * THE GATE — can this job move past step 1?
 *
 * Ordered so the reason names the FIRST thing to fix, not the last thing checked. Every branch
 * gets its own sentence: "RunPod is not ready" tells the user nothing about which of five
 * different problems they have.
 */
export function runpodReadiness({
  preflight = null, volumeId = null, gpuKey = null, preview = null,
  budget = null, busy = false, blockReason = '',
} = {}) {
  if (!preflight) {
    return { ready: false, reason: 'Checking whether RunPod can run this job…' }
  }
  if (!preflight.ok) {
    return { ready: false, reason: blockReason || 'RunPod is not ready to take a job yet.' }
  }
  if (!volumeId) {
    return { ready: false,
      reason: 'Pick the network volume that carries your patched NAMD and packages.' }
  }
  if (busy) return { ready: false, reason: 'Working out what this run would cost…' }
  if (!preview?.gpus?.length) {
    return { ready: false, reason: 'No compatible GPU is available right now.' }
  }
  if (!gpuKey) {
    return { ready: false, reason: 'Pick a GPU — compare both $/ns and ns/day.' }
  }
  if (budget?.over) {
    return { ready: false,
      reason: `${budget.message} Raise the cap or shorten the run.` }
  }
  // RunPod destroys every pod the instant the balance hits zero, so starting a run you cannot
  // afford to finish wastes the whole ladder, not just the overspend.
  // `Number(null)` is 0, so an UNKNOWN balance would read as "no credit" and block every job
  // on a disconnected session. Only a genuinely reported number gates.
  const bal = budget?.balanceUsd == null ? null : Number(budget.balanceUsd)
  if (bal != null && isFinite(bal) && budget?.estimated != null && bal < budget.estimated) {
    return { ready: false,
      reason: `Your RunPod balance (${formatUsd(bal)}) is below the estimate. `
        + 'RunPod destroys every pod at $0.' }
  }
  return { ready: true, reason: '' }
}
