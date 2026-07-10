import { describe, it, expect } from 'vitest'
import {
  newStage, newPlan, addStage, duplicateStage, removeStage, reorderStage,
  setStage, setRoot, buildChainPayload, isQueueable, chainStatusSummary,
  activeIndexAfterRemove, activeIndexAfterReorder,
} from './stage_planner_model.js'

describe('stage_planner_model — pure list ops', () => {
  it('newStage mirrors the backend ChainStageRequest field set with defaults', () => {
    const s = newStage()
    expect(Object.keys(s).sort()).toEqual(
      ['anchors', 'cluster_name', 'engine', 'field', 'label', 'length_ns',
        'protocol', 'run_target', 'steps', 'surface'].sort(),
    )
    expect(s.protocol).toBe('production')
    expect(s.run_target).toBe('local')
    expect(s.field).toBeNull()
  })

  it('addStage appends without mutating the source model', () => {
    const m0 = newPlan()
    const m1 = addStage(m0, { engine: 'oxdna', label: 'relax' })
    expect(m0.stages).toHaveLength(0) // immutable
    expect(m1.stages).toHaveLength(1)
    expect(m1.stages[0].engine).toBe('oxdna')
    expect(m1.stages[0].label).toBe('relax')
  })

  it('duplicateStage inserts a DEEP copy right after the source (field sweep seed)', () => {
    let m = newPlan()
    m = addStage(m, { engine: 'namd', field: { field_pN: 5, dir: [1, 0, 0] } })
    m = duplicateStage(m, 0)
    expect(m.stages).toHaveLength(2)
    // rotate the copy's field dir — proves the copy is independent of the source
    m = setStage(m, 1, { field: { field_pN: 5, dir: [0, 1, 0] } })
    expect(m.stages[0].field.dir).toEqual([1, 0, 0])
    expect(m.stages[1].field.dir).toEqual([0, 1, 0])
    // mutating the returned copy's field array must not touch the original
    m.stages[1].field.dir[0] = 99
    expect(m.stages[0].field.dir[0]).toBe(1)
  })

  it('removeStage and reorderStage move the right stage', () => {
    let m = newPlan()
    m = addStage(m, { label: 'a' })
    m = addStage(m, { label: 'b' })
    m = addStage(m, { label: 'c' })
    const removed = removeStage(m, 1)
    expect(removed.stages.map((s) => s.label)).toEqual(['a', 'c'])
    const moved = reorderStage(m, 2, 0)
    expect(moved.stages.map((s) => s.label)).toEqual(['c', 'a', 'b'])
    // clamps out-of-range target
    const clamped = reorderStage(m, 0, 99)
    expect(clamped.stages.map((s) => s.label)).toEqual(['b', 'c', 'a'])
  })

  it('out-of-range ops are no-ops', () => {
    const m = addStage(newPlan(), {})
    expect(removeStage(m, 5).stages).toHaveLength(1)
    expect(duplicateStage(m, -1).stages).toHaveLength(1)
    expect(setStage(m, 9, { engine: 'x' }).stages[0].engine).toBe('namd')
  })
})

describe('stage_planner_model — payload build (== valid MdPipeline)', () => {
  it('buildChainPayload emits the canonical CreateChainRequest shape', () => {
    let m = newPlan()
    m = setRoot(m, 'root-job-42', 'oxdna')
    m = addStage(m, {
      engine: 'namd', protocol: 'production',
      field: { field_pN: 8, dir: [0, 1, 0], enabled: true },
      anchors: [{ scope: 'strand', id: 0 }], length_ns: 2,
      run_target: 'alpine', cluster_name: 'amilan', label: 'deposit',
    })
    const p = buildChainPayload(m)
    expect(p.root_job_id).toBe('root-job-42')
    expect(p.root_engine).toBe('oxdna')
    expect(p.stages).toHaveLength(1)
    const st = p.stages[0]
    // exactly the ChainStageRequest keys
    expect(Object.keys(st).sort()).toEqual(
      ['anchors', 'cluster_name', 'engine', 'field', 'label', 'length_ns',
        'protocol', 'run_target', 'steps', 'surface'].sort(),
    )
    // Forces-card `enabled` sentinel stripped; only {field_pN, dir} survive
    expect(st.field).toEqual({ field_pN: 8, dir: [0, 1, 0] })
    expect(st.anchors).toEqual([{ scope: 'strand', id: 0 }])
    expect(st.cluster_name).toBe('amilan')
  })

  it('a disabled / zero field becomes null (no field on the stage)', () => {
    let m = addStage(newPlan(), { field: { field_pN: 8, dir: [1, 0, 0], enabled: false } })
    m = addStage(m, { field: { field_pN: 0, dir: [1, 0, 0], enabled: true } })
    const p = buildChainPayload(m)
    expect(p.stages[0].field).toBeNull()
    expect(p.stages[1].field).toBeNull()
  })

  it('isQueueable requires a root job and ≥1 stage', () => {
    expect(isQueueable(newPlan())).toBe(false)
    expect(isQueueable(setRoot(newPlan(), 'r'))).toBe(false)
    expect(isQueueable(addStage(setRoot(newPlan(), 'r'), {}))).toBe(true)
  })

  // The parity anchor: this literal is asserted BYTE-EQUAL by the backend oracle
  // (tests/test_stage_planner_payload.py) to be a valid MdPipeline that builds a linear
  // chain. Keep the two in sync — if this shape changes, that test must be updated too.
  it('a 3-stage deposition→immobilize→sweep payload matches the backend parity fixture', () => {
    let m = setRoot(newPlan(), 'oxdna-relax-1', 'oxdna')
    m = addStage(m, { engine: 'namd', protocol: 'production', label: 'deposit',
      field: { field_pN: 5, dir: [0, 0, 1], enabled: true }, anchors: null })
    m = addStage(m, { engine: 'namd', protocol: 'production', label: 'immobilize',
      anchors: [{ scope: 'strand', id: 0 }] })
    m = duplicateStage(m, 1)
    m = setStage(m, 2, { label: 'sweep-x', field: { field_pN: 5, dir: [1, 0, 0], enabled: true } })
    const p = buildChainPayload(m)
    expect(p).toEqual({
      root_job_id: 'oxdna-relax-1',
      root_engine: 'oxdna',
      stages: [
        { engine: 'namd', protocol: 'production', field: { field_pN: 5, dir: [0, 0, 1] },
          anchors: null, surface: null, run_target: 'local', cluster_name: null,
          length_ns: null, steps: null, label: 'deposit' },
        { engine: 'namd', protocol: 'production', field: null,
          anchors: [{ scope: 'strand', id: 0 }], surface: null, run_target: 'local',
          cluster_name: null, length_ns: null, steps: null, label: 'immobilize' },
        { engine: 'namd', protocol: 'production', field: { field_pN: 5, dir: [1, 0, 0] },
          anchors: [{ scope: 'strand', id: 0 }], surface: null, run_target: 'local',
          cluster_name: null, length_ns: null, steps: null, label: 'sweep-x' },
      ],
    })
  })
})

