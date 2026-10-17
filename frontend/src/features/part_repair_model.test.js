import { describe, expect, it } from 'vitest'
import { cloneRepairInput, repairActions, repairGuards,
  repairIssues, repairJobView, repairPublishedStatus, resolveRepairFeature } from './part_repair_model.js'

const context = { docId: 'doc', designId: 'part', loadoutId: 'main', revision: 4,
  editable: true, cursor: -1, subCursor: null }
const draft = { draft_id: 'proposal', generation: 2 }

describe('input-only repair model', () => {
  it('resolves exact routing-child identities and proposal generation guards', () => {
    const design = { feature_log: [{ id: 'group', feature_type: 'routing-cluster', children: [
      { id: 'child', params: { inputs: ['missing', 'retained'] } },
    ] }] }
    expect(resolveRepairFeature(design, 'child')).toEqual({ featureId: 'group', childId: 'child',
      index: 0, subIndex: 0, entry: design.feature_log[0].children[0] })
    expect(repairGuards(context, draft)).toEqual({ draft_version: 1, expected_design_id: 'part',
      expected_revision: 4, expected_draft_id: 'proposal', expected_generation: 2 })
  })

  it('refuses ambiguous or absent feature identities', () => {
    expect(() => resolveRepairFeature({ feature_log: [{ id: 'same' }, { id: 'same' }] }, 'same')).toThrow(/ambiguous/)
    expect(() => resolveRepairFeature({ feature_log: [] }, 'gone')).toThrow(/no longer/)
  })

  it('bounds and clones proposed JSON before storage or requests', () => {
    const value = [{ action: 'set_input', value: { ids: ['a'] } }]
    const copied = repairActions(value)
    copied[0].value.ids.push('b')
    expect(value[0].value.ids).toEqual(['a'])
    expect(() => repairActions(Array(65).fill({}))).toThrow(/64/)
    expect(() => cloneRepairInput(Array(10001).fill(null))).toThrow(/complex/)
    expect(() => cloneRepairInput('x'.repeat(64000))).toThrow(/size/)
    expect(() => cloneRepairInput({ invalid: Infinity })).toThrow(/finite/)
    expect(() => cloneRepairInput(new Map())).toThrow(/JSON/)
  })

  it('keeps structured feature/path diagnostics including integer tokens', () => {
    const issue = { code: 'missing_reference', feature_id: 'group', child_id: 'child',
      references: [{ kind: 'protein', identity: 'missing', parameter_path: ['ids', 0] }] }
    expect(repairIssues({ detail: issue })).toEqual([{ ...issue, parameter_path: ['ids', 0] }])
  })

  it('never derives readiness from saved proposal fields or nonpublishing jobs', () => {
    expect(repairJobView(null, context, { ...draft, status: 'ready' }).ready).toBe(false)
    const job = { context, operation: 'selection', response: { status: 'complete', result: { status: 'ready' } },
      draftId: draft.draft_id, generation: draft.generation }
    expect(repairJobView(job, context, draft).ready).toBe(false)
    expect(repairJobView({ ...job, operation: 'verify' }, context, draft).ready).toBe(false)
  })

  it('requires exact context, draft generation and available source for Apply', () => {
    const job = { context, operation: 'repair', draftId: 'proposal', generation: 2,
      response: { status: 'complete', result: { status: 'ready' } } }
    expect(repairJobView(job, context, draft).ready).toBe(true)
    for (const change of [{ revision: 5 }, { loadoutId: 'other' }, { docId: 'other' }]) {
      expect(repairJobView(job, { ...context, ...change }, draft).ready).toBe(false)
    }
    expect(repairJobView(job, context, { ...draft, generation: 3 }).ready).toBe(false)
    expect(repairJobView({ ...job, response: { ...job.response, source_busy: true } }, context, draft).ready).toBe(false)
    expect(repairJobView({ ...job, response: { ...job.response, stale: true } }, context, draft).ready).toBe(false)
  })

  it('labels only explicit current verification as published proof', () => {
    const job = { context, operation: 'verify', response: { status: 'complete', result: { status: 'reproduced_import' } } }
    expect(repairPublishedStatus(null, context)).toBe('unchecked')
    expect(repairPublishedStatus(job, context)).toBe('reproduced_import')
    expect(repairPublishedStatus(job, { ...context, revision: 5 })).toBe('unchecked')
    expect(repairPublishedStatus({ ...job, operation: 'repair' }, context)).toBe('unchecked')
  })
})
