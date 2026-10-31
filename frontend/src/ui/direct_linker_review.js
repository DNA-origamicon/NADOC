/** Prepared Direct-linker evidence. No design writes or candidate execution. */
import * as THREE from 'three'
import { createAttachmentReviewViewer } from './geometry_review_viewer.js'
import { auditDefectRows, auditMetricRows, auditStrandColorMap, copyAuditCameraState } from './molecular_placement_audit.js'

export function mountGeometryReview(host, evidence, { viewerFactory = createAttachmentReviewViewer } = {}) {
  host.innerHTML = `<h2 data-ref="title"></h2>
    <p class="gr-notice">Isolated diagnostic. Current is a relocated draft refused by production; Candidate preserves its original root-linker groups. This candidate is not enabled in NADOC.</p>
    <p data-ref="context"></p>
    <div class="gr-toolbar"><label>Atom builder <select aria-label="Atom builder"><option value="viewer">Viewer</option><option value="export">Export</option></select></label><button data-ref="focus">Focus driven root</button><button data-ref="reset">Fit full design</button><span>Drag to orbit · scroll to zoom · cameras move together</span></div>
    <div class="gr-grid"></div>
    <p data-ref="fit"></p><p data-ref="sweep"></p>
    <div class="gr-details"><section><h2>Root lengths and adjacent bonds</h2><p>Reference is before Connect. All distances are in nm.</p><div data-ref="roots"></div><div data-ref="bonds"></div></section><section><h2>Exact atom diagnostics</h2><div data-ref="reference-diagnostics"></div><div data-ref="metrics"></div><ul data-ref="defects"></ul></section></div>
    <details><summary>Adjacent bond angles</summary><div data-ref="angles"></div></details>
    <details open><summary>Construction sequence</summary><ol data-ref="construction"></ol></details>
    <details open><summary>Qualification limits</summary><ul data-ref="limits"></ul></details>`
  const ref = name => host.querySelector(`[data-ref="${name}"]`)
  const panels = ['current', 'candidate', 'difference', 'defects']
  const titles = ['Current — refused draft', 'Candidate — isolated', 'Displacement overlay', 'Exact defects and moved atoms']
  panels.forEach((id, i) => {
    const card = document.createElement('section'); card.className = 'gr-panel'
    card.innerHTML = `<div class="gr-bar"><h2>${titles[i]}</h2><select aria-label="${id} representation"><option value="ballstick">Ball and Stick</option><option value="full">Full</option></select></div><div class="gr-view" data-view="${id}"></div>`
    host.querySelector('.gr-grid').append(card)
  })
  ref('title').textContent = evidence.label
  ref('context').textContent = evidence.full_geometry_changed
    ? 'Every atom and the complete parent geometry are included. Full shows the rigid duplex placement; Ball and Stick shows the exact root linkers and molecular contacts.'
    : 'Every atom and the complete parent geometry are included. Ball and Stick shows the linker changes. Full shows the surrounding DNA; the coarse nucleotide geometry is identical on both sides.'
  for (const [name, rows] of [['construction', evidence.construction], ['limits', evidence.limitations]]) {
    for (const text of rows) { const li = document.createElement('li'); li.textContent = text; ref(name).append(li) }
  }
  ref('fit').textContent = evidence.fit_description ?? (evidence.fit_expected
    ? 'This imported layout is independently reachable. Candidate retains both original root lengths without moving either parent body.'
    : 'These native Extrude roots remain too far apart. Preserving their linker groups does not make the Direct connection feasible; automatic fitting still refuses it.')
  ref('sweep').textContent = evidence.phase_sweep
    ? `Engineering controls: ${evidence.phase_sweep.length} phase settings across a full turn, both atom builders; ${evidence.unchanged_2hb_sweep.length} unchanged reciprocal 2HB controls. Native defects remain reported.`
    : evidence.related_controls ? `Related engineering evidence: ${evidence.related_controls.phase_cases} local-linker phase settings and ${evidence.related_controls.unchanged_2hb_cases} unchanged reciprocal 2HB controls; the other Direct and 2HB review cases remain available in this menu.` : ''
  let viewers = [], synchronizing = false, disposed = false
  function table(name, rows) {
    const table = document.createElement('table')
    for (const fields of rows) { const tr = table.insertRow(); for (const value of fields) tr.insertCell().textContent = String(value) }
    ref(name).replaceChildren(table)
  }
  function sync(source) {
    if (synchronizing) return
    synchronizing = true
    try { for (const target of viewers) if (target !== source) { copyAuditCameraState(source, target); target.controls.update(); target.render?.() } }
    finally { synchronizing = false }
  }
  function release() { for (const v of viewers) v.dispose(); viewers = [] }
  const fmt = value => value.toFixed(6)
  function show() {
    release()
    const builder = host.querySelector('[aria-label="Atom builder"]').value
    let bundle = builder === 'viewer' ? evidence : { ...evidence, ...evidence.export_models }
    bundle = { ...bundle, provider: { label: evidence.label },
      strand_colors: auditStrandColorMap({ ...bundle, nucleotides: bundle.current.nucleotides }) }
    try {
      for (const id of panels) {
        const element = host.querySelector(`[data-view="${id}"]`)
        const select = element.parentElement.querySelector('select')
        const v = viewerFactory(element, id, bundle, select.value)
        viewers.push(v)
        v.controls.addEventListener('change', () => sync(v))
        select.onchange = () => v.setRepresentation(select.value)
      }
      sync(viewers[0])
      const junctions = evidence.junctions[builder]
      table('roots', [['Root', 'Reference', 'Current', 'Candidate'], ...junctions.map(j => [j.overhang_id,
        ...['reference', 'current', 'candidate'].map(s => fmt(j.roots[s].length_nm))])])
      const driven = junctions[1]
      table('bonds', [['Driven adjacent bond', 'Reference', 'Current', 'Candidate'], ...driven.adjacent_bonds.map(b => [b.names.join('–'),
        ...['reference', 'current', 'candidate'].map(s => fmt(b.values[s].length_nm))])])
      table('angles', [['Driven adjacent angle (°)', 'Reference', 'Current', 'Candidate'], ...driven.adjacent_angles.map(a => [a.names.join('–'),
        ...['reference', 'current', 'candidate'].map(s => fmt(a.degrees[s]))])])
      table('metrics', auditMetricRows(bundle).map(row => row.slice(0, 2)))
      table('reference-diagnostics', [['Defect count', 'Reference', 'Current', 'Candidate'],
        ['Clashes', ...['reference', 'current', 'candidate'].map(s => bundle[s].diagnostics.n_clashes)],
        ['Piercings', ...['reference', 'current', 'candidate'].map(s => bundle[s].diagnostics.piercing.n_pierced)],
        ['Bond flags', ...['reference', 'current', 'candidate'].map(s => bundle[s].diagnostics.bonds.n_overstretched)]])
      ref('defects').replaceChildren(...auditDefectRows(bundle).map(row => {
        const li = document.createElement('li'); li.textContent = row.text; return li
      }))
      ref('focus').onclick = () => {
        const points = ['current', 'candidate'].flatMap(s => driven.roots[s].serials.map(i => {
          const a = bundle[s].atoms[i]; return new THREE.Vector3(a.x, a.y, a.z)
        }))
        const bounds = new THREE.Box3().setFromPoints(points)
        const center = bounds.getCenter(new THREE.Vector3())
        const v = viewers[0], direction = v.camera.position.clone().sub(v.controls.target).normalize()
        const halfVertical = THREE.MathUtils.degToRad(v.camera.fov / 2)
        const halfFov = Math.min(halfVertical, Math.atan(Math.tan(halfVertical) * v.camera.aspect))
        const distance = Math.max(4, bounds.getSize(new THREE.Vector3()).length() * .575 / Math.sin(halfFov))
        v.controls.target.copy(center); v.camera.position.copy(center).addScaledVector(direction, distance)
        v.controls.update(); v.render?.(); sync(v)
      }
      ref('reset').onclick = () => { viewers[0].fit(); sync(viewers[0]) }
    } catch (error) { release(); throw error }
  }
  try { show() } catch (error) { host.replaceChildren(); throw error }
  host.querySelector('[aria-label="Atom builder"]').onchange = show
  return { isRendered: () => !disposed && viewers.length === 4 && viewers.every(v => v.isRendered()),
    dispose() { if (disposed) return; disposed = true; release(); host.replaceChildren() } }
}
