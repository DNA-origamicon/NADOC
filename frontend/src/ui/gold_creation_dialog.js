import { createGoldNanosphere } from '../api/client.js'
import { parseNanoparticleDiameter } from './nanoparticle_dialog.js'
import { GOLD_OPTICS, goldOptics, vendorMolar, crossSectionToMolar } from './gold_optics.js'
import './gold_creation_dialog.css'

export function openGoldCreationDialog({ create = createGoldNanosphere, onCreated = null } = {}) {
  const existing = document.getElementById('gold-creation-dialog')
  if (existing) { existing.focus(); return }
  const previous = document.activeElement
  const dialog = document.createElement('dialog')
  dialog.id = 'gold-creation-dialog'
  dialog.setAttribute('aria-labelledby', 'gold-creation-title')
  dialog.innerHTML = `<header><h2 id="gold-creation-title">Gold nanosphere</h2><button id="gold-close" aria-label="Close gold nanosphere dialog">×</button></header>
    <div class="gold-controls"><label>Gold core diameter (nm) <input id="gold-diameter" type="number" min="0" max="1000" step="any" value="10"></label>
    </div>
    <p id="gold-optics-status" role="status"></p>
    <div id="gold-optics-content"><div class="gold-metrics"><p>Extinction / plasmon-band peak<br><strong id="gold-peak"></strong></p><p>Absorption peak<br><strong id="gold-abs-peak"></strong></p><p>Peak molar extinction coefficient<br><strong id="gold-epsilon"></strong><br>M⁻¹ cm⁻¹ (moles of particles)</p></div>
    <svg id="gold-spectrum" viewBox="0 0 700 260" role="img" aria-label="Calculated gold absorption, scattering and extinction spectra"></svg>
    <p class="gold-legend"><span>● Extinction</span><span>● Absorption</span><span>● Scattering</span></p>
    <label>Inspect wavelength (nm) <input id="gold-wavelength" type="range" min="400" max="800" step="2" value="520"></label><p id="gold-spectral-value"></p></div>
    <details open><summary>Published size references — nanoComposix BioPure</summary><div class="gold-reference-table"><table><thead><tr><th>Diameter (nm)</th><th>Peak (nm)</th><th>Peak ε (M⁻¹ cm⁻¹)</th></tr></thead><tbody id="gold-reference-rows"></tbody></table></div><p>Nearest reference size is highlighted. Vendor values describe nominal dispersions; ε is derived from published optical density and particle concentration.</p></details>
    <details><summary>Sources and calculation assumptions</summary><p>Calculated spectra: an isolated, homogeneous gold sphere in water (n = 1.333), using bulk room-temperature optical constants. Extinction = absorption + scattering. Peaks are maxima within 400–800 nm, sampled every 2 nm. Fractional diameters interpolate cross sections between 1 nm size steps.</p><p>Reference calculations cover 5–100 nm. Small-particle surface damping, coatings, aggregation and solvent changes are not modeled; these are optical reference estimates, not a batch certificate or a quenching calibration.</p><p><a href="https://doi.org/10.1103/PhysRevB.6.4370" target="_blank" rel="noopener noreferrer">Johnson &amp; Christy optical constants</a> · <a href="https://nanocomposix.com/pages/standard-product-specifications" target="_blank" rel="noopener noreferrer">Vendor size reference</a> · <a href="https://doi.org/10.1021/ac0702084" target="_blank" rel="noopener noreferrer">Size-dependent gold optics (Haiss et al.)</a></p></details>
    <footer><span id="gold-error" role="alert"></span><button id="gold-cancel">Cancel</button><button id="gold-create">Create gold nanosphere</button></footer>`
  document.body.append(dialog)
  const $ = id => dialog.querySelector(`#${id}`)
  let busy = false, spectrum = null
  const scientific = value => value.toExponential(3)
  for (const row of GOLD_OPTICS.vendor_reference) {
    const tr = document.createElement('tr'); tr.dataset.diameter = row[0]
    for (const value of [row[0], row[1], scientific(vendorMolar(row))]) {
      const td = document.createElement('td'); td.textContent = value; tr.append(td)
    }
    $('gold-reference-rows').append(tr)
  }
  function inspect() {
    if (!spectrum) { $('gold-spectral-value').textContent = ''; return }
    const wavelength = Number($('gold-wavelength').value), index = (wavelength - 400) / 2
    $('gold-spectral-value').textContent = `${wavelength} nm: ε = ${scientific(crossSectionToMolar(spectrum.extinction[index]))} M⁻¹ cm⁻¹; absorption cross section = ${spectrum.absorption[index].toFixed(2)} nm²; scattering = ${spectrum.scattering[index].toFixed(2)} nm².`
  }
  function refresh() {
    const diameter = parseNanoparticleDiameter($('gold-diameter').value)
    const valid = diameter !== null
    $('gold-create').disabled = busy || !valid
    $('gold-error').textContent = diameter === null ? 'Enter a diameter greater than 0 and at most 1000 nm.' : ''
    spectrum = goldOptics(diameter)
    $('gold-optics-content').hidden = !spectrum
    $('gold-optics-status').textContent = spectrum ? `Calculated reference for ${diameter} nm gold in water${spectrum.interpolated ? ' (size-interpolated)' : ''}.`
      : diameter === null ? 'Enter a valid size to inspect optical reference data.' : 'Optical reference unavailable outside 5–100 nm. You can still create this scene size.'
    const nearest = diameter !== null && spectrum ? GOLD_OPTICS.vendor_reference.reduce((a, b) => Math.abs(a[0] - diameter) <= Math.abs(b[0] - diameter) ? a : b)[0] : null
    for (const row of $('gold-reference-rows').children) row.classList.toggle('gold-nearest', Number(row.dataset.diameter) === nearest)
    if (!spectrum) { $('gold-spectrum').replaceChildren(); inspect(); return }
    $('gold-peak').textContent = `${spectrum.peakNm} nm`
    $('gold-abs-peak').textContent = `${spectrum.absorptionPeakNm} nm`
    $('gold-epsilon').textContent = scientific(spectrum.epsilon)
    const maximum = Math.max(...spectrum.extinction)
    const svg = $('gold-spectrum')
    svg.innerHTML = `<path d="M60 15 V215 H675" fill="none" stroke="#9aa6b4"/><text x="60" y="238">400</text><text x="350" y="238">600</text><text x="648" y="238">800 nm</text><text x="65" y="13">Cross section (nm²), peak ${maximum.toFixed(1)}</text><text x="40" y="218">0</text>`
    for (const [key, color] of [['extinction', '#e6bc52'], ['absorption', '#59bfff'], ['scattering', '#c994ff']]) {
      const line = document.createElementNS('http://www.w3.org/2000/svg', 'polyline')
      line.setAttribute('points', spectrum[key].map((value, i) => `${60 + 615 * i / 200},${215 - 190 * value / maximum}`).join(' '))
      line.setAttribute('fill', 'none'); line.setAttribute('stroke', color); line.setAttribute('stroke-width', '2')
      svg.append(line)
    }
    inspect()
  }
  function close() { if (!busy) dialog.close() }
  dialog.oncancel = event => { if (busy) event.preventDefault() }
  dialog.onclose = () => { dialog.remove(); if (previous?.isConnected) previous.focus() }
  dialog.addEventListener('keydown', event => event.stopPropagation())
  $('gold-close').onclick = close; $('gold-cancel').onclick = close
  $('gold-diameter').oninput = refresh
  $('gold-wavelength').oninput = inspect
  $('gold-create').onclick = async () => {
    const diameter = parseNanoparticleDiameter($('gold-diameter').value)
    refresh()
    if (busy || diameter === null || $('gold-create').disabled) return
    busy = true
    for (const element of dialog.querySelectorAll('button,input,select')) element.disabled = true
    $('gold-error').textContent = 'Creating…'
    try {
      const response = await create(diameter)
      if (!response?.nanoparticle_id) throw new Error('Could not create gold nanosphere. Check the connection and try again.')
      busy = false; dialog.close()
      if (response?.nanoparticle_id) onCreated?.(response.nanoparticle_id)
    } catch (error) {
      busy = false
      for (const element of dialog.querySelectorAll('button,input,select')) element.disabled = false
      refresh(); $('gold-error').textContent = error?.message ?? 'Could not create gold nanosphere.'
    }
  }
  refresh(); dialog.showModal(); $('gold-diameter').focus()
  return dialog
}
