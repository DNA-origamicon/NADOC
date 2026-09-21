import { attachmentDirections, contextAtoms, elementStatus, projectAtoms, STATUS } from './cpd_progress_model.js'

export const ENDPOINT_COLORS = { 1: '#69c9ff', 2: '#d0a2ff' }
export const svgElement = (name, attrs = {}) => {
  const node = document.createElementNS('http://www.w3.org/2000/svg', name)
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v)
  return node
}

// Orthographic 3D projection shared by the eight comparison thumbnails and the
// interactive inspector. Context is never interpreted as validation evidence.
export function drawStructure(svg, model, { yaw = -.35, pitch = .6, zoom = 1, radius, context = true, torsions = [0, 0], overall = true, interactive, miniature = false } = {}) {
  const isomer = Boolean(model.stereochemistry)
  const moved = isomer ? contextAtoms(model, torsions) : model.atoms
  const atoms = moved.filter(a => !isomer || (a.element !== 'H' && (context || a.region === 'base')))
  const directions = isomer && context ? attachmentDirections(moved) : []
  const points = projectAtoms([...atoms, ...directions], yaw, pitch, zoom, isomer ? { center: [0, 0, 0], radius } : {})
  const map = new Map(points.map(a => [a.id, a]))
  svg.replaceChildren()
  const label = (a, text, color, size = 13) => {
    const node = svgElement('text', { x: a.x + 10, y: a.y - 8, fill: color, 'font-size': size, 'pointer-events': 'none', 'paint-order': 'stroke', stroke: '#101722', 'stroke-width': 3 })
    node.textContent = text; svg.append(node)
  }
  if (isomer && context) for (const endpoint of [1, 2]) {
    const ring = ["C1'", "C2'", "C3'", "C4'", "O4'"].map(n => map.get(`${endpoint}:${n}`))
    svg.append(svgElement('polygon', { points: ring.map(p => `${p.x},${p.y}`).join(' '), fill: ENDPOINT_COLORS[endpoint], 'fill-opacity': .14, 'data-sugar': endpoint }))
  }
  for (const d of directions) {
    const start = map.get(d.anchor), end = map.get(d.id), color = ENDPOINT_COLORS[d.endpoint]
    svg.append(svgElement('line', { x1: start.x, y1: start.y, x2: end.x, y2: end.y, stroke: color, 'stroke-width': 3, 'stroke-dasharray': '6 4', 'data-direction': d.id }))
    const angle = Math.atan2(end.y - start.y, end.x - start.x)
    const tips = [end, ...[-.5, .5].map(a => ({ x: end.x - 12 * Math.cos(angle + a), y: end.y - 12 * Math.sin(angle + a) }))]
    svg.append(svgElement('polygon', { points: tips.map(p => `${p.x},${p.y}`).join(' '), fill: color }))
    label(end, d.label, color, miniature ? 20 : 16)
  }
  for (const b of model.bonds) {
    const [a, c] = b.atoms.map(id => map.get(id)); if (!a || !c) continue
    const color = isomer ? (b.crosslink ? '#fff0b5' : ENDPOINT_COLORS[a.endpoint]) : STATUS[elementStatus(b.checks, overall)].color
    const line = svgElement('line', { x1: a.x, y1: a.y, x2: c.x, y2: c.y, stroke: color, 'stroke-width': b.crosslink ? 7 : 4, 'stroke-linecap': 'round', ...(miniature ? {} : { 'data-bond': b.id }), ...(b.crosslink ? { 'data-crosslink': '' } : {}) })
    interactive?.(line, b, 'Bond'); svg.append(line)
  }
  for (const a of points.filter(a => a.element).sort((a, b) => a.z - b.z)) {
    const color = isomer ? ENDPOINT_COLORS[a.endpoint] : STATUS[elementStatus(a.checks, overall)].color
    const circle = svgElement('circle', { cx: a.x, cy: a.y, r: a.element === 'H' ? 4 : 7, fill: color, stroke: '#101722', 'stroke-width': 1.5, ...(miniature ? {} : { 'data-atom': a.id }) })
    interactive?.(circle, a, 'Atom'); svg.append(circle)
    if (isomer && a.id.endsWith(":O5'")) svg.append(svgElement('circle', { cx: a.x, cy: a.y, r: 12, fill: 'none', stroke: color, 'stroke-width': 2, 'data-backbone-bead': a.endpoint, 'pointer-events': 'none' }))
    const named = context ? /:(C1'|O5')$/.test(a.id) : /:(C5|C6|N1)$/.test(a.id)
    if (!miniature && a.element !== 'H' && (!isomer || named)) label(a, a.id, '#dce6f4', 12)
  }
  return moved
}
