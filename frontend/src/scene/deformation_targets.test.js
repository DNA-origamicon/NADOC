import { expect, it } from 'vitest'
import { deformationTargets, targetState } from './deformation_targets.js'
const design = { helices: [{ id: 'h', bp_start: 10, length_bp: 50 }],
  strands: [{ id: 's', domains: [{ helix_id: 'h', start_bp: 20, end_bp: 30 }] }],
  cluster_transforms: [{ id: 'c', helix_ids: ['h'], domain_ids: [{ strand_id: 's', domain_index: 0 }] }] }
it('resolves domain clusters narrowly and supports mixed targets', () => {
  const refs = [{ kind: 'cluster', id: 'c' }, { kind: 'strand', id: 's' }]
  const result = deformationTargets(targetState(design, refs))
  expect(result.error).toBeNull()
  expect(result.targets).toEqual(refs)
  expect(result.ranges.every(r => r.lo === 20 && r.hi === 30)).toBe(true)
})
it.each([[], [{ kind: 'domain', strandId: 's', domainIndex: 4 }], [{ kind: 'protein', id: 'p' }]])('rejects empty or invalid selection %j', refs => {
  expect(deformationTargets(targetState(design, refs)).error).toBeTruthy()
})
