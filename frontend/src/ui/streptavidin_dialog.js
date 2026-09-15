import { generateRandomSequence } from '../api/overhang_endpoints.js'
import { patchNanoparticle, createNanoparticleBiotinDNA, removeNanoparticleBiotinDNA } from '../api/client.js'
import './gold_creation_dialog.css'
import coverage from '../../../backend/data/proteins/streptavidin_coverage.json'

export function openStreptavidinDialog(particle, { container = null, onSaved = null, compact = false, onPreview = null, onChanged = null } = {}) {
  if (document.getElementById('streptavidin-dialog')) return
  const dialog = document.createElement(container ? 'div' : 'dialog')
  dialog.id = 'streptavidin-dialog'
  dialog.setAttribute('aria-label', 'Streptavidin coating')
  dialog.innerHTML = `<h2>Streptavidin coating</h2><p id="strep-size"></p>
    <label>Attachment method <select id="strep-mode"><option value="adsorption">Adsorption — sampled contact orientations</option><option value="biotin_tether">Biotin tether — occupied pocket toward particle</option></select></label>
    <p><label>Coverage publication <select id="strep-reference"></select></label></p>
    <p><a id="strep-source" target="_blank" rel="noopener noreferrer">Supporting publication</a></p><p id="strep-reference-note"></p>
    <p><label>Tetramers per particle <input id="strep-count" type="number" min="1" max="1500" step="1"></label> <button id="strep-reset">Use publication estimate</button></p>
    <p><label>Surface spacer (nm) <input id="strep-spacer" type="number" min="0.2" max="20" step="0.1" value="0.3"></label></p>
    <p id="strep-estimate" role="status"></p>
    <p>Imports the complete PDB 1STP biological tetramer. Packing is an estimate; colliding placements are omitted and the final count is saved. Adsorption does not imply a unique experimental orientation. Biotin mode occupies one binding pocket; its linker is a geometric spacer.</p>
    <p id="strep-scope"></p><p>NAMD coating simulation remains unsupported. Fixed-core oxDNA uses simplified core excluded volume, protein anchors and DNA attachment restraints; equilibrium sampling and experimental validation remain open.</p>
    <p><a href="https://www.rcsb.org/structure/1STP" target="_blank" rel="noopener noreferrer">PDB structure</a> · <a href="https://doi.org/10.1016/j.mee.2007.01.247" target="_blank" rel="noopener noreferrer">40 nm² coverage reference</a></p>
    <details open id="strep-dna-panel"><summary>Biotinylated DNA</summary>
    <p>Apply the streptavidin coating first, then choose the number of DNA strands per applied tetramer. Gold stays fixed; DNANM models the protein and DNA with prescribed attachment restraints. The oxDNA job uses GPU by default; CPU is also available.</p>
    <p id="strep-dna-current"></p><label>5′ biotin DNA sequence <input id="strep-dna-sequence" value="ACGTACGTACGTACGT" maxlength="200"></label>
    <label>Length <input id="strep-dna-length" type="number" min="2" max="200" step="1" value="16"></label> <button id="strep-dna-generate">Generate sequence</button>
    <label>DNA per strep <input id="strep-dna-count" type="number" min="1" max="4" step="1" value="1"></label>
    <label>Pocket <select id="strep-dna-pocket"><option value="auto">Automatic clash-screened pockets</option><option>A</option><option>B</option><option>C</option><option>D</option></select></label>
    <label>Linker reach (nm) <input id="strep-dna-linker" type="number" min="1" max="10" step="0.1" value="1.8"></label>
    <p>Linker and biotin binding are represented by a coarse-grained spring; pocket selection is a geometric screen, not a binding-affinity prediction.</p>
    <button id="strep-dna-create">Attach biotinylated DNA</button> <button id="strep-dna-remove">Remove DNA</button></details>
    <p id="strep-error" role="alert"></p><button id="strep-cancel">Cancel</button> <button id="strep-remove">Remove coating</button> <button id="strep-apply">Apply</button>`
  ;(container ?? document.body).append(dialog)
  if (container) {
    dialog.style.cssText = 'position:static;inset:auto;margin:0;width:100%;max-height:none;box-sizing:border-box;overflow:auto;border:0;padding:12px'
    dialog.close = () => { dialog.remove(); onSaved?.() }
  }
  const $ = id => dialog.querySelector(`#${id}`)
  if (compact) {
    dialog.classList.add('strep-compact')
    const dna = document.createElement('div'), coating = document.createElement('div')
    dna.className = 'strep-controls strep-dna-controls'; coating.className = 'strep-controls strep-coating-controls'
    const move = (target, id, parent = false) => { const node = $(id); target.append(parent ? node.closest('label') : node) }
    const heading = (target, text) => { const h = document.createElement('div'); h.className = 'strep-heading'; h.textContent = text; target.append(h) }
    heading(dna, '2. Attach biotinylated DNA')
    move(dna, 'strep-dna-sequence', true)
    const lengthRow = document.createElement('div'); lengthRow.className = 'strep-length-row'
    move(lengthRow, 'strep-dna-length', true); move(lengthRow, 'strep-dna-generate'); dna.append(lengthRow)
    move(dna, 'strep-dna-count', true); move(dna, 'strep-dna-pocket', true); move(dna, 'strep-dna-linker', true)
    move(dna, 'strep-dna-current'); move(dna, 'strep-dna-create'); move(dna, 'strep-dna-remove')
    heading(coating, '1. Apply strep coating')
    move(coating, 'strep-mode', true); move(coating, 'strep-reference', true)
    move(coating, 'strep-count', true); move(coating, 'strep-reset'); move(coating, 'strep-spacer', true)
    move(coating, 'strep-estimate'); move(coating, 'strep-remove')
    move(dna, 'strep-error')
    const actions = document.createElement('div'); actions.className = 'strep-actions'
    move(actions, 'strep-cancel'); move(actions, 'strep-apply'); dna.append(actions)
    const hidden = document.createElement('div'); hidden.hidden = true
    while (dialog.firstChild) hidden.append(dialog.firstChild)
    dialog.append(hidden, coating, dna)
    $('strep-mode').options[0].textContent = 'Adsorption'
    $('strep-mode').options[1].textContent = 'Biotin tether'
    $('strep-dna-pocket').options[0].textContent = 'Auto (outward)'
  }
  const tips = {
    'strep-mode': 'Adsorption samples contact orientations; biotin tether points occupied pocket A toward gold. Geometric placement does not predict adsorption energy. PDB 1STP: https://www.rcsb.org/structure/1STP',
    'strep-count': 'Requested tetramers; colliding placements are omitted. The preview reports the actual count. Coverage depends on preparation and curvature.',
    'strep-spacer': 'Geometric distance from the gold surface in nm, not an atomistic linker or adsorption potential.',
    'strep-dna-pocket': 'Automatic selection searches unoccupied PDB pockets and rigid DNA orientations/phases. Native B-form beads and connecting segments are screened against cores, coatings and other DNA. A finite geometric search does not predict binding affinity or equilibrium ssDNA structure. Pocket A is occupied in biotin-tether mode. Structure: https://www.rcsb.org/structure/1STP',
    'strep-dna-count': 'Exact number on every applied tetramer: up to four for adsorption or three when pocket A tethers the protein. If the requested occupancy cannot be placed without clashes, nothing is attached. The entered sequence is used for every strand.',
    'strep-dna-linker': 'Atomistic views use 5′ biotin-TEG (IDT /5BiotinTEG/), fitted to the actual DNA phosphate without stretching bonds. An unreachable spacer is shown unconnected with a warning. Reach from the bound biotin carboxyl tail to the first native DNA backbone bead. The ideal B-form strand may turn at this flexible connection. oxDNA uses a prescribed coarse-grained spring, not explicit ligand atoms.',
    'strep-dna-create': 'Apply the coating first; unsaved coating edits must be applied before attaching DNA. All requested strands are created together with one undo action. Fixed gold CPU/GPU DNANM remains a simplified restraint model; NAMD coating validation is pending.',
  }
  for (const [id, text] of Object.entries(tips)) { $(id).title = text; for (const option of $(id).options ?? []) option.title = text }

  const old = particle.coating
  $('strep-size').textContent = `Core diameter: ${particle.diameter_nm} nm${old ? ` · Current coating: ${old.poses.length} tetramers (target ${old.target_count})` : ''}`
  $('strep-scope').textContent = particle.kind === 'quantum_dot'
    ? 'For QDs this is a custom geometric coating using a gold-derived footprint estimate, not the loading or chemistry of a vendor streptavidin Qdot.'
    : 'The selected publication supplies a loading estimate; solvent, attachment chemistry and curvature affect actual loading.'
  for (const preset of coverage.presets) { const option = new Option(preset.label, preset.id); option.title = `${preset.note} Source: ${preset.url}`; $('strep-reference').add(option) }
  $('strep-reference').value = old?.coverage_reference ?? 'gold_2007'
  if (old) { $('strep-mode').value = old.mode; $('strep-spacer').value = old.spacer_nm }
  let manual = Boolean(old && (old.count_override != null || !old.coverage_reference))
  const estimate = () => Math.max(1, Math.floor(Math.PI * particle.diameter_nm ** 2 / coverage.presets.find(p => p.id === $('strep-reference').value).effective_area_nm2 + 1e-9))
  $('strep-count').value = old?.count_override ?? (manual ? old.target_count : estimate())
  let hasDNA = Boolean(particle.biotin_dna?.length)
  if (hasDNA) $('strep-dna-linker').value = String(particle.biotin_dna[0].linker_nm ?? 2)
  $('strep-dna-panel').hidden = particle.kind === 'quantum_dot'
  const appliedCount = old?.poses.length ?? 0
  const maxDNA = old?.mode === 'biotin_tether' ? 3 : 4
  $('strep-dna-count').max = String(maxDNA)
  $('strep-dna-count').value = String(hasDNA ? particle.biotin_dna.length / appliedCount : 1)
  const coatingValues = () => JSON.stringify(['strep-mode', 'strep-reference', 'strep-count', 'strep-spacer'].map(id => $(id).value))
  const appliedValues = coatingValues()
  function updateDNA() {
    const applied = particle.kind === 'gold_nanosphere' && appliedCount > 0
    const dirty = coatingValues() !== appliedValues
    const count = Number($('strep-dna-count').value)
    const seq = $('strep-dna-sequence').value.trim().toUpperCase()
    const linker = Number($('strep-dna-linker').value)
    const valid = Number.isInteger(count) && count >= 1 && count <= maxDNA && /^[ACGT]{2,200}$/.test(seq) && linker >= 1 && linker <= 10
    const locked = !applied || dirty || busy || hasDNA
    for (const id of ['strep-dna-count', 'strep-dna-sequence', 'strep-dna-length', 'strep-dna-generate', 'strep-dna-linker']) $(id).disabled = locked
    if (count > 1) $('strep-dna-pocket').value = 'auto'
    $('strep-dna-pocket').disabled = locked || count > 1
    for (const option of $('strep-dna-pocket').options) option.disabled = old?.mode === 'biotin_tether' && option.value === 'A'
    $('strep-dna-create').disabled = locked || !valid || $('strep-dna-pocket').selectedOptions[0]?.disabled
    $('strep-dna-remove').disabled = busy || !hasDNA
    $('strep-dna-current').textContent = !applied ? 'Apply the strep coating first.' : dirty ? 'Apply coating changes before attaching DNA.' : hasDNA
      ? `${particle.biotin_dna.length / appliedCount} DNA / strep · ${particle.biotin_dna.length} attached`
      : `Applied: ${appliedCount} strep · ${valid ? count * appliedCount : '—'} DNA requested`
  }
  for (const id of ['strep-dna-count', 'strep-dna-sequence', 'strep-dna-linker', 'strep-dna-pocket']) $(id).addEventListener('input', updateDNA)
  async function changeDNA(remove) {
    updateDNA()
    if (busy || $(remove ? 'strep-dna-remove' : 'strep-dna-create').disabled) return
    busy = true; updateDNA(); $('strep-error').textContent = 'Updating biotinylated DNA…'
    try {
      const result = remove ? await removeNanoparticleBiotinDNA(particle.id) : await createNanoparticleBiotinDNA(particle.id, { sequence: $('strep-dna-sequence').value, dna_per_strep: Number($('strep-dna-count').value), pocket: $('strep-dna-pocket').value, linker_nm: Number($('strep-dna-linker').value) })
      if (!result) throw new Error('DNA update failed; check the sequence and pocket selection.')
      const updated = result.design?.nanoparticles?.find(p => p.id === particle.id)
      if (!updated) throw new Error('Could not refresh the nanoparticle after updating DNA.')
      particle = updated
      hasDNA = Boolean(particle.biotin_dna?.length)
      busy = false
      update(); $('strep-error').textContent = ''
      onChanged?.(result)
    } catch (error) { busy = false; updateDNA(); $('strep-error').textContent = error.message }
  }
  $('strep-dna-generate').onclick = async () => {
    const length = Number($('strep-dna-length').value)
    if (!Number.isInteger(length) || length < 2 || length > 200) { $('strep-error').textContent = 'Use an integer length of 2–200.'; return }
    $('strep-dna-generate').disabled = true
    try {
      const generated = await generateRandomSequence(length)
      if (!generated) throw new Error('Sequence generation failed. Please try again.')
      $('strep-dna-sequence').value = generated; $('strep-error').textContent = ''
    }
    catch (error) { $('strep-error').textContent = error.message }
    finally { updateDNA() }
  }
  $('strep-dna-create').onclick = () => changeDNA(false)
  $('strep-dna-remove').onclick = () => changeDNA(true)
  let busy = false
  function update() {
    updateDNA()
    const count = Number($('strep-count').value), spacer = Number($('strep-spacer').value)
    const valid = particle.diameter_nm >= 5 && particle.diameter_nm <= 100 && Number.isInteger(count) && count >= 1 && count <= 1500 && spacer >= .2 && spacer <= 20
    $('strep-apply').disabled = busy || !valid
    for (const id of ['strep-mode', 'strep-reference', 'strep-count', 'strep-reset', 'strep-spacer']) $(id).disabled = busy || hasDNA
    $('strep-remove').disabled = busy || !old || hasDNA
    const preset = coverage.presets.find(p => p.id === $('strep-reference').value)
    $('strep-reference').title = `${preset.note} Source: ${preset.url}`
    $('strep-source').href = preset.url
    $('strep-reference-note').textContent = preset.note
    $('strep-estimate').textContent = compact && valid ? `Target: ${count} tetramers` : valid ? `Publication target: ${estimate()} tetramers. Requested: ${count}${manual ? ' (override)' : ''}. Actual count may be lower after clash checks.` : 'Use a 5–100 nm core, an integer count of 1–1500 and a 0.2–20 nm spacer.'
    if (valid) onPreview?.({ mode: $('strep-mode').value, coverage_reference: preset.id, count_override: manual ? count : null, spacer_nm: spacer, seed: old?.seed ?? 1 })
  }
  $('strep-mode').onchange = () => { $('strep-spacer').value = $('strep-mode').value === 'adsorption' ? .3 : 4; update() }
  $('strep-reference').onchange = () => { manual = false; $('strep-count').value = estimate(); update() }
  $('strep-reset').onclick = () => { manual = false; $('strep-count').value = estimate(); update() }
  $('strep-count').oninput = () => { manual = true; update() };  $('strep-spacer').oninput = update
  $('strep-remove').disabled = !old || hasDNA
  async function apply(coating) {
    if (busy) return
    busy = true
    for (const control of dialog.querySelectorAll('button,input,select')) control.disabled = true
    $('strep-error').textContent = 'Preparing PDB coating…'
    try {
      const result = await patchNanoparticle(particle.id, { coating })
      if (!result) throw new Error('Coating update failed. Check the connection and requested packing.')
      busy = false; dialog.close()
    } catch (error) {
      busy = false
      for (const control of dialog.querySelectorAll('button,input,select')) control.disabled = false
      $('strep-remove').disabled = !old || hasDNA
      update(); $('strep-error').textContent = error.message
    }
  }
  $('strep-apply').onclick = () => {
    update(); if ($('strep-apply').disabled) return
    // DNA edits are already saved. Final Apply finishes without recreating the
    // coating (which would invalidate attached strands or add an undo entry).
    if (old && coatingValues() === appliedValues) { dialog.close(); return }
    apply({ mode: $('strep-mode').value, coverage_reference: $('strep-reference').value, count_override: manual ? Number($('strep-count').value) : null, spacer_nm: Number($('strep-spacer').value), seed: old?.seed ?? 1 })
  }
  $('strep-remove').onclick = () => apply(null)
  $('strep-cancel').onclick = () => { if (!busy) dialog.close() }
  dialog.oncancel = event => { if (busy) event.preventDefault() }
  dialog.onclose = () => dialog.remove()
  dialog.addEventListener('keydown', event => event.stopPropagation())
  update(); if (!container) dialog.showModal()
  return dialog
}
