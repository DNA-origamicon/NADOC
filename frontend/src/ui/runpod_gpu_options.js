/**
 * Pure formatting + rendering for the RunPod GPU picker (Clusters card).
 *
 * Turns the backend `/runpod/gpu-options` rows (label, vram_gb, usd_per_hour, available,
 * ns_day, relax_hours, est_cost) into the scrollable list the user reads: price, estimated
 * relaxation wall-clock, and estimated cost per card. Kept pure + separately tested so the
 * number formatting and row markup are verified without a DOM or a network.
 */

/** Human relax wall-clock: minutes under 1 h, hours under 2 days, else days. */
export function formatRelaxTime(hours) {
  if (hours == null || !isFinite(hours)) return '—'
  if (hours < 1) return `${Math.round(hours * 60)} min`
  if (hours < 48) return `${hours.toFixed(1)} h`
  return `${(hours / 24).toFixed(1)} d`
}

/** Dollar cost: cents under $10, whole dollars above (a relax run is never sub-cent-precise). */
export function formatCost(usd) {
  if (usd == null || !isFinite(usd)) return '—'
  return usd < 10 ? `$${usd.toFixed(2)}` : `$${Math.round(usd)}`
}

/** Stock dot: green in-stock / red out / grey unknown (live stock not available). */
export function stockBadge(available) {
  if (available === true) return { text: 'in stock', color: '#3fb950' }
  if (available === false) return { text: 'out', color: '#f85149' }
  return { text: 'unknown', color: '#8b949e' }
}

/** The message under the list — prompt / busy / empty / error / indicative-price note. */
export function gpuOptionsMessage(resp, { busy = false } = {}) {
  if (busy) return 'Checking RunPod availability…'
  if (!resp) return 'Click “Check RunPod GPUs” to list availability, cost and time.'
  if (resp.ok === false) return resp.note || 'Could not list GPUs — is a design loaded?'
  if (!(resp.gpus && resp.gpus.length)) return 'No compatible GPUs available right now.'
  return resp.note || ''
}

/** One row's display fields (pure) — the unit the render + tests share. */
export function gpuOptionView(row) {
  return {
    key: row.key,
    label: row.label,
    vram: `${row.vram_gb} GB`,
    price: `$${row.usd_per_hour}/hr${row.live_price ? '' : '*'}`,
    time: formatRelaxTime(row.relax_hours),
    cost: formatCost(row.est_cost),
    nsday: row.ns_day != null ? `${row.ns_day} ns/day` : '',
    stock: stockBadge(row.available),
  }
}

