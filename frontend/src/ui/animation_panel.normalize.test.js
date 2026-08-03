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

// The dropdown must read like a Simulations-tab row: relaxations as "relax N",
// their derived runs as "Run N [tags]", each child directly under its parent.
// Before this, every entry ran through jobDisplayName → one relaxation and all of
// its production runs rendered as the SAME design stem.
describe('normalizeTrajJobs — Simulations-tab naming + tree order', () => {
  const ox = (id, created_at, over = {}) =>
    ({ job_id: id, design_source_path: PATH, status: 'completed', created_at, stages: [], ...over })

  it('names an oxDNA root "relax N" (creation order) and a child "Run N"', () => {
    const out = normalizeTrajJobs([
      ox('r1', 10),
      ox('c1', 20, { parent_job_id: 'r1', run_config: { field: true, anchors: ['a'] } }),
    ], [], PATH)
    expect(out.map(j => j.label)).toEqual(['relax 1', 'Run 1 [A][E]'])
  })

  it('puts each child directly under its own parent, roots newest-first', () => {
    const out = normalizeTrajJobs([
      ox('r1', 10), ox('c1', 15, { parent_job_id: 'r1' }),
      ox('r2', 20), ox('c2', 25, { parent_job_id: 'r2' }),
    ], [], PATH)
    expect(out.map(j => j.id)).toEqual(['r2', 'c2', 'r1', 'c1'])
    expect(out.map(j => j.label)).toEqual(['relax 2', 'Run 2', 'relax 1', 'Run 1'])
  })

  it('marks depth so the option can flag a derived run, and numbers roots only', () => {
    const out = normalizeTrajJobs([ox('r1', 10), ox('c1', 20, { parent_job_id: 'r1' })], [], PATH)
    expect(out.map(j => [j.depth, j.listIndex])).toEqual([[0, 1], [1, 0]])
  })

  it('labels NAMD entries with the NAMD tab’s own names', () => {
    const out = normalizeTrajJobs([], [
      { job_id: 'm1', design_source_path: PATH, design_name: 'plate', created_at: 10 },
      { job_id: 'm2', design_source_path: PATH, created_at: 20, parent_job_id: 'm1',
        run_kind: 'production', ensemble_seed: 77 },
    ], PATH)
    expect(out.map(j => j.label)).toEqual(['plate', 'Production 1 · seed 77'])
  })
})
