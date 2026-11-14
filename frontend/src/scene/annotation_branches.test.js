import { expect, it } from 'vitest'
import { annotationTargetGroups, annotationBranchAnchors, routeAnnotationBranches } from './annotation_branches.js'
import { buildOccupancy } from './annotation_occupancy.js'

it('keeps thirteen strands separate, even when their projections overlap', () => {
  const entries = Array.from({ length: 13 }, (_, i) => ({ nuc: { strand_id: `X${i + 3}` }, pos: { x: 0, y: 0 } }))
  const refs = entries.map(e => ({ kind: 'strand', id: e.nuc.strand_id }))
  const groups = annotationTargetGroups([...refs, refs[0]], {}, entries)
  expect(annotationBranchAnchors(groups, p => p)).toHaveLength(13)
})
it('retains disjoint individual bases and domains and reads their live positions', () => {
  const entries = [0, 20, 40].map((bp, i) => ({ nuc: { strand_id: 's', helix_id: 'h', bp_index: bp, direction: 'FORWARD', domain_index: i }, pos: { x: bp, y: 0 } }))
  const refs = [{ kind: 'base', key: 'h:0:FORWARD' }, { kind: 'domain', strandId: 's', domainIndex: 2 }]
  const groups = annotationTargetGroups(refs, {}, entries)
  expect(groups).toEqual([[entries[0].pos], [entries[2].pos]])
  entries[2].pos.x = 100
  expect(annotationBranchAnchors(groups, p => p)).toEqual([{ x: 0, y: 0 }, { x: 100, y: 0 }])
})
it('splits distant islands, ignores clipped points and anchors on actual members', () => {
  const groups = [[{ x: 0, y: 0 }, { x: 10, y: 0 }, { x: 150, y: 0 }, { x: 160, y: 0 }, null]]
  const anchors = annotationBranchAnchors(groups, p => p)
  expect(anchors).toHaveLength(2)
  expect(groups[0]).toEqual(expect.arrayContaining(anchors))
  expect(annotationBranchAnchors(groups, () => null)).toEqual([])
})
it('routes an elbow around a blocking label while retaining the selected endpoint', () => {
  const rect = { x: 0, y: 80, w: 40, h: 40 }, anchor = { x: 300, y: 100 }
  const routes = routeAnnotationBranches({ anchors: [anchor], type: 'elbow', rect, size: { w: 40, h: 40 },
    obstacles: [{ x: 100, y: 80, w: 80, h: 40 }], occupancy: buildOccupancy([], [], { width: 400, height: 300 }) })
  expect(routes[0].at(-1)).toEqual(anchor)
  expect(routes[0].some(p => p.y < 80 || p.y > 120)).toBe(true)
})
it('has no branch limit and retains straight leaders and rotated edge attachment', () => {
  const anchors = Array.from({ length: 40 }, (_, i) => ({ x: 300, y: i * 20 }))
  const routes = routeAnnotationBranches({ anchors, type: 'straight', rect: { x: 40, y: 40, w: 40, h: 100 }, size: { w: 100, h: 40 }, angle: 90 })
  expect(routes).toHaveLength(40)
  expect(routes.every(r => r.length === 2)).toBe(true)
  expect(routes.map(r => r.at(-1))).toEqual(anchors)
})
it('merges adjacent exact selections but never bridges omitted bases', () => {
  const entries = [0, 1, 2, 3].map(bp => ({ nuc: { strand_id: 's', helix_id: 'h', bp_index: bp, direction: 'FORWARD', domain_index: bp < 2 ? 0 : 1 }, pos: { x: bp, y: 0 } }))
  const refs = [0, 1, 3].map(bp => ({ kind: 'base', key: `h:${bp}:FORWARD` }))
  expect(annotationTargetGroups(refs, {}, entries).map(g => g.length)).toEqual([2, 1])
  expect(annotationTargetGroups([0, 1].map(domainIndex => ({ kind: 'domain', strandId: 's', domainIndex })), {}, entries)).toHaveLength(1)
})
it('keeps assembly instances with the same source strand independent and live', () => {
  const refs = ['a', 'b'].map(instanceId => ({ kind: 'assembly-part', instanceId }))
  const nuc = { strand_id: 'shared', bp_index: 0 }
  const rows = { a: [{ nuc, pos: { x: 1, y: 0 } }], b: [{ nuc, pos: { x: 2, y: 0 } }] }
  const groups = annotationTargetGroups(refs, {}, [], refs => refs.flatMap(r => rows[r.instanceId]))
  rows.b[0].pos.x = 50
  expect(annotationBranchAnchors(groups, p => p)).toEqual([{ x: 1, y: 0 }, { x: 50, y: 0 }])
})
it('does not branch at every base when a continuous domain is magnified', () => {
  const points = Array.from({ length: 12 }, (_, i) => ({ x: i * 70, y: 0 }))
  expect(annotationBranchAnchors([points], p => p)).toHaveLength(1)
  const islands = [...points.slice(0, 6), ...points.slice(6).map(p => ({ x: p.x + 600, y: p.y }))]
  expect(annotationBranchAnchors([islands], p => p)).toHaveLength(2)
})
it('treats an explicitly selected cluster as one target instead of expanding every internal strand', () => {
  const entries = Array.from({ length: 100 }, (_, i) => ({ nuc: { strand_id: `s${i}`, helix_id: 'h', bp_index: i }, pos: { x: i, y: 0 } }))
  const design = { cluster_transforms: [{ id: 'whole', helix_ids: ['h'] }] }
  const groups = annotationTargetGroups([{ kind: 'cluster', id: 'whole' }], design, entries)
  expect(groups).toHaveLength(1)
  expect(annotationBranchAnchors(groups, p => p)).toHaveLength(1)
  expect(annotationTargetGroups(entries.map(e => ({ kind: 'strand', id: e.nuc.strand_id })), design, entries)).toHaveLength(100)
})
