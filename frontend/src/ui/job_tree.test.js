import { describe, it, expect } from 'vitest'
import { flattenJobTree, descendantIds } from './job_tree.js'

describe('job_tree.flattenJobTree', () => {
  it('nests children under their parent, numbered by run order, roots newest first', () => {
    const jobs = [
      { job_id: 'P', created_at: 100 },
      { job_id: 'F2', parent_job_id: 'P', created_at: 220 },
      { job_id: 'F1', parent_job_id: 'P', created_at: 210 },
      { job_id: 'Q', created_at: 50 },
    ]
    const rows = flattenJobTree(jobs)
    expect(rows.map(r => r.job.job_id)).toEqual(['P', 'F1', 'F2', 'Q'])
    expect(rows.map(r => r.depth)).toEqual([0, 1, 1, 0])
    expect(rows.map(r => r.index)).toEqual([0, 1, 2, 0])
  })
  it('floats a parent to the top by its newest child, above a newer childless root', () => {
    // P is OLD but has a brand-new production child C; N is a childless root created
    // after P but before C. Chronological-float: P's subtree (max=500) must outrank N
    // (300), so the newest job C is NOT buried below N.
    const jobs = [
      { job_id: 'N', created_at: 300 },
      { job_id: 'P', created_at: 100 },
      { job_id: 'C', parent_job_id: 'P', created_at: 500 },
    ]
    const rows = flattenJobTree(jobs)
    expect(rows.map(r => r.job.job_id)).toEqual(['P', 'C', 'N'])
    expect(rows.map(r => r.depth)).toEqual([0, 1, 0])
  })
  it('pre-order flattens a chained lineage with increasing depth', () => {
    const jobs = [
      { job_id: 'R', created_at: 100 },
      { job_id: 'A', parent_job_id: 'R', created_at: 110 },
      { job_id: 'B', parent_job_id: 'A', created_at: 120 },
    ]
    const rows = flattenJobTree(jobs)
    expect(rows.map(r => r.job.job_id)).toEqual(['R', 'A', 'B'])
    expect(rows.map(r => r.depth)).toEqual([0, 1, 2])
  })
  it('an orphan child (parent absent) is treated as its own root', () => {
    const rows = flattenJobTree([{ job_id: 'F', parent_job_id: 'gone', created_at: 1 }])
    expect(rows.map(r => r.job.job_id)).toEqual(['F'])
    expect(rows[0].depth).toBe(0)
  })
  it('handles empty/undefined input', () => {
    expect(flattenJobTree()).toEqual([])
    expect(flattenJobTree([])).toEqual([])
  })
  it('reports childCount per node (drives the expand chevron)', () => {
    const jobs = [
      { job_id: 'P', created_at: 100 },
      { job_id: 'R1', parent_job_id: 'P', created_at: 210 },
      { job_id: 'R2', parent_job_id: 'P', created_at: 220 },
    ]
    const rows = flattenJobTree(jobs)
    const byId = Object.fromEntries(rows.map(r => [r.job.job_id, r.childCount]))
    expect(byId).toEqual({ P: 2, R1: 0, R2: 0 })
  })
  it('collapsedIds hides a subtree but keeps the parent row + its childCount', () => {
    const jobs = [
      { job_id: 'P', created_at: 100 },
      { job_id: 'R1', parent_job_id: 'P', created_at: 210 },
      { job_id: 'R2', parent_job_id: 'P', created_at: 220 },
      { job_id: 'Q', created_at: 50 },
    ]
    const rows = flattenJobTree(jobs, { collapsedIds: new Set(['P']) })
    expect(rows.map(r => r.job.job_id)).toEqual(['P', 'Q'])
    expect(rows.find(r => r.job.job_id === 'P').childCount).toBe(2)
  })
})

describe('job_tree.descendantIds', () => {
  it('collects the full subtree (children + grandchildren)', () => {
    const jobs = [
      { job_id: 'R' },
      { job_id: 'A', parent_job_id: 'R' },
      { job_id: 'B', parent_job_id: 'A' },
      { job_id: 'C', parent_job_id: 'R' },
      { job_id: 'X' },
    ]
    expect([...descendantIds(jobs, 'R')].sort()).toEqual(['A', 'B', 'C'])
    expect([...descendantIds(jobs, 'A')]).toEqual(['B'])
    expect([...descendantIds(jobs, 'X')]).toEqual([])
  })
})
