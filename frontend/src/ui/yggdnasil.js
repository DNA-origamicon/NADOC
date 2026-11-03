import { enumerateCylinders } from '../design/yggdnasil_cylinders.js'
import { buildCylinderTree } from '../design/yggdnasil_cylinder_tree.js'
import { enumerateRods } from '../design/yggdnasil.js'
import { routingTotals, routingExport, routingScreen, CYLINDER_ROUTING_REPORT } from '../design/yggdnasil_routing.js'
import { buildYggBranches } from '../design/yggdnasil_branches.js'
import { cellAllocation, CURVATURE_LIMITS } from '../design/yggdnasil_curvature.js'
import { arcPreview } from './yggdnasil_arc.js'
import { createYggTreeViewer } from '../scene/yggdnasil_tree.js'
import { createModal } from './primitives/modal.js'
import './yggdnasil.css'
let active = null
const svg = (content, viewBox, label) => `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${viewBox}" role="img" aria-label="${label}">${content}</svg>`
export function showYggDNAsil({ viewerFactory = createYggTreeViewer } = {}) {
  if (active?.isOpen()) { active.root.querySelector('button')?.focus(); return active }
  const priorFocus = document.activeElement
  const body = document.createElement('div'); body.className = 'ygg'
  body.innerHTML = `<p class="ygg-kicker">YggDNAsil / the architecture tree</p>
    <p>Two lattices. One 7249-nt budget. Explore radius twigs with solid-rod curvature branches and straight hollow cylinders.</p>
    <div class="ygg-controls"><label>Scaffold <select data-scaffold disabled><option>7249</option></select> nt</label>
    <label>Minimum length <input data-min type="number" min="21" max="8064" value="21"> bp</label>
    <label>Reserved scaffold <input data-reserve type="number" min="0" max="8063" value="0"> nt</label>
    <label>Shapes <select data-shape><option value="all">Solids + hollow cylinders</option><option value="solid">Solid rods</option><option value="hollow">Hollow cylinders (straight)</option></select></label>
    <label>Routing screen <select data-filter><option value="all">All candidates</option><option value="remaining">Keep possible / unresolved</option><option value="excluded">Excluded by traversal rules</option><option value="unresolved">Search unresolved</option></select></label>
    <button type="button" data-export>Export atlas JSON</button></div>
    <p data-status role="status" aria-live="polite"></p><p class="ygg-screen-summary" data-routing-summary></p><p class="ygg-screen-summary" data-cylinder-status></p>
    <div class="ygg-layout"><section class="ygg-tree-column" aria-label="YggDNAsil design tree">
      <div class="ygg-tree-toolbar"><label>All points at <input data-tree-length type="number" min="21" max="7249" value="100"> bp</label><button data-reset type="button">Reset view</button></div>
      <div class="ygg-tree-view" data-tree-view></div>
      <div class="ygg-tree-legend"><span class="square">● Square</span><span class="honeycomb">● Honeycomb</span><span class="excluded">● Excluded by traversal</span><span>○ Hollow cylinder</span><span>◉ Selected structure</span></div>
      <p class="ygg-caption">Drag to orbit · scroll to zoom · click a point or its label. Solid points sprout curvature branches; hollow limbs increase inner radius at fixed outer radius and length; the trunk groups families. Each lattice splits into helix-, bond- and cell-centered twigs.</p>
      <p class="ygg-caption" data-slice-status></p>
      <label class="ygg-node-picker">Select a structure <select data-node aria-label="Select a structure"></select></label>
    </section><section class="ygg-detail" aria-label="Selected structure"></section></div>
    <details class="ygg-method"><summary>Tree connections and counting rules</summary>
      <p>Every point is a specific footprint at the shared axial length. Within each lattice and center family, an edge joins consecutive disk radii. This is one parameter step, not necessarily two helices: boundary shells may add more. Neighbor buttons show the actual helix-count change. No intermediate footprints are invented. Filtering a structure leaves a gap; it never connects across a missing shell. The same footprint may appear on more than one centering twig; these are aliases, counted only once.</p>
      <p>Curvature is limited to uniform planar arcs in the canonical +X bend direction, with no added twist and at most 360° total turn. Sweep’s native limit is three insertions/deletions per seven-bp cell. Count classes distinguish total inserted and deleted bases separately, including baseline square-lattice compensation, while ignoring allocation and sequence variants. Preview angles are canonical representatives; the same totals do not imply identical physical curvature for arbitrary allocations. Cell allocations respect the local cap but do not yet check routed crossover-safe sites. Every eligible straight point is the zero-curvature junction of its own count-class branch. Curvature increases outward on a 5° target grid, stopping at the largest admissible multiple of 5°. Repeated insertion/deletion totals are merged, so some links span more than 5°. Targets that round to zero bend modifications remain at the straight junction. Excluded traversal designs have no curvature branches; unresolved searches remain labeled. Branches stop at the first rejected class, without bridging gaps.</p>
      <p>The atlas enumerates connected closed disks at helix, bond and cell symmetry centers. Equal-distance sites enter together. Translation and lattice rotations identify duplicate footprints. Lengths range from the minimum to floor((scaffold − reserve) / helices), in integer bp. The default 21 bp minimum is an atlas boundary, not a rigidity threshold. Pitch is 2.25 nm; axial rise is ${CURVATURE_LIMITS.rise_nm} nm/bp. Radius measures inclusion of helix centers.</p>
      <p>Traversal screening applies to NADOC’s uniform-bundle Hamiltonian routing family. Parity imbalance or exhaustive path failure excludes a footprint within this family; hitting the search limit stays unresolved. Traversal witnesses do not validate nucleotide-level routing, exact scaffold completion, staples, folding or rigidity. Curved hollow cylinders, nonuniform bends, added twist, arbitrary disk centers and custom return paths remain outside this atlas. The preliminary budget is H × L + insertions − deletions + reserve ≤ 7249; unallocated scaffold and unverified turn overhead are shown explicitly. A 360° preview does not certify end closure or collision freedom.</p>
      <p>Hollow cylinders remove complete concentric shells, leaving a connected wall enclosing the removed lattice sites. The inner cutoff Ri is the radius of the last removed helix-center shell (including Ri = 0 when the central helix is removed), not a molecular bore radius. Occupied sites satisfy Ri &lt; r ≤ Ro. Wider thin walls are included even when their filled disk exceeds the scaffold budget. Cylinders use H × L + reserve ≤ 7249; no added bend or twist is enumerated. Solid and hollow limbs share categorical stems, not cross-shape design-step links. Known traversal failures are omitted from hollow limbs; unresolved cases remain labeled. Native traversal screening covers walls up to 72 helices; larger walls receive the parity test and remain unresolved if it passes.</p>
    </details>`
  let atlas, model, solidModel, cylinderAtlas, cylinderKey, worker, revision = 0, selectedNode, viewer
  const modal = createModal({ title: 'YggDNAsil · Design atlas', size: 'xl', className: 'ygg-modal', body,
    onClose: () => { revision++; worker?.terminate(); viewer?.dispose(); active = null; if (priorFocus?.isConnected) priorFocus.focus() } })
  active = modal
  modal.header.querySelector('.modal__title').id = 'ygg-title'; modal.root.setAttribute('aria-labelledby', 'ygg-title')
  function selectNode(id) {
    selectedNode = model.nodes.find(n => n.id === id)
    body.querySelector('[data-node]').value = selectedNode?.id || ''
    viewer?.update(model, selectedNode?.id)
    detail()
  }
  function detail() {
    const panel = body.querySelector('.ygg-detail')
    if (!selectedNode) { panel.textContent = 'No footprints or count classes match this length, budget and filter. Adjust the tree length, reserve or routing filter.'; return }
    const { entry, routing: screen, length, center } = selectedNode, p = entry.points
    const minX = Math.min(...p.map(v => v.x)), maxX = Math.max(...p.map(v => v.x))
    const minY = Math.min(...p.map(v => v.y)), maxY = Math.max(...p.map(v => v.y))
    const width = maxX - minX + 1.2, height = maxY - minY + 1.2
    const footprint = svg(p.map(v => `<circle cx="${v.x}" cy="${v.y}" r="0.44"/>`).join(''), `${minX - 0.6} ${minY - 0.6} ${width} ${height}`, `${entry.helices} helix cross-section`)
    const curve = selectedNode.curvature, hollow = entry.shape === 'hollow'
    const used = curve ? curve.used : entry.helices * length, remaining = atlas.scaffold - used, axial = length * CURVATURE_LIMITS.rise_nm
    const span = Math.max(1, (maxX - minX) * 2.25 + 2)
    panel.innerHTML = `<p class="ygg-kicker">${entry.lattice} / ${hollow ? 'straight hollow cylinder' : curve ? 'curvature counts' : `${center}-centered`} / ${entry.id}</p><h2>${entry.helices}hb <small>× ${length} bp</small></h2>
      <p class="ygg-screen ${screen.excluded ? 'ygg-screen--excluded' : ''}">${screen.label}${screen.even !== undefined ? ` · parity ${screen.even}:${screen.odd}` : ''}</p>
      <div data-curve-summary></div><div class="ygg-neighbors" data-neighbors aria-label="Adjacent design steps"></div>
      <div class="ygg-footprint">${curve ? arcPreview(entry, length, curve.angleRad) : footprint}</div>
      <p class="ygg-caption">${curve ? 'Nominal arc envelope; cross-section' : 'Cross-section'} · ${((maxX - minX) * 2.25).toFixed(2)} × ${((maxY - minY) * 2.25).toFixed(2)} nm between outermost helix centers</p>
      <div data-measure>${curve ? `<details><summary>Cross-section</summary><div class="ygg-footprint">${footprint}</div></details>` : `<div class="ygg-side">${svg(`<rect x="0" y="0" width="${axial}" height="${span}" rx="0.5"/>`, `-2 -2 ${axial + 4} ${span + 4}`, 'Rod side silhouette at true aspect ratio')}</div>`}
      <p><strong>${length} bp · ${axial.toFixed(2)} nm long</strong></p><div class="ygg-budget"><i style="width:${100 * used / atlas.scaffold}%"></i></div><p>${used.toLocaleString()} nt ${curve ? 'structural budget' : 'paired'} · ${remaining.toLocaleString()} nt unallocated (${atlas.reserve} reserved)</p></div>
      <p class="ygg-caption">${hollow ? `One straight cylinder at ${length} bp. Preliminary paired-base budget permits lengths from 21 to ${entry.maxLength} bp; turn overhead and square compensation remain unallocated.` : curve ? `Preliminary budget only: H × L + I − D ≤ 7249. The original straight-footprint range was ${entry.minLength}–${entry.maxLength} bp; curvature counts and square compensation can change the allowable length.` : `${entry.count.toLocaleString()} axial sizes in the straight atlas (${entry.minLength}–${entry.maxLength} bp). The tree holds all structures at ${length} bp.`}</p>`
    if (hollow) {
      panel.querySelector('[data-curve-summary]').innerHTML = `<p data-hollow-summary><strong>Straight hollow cylinder · 0°</strong><br>Outer radius Ro ${selectedNode.outerRadiusNm.toFixed(2)} nm · inner cutoff Ri ${selectedNode.innerRadiusNm.toFixed(2)} nm<br>${selectedNode.source.removedHelices} interior helix sites removed · ${entry.helices} wall helices</p><p class="ygg-caption">Curved cylinders are not included. Radii describe helix-center occupancy, not molecular surfaces.</p>`
    }
    if (curve) {
      panel.querySelector('[data-curve-summary]').innerHTML = `<p class="ygg-curvature-title"><strong>${curve.angleDeg.toFixed(2)}°</strong> · ${curve.radiusNm === null ? 'straight' : `R ${curve.radiusNm.toFixed(2)} nm`}</p><p><b>${curve.loops} inserted · ${curve.skips} deleted</b> (${curve.baselineSkips} baseline square skips)</p><p class="ygg-caption"><b>${used.toLocaleString()} / 7249 nt</b> · ${remaining.toLocaleString()} unallocated (${atlas.reserve} reserved)</p><p class="ygg-caption">Nominal target on a 5° grid; rounded counts do not guarantee exact relaxed curvature · demand ${curve.maxDeltaPerCell.toFixed(2)} / ${CURVATURE_LIMITS.max_delta_per_cell} per ${CURVATURE_LIMITS.cell_bp}-bp cell.</p>`
    }
    for (const parameter of (hollow ? ['inner-radius'] : ['radius', 'curvature-counts'])) {
      for (const [direction, symbol] of [['previous', '←'], ['next', '→']]) {
        const edge = model.edges.find(e => e.parameter === parameter && (direction === 'next' ? e.from === selectedNode.id : e.to === selectedNode.id))
        const node = edge && model.nodes.find(n => n.id === (direction === 'next' ? edge.to : edge.from))
        const button = document.createElement('button'); button.type = 'button'; button.disabled = !node
        const key = parameter === 'radius' ? direction : parameter === 'inner-radius' ? `inner-${direction}` : `bend-${direction}`; button.dataset.step = key
        button.textContent = node ? (parameter === 'inner-radius' ? `${symbol} Inner cutoff ${node.innerRadiusNm.toFixed(2)} nm · ${node.entry.helices}hb` : parameter === 'curvature-counts' ? `${symbol} Bend ${node.curvature.angleDeg.toFixed(1)}° · I${node.curvature.loops}/D${node.curvature.skips}` : `${symbol} Radius: ${node.entry.helices}hb (${direction === 'next' ? '+' : '−'}${edge.deltaHelices})`) : `${symbol} No ${parameter === 'radius' ? 'radius' : parameter === 'inner-radius' ? 'inner-radius' : 'bend'} step`
        button.addEventListener('click', () => { selectNode(node.id); panel.querySelector(`[data-step=${key}]`)?.focus() })
        panel.querySelector('[data-neighbors]').append(button)
      }
    }
    if (!hollow && selectedNode.rootId && selectedNode.rootId !== selectedNode.id) {
      const button = document.createElement('button'); button.type = 'button'; button.textContent = 'Back to straight junction'; button.dataset.straight = ''
      button.addEventListener('click', () => selectNode(selectedNode.rootId))
      panel.querySelector('[data-neighbors]').append(button)
    }
  }

  function rebuild() {
    const current = ++revision; worker?.terminate(); worker = null
    const scaffold = Number(body.querySelector('[data-scaffold]').value)
    const min = body.querySelector('[data-min]'), reserve = body.querySelector('[data-reserve]'), axial = body.querySelector('[data-tree-length]')
    min.max = scaffold; reserve.max = scaffold - 1; axial.min = min.value; axial.max = scaffold
    if (![min, reserve, axial].every(input => input.value !== '' && input.checkValidity())) {
      body.querySelector('[data-status]').textContent = 'Enter whole-number bounds and a tree length within the selected scaffold and minimum.'
      body.querySelector('[data-export]').disabled = true
      return
    }
    body.querySelector('[data-export]').disabled = false
    atlas = enumerateRods({ scaffold, minLength: Number(min.value), reserve: Number(reserve.value) })
    solidModel = buildYggBranches(atlas, { length: Number(axial.value), filter: body.querySelector('[data-filter]').value })
    const key = `${scaffold}:${axial.value}:${reserve.value}`
    if (cylinderKey === key && cylinderAtlas) { renderTree(); return }
    cylinderAtlas = null; cylinderKey = key; renderTree()
    body.querySelector('[data-export]').disabled = true
    body.querySelector('[data-cylinder-status]').textContent = 'Enumerating straight hollow cylinders…'
    const options = { scaffold, length: Number(axial.value), reserve: Number(reserve.value) }
    const accept = result => {
      if (current !== revision) return
      worker?.terminate(); worker = null
      if (result.error) { body.querySelector('[data-cylinder-status]').textContent = `Cylinder enumeration failed: ${result.error}`; cylinderKey = null; return }
      cylinderAtlas = result.atlas; body.querySelector('[data-export]').disabled = false; renderTree()
    }
    if (typeof Worker === 'undefined') { accept({ atlas: enumerateCylinders(options) }); return }
    worker = new Worker(new URL('../design/yggdnasil_cylinder_worker.js', import.meta.url), { type: 'module' })
    worker.onmessage = event => accept(event.data)
    worker.onerror = () => accept({ error: 'Worker unavailable. Reload to retry.' })
    worker.postMessage(options)
  }
  function renderTree() {
    const shape = body.querySelector('[data-shape]').value
    const cylinders = cylinderAtlas ? buildCylinderTree(cylinderAtlas, { filter: body.querySelector('[data-filter]').value }) : { nodes: [], edges: [], stems: [], structureCount: 0 }
    const solid = shape !== 'hollow', hollow = shape !== 'solid'
    model = { ...solidModel, branchCount: solid ? solidModel.branchCount : 0,
      nodes: [...(solid ? solidModel.nodes : []), ...(hollow ? cylinders.nodes : [])],
      edges: [...(solid ? solidModel.edges : []), ...(hollow ? cylinders.edges : [])],
      stems: [...(solid ? solidModel.stems : []), ...(hollow ? cylinders.stems : [])],
      structureCount: (solid ? solidModel.structureCount : 0) + (hollow ? cylinders.structureCount : 0) }
    const totals = routingTotals(atlas.entries)
    body.querySelector('[data-routing-summary]').textContent = `${totals.excluded.toLocaleString()} excluded (${totals.total ? (100 * totals.excluded / totals.total).toFixed(1) : '0.0'}%) · ${totals.path_found.toLocaleString()} with a helix traversal · ${totals.unresolved.toLocaleString()} unresolved. Full scaffold routing remains untested.`
    body.querySelector('[data-status]').textContent = `Solid occupancy atlas: ${atlas.entries.length} unique footprints · ${atlas.count.toLocaleString()} footprint × length candidates · one ${atlas.scaffold} nt scaffold`
    body.querySelector('[data-slice-status]').textContent = `${model.branchCount} curvature branches · ${model.structureCount} distinct structures at ${model.length} bp · ${model.nodes.length} points including centering aliases · ${model.edges.length} single-parameter links. Filters preserve gaps.`
    if (cylinderAtlas) {
      const t = routingTotals(cylinderAtlas.entries)
      body.querySelector('[data-cylinder-status]').textContent = `Straight cylinders at ${cylinderAtlas.length} bp: ${cylinderAtlas.entries.length.toLocaleString()} unique footprints · ${t.excluded.toLocaleString()} excluded · ${t.path_found.toLocaleString()} with a traversal · ${t.unresolved.toLocaleString()} unresolved. Known failures are omitted from hollow limbs.`
    }
    const picker = body.querySelector('[data-node]'); picker.replaceChildren()
    for (const lattice of ['square', 'honeycomb']) {
      const group = document.createElement('optgroup'); group.label = lattice === 'square' ? 'Square' : 'Honeycomb'
      for (const node of model.nodes.filter(n => n.lattice === lattice)) {
        const option = document.createElement('option'); option.value = node.id
        option.textContent = node.shape === 'hollow' ? `Hollow ${node.entry.helices}hb × ${node.length} bp · Ro ${node.outerRadiusNm.toFixed(2)} / Ri ${node.innerRadiusNm.toFixed(2)} nm · ${node.center}${node.routing.status === 'unresolved' ? ' · unresolved' : ''}` : node.curvature?.angleRad > 0 ? `${node.curvature.angleDeg.toFixed(2)}° · I${node.curvature.loops} / D${node.curvature.skips} · ${node.entry.helices}hb × ${node.length} bp · ${node.center} center${node.routing.status === 'unresolved' ? ' · unresolved' : ''}` : `${node.entry.helices}hb × ${node.length} bp · ${node.center} center${node.routing.excluded ? ' · excluded' : node.routing.status === 'unresolved' ? ' · unresolved' : ''}`; group.append(option)
      }
      picker.append(group)
    }
    picker.disabled = !model.nodes.length
    const next = model.nodes.find(n => n.id === selectedNode?.id) || model.nodes.find(n => n.entry.id === selectedNode?.entry.id) || model.nodes.find(n => n.entry.helices >= 6 && !n.routing.excluded) || model.nodes[0]
    selectNode(next?.id)
  }
  for (const input of body.querySelectorAll('[data-scaffold], [data-min], [data-reserve], [data-filter], [data-tree-length]')) input.addEventListener('change', rebuild)
  body.querySelector('[data-shape]').addEventListener('change', renderTree)
  body.querySelector('[data-node]').addEventListener('change', event => selectNode(event.target.value))
  body.querySelector('[data-reset]').addEventListener('click', () => viewer?.reset())
  body.querySelector('[data-export]').addEventListener('click', () => {
    const output = { ...routingExport(atlas), tree: { length: model.length, filter: model.filter, nodes: model.nodes.map(n => ({ id: n.id, footprintId: n.entry.id, center: n.center, shape: n.shape || 'solid', outerRadiusNm: n.outerRadiusNm, innerRadiusNm: n.innerRadiusNm, length: n.length, rootId: n.rootId, curvature: n.curvature })), edges: model.edges } }
    if (cylinderAtlas) output.cylinders = { ...cylinderAtlas, entries: cylinderAtlas.entries.map(entry => ({ ...entry, routing: routingScreen(entry) })), routingScreen: { scope: CYLINDER_ROUTING_REPORT.scope, max_helices: CYLINDER_ROUTING_REPORT.max_helices, source_sha256: CYLINDER_ROUTING_REPORT.source_sha256 } }
    const catalog = model.catalogs.get(selectedNode?.entry.id)
    if (catalog) output.curvature = { scope: catalog.scope, limits: CURVATURE_LIMITS, maxAngleDeg: catalog.maxAngleDeg, angleStepDeg: catalog.angleStepDeg, maxSampleAngleDeg: catalog.maxSampleAngleDeg, excluded: catalog.excluded, classes: catalog.classes, selectedCellAllocation: selectedNode?.curvature ? cellAllocation(catalog, selectedNode.curvature) : [] }
    const url = URL.createObjectURL(new Blob([JSON.stringify(output, null, 2)], { type: 'application/json' }))
    const a = document.createElement('a'); a.href = url; a.download = `yggdnasil-${atlas.scaffold}.json`; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000)
  })
  modal.root.addEventListener('keydown', event => {
    event.stopPropagation()
    if (event.key === 'Escape') { event.preventDefault(); modal.close() }
    if (event.key === 'Tab') {
      const controls = [...modal.root.querySelectorAll('button,input,select,summary,canvas')].filter(e => !e.disabled && e.tabIndex >= 0 && e.getClientRects().length)
      const first = controls[0], last = controls.at(-1)
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
    }
  })
  modal.open()
  try { viewer = viewerFactory(body.querySelector('[data-tree-view]'), selectNode) }
  catch { body.querySelector('[data-tree-view]').textContent = '3D rendering is unavailable. Use the structure selector and adjacent-step buttons below to explore the same tree.' }
  rebuild(); body.querySelector('[data-tree-length]').focus()
  return modal
}
