import { createModal } from './primitives/modal.js'
import { el } from './primitives/dom.js'

// Generalized from the native Gerling circular contact map. Coordinates follow
// the stored scaffold route, not sequence matching or a particular scaffold stock.
export function buildCircleGraph(design) {
  if (!design) throw new Error('Open or create a design first.')
  const strands = (design.strands ?? []).filter(s => !s.is_reference)
  const scaffolds = strands.filter(s => s.strand_type === 'scaffold')
  if (!scaffolds.length) throw new Error('The design needs a routed scaffold before a circle graph can be made.')
  if (scaffolds.length !== 1) throw new Error('Circle graphs currently support one scaffold. Multiple-scaffold mapping will be added later.')
  const helices = new Map((design.helices ?? []).map(h => [h.id, h]))
  const scaffold = scaffolds[0]
  const positions = new Map()
  let length = 0
  function sites(domain) {
    const h = helices.get(domain.helix_id)
    if (!h || !Number.isInteger(domain.start_bp) || !Number.isInteger(domain.end_bp)) {
      throw new Error('A strand has missing helix data or invalid domain coordinates.')
    }
    const lo = Math.min(domain.start_bp, domain.end_bp), hi = Math.max(domain.start_bp, domain.end_bp)
    if ((h.loop_skips ?? []).some(ls => ls.bp_index >= lo && ls.bp_index <= hi && ls.delta)) {
      throw new Error('Circle graphs do not yet support routed domains with insertions or deletions.')
    }
    if (hi - lo > 1000000) throw new Error('A domain is too large to display in a circle graph.')
    const step = domain.start_bp <= domain.end_bp ? 1 : -1
    return Array.from({ length: hi - lo + 1 }, (_, i) => JSON.stringify([domain.helix_id, domain.start_bp + i * step]))
  }
  for (const domain of scaffold.domains ?? []) {
    for (const site of sites(domain)) {
      if (positions.has(site)) throw new Error('The scaffold visits the same helix position more than once, so its mapping is ambiguous.')
      positions.set(site, { index: length++, direction: domain.direction, overhang: !!domain.overhang_id })
    }
  }
  if (!length) throw new Error('The scaffold has no routed bases to display.')
  // Junction bases have no helix coordinate; avoid presenting shifted nt indices.
  for (const junction of [...(design.crossovers ?? []), ...(design.forced_ligations ?? []).map(j => ({ extra_bases: j.extra_bases, half_a: { helix_id: j.three_prime_helix_id, index: j.three_prime_bp, strand: j.three_prime_direction } }))]) {
    if (!junction.extra_bases) continue
    for (const half of [junction.half_a, junction.half_b]) {
      const p = half && positions.get(JSON.stringify([half.helix_id, half.index]))
      if (p && p.direction === half.strand) throw new Error('Circle graphs do not yet support extra bases at scaffold junctions.')
    }
  }
  const covered = new Set(), overlaps = new Set()
  let unmapped = 0
  const staples = strands.filter(s => s.strand_type === 'staple').map(staple => {
    const segments = []
    for (const domain of staple.domains ?? []) {
      if (domain.overhang_id) continue
      let run = []
      const flush = () => { if (run.length) segments.push(run); run = [] }
      for (const site of sites(domain)) {
        const p = positions.get(site)
        if (!p || p.overhang || (p.direction != null && domain.direction === p.direction)) {
          flush(); unmapped++; continue
        }
        if (run.length && p.index !== run[run.length - 1] - 1) flush()
        run.push(p.index)
        if (covered.has(p.index)) overlaps.add(p.index)
        covered.add(p.index)
      }
      flush()
    }
    return { name: staple.name || staple.id || 'Staple', segments }
  })
  if (!covered.size) throw new Error('No staple binding intervals could be mapped to the scaffold. Add antiparallel staple domains on the scaffold route.')
  return { length, staples, covered: covered.size, overlaps: [...overlaps], unmapped,
    intervals: staples.reduce((n, s) => n + s.segments.length, 0),
    links: staples.reduce((n, s) => n + Math.max(0, s.segments.length - 1), 0) }
}

