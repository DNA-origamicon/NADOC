import { createQuantumDot } from '../api/client.js'
import { bundledQuantumDotCatalog, quantumDotPlotUrl } from './quantum_dot_catalog.js'
import './quantum_dot_dialog.css'

const range = values => values ? `${values[0]}–${values[1]} nm` : 'Not specified'

/** Catalog selection imports an inert particle; surface chemistry stays deferred. */
export function openQuantumDotDialog({ loadCatalog = bundledQuantumDotCatalog, importDot = createQuantumDot, onImported = null } = {}) {
  const existing = document.getElementById('quantum-dot-dialog')
  if (existing) { existing.focus(); return null }
  const previousFocus = document.activeElement
  const overlay = document.createElement('div')
  overlay.className = 'qd-overlay'
  overlay.innerHTML = `
    <section id="quantum-dot-dialog" class="qd-dialog" role="dialog" aria-modal="true" aria-labelledby="qd-title" tabindex="-1">
      <header><div><h2 id="qd-title">Quantum dots</h2><p>Choose a vendor dot, review its size and spectra, then import it into the design.</p></div><button type="button" id="qd-close" aria-label="Close quantum dot catalog">×</button></header>
      <div class="qd-filters"><label>Search <input id="qd-search" type="search" placeholder="Dot, wavelength, coating…"></label><label>Vendor <select id="qd-vendor"><option value="">All vendors</option></select></label><span id="qd-count"></span></div>
      <div id="qd-status" role="status">Loading catalog…</div>
      <div class="qd-table-wrap"><table><thead><tr><th scope="col">Select / dot</th><th scope="col">Vendor / catalog</th><th scope="col">Emission</th><th scope="col">Absorption peak</th><th scope="col">Diameter</th><th scope="col">Surface coating</th><th scope="col">Functionalization</th></tr></thead><tbody id="qd-rows"></tbody></table></div>
      <section id="qd-detail" class="qd-detail" hidden><div><h3 id="qd-selected-name"></h3><label class="qd-diameter-label">Scene diameter (nm) <input id="qd-diameter" type="number" step="any"></label><p id="qd-diameter-note"></p><p class="qd-links"><a id="qd-product-link" target="_blank" rel="noopener noreferrer">Vendor product</a><a id="qd-size-link" target="_blank" rel="noopener noreferrer">Size specification</a><a id="qd-spectra-link" target="_blank" rel="noopener noreferrer">Original spectra</a></p><details><summary>Size and spectra provenance</summary><p id="qd-size-note"></p><p id="qd-spectra-note"></p></details><p id="qd-policy"></p></div><figure><img id="qd-spectra" alt=""><figcaption>Vendor absorption and emission curves · full published plot</figcaption></figure></section>
      <footer><span id="qd-error" role="alert"></span><button type="button" id="qd-cancel">Cancel</button><button type="button" id="qd-import" class="qd-primary" disabled>Import quantum dot</button></footer>
    </section>`
  document.body.appendChild(overlay)
  const $ = id => overlay.querySelector(`#${id}`)
  const dialog = $('quantum-dot-dialog')
  let entries = [], selected = null, busy = false, closed = false
  function close() {
    if (busy || closed) return
    closed = true
    document.removeEventListener('keydown', onKey, true)
    overlay.remove()
    if (previousFocus?.isConnected) previousFocus.focus()
  }
  function onKey(event) {
    if (event.key === 'Escape') { event.preventDefault(); event.stopImmediatePropagation(); close() }
    if (event.key === 'Tab') {
      const focusable = [...dialog.querySelectorAll('button:not(:disabled), input:not(:disabled), select:not(:disabled), a[href], summary')]
        .filter(el => !el.closest('[hidden]'))
      const first = focusable[0], last = focusable.at(-1)
      if (event.shiftKey && (document.activeElement === first || document.activeElement === dialog)) { event.preventDefault(); last?.focus() }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
    }
  }
  document.addEventListener('keydown', onKey, true)
  $('qd-close').onclick = close
  $('qd-cancel').onclick = close
  overlay.onclick = event => { if (event.target === overlay) close() }
  function validate() {
    const diameter = Number($('qd-diameter').value)
    const [low, high] = selected?.diameter_range_nm ?? [0, 0]
    const valid = !!selected?.import_enabled && Number.isFinite(diameter) && diameter >= low && diameter <= high
    $('qd-import').disabled = busy || !valid
    return valid
  }
  function select(entry) {
    if (busy) return
    selected = entry
    $('qd-error').textContent = ''
    $('qd-detail').hidden = false
    $('qd-selected-name').textContent = `${entry.product_name} · ${entry.functionalization}`
    $('qd-size-note').textContent = `${range(entry.diameter_range_nm)} total; core: ${range(entry.core_diameter_range_nm)}. ${entry.size_basis}`
    $('qd-spectra-note').textContent = entry.spectra.note
    $('qd-product-link').href = entry.product_url
    $('qd-size-link').href = entry.size_source_url
    $('qd-spectra-link').href = `${entry.spectra.source_url}#page=${entry.spectra.source_page}`
    $('qd-spectra').src = quantumDotPlotUrl(entry)
    $('qd-spectra').alt = `${entry.product_name}: vendor absorption and emission spectra`
    const [low, high] = entry.diameter_range_nm
    $('qd-diameter').min = low
    $('qd-diameter').max = high
    $('qd-diameter').value = (low + high) / 2
    $('qd-diameter').disabled = !entry.import_enabled
    $('qd-diameter-note').textContent = `Vendor range: ${range(entry.diameter_range_nm)}. The midpoint is used by default; it is a scene approximation.`
    $('qd-policy').textContent = entry.import_enabled
      ? 'Imports an unbound dot. Move or rotate it after import.'
      : entry.disabled_reason
    for (const row of $('qd-rows').children) {
      const active = row.dataset.catalogId === entry.catalog_id
      row.classList.toggle('qd-selected', active)
      row.querySelector('input').checked = active
    }
    validate()
  }
  function render() {
    if (busy) return
    const query = $('qd-search').value.trim().toLowerCase(), vendor = $('qd-vendor').value
    const matches = entries.filter(entry => (!vendor || entry.vendor === vendor) &&
      `${entry.product_name} ${entry.product_code} ${entry.composition} ${entry.surface_coating} ${entry.functionalization} ${entry.vendor}`.toLowerCase().includes(query))
    $('qd-rows').replaceChildren()
    for (const entry of matches) {
      const row = document.createElement('tr')
      row.dataset.catalogId = entry.catalog_id
      const choice = document.createElement('td')
      const label = document.createElement('label')
      const radio = document.createElement('input')
      radio.type = 'radio'; radio.name = 'qd-choice'; radio.value = entry.catalog_id
      radio.checked = entry.catalog_id === selected?.catalog_id
      radio.onchange = () => select(entry)
      label.append(radio, ` ${entry.product_name}`)
      choice.append(label)
      const composition = document.createElement('small'); composition.textContent = entry.composition; choice.append(composition)
      row.append(choice)
      const cells = [
        `${entry.vendor}\n${entry.product_code}`,
        `${entry.emission_peak_nm}${entry.emission_tolerance_nm ? ` ± ${entry.emission_tolerance_nm}` : ''} nm`,
        entry.absorption_peak_nm ? `${entry.absorption_peak_nm}${entry.absorption_tolerance_nm ? ` ± ${entry.absorption_tolerance_nm}` : ''} nm` : 'Broad · see curves',
        range(entry.diameter_range_nm), entry.surface_coating,
        `${entry.functionalization}${entry.import_enabled ? '' : '\nPreview only'}`,
      ]
      for (const text of cells) { const cell = document.createElement('td'); cell.textContent = text; row.append(cell) }
      row.classList.toggle('qd-selected', radio.checked)
      row.onclick = () => select(entry)
      $('qd-rows').append(row)
    }
    $('qd-count').textContent = `${matches.length} of ${entries.length} dots`
    $('qd-status').textContent = matches.length ? 'Functionalized variants are listed for reference; their import and binding tools are not enabled yet.' : 'No matching dots.'
    // Filtering must not leave a hidden product armed for import.
    if (!matches.some(e => e.catalog_id === selected?.catalog_id)) {
      selected = null; $('qd-detail').hidden = true; validate()
    }
  }
  $('qd-search').oninput = render
  $('qd-vendor').onchange = render
  $('qd-diameter').oninput = validate
  $('qd-import').onclick = async () => {
    if (busy || !validate()) return
    const entry = selected, diameter = Number($('qd-diameter').value)
    busy = true; validate()
    $('qd-error').textContent = ''
    $('qd-import').textContent = 'Importing…'
    for (const id of ['qd-close','qd-cancel','qd-search','qd-vendor','qd-diameter']) $(id).disabled = true
    try {
      const result = await importDot(entry.catalog_id, diameter)
      if (!result?.nanoparticle_id) throw new Error('Import could not be confirmed. Check the design and retry if needed.')
      busy = false
      close()
      onImported?.(result.nanoparticle_id)
    } catch (error) {
      $('qd-error').textContent = error.message || 'Unable to import this quantum dot.'
    } finally {
      busy = false
      if (!closed) {
        for (const id of ['qd-close','qd-cancel','qd-search','qd-vendor','qd-diameter']) $(id).disabled = false
        $('qd-import').textContent = 'Import quantum dot'
        validate()
      }
    }
  }
  dialog.focus()
  const ready = Promise.resolve().then(loadCatalog).then(catalog => {
    if (closed) return
    if (!catalog?.entries?.length) throw new Error('The quantum-dot catalog could not be loaded. Close and reopen to retry.')
    entries = catalog.entries
    for (const vendor of [...new Set(entries.map(e => e.vendor))]) {
      const option = document.createElement('option'); option.value = vendor; option.textContent = vendor; $('qd-vendor').append(option)
    }
    render()
    const first = entries.find(e => e.import_enabled)
    if (first) select(first)
    $('qd-search').focus()
  }).catch(error => { if (!closed) $('qd-status').textContent = error.message })
  return { close, ready }
}
