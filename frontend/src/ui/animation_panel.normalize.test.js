import { describe, it, expect } from 'vitest'
import { normalizeTrajJobs } from './animation_panel.js'

// Regression: oxDNA AND MD jobs both key their id as `job_id`. A trajectory
// dropdown entry's `id` must be the job_id (reading `j.id` → undefined → the
// dropdown can't select the job → "no trajectory yet").
const PATH = 'workspace/6hb.nadoc'
const ox = [{ job_id: 'ox1', design_source_path: PATH, status: 'completed' }]
const md = [{ job_id: 'md1', design_source_path: PATH, status: 'completed' }]

describe('normalizeTrajJobs', () => {
  it('maps oxDNA job_id → id and tags engine oxdna', () => {
    const out = normalizeTrajJobs(ox, [], PATH)
    expect(out).toHaveLength(1)
    expect(out[0].id).toBe('ox1')        // NOT undefined
    expect(out[0].engine).toBe('oxdna')
  })
  it('maps MD job_id → id and tags engine namd', () => {
    const out = normalizeTrajJobs([], md, PATH)
    expect(out[0].id).toBe('md1')
    expect(out[0].engine).toBe('namd')
  })
  it('combines both engines, oxDNA first', () => {
    const out = normalizeTrajJobs(ox, md, PATH)
    expect(out.map(j => [j.id, j.engine])).toEqual([['ox1', 'oxdna'], ['md1', 'namd']])
  })
  it('filters to the part path (no path → nothing)', () => {
    expect(normalizeTrajJobs(ox, md, null)).toEqual([])
    expect(normalizeTrajJobs(ox, md, 'workspace/other.nadoc')).toEqual([])
  })
  it('tolerates null/non-array inputs', () => {
    expect(normalizeTrajJobs(null, null, PATH)).toEqual([])
  })
})