function graphSVG(graph) {
  const ns = 'http://www.w3.org/2000/svg'
  function node(tag, attrs, text) {
    const n = document.createElementNS(ns, tag)
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v)
    if (text != null) n.textContent = text
    return n
  }
  const svg = node('svg', { viewBox: '-310 -310 620 620', role: 'img', 'aria-label': 'Scaffold–staple circle graph' })
  svg.style.cssText = 'display:block;width:100%;max-height:65vh;background:white;border-radius:6px'
  const xy = (p, r = 250) => {
    const a = 2 * Math.PI * p / graph.length - Math.PI / 2
    return [r * Math.cos(a), r * Math.sin(a)]
  }
  svg.append(node('circle', { r: 250, fill: 'none', stroke: '#d9dee5', 'stroke-width': 7 }))
  for (const staple of graph.staples) {
    for (let i = 1; i < staple.segments.length; i++) {
      const midpoint = s => (s[0] + s[s.length - 1]) / 2
      const a = xy(midpoint(staple.segments[i - 1]), 244), b = xy(midpoint(staple.segments[i]), 244)
      const path = node('path', { d: `M ${a} C ${a.map(v => v * .3)} ${b.map(v => v * .3)} ${b}`, fill: 'none', stroke: '#315b8a', 'stroke-opacity': .3, 'stroke-width': .8 })
      path.append(node('title', {}, staple.name)); svg.append(path)
    }
  }
  for (const staple of graph.staples) for (const segment of staple.segments) {
    // Half-base edges keep one-base intervals visible.
    const points = [xy(segment[0] + .5), ...segment.map(p => xy(p)), xy(segment.at(-1) - .5)]
    const path = node('polyline', { points: points.join(' '), fill: 'none', stroke: '#247aa0', 'stroke-width': 4 })
    path.append(node('title', {}, `${staple.name}: ${segment[0]}–${segment.at(-1)}`)); svg.append(path)
  }
  for (const p of graph.overlaps) {
    const [cx, cy] = xy(p, 257)
    svg.append(node('circle', { cx, cy, r: 2, fill: '#cb3b51' }))
  }
  const step = Math.max(1, 10 ** Math.floor(Math.log10(graph.length / 6)))
  const tickStep = Math.ceil(graph.length / 8 / step) * step
  for (let p = 0; p < graph.length; p += tickStep) {
    const [x, y] = xy(p, 281)
    svg.append(node('text', { x, y, fill: '#425166', 'font-size': 12, 'text-anchor': 'middle', 'dominant-baseline': 'middle' }, p))
  }
  return svg
}

export function initCircleGraph({ store }) {
  let modal
  function open() {
    modal?.close()
    const body = el('div')
    let title = 'Circle graph'
    try {
      const graph = buildCircleGraph(store.getState().currentDesign)
      body.append(graphSVG(graph), el('p', { text: `${graph.staples.filter(s => s.segments.length).length}/${graph.staples.length} staples shown · ${graph.intervals} intervals · ${graph.links} links · ${graph.covered}/${graph.length} scaffold bases covered` }),
        el('p', { text: 'Scaffold route indices start at 0 and run clockwise from the top. Blue rim: mapped binding; gray: unmapped. Interior lines join successive binding intervals of a staple. The circle is a layout, not the physical shape or proof of scaffold closure.' }))
      if (graph.unmapped || graph.overlaps.length) body.append(el('p', { text: `Partial or conflicting mapping: ${graph.unmapped} staple bases outside paired scaffold positions; ${graph.overlaps.length} overlapping scaffold positions (red). Overhangs are excluded.` }))
    } catch (error) {
      title = 'Cannot make circle graph'
      body.append(el('p', { attrs: { role: 'alert' }, text: error instanceof Error ? error.message : 'The design could not be mapped. Check its scaffold and staple routing.' }))
    }
    modal = createModal({ title, size: title === 'Circle graph' ? 'lg' : 'sm', body, className: 'circle-graph' })
    modal.open()
    return modal
  }
  document.getElementById('menu-view-circle-graph')?.addEventListener('click', open)
  return { open }
}
