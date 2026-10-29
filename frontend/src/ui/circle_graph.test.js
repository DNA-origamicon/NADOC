import { afterEach, expect, it } from 'vitest'
import { buildCircleGraph, initCircleGraph } from './circle_graph.js'
const domain = (h, a, b) => ({ helix_id: h, start_bp: a, end_bp: b, direction: a <= b ? 'forward' : 'reverse' })
const design = () => ({ helices: [{ id: 'a' }, { id: 'b' }], strands: [
  { id: 'sc', strand_type: 'scaffold', domains: [domain('a', 0, 3), domain('b', 0, 3)] },
  { id: 'st', strand_type: 'staple', domains: [domain('a', 3, 2), domain('b', 3, 2)] },
] })
afterEach(() => { document.body.replaceChildren(); window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })) })
it('maps topology without requiring a sequence and preserves staple order', () => {
  const d = design(), before = JSON.stringify(d), g = buildCircleGraph(d)
  expect(g).toMatchObject({ length: 8, covered: 4, intervals: 2, links: 1, unmapped: 0 })
  expect(g.staples[0].segments).toEqual([[3, 2], [7, 6]])
  expect(JSON.stringify(d)).toBe(before)
})
it('reports missing, multiple, ambiguous and unsupported scaffold routes', () => {
  expect(() => buildCircleGraph(null)).toThrow('Open or create')
  expect(() => buildCircleGraph({})).toThrow('routed scaffold')
  const d = design(); d.strands.push({ ...d.strands[0] })
  expect(() => buildCircleGraph(d)).toThrow('Multiple-scaffold')
  d.strands.pop(); d.strands[0].domains.push(domain('a', 0, 3))
  expect(() => buildCircleGraph(d)).toThrow('ambiguous')
  d.strands[0].domains.pop(); d.helices[0].loop_skips = [{ bp_index: 1, delta: 1 }]
  expect(() => buildCircleGraph(d)).toThrow('insertions or deletions')
})
it('excludes reference strands and overhangs, reports unmapped bases and overlaps', () => {
  const d = design(); d.strands.push({ ...d.strands[0], is_reference: true })
  d.strands[1].domains.push({ ...domain('a', 1, 0), overhang_id: 'oh' }, domain('b', 6, 5))
  d.strands.push({ ...d.strands[1], id: 'duplicate' })
  expect(buildCircleGraph(d)).toMatchObject({ covered: 4, unmapped: 4, overlaps: [3, 2, 7, 6] })
})
it('regenerates from current design and opens explanatory errors through the menu', () => {
  document.body.innerHTML = '<button id="menu-view-circle-graph">Circle graph</button>'
  let currentDesign = design()
  const ui = initCircleGraph({ store: { getState: () => ({ currentDesign }) } })
  document.querySelector('button').click()
  expect(document.querySelector('svg[role="img"]')).not.toBeNull()
  expect(document.querySelector('.circle-graph').textContent).toContain('4/8 scaffold bases')
  currentDesign = null
  const modal = ui.open()
  expect(document.querySelectorAll('.circle-graph')).toHaveLength(1)
  expect(document.querySelector('[role="alert"]').textContent).toContain('Open or create')
  modal.close()
  expect(document.querySelector('.circle-graph')).toBeNull()
})
it('explains empty binding and scaffold junction bases instead of drawing misleading indices', () => {
  const d = design(); d.strands.pop()
  expect(() => buildCircleGraph(d)).toThrow('No staple binding')
  d.forced_ligations = [{ three_prime_helix_id: 'a', three_prime_bp: 3, three_prime_direction: 'forward', extra_bases: 'TT' }]
  expect(() => buildCircleGraph(d)).toThrow('extra bases at scaffold junctions')
})
