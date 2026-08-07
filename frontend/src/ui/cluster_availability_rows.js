/**
 * Pure formatting + markup for the Alpine GPU availability popup.
 *
 * Turns the backend `/api/cluster/availability` rows (per-partition GPU occupancy,
 * pending queue depth, and the three wait signals) into the table the user reads.
 * Kept pure + separately tested so number formatting, the "unknown vs zero" rule
 * and the row markup are verified without a DOM or a network.
 *
 * The one rule worth stating loudly: a missing wait estimate renders as "unknown",
 * never as "starts now". Backend `wait_min: null` means SLURM could not place the
 * job — presenting that as an immediate start is the whole failure mode this view
 * exists to avoid.
 */

const _esc = s => String(s ?? '').replace(/[&<>"]/g, c =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]))

/** Wall-clock from minutes: minutes under 1 h, hours under a day, else days. */
export function formatWait(minutes) {
  if (minutes == null || !isFinite(minutes)) return 'unknown'
  const m = Math.max(0, Math.round(minutes))
  if (m < 1) return 'now'
  if (m < 60) return `${m} min`
  const h = Math.floor(m / 60)
  const rem = m % 60
  if (h < 24) return rem < 5 ? `${h} h` : `${h} h ${rem} m`
  const d = Math.floor(h / 24)
  const remH = h % 24
  return remH < 1 ? `${d} d` : `${d} d ${remH} h`
}

/** Hours → compact wall-clock for the "time to result" column. */
export function formatHours(hours) {
  if (hours == null || !isFinite(hours)) return '—'
  if (hours < 1) return `${Math.round(hours * 60)} min`
  if (hours < 48) return `${hours.toFixed(1)} h`
  return `${(hours / 24).toFixed(1)} d`
}

/** SU cost — whole units above 100, one decimal below (allocations are integer-ish). */
export function formatSu(su) {
  if (su == null || !isFinite(su)) return '—'
  if (su >= 100_000) return `${Math.round(su / 1000)}k SU`
  if (su >= 100) return `${Math.round(su)} SU`
  return `${su.toFixed(1)} SU`
}

/**
 * Availability dot for a partition: green when it could start now, amber when
 * something is free but queued behind other work, red when nothing is free.
 */
export function availabilityBadge(row) {
  if (row.request_only) return { text: 'request-only', color: '#8b949e' }
  const free = row.gpus_free ?? 0
  if (!free) return { text: 'full', color: '#f85149' }
  if ((row.pending_gpus ?? 0) > 0) return { text: 'contended', color: '#d29922' }
  return { text: 'free', color: '#3fb950' }
}

/** One row's display fields (pure) — the unit the render + tests share. */
export function availabilityView(row) {
  return {
    partition: row.partition,
    gpu: row.gpu_model || row.gres_type || '—',
    badge: availabilityBadge(row),
    free: row.request_only ? '—' : `${row.gpus_free ?? 0} / ${row.gpus_total ?? 0}`,
    // MIG slices are shown apart from whole cards, never added to them: NADOC asks
    // for a whole GPU, so a free 35 GB slice is not capacity this job can use.
    mig: (row.mig_total ?? 0) ? `+${row.mig_free ?? 0}/${row.mig_total} MIG` : '',
    nodes: row.request_only
      ? `${row.nodes_total ?? 0} nodes`
      : `${row.nodes_idle ?? 0} idle · ${row.nodes_mixed ?? 0} partial · ` +
        `${row.nodes_alloc ?? 0} busy${(row.nodes_down ?? 0) ? ` · ${row.nodes_down} down` : ''}`,
    pending: (row.pending_jobs ?? 0)
      ? `${row.pending_jobs} job${row.pending_jobs === 1 ? '' : 's'} (${row.pending_gpus ?? 0} GPU)`
      : 'none',
    reason: row.top_reason || '',
    wait: row.request_only ? 'request access' : formatWait(row.wait_min),
    waitBasis: row.wait_basis || '',
    ttr: formatHours(row.time_to_result_h),
    cost: formatSu(row.job_cost_su),
    // Cost EFFICIENCY, not just total: equally-fast partitions can differ ~30%.
    suPerNs: row.job_su_per_ns != null ? `${Math.round(row.job_su_per_ns)} SU/ns` : '',
    nsday: row.job_ns_per_day != null ? `${row.job_ns_per_day} ns/day` : '',
    maxWall: row.max_walltime_h != null ? `${row.max_walltime_h} h` : '—',
    requestOnly: !!row.request_only,
  }
}

/** Column header for the table. */
export function availabilityHeader() {
  const cols = ['Partition', 'GPUs free', 'Queue', 'Est. wait', 'This job', 'Done in']
  return (
    `<div style="display:grid;grid-template-columns:1.5fr .8fr 1fr .9fr 1fr .8fr;gap:10px;` +
    `padding:4px 9px;font-size:9px;color:#6e7681;text-transform:uppercase;letter-spacing:.04em;` +
    `border-bottom:1px solid #30363d">` +
    cols.map(c => `<span>${c}</span>`).join('') +
    `</div>`
  )
}

/** Rows as HTML for the table body. */
export function renderAvailabilityRows(rows) {
  if (!(rows && rows.length)) return ''
  return rows
    .map(row => {
      const v = availabilityView(row)
      const dim = v.requestOnly ? 'opacity:.55;' : ''
      return (
        `<div class="alpine-avail-row" data-partition="${_esc(v.partition)}" ` +
        `style="display:grid;grid-template-columns:1.5fr .8fr 1fr .9fr 1fr .8fr;gap:10px;` +
        `align-items:baseline;padding:6px 9px;border-radius:4px;${dim}">` +
        `<span><span style="color:#c9d1d9;font-weight:600">${_esc(v.partition)}</span> ` +
        `<span style="color:#6e7681;font-size:9px">${_esc(v.gpu)}</span><br>` +
        `<span style="color:${v.badge.color};font-size:9px">● ${_esc(v.badge.text)}</span></span>` +
        `<span style="color:#8b949e" title="${_esc(v.nodes)}">${_esc(v.free)}` +
        (v.mig ? `<br><span style="color:#6e7681;font-size:9px" ` +
                 `title="MIG slices — a whole-GPU job cannot use these">${_esc(v.mig)}</span>` : '') +
        `</span>` +
        `<span style="color:#8b949e" title="${_esc(v.reason)}">${_esc(v.pending)}</span>` +
        `<span style="color:#c9d1d9" title="${_esc(v.waitBasis)}">${_esc(v.wait)}</span>` +
        `<span style="color:#8b949e" title="${_esc(v.nsday)}">${_esc(v.cost)}` +
        (v.suPerNs ? `<br><span style="color:#6e7681;font-size:9px">${_esc(v.suPerNs)}</span>` : '') +
        `</span>` +
        `<span style="color:#3fb950" title="est. wait + runtime">${_esc(v.ttr)}</span>` +
        `</div>`
      )
    })
    .join('')
}

/** The footnote under the table — provenance of the numbers, and any probe warnings. */
export function availabilityMessage(resp, { busy = false, error = '' } = {}) {
  if (busy) return 'Querying Alpine…'
  if (error) return error
  if (!resp) return 'Click “GPU availability” to query Alpine for free GPUs and queue depth.'
  if (!(resp.partitions && resp.partitions.length)) return 'No GPU partitions reported.'
  const bits = []
  if (resp.checked_at) bits.push(`checked ${resp.checked_at.replace('T', ' ')}${resp.cached ? ' (cached)' : ''}`)
  if (resp.history_scope) bits.push(`history: last ${resp.history_days} d, ${resp.history_scope}`)
  if (!resp.job_shape) bits.push('no job selected — cost/time columns need a prepared job')
  if (resp.warnings && resp.warnings.length) bits.push(`⚠ ${resp.warnings.join('; ')}`)
  return bits.join(' · ')
}

/**
 * The one-line recommendation above the table: the partition that finishes soonest.
 * Only rows with a real time-to-result qualify — an unknown wait must never win by
 * looking like zero.
 */
export function bestPartitionHint(rows) {
  const usable = (rows || []).filter(r => !r.request_only && r.time_to_result_h != null)
  if (!usable.length) return ''
  const best = usable.reduce((a, b) => (b.time_to_result_h < a.time_to_result_h ? b : a))
  const v = availabilityView(best)
  return `Fastest to a finished run: ${best.partition} — starts in ${v.wait}, done in ${v.ttr} (${v.cost})`
}
