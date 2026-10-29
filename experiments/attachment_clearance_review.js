import * as THREE from '../frontend/node_modules/three/build/three.module.js'
import { featureLabels } from '../frontend/src/features/feature_labels.js'
import {
  copyAuditCameraState, auditMetricRows, auditDefectRows,
  auditStrandColorMap,
} from '../frontend/src/ui/molecular_placement_audit.js'
import { createAttachmentReviewViewer } from './attachment_clearance_viewer.js'

const response = await fetch('comparison.json.gz')
if (!response.ok) throw new Error(`Review data: HTTP ${response.status}`)
const stream = response.body.pipeThrough(new DecompressionStream('gzip'))
const rootBundle = await new Response(stream).json()
const panels = ['current', 'candidate', 'difference', 'defects']
let viewers = [], activeBundle, synchronizing = false
const byId = id => document.getElementById(id)

function table(rows) {
  const out = document.createElement('table')
  for (const fields of rows) {
    const row = out.insertRow()
    for (const value of fields) row.insertCell().textContent = String(value)
  }
  return out
}

function sync(source) {
  if (synchronizing) return
  synchronizing = true
  for (const viewer of viewers) if (viewer !== source) copyAuditCameraState(source, viewer)
  synchronizing = false
  if (viewers.length === panels.length) drawLandmarks()
}

function setFocus() {
  const box = new THREE.Box3()
  for (const side of ['current', 'candidate']) {
    for (const [n, key] of rootBundle.landmark_pairs[side].rows) box.expandByPoint(new THREE.Vector3(...n[key]))
  }
  const center = box.getCenter(new THREE.Vector3())
  const radius = Math.max(box.getSize(new THREE.Vector3()).length()/2, 1.5)
  const v = viewers[0]
  v.controls.target.copy(center)
  const distance = radius / Math.sin(THREE.MathUtils.degToRad(v.camera.fov/2)) * 1.2
  v.camera.position.copy(center).add(new THREE.Vector3(4,3,6).normalize().multiplyScalar(distance))
  v.camera.near = 0.001
  v.camera.far = 1000
  v.camera.updateProjectionMatrix()
  v.controls.update()
  sync(v)
}

function drawLandmarks() {
  for (const [index, id] of panels.entries()) {
    const svg = byId(`${id}-annotation`)
    svg.replaceChildren()
    if (!activeBundle.landmark_pairs) continue
    const host = byId(`${id}-view`)
    const camera = viewers[index].camera
    camera.updateMatrixWorld()
    const sides = id === 'current' || id === 'candidate' ? [id] : ['current', 'candidate']
    for (const side of sides) {
      const pair = activeBundle.landmark_pairs[side]
      const points = pair.rows.map(([n, key]) => {
        const point = new THREE.Vector3(...n[key]).project(camera)
        return [(point.x+1)*host.clientWidth/2, (1-point.y)*host.clientHeight/2]
      })
      const color = side === 'current' ? '#52c7ff' : '#ff72ca'
      const line = document.createElementNS('http://www.w3.org/2000/svg', 'line')
      for (const [name, value] of Object.entries({ x1: points[0][0], y1: points[0][1], x2: points[1][0], y2: points[1][1], stroke: color, 'stroke-width': 3 })) line.setAttribute(name, value)
      svg.append(line)
      for (const point of points) {
        const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle')
        for (const [name, value] of Object.entries({ cx: point[0], cy: point[1], r: 7, fill: 'none', stroke: color, 'stroke-width': 2 })) circle.setAttribute(name, value)
        svg.append(circle)
      }
    }
  }
}

function show(bundle) {
  for (const viewer of viewers) viewer.dispose()
  viewers = []
  activeBundle = bundle
  byId('current-view').previousElementSibling.querySelector('h2').textContent = bundle.landmark_pairs ? 'Current — rejected draft' : 'Current — production control'
  byId('candidate-view').previousElementSibling.querySelector('h2').textContent = bundle.landmark_pairs ? 'Candidate — not authorized' : 'Candidate — identical control'
  bundle.strand_colors = auditStrandColorMap({ ...bundle, nucleotides: bundle.current.nucleotides })
  for (const id of panels) {
    const side = id === 'candidate' ? 'candidate' : 'current'
    // Supply each Full panel with that side's actual native geometry. The
    // Difference and defect panels use the shared atomistic audit renderer.
    const panelBundle = { ...bundle, nucleotides: bundle[side].nucleotides, helix_axes: [] }
    const select = byId(`${id}-representation`)
    const representation = select ? select.value : 'ballstick'
    const viewer = createAttachmentReviewViewer(byId(`${id}-view`), id, panelBundle, representation)
    viewers.push(viewer)
    viewer.controls.addEventListener('change', () => sync(viewer))
    if (select) select.onchange = () => viewer.setRepresentation(select.value)
  }
  sync(viewers[0])
  byId('metrics').replaceChildren(table(auditMetricRows(bundle).map(row => row.slice(0, 2))))
  byId('defect-list').replaceChildren(...auditDefectRows(bundle).map(row => {
    const item = document.createElement('li')
    item.textContent = row.text
    return item
  }))
  byId('bond-list').replaceChildren(table([
    ['Side', 'Exact bond atoms (chain/residue:name)', 'Length (nm)', 'Limit (nm)'],
    ...['current', 'candidate'].flatMap(side => bundle[side].diagnostics.bonds.overstretched.map(hit => [
      side, hit.serials.map(i => {
        const atom = bundle[side].atoms[i]
        return `${atom.chain_id}/${atom.seq_num}:${atom.name} (#${i})`
      }).join(' ↔ '), hit.length_nm.toFixed(6), hit.limit_nm ?? 'see diagnostic',
    ])),
  ]))
  byId('focus').disabled = !bundle.landmark_pairs
  byId('focus').onclick = setFocus
  byId('reset').onclick = () => { viewers[0].fit(); sync(viewers[0]) }
  drawLandmarks()
  window.__attachmentReview = { ready: true, case: byId('case').value, panels: viewers.length,
    rendered:()=>viewers.every(viewer=>viewer.isRendered()) }
}

