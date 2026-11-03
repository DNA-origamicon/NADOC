import { el } from './primitives/dom.js'
import { formatHours, formatUsd } from './md_job_wizard_runpod_model.js'

export function quoteSummary(quote) {
  if (!quote?.available) return { duration: 'Unavailable', cost: '—', note: quote?.reason || 'Choose a plan first.' }
  const unknown = quote.unknown?.length ? ` + ${quote.unknown.join('; ').toLowerCase()}` : ''
  const money = n => quote.cost_unit === 'SU' ? `${Math.round(n).toLocaleString()} SU` : formatUsd(n)
  return {
    duration: `${formatHours(quote.known_hours)} (${formatHours(quote.low_hours)}–${formatHours(quote.high_hours)})${unknown}`,
    cost: quote.target === 'local' ? '$0 rental fee; electricity excluded'
      : quote.cost == null ? 'Unknown rate' : `${money(quote.cost)} (${money(quote.low_cost)}–${money(quote.high_cost)})`,
    note: quote.target === 'runpod'
      ? `${formatHours(quote.billed_hours)} billed. ${quote.transfer_mode === 's3' ? 'S3 upload/download are outside GPU rental.' : 'SSH upload/download keep the GPU rented.'}`
        + (quote.storage_monthly_cost == null ? ' Network-volume price unknown.' : ` Standard volume: ${formatUsd(quote.storage_window_cost)} for this window; ${formatUsd(quote.storage_monthly_cost)}/month while retained.`)
      : quote.target === 'alpine' ? `${quote.submissions} submission(s); SU are allocation units, not dollars.`
        : quote.calibrated_compute ? 'Compute calibrated to this engine and local hardware.' : 'Some stages use throughput assumptions.',
  }
}

export function comparisonRows(preview, gpuKey) {
  if (!preview?.sized) return []
  const card = preview.runpod?.find(r => r.key === gpuKey && r.eligible !== false)
    || preview.runpod?.find(r => r.eligible !== false)
  return [
    { label: 'Local', quote: preview.local },
    { label: `Alpine · ${preview.alpine?.gpu_profile_label || preview.alpine?.partition || 'selected resource'}`, quote: preview.alpine?.completion },
    { label: `Runpod · ${card?.label || 'no eligible GPU'}${card?.live_price ? ' · live price' : ' · indicative price'}`, quote: card?.completion },
  ].map(row => ({ ...row, ...quoteSummary(row.quote) }))
}

export function initRuntimeComparison({ mount, fetchPreview, getShape, getPartition, getGresType, getGpuKey, onAssumptionsChange = () => {} }) {
  let preview = null
  let key = ''
  let generation = 0
  let disposed = false
  let busy = false
  let error = ''
  let upload = getShape?.()?.upload_mbps || 11
  let download = getShape?.()?.download_mbps || 50

  function paint() {
    if (disposed) return
    mount.replaceChildren()
    mount.appendChild(el('strong', { text: 'Time until results and total cost', attrs: { style: 'font-size:12px' } }))
    mount.appendChild(el('p', { text: 'Planning ranges include preparation, startup, health checks, transfers and result processing. Queue/capacity waits and retries are additional.', attrs: { style: 'font-size:11px;color:#8b949e' } }))
    if (busy || error || !preview?.sized) {
      mount.appendChild(el('p', { text: busy ? 'Updating estimates…' : error || preview?.reason || 'Choose a plan to compare targets.' }))
    } else {
      const table = el('table', { attrs: { style: 'width:100%;font-size:11px;border-spacing:6px' } })
      const head = el('tr')
      for (const text of ['Target', 'Time until results (range)', 'Cost (range)']) head.appendChild(el('th', { text, attrs: { style: 'text-align:left' } }))
      table.appendChild(head)
      for (const row of comparisonRows(preview, getGpuKey?.())) {
        const tr = el('tr')
        for (const text of [row.label, row.duration, row.cost]) tr.appendChild(el('td', { text, attrs: { style: 'vertical-align:top' } }))
        table.appendChild(tr)
        const detail = el('details')
        detail.appendChild(el('summary', { text: row.note || 'Estimate details' }))
        for (const c of row.quote?.components || []) detail.appendChild(el('div', { text: `${c.name}: ${formatHours(c.hours)} (${formatHours(c.low_hours)}–${formatHours(c.high_hours)}) · ${c.basis}` }))
        if (row.quote?.note) detail.appendChild(el('p', { text: row.quote.note }))
        const td = el('td', { attrs: { colspan: '3', style: 'color:#8b949e;padding-bottom:8px' } })
        td.appendChild(detail)
        const notes = el('tr'); notes.appendChild(td); table.appendChild(notes)
      }
      mount.appendChild(table)
    }
    const controls = el('div', { attrs: { style: 'display:flex;gap:8px;font-size:10px;align-items:center' } })
    for (const [label, value, update] of [
      ['Upload Mbps', upload, v => { upload = v }], ['Download Mbps', download, v => { download = v }],
    ]) {
      const l = el('label', { text: `${label} ` })
      const input = el('input', { attrs: { type: 'number', min: '.1', step: '1', value: String(value), style: 'width:65px' } })
      input.addEventListener('change', () => { if (Number(input.value) > 0) { update(Number(input.value)); onAssumptionsChange({ upload_mbps: upload, download_mbps: download }); void refresh() } })
      l.appendChild(input); controls.appendChild(l)
    }
    const button = el('button', { text: 'Refresh prices', attrs: { type: 'button', disabled: busy } })
    button.addEventListener('click', () => { key = ''; void refresh() })
    controls.appendChild(button); mount.appendChild(controls)
  }

  async function refresh() {
    if (disposed || !fetchPreview) return
    const shape = getShape?.()
    if (!shape?.stages?.length && !(shape?.production_ns > 0)) { paint(); return }
    const body = { ...shape, partition: getPartition?.() || 'ah200', gres_type: getGresType?.() || null,
      upload_mbps: upload, download_mbps: download }
    const nextKey = JSON.stringify(body)
    if (nextKey === key && (preview || busy)) { paint(); return }
    key = nextKey
    const request = ++generation
    busy = true; error = ''; paint()
    try {
      const result = await fetchPreview(body)
      if (disposed || request !== generation) return
      preview = result
    } catch (err) {
      if (disposed || request !== generation) return
      error = `Could not estimate duration: ${err?.message || err}`
      preview = null
    } finally {
      if (!disposed && request === generation) { busy = false; paint() }
    }
  }
  paint()
  return { refresh, dispose() { disposed = true; generation++ } }
}
