import { enumerateRods, SCAFFOLDS } from '../design/yggdnasil.js'
import { routingTotals, routingExport } from '../design/yggdnasil_routing.js'
import { buildYggTree } from '../design/yggdnasil_tree.js'
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
    <p>Two lattices. One length. Follow a branch to grow the radius, one discrete shell at a time.</p>
    <div class="ygg-controls"><label>Scaffold <select data-scaffold>${SCAFFOLDS.map(s => `<option>${s}</option>`).join('')}</select> nt</label>
    <label>Minimum length <input data-min type="number" min="21" max="8064" value="21"> bp</label>
    <label>Reserved scaffold <input data-reserve type="number" min="0" max="8063" value="0"> nt</label>
    <label>Routing screen <select data-filter><option value="all">All candidates</option><option value="remaining">Keep possible / unresolved</option><option value="excluded">Excluded by traversal rules</option><option value="unresolved">Search unresolved</option></select></label>
    <button type="button" data-export>Export atlas JSON</button></div>
    <p data-status role="status" aria-live="polite"></p><p class="ygg-screen-summary" data-routing-summary></p>
    <div class="ygg-layout"><section class="ygg-tree-column" aria-label="YggDNAsil design tree">
      <div class="ygg-tree-toolbar"><label>All points at <input data-tree-length type="number" min="21" max="7249" value="100"> bp</label><button data-reset type="button">Reset view</button></div>
      <div class="ygg-tree-view" data-tree-view></div>
      <div class="ygg-tree-legend"><span class="square">● Square</span><span class="honeycomb">● Honeycomb</span><span class="excluded">● Excluded by traversal</span><span>◉ Selected structure</span></div>
      <p class="ygg-caption">Drag to orbit · scroll to zoom · click a point or its label. Colored links change only radius; the trunk groups families. Each lattice splits into helix-, bond- and cell-centered twigs.</p>
      <p class="ygg-caption" data-slice-status></p>
      <label class="ygg-node-picker">Select a structure <select data-node aria-label="Select a structure"></select></label>
    </section><section class="ygg-detail" aria-label="Selected rod"></section></div>
    <details class="ygg-method"><summary>Tree connections and counting rules</summary>
      <p>Every point is a specific footprint at the shared axial length. Within each lattice and center family, an edge joins consecutive disk radii. This is one parameter step, not necessarily two helices: boundary shells may add more. Neighbor buttons show the actual helix-count change. No intermediate footprints are invented. Filtering a structure leaves a gap; it never connects across a missing shell. The same footprint may appear on more than one centering twig; these are aliases, counted only once.</p>
      <p>The atlas enumerates connected closed disks at helix, bond and cell symmetry centers. Equal-distance sites enter together. Translation and lattice rotations identify duplicate footprints. Lengths range from the minimum to floor((scaffold − reserve) / helices), in integer bp. The default 21 bp minimum is an atlas boundary, not a rigidity threshold. Pitch is 2.25 nm; axial rise is 0.34 nm/bp. Radius measures inclusion of helix centers.</p>
      <p>Traversal screening applies to NADOC’s uniform-bundle Hamiltonian routing family. Parity imbalance or exhaustive path failure excludes a footprint within this family; hitting the search limit stays unresolved. Traversal witnesses do not validate nucleotide-level routing, exact scaffold completion, staples, folding or rigidity. Bend, twist, hollow tubes, arbitrary disk centers and custom return paths remain outside this atlas.</p>
    </details>`
  let atlas, model, selectedNode, viewer
  const modal = createModal({ title: 'YggDNAsil · Solid rod atlas', size: 'xl', className: 'ygg-modal', body,
    onClose: () => { viewer?.dispose(); active = null; if (priorFocus?.isConnected) priorFocus.focus() } })
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
    if (!selectedNode) { panel.textContent = 'No footprints match this length, budget and filter. Adjust the tree length, reserve or routing filter.'; return }
    const { entry, routing: screen, length, center } = selectedNode, p = entry.points
    const minX = Math.min(...p.map(v => v.x)), maxX = Math.max(...p.map(v => v.x))
    const minY = Math.min(...p.map(v => v.y)), maxY = Math.max(...p.map(v => v.y))
    const width = maxX - minX + 1.2, height = maxY - minY + 1.2
    const footprint = svg(p.map(v => `<circle cx="${v.x}" cy="${v.y}" r="0.44"/>`).join(''), `${minX - 0.6} ${minY - 0.6} ${width} ${height}`, `${entry.helices} helix cross-section`)
    const used = entry.helices * length, remaining = atlas.scaffold - used, axial = length * 0.34
    const span = Math.max(1, (maxX - minX) * 2.25 + 2)
    panel.innerHTML = `<p class="ygg-kicker">${entry.lattice} / ${center}-centered / ${entry.id}</p><h2>${entry.helices}hb <small>× ${length} bp</small></h2>
      <p class="ygg-screen ${screen.excluded ? 'ygg-screen--excluded' : ''}">${screen.label}${screen.even !== undefined ? ` · parity ${screen.even}:${screen.odd}` : ''}</p>
      <div class="ygg-neighbors" data-neighbors aria-label="Adjacent radius steps"></div>
      <div class="ygg-footprint">${footprint}</div>
      <p class="ygg-caption">Cross-section · ${((maxX - minX) * 2.25).toFixed(2)} × ${((maxY - minY) * 2.25).toFixed(2)} nm between outermost helix centers</p>
      <div data-measure><div class="ygg-side">${svg(`<rect x="0" y="0" width="${axial}" height="${span}" rx="0.5"/>`, `-2 -2 ${axial + 4} ${span + 4}`, 'Rod side silhouette at true aspect ratio')}</div>
      <p><strong>${length} bp · ${axial.toFixed(2)} nm long</strong></p><div class="ygg-budget"><i style="width:${100 * used / atlas.scaffold}%"></i></div><p>${used.toLocaleString()} nt paired · ${remaining.toLocaleString()} nt remaining (${atlas.reserve} reserved)</p></div>
      <p class="ygg-caption">${entry.count.toLocaleString()} axial sizes in the full atlas (${entry.minLength}–${entry.maxLength} bp). The tree holds all structures at ${length} bp.</p>`
    for (const [direction, symbol] of [['previous', '←'], ['next', '→']]) {
      const edge = model.edges.find(e => direction === 'next' ? e.from === selectedNode.id : e.to === selectedNode.id)
      const node = edge && model.nodes.find(n => n.id === (direction === 'next' ? edge.to : edge.from))
      const button = document.createElement('button'); button.type = 'button'; button.disabled = !node; button.dataset.step = direction
      button.textContent = node ? `${symbol} ${node.entry.helices}hb (${direction === 'next' ? '+' : '−'}${edge.deltaHelices})` : `${symbol} No adjacent step`
      button.addEventListener('click', () => { selectNode(node.id); panel.querySelector(`[data-step=${direction}]`)?.focus() })
      panel.querySelector('[data-neighbors]').append(button)
    }
  }
  function rebuild() {
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
    model = buildYggTree(atlas, { length: Number(axial.value), filter: body.querySelector('[data-filter]').value })
    const totals = routingTotals(atlas.entries)
    body.querySelector('[data-routing-summary]').textContent = `${totals.excluded.toLocaleString()} excluded (${totals.total ? (100 * totals.excluded / totals.total).toFixed(1) : '0.0'}%) · ${totals.path_found.toLocaleString()} with a helix traversal · ${totals.unresolved.toLocaleString()} unresolved. Full scaffold routing remains untested.`
    body.querySelector('[data-status]').textContent = `${atlas.entries.length} unique footprints · ${atlas.count.toLocaleString()} footprint × length candidates · one ${scaffold} nt scaffold`
    body.querySelector('[data-slice-status]').textContent = `${model.structureCount} distinct structures at ${model.length} bp · ${model.nodes.length} points including centering aliases · ${model.edges.length} single-parameter links. Filters preserve gaps.`
    const picker = body.querySelector('[data-node]'); picker.replaceChildren()
    for (const lattice of ['square', 'honeycomb']) {
      const group = document.createElement('optgroup'); group.label = lattice === 'square' ? 'Square' : 'Honeycomb'
      for (const node of model.nodes.filter(n => n.lattice === lattice)) {
        const option = document.createElement('option'); option.value = node.id
        option.textContent = `${node.entry.helices}hb × ${node.length} bp · ${node.center} center${node.routing.excluded ? ' · excluded' : ''}`; group.append(option)
      }
      picker.append(group)
    }
    picker.disabled = !model.nodes.length
    const next = model.nodes.find(n => n.id === selectedNode?.id) || model.nodes.find(n => n.entry.helices >= 6 && !n.routing.excluded) || model.nodes[0]
    selectNode(next?.id)
  }
  for (const input of body.querySelectorAll('[data-scaffold], [data-min], [data-reserve], [data-filter], [data-tree-length]')) input.addEventListener('change', rebuild)
  body.querySelector('[data-node]').addEventListener('change', event => selectNode(event.target.value))
  body.querySelector('[data-reset]').addEventListener('click', () => viewer?.reset())
  body.querySelector('[data-export]').addEventListener('click', () => {
    const output = { ...routingExport(atlas), tree: { length: model.length, filter: model.filter, nodes: model.nodes.map(n => ({ id: n.id, footprintId: n.entry.id, center: n.center, length: n.length })), edges: model.edges } }
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