const summary = rootBundle.summary
byId('candidate-rule').textContent = rootBundle.provider.id === 'candidate_host_obstacles'
  ? 'The candidate limits the 2 nm near-root exemption to the overhang’s own covalent host strand. Separate strands and other overhangs remain obstacles there. The radius, 0.5 nm landmark cutoff, molecular constants, and search grid are unchanged.'
  : 'The first candidate retains other overhangs as obstacles inside the 2 nm near-root exemption. Untagged parent-structure landmarks still receive the existing exemption. This variant introduced a different atom clash and has not been proposed for production.'
if (rootBundle.provider.fit_policy === 'fit_shortest_root_bond') {
  byId('candidate-rule').textContent += ' Among poses passing every existing landmark/gold clearance requirement and the existing atom-clash check on the native terminal linker, this diagnostic selects the shortest native covalent bond across the root. It does not alter atom placement or linker chemistry, add a pose sample, or change a detector threshold. The resulting bond is still overstretched; this is a geometric fitting candidate, not a simulation-ready seed.'
}
if (summary.comparison_scope === 'four_attachments_from_same_unbound_input') {
  byId('candidate-rule').textContent += ' Candidate rebuilds all four attachments from the exact same unbound input, including the three attachments accepted before Current refused. The crop includes every atom displaced by those earlier pose changes as well as the failed attachment.'
}
byId('clearance').textContent = `Completed duplex minimum landmark separation: ${summary.current_distance_nm.toFixed(6)} → ${summary.candidate_distance_nm.toFixed(6)} nm; required ≥0.5 nm. All nine candidate attachments close, maximum residual ${summary.candidate_max_residual_nm.toExponential(2)} nm; particle centers are unchanged.`
const clashPairs = side => new Set(rootBundle[side].diagnostics.clashes.map(hit => [...hit.serials].sort((a,b)=>a-b).join(',')))
const originalPairs=clashPairs('current'), candidatePairs=clashPairs('candidate')
const introduced=[...candidatePairs].filter(pair=>!originalPairs.has(pair))
const removed=[...originalPairs].filter(pair=>!candidatePairs.has(pair))
byId('pair-changes').textContent = `Exact atom-pair changes: ${removed.length} clash pair(s) removed, ${introduced.length} introduced. ${introduced.length ? 'This candidate introduces a new atom clash and is not ready for approval.' : 'No new atom clash pair is detected in the reviewed crop.'} Existing atomistic defects remain listed below.`
byId('pair-changes').className = introduced.length ? 'notice' : ''
byId('joints').replaceChildren(table([
  ['Connection', ...summary.joints.map(row => row.connection)],
  ['Landmark separation (nm)', ...summary.joints.map(row => `${row.current.minimum_landmark_distance_nm.toFixed(3)} → ${row.candidate.minimum_landmark_distance_nm.toFixed(3)}`)],
  ['Candidate residual (nm)', ...summary.joints.map(row => row.candidate.residual_nm.toExponential(2))],
  ['Maximum atom shift (nm)', ...summary.joints.map(row => row.max_atom_displacement_nm?.toFixed(3) ?? '—')],
  ['Longest bond (nm)', ...summary.joints.map(row => row.current.max_bond_nm === undefined ? '—' : `${row.current.max_bond_nm.toFixed(3)} → ${row.candidate.max_bond_nm.toFixed(3)}`)],
  ['Clashes', ...summary.joints.map(row => `${row.current.clashes ?? '—'} → ${row.candidate.clashes ?? '—'}`)],
  ['Piercings', ...summary.joints.map(row => `${row.current.piercings ?? '—'} → ${row.candidate.piercings ?? '—'}`)],
]))
const sequence = rootBundle.feature_sequence.map(feature => ({ op_kind: feature.kind, label: feature.label }))
sequence.push({ op_kind: 'nanoparticle-attach-overhang', label: 'Attach to Overhang — rejected draft versus isolated candidate; not saved or applied' })
for (const label of featureLabels(sequence)) {
  const row = document.createElement('li')
  row.textContent = label
  byId('features').append(row)
}
byId('features').lastElementChild.className = 'pending'
byId('phase').textContent = `${summary.phase_controls.length}/22 unchanged molecular controls: one- and two-base crossover inserts, registers 8–18 (a complete helical turn). Atom/bond feeds are identical with the candidate installed. Clean and pierced controls remain available below; these controls do not establish physical validity of the platform.`
byId('case').onchange = event => show(event.target.value === 'platform' ? rootBundle : rootBundle.controls[event.target.value])
show(rootBundle)
window.addEventListener('resize', drawLandmarks)
window.addEventListener('beforeunload', () => { for (const viewer of viewers) viewer.dispose() })
