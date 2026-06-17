import { describe, it, expect } from 'vitest'
import { jobCount, jobCleanupSummary, runningJobIds } from './file_deletion.js'

describe('jobCount', () => {
  it('sums md + oxdna', () => {
    expect(jobCount({ md: [1, 2], oxdna: [3] })).toBe(3)
  })
  it('handles empty / missing', () => {
    expect(jobCount({})).toBe(0)
    expect(jobCount({ md: [], oxdna: [] })).toBe(0)
    expect(jobCount(null)).toBe(0)
  })
})

describe('jobCleanupSummary', () => {
  it('returns empty string when no jobs', () => {
    expect(jobCleanupSummary({ md: [], oxdna: [] })).toBe('')
  })
  it('singular MD only', () => {
    expect(jobCleanupSummary({ md: [{}], oxdna: [] })).toBe('1 MD job folder')
  })
  it('plural oxDNA only', () => {
    expect(jobCleanupSummary({ md: [], oxdna: [{}, {}] })).toBe('2 oxDNA job folders')
  })
  it('joins both with "and"', () => {
    expect(jobCleanupSummary({ md: [{}], oxdna: [{}, {}] }))
      .toBe('1 MD job folder and 2 oxDNA job folders')
  })
})

describe('runningJobIds', () => {
  it('collects ids of running jobs across both lists', () => {
    const jobs = {
      md: [{ job_id: 'a', running: true }, { job_id: 'b', running: false }],
      oxdna: [{ job_id: 'c', running: true }],
    }
    expect(runningJobIds(jobs)).toEqual(['a', 'c'])
  })
  it('returns empty when none running', () => {
    expect(runningJobIds({ md: [{ job_id: 'a', running: false }], oxdna: [] })).toEqual([])
  })
  it('handles missing lists', () => {
    expect(runningJobIds({})).toEqual([])
  })
})
