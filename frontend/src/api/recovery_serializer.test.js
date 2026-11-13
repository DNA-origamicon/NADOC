import { it, expect } from 'vitest'
import { createRecoverySerializer } from './recovery_serializer.js'
it('preserves full recovery across fresh objects, same-ID body clearing, and child/metadata changes', () => {
  const serialize = createRecoverySerializer()
  expect(JSON.parse(serialize({ feature_log: [] }))).toEqual({ feature_log: [] })
  const original = { id: 'part', feature_log: [{ id: 'e', label: 'quotes " and \\ and 🌱',
    post_state_gz_b64: 'full-body', children: [{ id: 'c', diff_added_b64: 'bases' }] }] }
  for (const change of [d => d, d => { d.feature_log[0].post_state_gz_b64 = ''; return d },
    d => { d.feature_log[0].children[0].diff_added_b64 = 'different'; return d },
    d => { d.feature_log[0].label = 'changed'; return d }, d => { d.feature_log = []; return d }]) {
    const design = change(structuredClone(original))
    expect(JSON.parse(serialize(design))).toEqual(design)
    expect(JSON.parse(serialize(structuredClone(design)))).toEqual(design)
  }
})

it('distinguishes equal bodies moved to different fields on the same entry', () => {
  const serialize = createRecoverySerializer()
  serialize({ feature_log: [{ id: 'e', pre_state_gz_b64: 'same' }] })
  const changed = { feature_log: [{ id: 'e', post_state_gz_b64: 'same' }] }
  expect(JSON.parse(serialize(changed))).toEqual(changed)
})