describe('stage_planner_model — active-index tracking (editor pins to the same stage)', () => {
  it('remove BEFORE the active stage shifts the selection down (not stale)', () => {
    // 4 stages, index 2 active; remove index 0 → active follows to index 1
    expect(activeIndexAfterRemove(2, 0, 3)).toBe(1)
  })
  it('remove AFTER the active stage leaves it put', () => {
    expect(activeIndexAfterRemove(1, 3, 3)).toBe(1)
  })
  it('remove the active stage (or the last) clamps into range; empty → -1', () => {
    expect(activeIndexAfterRemove(2, 2, 3)).toBe(2)   // now points at the next stage
    expect(activeIndexAfterRemove(3, 3, 3)).toBe(2)   // removed the last → clamp
    expect(activeIndexAfterRemove(0, 0, 0)).toBe(-1)  // list emptied
  })
  it('reorder: moving a bystander across the active stage remaps its index', () => {
    // [A,B,C], B active (1); move A(0)→1 → [B,A,C]; B is now at index 0
    expect(activeIndexAfterReorder(1, 0, 1)).toBe(0)
    // [A,B,C], B active (1); move C(2)→0 → [C,A,B]; B is now at index 2
    expect(activeIndexAfterReorder(1, 2, 0)).toBe(2)
  })
  it('reorder: moving the active stage itself follows to the destination', () => {
    expect(activeIndexAfterReorder(1, 1, 2)).toBe(2)
    expect(activeIndexAfterReorder(2, 2, 0)).toBe(0)
  })
})

describe('stage_planner_model — chain status vocabulary', () => {
  const mkChain = (status, stageStatuses) => ({
    chain_id: 'c1', status, error: null,
    stages: stageStatuses.map((st, i) => ({ index: i, status: st, engine: 'namd', job_id: null })),
  })

  it('running → "stage N of M"', () => {
    const s = chainStatusSummary(mkChain('running', ['done', 'running', 'pending']))
    expect(s.headline).toMatch(/stage 2 of 3/)
    expect(s.currentIndex).toBe(1)
    expect(s.doneCount).toBe(1)
    expect(s.resumable).toBe(false)
  })

  it('failed → resumable + partial-failure headline + queued-behind badges', () => {
    const s = chainStatusSummary(mkChain('failed', ['done', 'failed', 'pending', 'pending']))
    expect(s.resumable).toBe(true)
    expect(s.failedIndex).toBe(1)
    expect(s.headline).toMatch(/Halted at stage 2 of 4/)
    // stages after the failure are "queued behind" the halt
    expect(s.stageBadges[2].queuedBehind).toBe(true)
    expect(s.stageBadges[3].queuedBehind).toBe(true)
    expect(s.stageBadges[0].queuedBehind).toBe(false)
  })

  it('completed → all-done headline', () => {
    const s = chainStatusSummary(mkChain('completed', ['done', 'done']))
    expect(s.headline).toMatch(/Chain complete — 2 of 2/)
    expect(s.doneCount).toBe(2)
  })

  it('failed → surfaces the backend error verbatim so the sidebar can explain WHY', () => {
    const chain = mkChain('failed', ['done', 'failed', 'pending'])
    chain.error = "409: A different design is loaded ... Open '6hbx100_1xT' to continue this run."
    const s = chainStatusSummary(chain)
    expect(s.error).toBe(chain.error)
  })

  it('healthy chains carry no error (only a halt surfaces one)', () => {
    expect(chainStatusSummary(mkChain('running', ['running', 'pending'])).error).toBeNull()
    // even if a stray error rode along on a non-failed chain, it is not surfaced
    const c = mkChain('completed', ['done', 'done']); c.error = 'stale'
    expect(chainStatusSummary(c).error).toBeNull()
  })
})
