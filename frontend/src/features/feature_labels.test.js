import { expect, it } from 'vitest'
import { featureLabels } from './feature_labels.js'

it('numbers tools independently of history positions and keeps user elaboration', () => {
  expect(featureLabels([
    { feature_type: 'snapshot', op_kind: 'bundle-create', label: 'Two helices' },
    { feature_type: 'snapshot', op_kind: 'nucleotide-transform', label: 'Move selected base' },
    { feature_type: 'snapshot', op_kind: 'extrude-continuation', label: 'Extend 8 bp', suppressed: true },
    { feature_type: 'snapshot', op_kind: 'nucleotide-transform-delete', label: 'Reset base pose' },
  ])).toEqual(['F1: Extrude 1 [Two helices]', 'F2: Move/Rotate 1 [Move selected base]',
    'F3: Extrude 2 [Extend 8 bp]', 'F4: Move/Rotate 2 [Reset base pose]'])
})
it('covers delta, grouped routing, and assembly entries without leaking recipe identifiers', () => {
  expect(featureLabels([
    { feature_type: 'deformation', op_snapshot: { type: 'bend' } },
    { feature_type: 'cluster_op' },
    { feature_type: 'snapshot', op_kind: 'assembly-transform-instance' },
    { feature_type: 'snapshot', op_kind: 'future-internal-kind', label: 'Useful explanation' },
  ])).toEqual(['F1: Bend 1', 'F2: Move/Rotate 1', 'F3: Move/Rotate 2', 'F4: Feature 1 [Useful explanation]'])
  expect(featureLabels([{ feature_type: 'minor', op_subtype: 'nick', label: 'nick' }], 'F2-'))
    .toEqual(['F2-1: Nick 1'])
})
it('recomputes numbering after reorder without changing stored elaboration', () => {
  const log = [{ op_kind: 'bundle-create', label: 'Initial' }, { op_kind: 'extrude-segment', label: 'Other' }]
  expect(featureLabels(log.toReversed())).toEqual(['F1: Extrude 1 [Other]', 'F2: Extrude 2 [Initial]'])
  expect(log[0].label).toBe('Initial')
})
