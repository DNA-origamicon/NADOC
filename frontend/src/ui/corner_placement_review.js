/** Prepared Corner molecular evidence, isolated from all authoring controls. */
import { createAttachmentReviewViewer } from './geometry_review_viewer.js'
import { auditStrandColorMap, auditDefectRows, copyAuditCameraState } from './molecular_placement_audit.js'

export function mountGeometryReview(host, evidence) {
  host.innerHTML = `<h2 data-ref="title"></h2>
    <p class="gr-notice">Current: exact native atomistic reconstruction of the recorded Corner. Candidate: the same topology with seam inserts constructed in the final wedge frames and their phosphate bonds closed jointly. Candidate is isolated and not approved.</p>
    <p>Rigid duplex atoms stay fixed. Insert rings move rigidly; seam phosphate atoms move. The native terminal gamma adjustment is not preserved. Compare the stretched bonds and exact defect markers, then use a junction row to focus all four panels.</p>
    <div class="gr-toolbar"><button data-ref="fit">Fit full design</button><button data-ref="focus">Focus corner seams</button></div>
    <div class="gr-grid"></div><h2>Whole-model checks</h2><p>Contacts use NADOC’s severe-overlap screen, excluding covalent 1–2 and 1–3 pairs. Zero does not establish van der Waals clearance or physical stability.</p><div data-ref="metrics"></div>
    <h2>Individual junctions</h2><p>Lengths and displacements are in nm. Clash/piercing columns show Current → Candidate; a defect touching two seams appears in both rows.</p><div data-ref="junctions"></div>
    <h2>Native construction</h2><ol data-ref="construction"></ol>
    <h2>Separate diagnostic candidate process</h2><ol data-ref="process"></ol>
    <h2>Helical-phase checks</h2><p data-ref="phases"></p>
    <h2>Exact defects</h2><ul data-ref="defects"></ul><h2>Scope and limitations</h2><ul data-ref="limits"></ul>`
  const ref = name => host.querySelector(`[data-ref="${name}"]`)
  ref('title').textContent = evidence.label
  const bundle = { ...evidence, max_displacement_vectors: 160,
    strand_colors: auditStrandColorMap(evidence) }
  const viewers = []; let syncing = false, disposed = false
  const sync = source => {
    if (syncing) return
    syncing = true
    try { for (const view of viewers) if (view !== source) { copyAuditCameraState(source, view); view.controls.update() } }
    finally { syncing = false }
  }
  const dispose = () => { if (disposed) return; disposed = true; viewers.forEach(v => v.dispose()); host.replaceChildren() }
  const table = (name, headers) => {
    const result = document.createElement('table'), row = result.insertRow()
    for (const label of headers) { const th = document.createElement('th'); th.textContent = label; row.append(th) }
    ref(name).append(result); return result
  }
  const addRow = (target, fields) => { const row = target.insertRow(); fields.forEach(v => { row.insertCell().textContent = String(v) }); return row }
  try {
    for (const [id, title] of [['current','Current'], ['candidate','Candidate — not approved'], ['difference','Displacement overlay'], ['defects','Exact defects']]) {
      const panel = document.createElement('section'); panel.className = 'gr-panel'
      panel.innerHTML = `<div class="gr-bar"><h2></h2><select aria-label="${id} representation"><option value="full">Full-style atom projection</option><option value="ballstick">Ball and Stick</option></select></div><div class="gr-view"></div>`
      panel.querySelector('h2').textContent = title; host.querySelector('.gr-grid').append(panel)
      const view = createAttachmentReviewViewer(panel.querySelector('.gr-view'), id, bundle, 'full')
      viewers.push(view); view.controls.addEventListener('change', () => sync(view))
      panel.querySelector('select').onchange = event => view.setRepresentation(event.target.value)
    }
    const focus = serials => { viewers[0].focusAtoms(serials); sync(viewers[0]) }
    ref('fit').onclick = () => { viewers[0].fit(); sync(viewers[0]) }
    ref('focus').onclick = () => focus(evidence.junctions.flatMap(j => j.atom_serials))
    sync(viewers[0])
    const metrics = table('metrics', ['Measurement', 'Current', 'Candidate'])
    const a = evidence.current.diagnostics, b = evidence.candidate.diagnostics
    addRow(metrics, [`Heavy-atom contacts < ${a.clash_threshold_nm.toFixed(3)} nm`, a.n_clashes, b.n_clashes])
    addRow(metrics, ['Ring piercings', a.piercing.n_pierced, b.piercing.n_pierced])
    addRow(metrics, ['Maximum junction covalent bond', a.max_junction_covalent_nm.toFixed(6), b.max_junction_covalent_nm.toFixed(6)])
    addRow(metrics, ['Displaced atoms', 0, evidence.displacement.n_displaced])
    const junctions = table('junctions', ['Junction', 'Unpaired bases', 'Current max bond', 'Candidate max bond', 'Max displacement', 'Clashes', 'Piercings'])
    for (const j of evidence.junctions) {
      const row = addRow(junctions, ['', j.insert_bases, j.current.max_covalent_nm.toFixed(6), j.candidate.max_covalent_nm.toFixed(6), j.max_displacement_nm.toFixed(6), `${j.current.clashes} → ${j.candidate.clashes}`, `${j.current.piercings} → ${j.candidate.piercings}`])
      const button = document.createElement('button'); button.textContent = j.label; button.onclick = () => focus(j.atom_serials); row.cells[0].append(button)
    }
    for (const [name, rows] of [['construction', evidence.construction], ['process', evidence.candidate_process], ['limits', evidence.limitations], ['defects', auditDefectRows(bundle).map(r => r.text)]]) {
      for (const text of rows) { const li = document.createElement('li'); li.textContent = text; ref(name).append(li) }
    }
    const phases = evidence.phase_sweep.cases
    const passed = phases.filter(p => p.candidate_invalid_atoms === 0 && p.candidate_clashes === 0 && p.candidate_piercings === 0 && p.candidate_max_covalent_nm <= .20).length
    ref('phases').textContent = `${passed}/${phases.length} native 2HB cases pass these candidate checks across all 21 honeycomb and 32 square bp phase classes at a 90° corner and 15° direction. ${phases.filter(p => p.current_invalid_atoms > 0).length} Current builds contain nonfinite atoms; those are reported as invalid, never as clear geometry. This sweep does not establish coverage of every angle or routed source.`
  } catch (error) { dispose(); throw error }
  return { dispose, isRendered: () => !disposed && viewers.length === 4 && viewers.every(v => v.isRendered()) }
}
