// @vitest-environment jsdom
import { expect, it, vi } from 'vitest'
import { scaffoldScope, selectedSequenceTarget, confirmScaffoldScope, confirmedScaffoldOptions } from './scaffold_sequence_target.js'
import { showConfirm } from './primitives/confirm.js'
vi.mock('./primitives/confirm.js', () => ({ showConfirm: vi.fn() }))
const strand = (id, helix) => ({ id, strand_type: 'scaffold', domains: [{ helix_id: helix, start_bp: 0, end_bp: 41 }] })
const design = { strands: [strand('s1', 'h1'), strand('s2', 'h2'), strand('s3', 'h3')],
  cluster_transforms: [{ id: 'c', helix_ids: ['h1', 'h2'] }] }
it('uses explicit context-menu target, selected scaffold, selected cluster, then default', () => {
  const state = { currentDesign: design, selection: { items: [{ kind: 'cluster', id: 'c' }] } }
  expect(selectedSequenceTarget(state)).toBe('cluster:c')
  expect(selectedSequenceTarget(state, 's3')).toBe('strand:s3')
  expect(selectedSequenceTarget({ ...state, selection: { items: [{ kind: 'strand', id: 's2' }] } })).toBe('strand:s2')
  expect(selectedSequenceTarget({ currentDesign: design })).toBe('default')
})
it('resolves default, strand and independent cluster scaffolds without touching other clusters', () => {
  expect(scaffoldScope(design, 'default').strands.map(s => s.id)).toEqual(['s1'])
  expect(scaffoldScope(design, 'strand:s3').options).toEqual({ strandId: 's3' })
  expect(scaffoldScope(design, 'cluster:c').strands.map(s => s.id)).toEqual(['s1', 's2'])
})
it('rejects a scaffold that leaves the cluster, including partial-domain membership', () => {
  const crossing = { ...design, strands: [{ ...strand('s1', 'h1'), domains: [...strand('s1', 'h1').domains, ...strand('s3', 'h3').domains] }] }
  expect(() => scaffoldScope(crossing, 'cluster:c')).toThrow('crosses')
  const partial = { ...design, strands: [...design.strands, { id: 'marker', domains: [{ helix_id: 'h1', start_bp: 0, end_bp: 20 }] }],
    cluster_transforms: [{ id: 'c', helix_ids: ['h1'], domain_ids: [{ strand_id: 'marker', domain_index: 0 }] }] }
  expect(() => scaffoldScope(partial, 'cluster:c')).toThrow('crosses')
})
it('requires Yes for multiple scaffolds and does not prompt for one', async () => {
  showConfirm.mockResolvedValue(false)
  expect(await confirmScaffoldScope(scaffoldScope(design, 'cluster:c'))).toBe(false)
  expect(showConfirm).toHaveBeenCalledWith(expect.objectContaining({ message: 'Multiple scaffolds detected, assign sequence to all?', confirmLabel: 'Yes', cancelLabel: 'No' }))
  showConfirm.mockResolvedValue(true)
  expect(await confirmScaffoldScope(scaffoldScope(design, 'cluster:c'))).toBe(true)
  showConfirm.mockClear()
  expect(await confirmScaffoldScope(scaffoldScope(design, 'default'))).toBe(true)
  expect(showConfirm).not.toHaveBeenCalled()
})

it('returns confirmed options and surfaces invalid scopes without applying', async () => {
  const toast = vi.fn()
  expect(await confirmedScaffoldOptions({ read: () => scaffoldScope(design, 'default') }, toast)).toEqual({ strandId: null })
  expect(await confirmedScaffoldOptions({ read: () => { throw new Error('stale target') } }, toast)).toBeNull()
  expect(toast).toHaveBeenCalledWith('stale target', { severity: 'error' })
})
