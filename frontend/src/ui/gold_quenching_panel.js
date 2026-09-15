import { GOLD_QUENCHING_DATA } from '../scene/gold_quenching.js'
import './gold_quenching_panel.css'

/** View-only diagnostics: no design mutations or history entries. */
export function initGoldQuenchingPanel() {
  const button = document.createElement('button')
  button.id = 'gold-quenching-status'
  button.hidden = true
  button.title = 'Inspect gold quenching estimates, missing calibrations and literature sources'
  document.body.append(button)
  let results = [], dialog = null, lastText = '', lastRows = ''
  const number = value => Number.isFinite(value) ? value.toFixed(2) : '—'
  function updateRows() {
    if (!dialog) return
    const rows = results.flatMap(result => result.pairs.map(pair => [
      result.donor.label, pair.goldId, number(pair.goldDiameterNm), number(pair.distanceNm),
      pair.reason ?? `${pair.profile.interpolated ? 'Size-interpolated' : 'Reference'} NSET; d₀ ${number(pair.profile.d0_nm)} nm; n = ${pair.profile.exponent}`,
      pair.quenching === null ? 'Unknown' : `${number(100 * pair.quenching)}% (pair only)`,
    ]))
    const text = JSON.stringify(rows)
    if (text === lastRows) return
    lastRows = text
    const body = dialog.querySelector('tbody')
    body.replaceChildren()
    for (const values of rows) {
      const row = document.createElement('tr')
      for (const value of values) { const cell = document.createElement('td'); cell.textContent = value; row.append(cell) }
      body.append(row)
    }
  }
  button.onclick = () => {
    if (dialog) return
    dialog = document.createElement('dialog')
    dialog.id = 'gold-quenching-dialog'
    dialog.setAttribute('aria-labelledby', 'gold-quenching-title')
    dialog.innerHTML = `<h2 id="gold-quenching-title">Gold quenching estimates</h2>
      <p>FRET Checker attenuates glow continuously using the supported gold transfer curves. A characteristic distance is the 50% transfer point, not an on/off boundary.</p>
      <p><strong>Unknown means not calibrated, not unquenched.</strong> Vendor QDs retain reference brightness because their gold-quenching calibration is missing. Fluorescence alone shows reference emission.</p>
      <p>Distances below are donor center to gold surface. Values assume the reference dye quantum yield and environment. Hidden gold particles still participate.</p>
      <div class="gold-quenching-table"><table><thead><tr><th>Donor</th><th>Gold ID</th><th>Gold diameter (nm)</th><th>Separation (nm)</th><th>Model / status</th><th>Estimated transfer</th></tr></thead><tbody></tbody></table></div>
      <details><summary>Imported measurements and research</summary><div class="gold-quenching-sources"></div></details>
      <details><summary>Model assumptions and limits</summary><ul class="gold-quenching-limits"></ul></details>
      <form method="dialog"><button>Close</button></form>`
    const sources = dialog.querySelector('.gold-quenching-sources')
    for (const profile of GOLD_QUENCHING_DATA.profiles) {
      const p = document.createElement('p')
      p.textContent = `${profile.donor_label}, quantum yield ${profile.quantum_yield}: gold diameter → d₀ (nm): ${profile.points.map(point => `${point.gold_diameter_nm} → ${point.d0_nm}`).join('; ')}. `
      const a = document.createElement('a'); a.href = profile.data_source; a.textContent = 'Experimental table'
      a.target = '_blank'; a.rel = 'noopener noreferrer'; p.append(a); sources.append(p)
    }
    for (const record of GOLD_QUENCHING_DATA.evidence) {
      const p = document.createElement('p')
      const law = record.exponents_by_diameter ? `Transfer exponents, respectively: ${record.exponents_by_diameter.join(', ')}. `
        : record.exponent ? `Transfer exponent: ${record.exponent}. ` : ''
      p.textContent = `${record.donor}; gold ${record.gold_diameter_nm.join(', ')} nm: ${record.finding} ${law}${record.reason ?? ''} `
      const a = document.createElement('a'); a.href = record.source; a.textContent = 'Study'
      a.target = '_blank'; a.rel = 'noopener noreferrer'; p.append(a); sources.append(p)
    }
    for (const note of GOLD_QUENCHING_DATA.limitations) {
      const li = document.createElement('li'); li.textContent = note
      dialog.querySelector('.gold-quenching-limits').append(li)
    }
    dialog.addEventListener('keydown', event => event.stopPropagation())
    dialog.onclose = () => { dialog.remove(); dialog = null; lastRows = ''; button.focus() }
    document.body.append(dialog)
    updateRows()
    dialog.showModal()
  }
  return {
    update(nextResults, enabled) {
      results = enabled ? nextResults : []
      const active = results.filter(result => result.pairs.length)
      const unknown = active.filter(result => result.incomplete).length
      button.hidden = !enabled || active.length === 0
      const text = `Gold quenching: ${active.length - unknown} estimated · ${unknown} uncalibrated — Details`
      if (text !== lastText) { button.textContent = text; lastText = text }
      updateRows()
    },
  }
}