const _esc = s => String(s).replace(/[&<>"]/g, c =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]))

/**
 * One row's display fields for the Job Wizard's WHOLE-PLAN table (pure).
 *
 * The wizard asks a wider question than the Clusters card: it knows the production length as
 * well as the ladder, so relaxation and production are shown as separate columns plus a total.
 * `overBudget` is advisory — an over-budget row is flagged but stays selectable, because
 * raising the cap is a legitimate response to seeing the number.
 */
export function jobOptionView(row, { budgetUsd = null } = {}) {
  const total = row.total_cost
  return {
    ...gpuOptionView(row),
    relaxCost: formatCost(row.relax_cost),
    production: formatRelaxTime(row.production_hours),
    productionCost: formatCost(row.production_cost),
    total: formatRelaxTime(row.total_hours),
    totalCost: formatCost(total),
    nsdayRelax: row.ns_day_relax != null ? `${row.ns_day_relax} ns/day relaxing` : '',
    overBudget: budgetUsd != null && total != null && total > budgetUsd,
    eligible: row.eligible !== false,
    insufficientReason: row.insufficient_reason || '',
  }
}

/** Column header for the wizard's six-column table. */
export function jobOptionsHeader() {
  return (
    `<div style="display:grid;grid-template-columns:1.6fr auto auto auto auto;gap:8px;` +
    `padding:2px 7px;font-size:9px;color:#6e7681;text-transform:uppercase;letter-spacing:.04em">` +
    `<span>GPU</span><span>$/hr</span><span>relax</span><span>production</span>` +
    `<span>total</span></div>`
  )
}

/**
 * Rows for the wizard's table; `selectedKey` highlights the chosen card.
 *
 * **The order is the backend's and is never re-sorted here.** `plan_options` already applied
 * the two-axis rule (within 0.6x of the fastest card's ns/day, then cheapest $/ns). A
 * client-side "cheapest first" would put a glacially slow card at the top — exactly the
 * fallback that silently degraded a real run by 4x.
 */
export function renderJobOptionRows(gpus, selectedKey = null, { budgetUsd = null } = {}) {
  if (!(gpus && gpus.length)) return ''
  return gpus
    .map((row, i) => {
      const v = jobOptionView(row, { budgetUsd })
      const sel = row.key === selectedKey
      const eligible = v.eligible
      const costColor = v.overBudget ? '#d29922' : '#3fb950'
      const title = !eligible
        ? `Insufficient for this job: ${v.insufficientReason}`
        : v.overBudget
        ? `Estimated ${v.totalCost} — over your cap. Raise the cap or shorten the run.`
        : 'est. total cost for this whole plan'
      return (
        `<div class="runpod-gpu-row" data-key="${_esc(row.key)}" ` +
        `data-eligible="${eligible}" role="${eligible ? 'button' : 'note'}" ` +
        `tabindex="${eligible ? '0' : '-1'}" title="${_esc(title)}" ` +
        `style="display:grid;grid-template-columns:1.6fr auto auto auto auto;gap:8px;` +
        `align-items:baseline;padding:5px 7px;border-radius:4px;cursor:${eligible ? 'pointer' : 'not-allowed'};` +
        `background:${!eligible ? 'rgba(248,81,73,.09)' : sel ? 'rgba(31,111,235,.18)' : 'transparent'};` +
        `border:1px solid ${!eligible ? 'rgba(248,81,73,.65)' : sel ? '#1f6feb' : 'transparent'};` +
        `opacity:${eligible ? 1 : .82}">` +
        `<span><span style="color:${eligible ? '#c9d1d9' : '#f85149'};font-weight:${sel ? 600 : 400}">${_esc(v.label)}</span> ` +
        `<span style="color:#6e7681;font-size:9px">${v.vram}</span> ` +
        `<span style="color:${v.stock.color};font-size:9px">● ${v.stock.text}</span>` +
        (i === 0 && eligible
          ? ' <span style="color:#58a6ff;font-size:9px">best value</span>'
          : '') +
        (!eligible
          ? `<br><span style="color:#f85149;font-size:9px">⚠ ${_esc(v.insufficientReason)}</span>`
          : '') +
        `<br><span style="color:#6e7681;font-size:9px">${v.nsday}` +
        `${v.nsdayRelax ? ` · ${v.nsdayRelax}` : ''}</span></span>` +
        `<span style="color:#8b949e" title="price per hour">${v.price}</span>` +
        `<span style="color:#8b949e" title="relaxation ladder">${v.time}<br>` +
        `<span style="font-size:9px">${v.relaxCost}</span></span>` +
        `<span style="color:#8b949e" title="production run">${v.production}<br>` +
        `<span style="font-size:9px">${v.productionCost}</span></span>` +
        `<span style="color:${costColor}" title="${_esc(title)}">${v.total}<br>` +
        `<span style="font-size:9px;font-weight:600">${v.totalCost}</span></span>` +
        `</div>`
      )
    })
    .join('')
}

/** Column header for the scrollable box. */
export function gpuOptionsHeader() {
  return (
    `<div style="display:grid;grid-template-columns:1fr auto auto auto;gap:8px;` +
    `padding:2px 7px;font-size:9px;color:#6e7681;text-transform:uppercase;letter-spacing:.04em">` +
    `<span>GPU</span><span>$/hr</span><span>relax</span><span>cost</span></div>`
  )
}

/** Rows as HTML for the scrollable box; `selectedKey` highlights the chosen card. */
export function renderGpuOptionRows(gpus, selectedKey = null) {
  if (!(gpus && gpus.length)) return ''
  return gpus
    .map(row => {
      const v = gpuOptionView(row)
      const sel = row.key === selectedKey
      return (
        `<div class="runpod-gpu-row" data-key="${_esc(row.key)}" role="button" tabindex="0" ` +
        `style="display:grid;grid-template-columns:1fr auto auto auto;gap:8px;align-items:baseline;` +
        `padding:5px 7px;border-radius:4px;cursor:pointer;` +
        `background:${sel ? 'rgba(31,111,235,.18)' : 'transparent'};` +
        `border:1px solid ${sel ? '#1f6feb' : 'transparent'}">` +
        `<span><span style="color:#c9d1d9;font-weight:${sel ? 600 : 400}">${_esc(v.label)}</span> ` +
        `<span style="color:#6e7681;font-size:9px">${v.vram}</span> ` +
        `<span style="color:${v.stock.color};font-size:9px">● ${v.stock.text}</span></span>` +
        `<span style="color:#8b949e" title="price per hour">${v.price}</span>` +
        `<span style="color:#8b949e" title="est. relaxation wall-clock${v.nsday ? ' · ' + v.nsday : ''}">` +
        `${v.time}</span>` +
        `<span style="color:#3fb950" title="est. relaxation cost">${v.cost}</span>` +
        `</div>`
      )
    })
    .join('')
}
