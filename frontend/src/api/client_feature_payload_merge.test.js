import { describe, expect, it } from 'vitest'
import { _mergeFeatureLogPayloads } from './client.js'

describe('slim mutation history merge', () => {
  it('restores old bodies while leaving the new entry payload intact', () => {
    const previous = { feature_log: [
      { id: 'old', design_snapshot_gz_b64: 'old-pre', post_state_gz_b64: 'old-post' },
    ] }
    const incoming = { feature_log: [
      { id: 'old', design_snapshot_gz_b64: '', post_state_gz_b64: '' },
      { id: 'new', design_snapshot_gz_b64: 'new-pre', post_state_gz_b64: 'new-post' },
    ] }

    expect(_mergeFeatureLogPayloads(incoming, previous).feature_log).toEqual([
      { id: 'old', design_snapshot_gz_b64: 'old-pre', post_state_gz_b64: 'old-post' },
      { id: 'new', design_snapshot_gz_b64: 'new-pre', post_state_gz_b64: 'new-post' },
    ])
  })
})
