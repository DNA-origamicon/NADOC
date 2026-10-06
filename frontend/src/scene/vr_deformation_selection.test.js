import { it, expect } from 'vitest'
import { vrDeformationSelection, resolveVRDeformationSelection } from './vr_deformation_selection.js'
import { buildVRParameterizedToolPlan } from './vr_tool_execution_plan.js'
const refs = [{ kind: 'cluster', id: 'c' }, { kind: 'strand', id: 's' }, { kind: 'domain', strandId: 's', domainIndex: 0 }]
const design = { helices: [{ id: 'h', length_bp: 101 }],
  cluster_transforms: [{ id: 'c', helix_ids: ['h'], domain_ids: [{ strand_id: 's', domain_index: 0 }] }],
  strands: [{ id: 's', domains: [{ helix_id: 'h', start_bp: 30, end_bp: 70, direction: 'FORWARD' }] }] }
it('binds the whole mixed selection and invalidates a changed non-primary member', () => {
  const target = vrDeformationSelection(refs)
  expect(resolveVRDeformationSelection(target, structuredClone(refs)).selectedRefs).toEqual(refs)
  expect(resolveVRDeformationSelection(target, refs.slice(1))).toBeNull()
  expect(resolveVRDeformationSelection(target, refs)).toBeNull()
  expect(vrDeformationSelection([refs[0], { kind: 'base', key: 'h:0:FORWARD' }])).toBeNull()
})
for (const mode of ['bend', 'twist']) it(`${mode} preflight and commit retain exact mixed targets`, () => {
  const target = vrDeformationSelection(refs)
  const draft = { mode, target_kind: target.selectionKind, target_identity: target.identity, target_owner_tokens: target.ownerTokens,
    plane_a_bp: 30, plane_b_bp: 70, angle_deg: 60, direction_deg: 0, amount_mode: 'total_degrees', amount: -60 }
  const result = buildVRParameterizedToolPlan(draft, { toolTarget: target, design })
  expect(result.accepted).toBe(true)
  expect(result.plan.targets).toEqual(refs)
  expect(result.plan.preflight.arguments).toMatchObject({ targets: refs, helixIds: ['h'], clusterIds: [] })
  expect(buildVRParameterizedToolPlan(draft, { toolTarget: target, design: { ...design, strands: [] } }).accepted).toBe(false)
})

it('resolves native domain and strand picks even when the desktop has no bead meshes', async () => {
  const { vrDeformationRefForOwner } = await import('./vr_deformation_selection.js')
  const n = { strand_id: 's', domain_index: 0, helix_id: 'h' }
  const owner = { kind: 'nucleotide', nucleotide: n }
  expect(vrDeformationRefForOwner(owner, 'strand', design, [n])).toEqual({ kind: 'strand', id: 's' })
  expect(vrDeformationRefForOwner(owner, 'domain', design, [n])).toEqual({ kind: 'domain', strandId: 's', domainIndex: 0 })
  expect(vrDeformationRefForOwner({ kind: 'domain', ref: { strandId: 's', domainIndex: 0 } }, 'cluster', design, [n])).toEqual({ kind: 'cluster', id: 'c' })
  expect(vrDeformationRefForOwner(owner, 'base', design, [n])).toBeNull()
})
