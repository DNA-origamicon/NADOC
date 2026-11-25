import { describe, it, expect } from 'vitest'
import { mergeMdSelectionSnapshot } from './md_selection_snapshot.js'

describe('NAMD selection metadata', () => {
  const parent = { engine: 'namd', job_id: 'parent', prep_params: { padding_nm: 6 } }
  const child = { engine: 'namd', job_id: 'child', parent_job_id: 'parent' }
  it('carries parent settings alongside the selected production child', () => {
    expect(mergeMdSelectionSnapshot([], 'child', [parent, child])).toEqual([parent, child])
  })
  it('preserves refreshed panel records and excludes other engines and duplicates', () => {
    const current = { ...parent, status: 'completed' }
    expect(mergeMdSelectionSnapshot([current], 'child', [parent, child, child, { engine: 'oxdna', job_id: 'other' }]))
      .toEqual([current, child])
  })
  it('does not seed records from a snapshot missing the requested NAMD job', () => {
    const jobs = []
    expect(mergeMdSelectionSnapshot(jobs, 'missing', [parent])).toBe(jobs)
    expect(mergeMdSelectionSnapshot(jobs, 'other', [{ engine: 'oxdna', job_id: 'other' }])).toBe(jobs)
  })
})
