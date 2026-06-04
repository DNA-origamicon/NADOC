import { describe, it, expect } from 'vitest'
import { revoluteCommitValue } from './group_gizmo.js'

// The pure commit-value math for a finished revolute gizmo drag, lifted from
// main.js's `_revoluteGizmoCommitValue`. Inputs: the motion constraint, the live
// unwrapped-angle accumulator, and the seed joint snapshot.

const REV = { dof: 'revolute', jointId: 'j1' }

describe('revoluteCommitValue', () => {
  it('returns null for a non-revolute constraint', () => {
    expect(revoluteCommitValue({
      constraint: { dof: 'prismatic', jointId: 'j1' },
      gizmoAngle: { jointId: 'j1', accum: 1, sideSign: 1 },
      seedJoint: { current_value: 0 },
    })).toBeNull()
  })

  it('returns null when there is no accumulated angle', () => {
    expect(revoluteCommitValue({
      constraint: REV, gizmoAngle: null, seedJoint: { current_value: 0 },
    })).toBeNull()
  })

  it('returns null when the accumulator belongs to a different joint', () => {
    expect(revoluteCommitValue({
      constraint: REV,
      gizmoAngle: { jointId: 'other', accum: 1, sideSign: 1 },
      seedJoint: { current_value: 0 },
    })).toBeNull()
  })

  it('adds the accumulated angle to the seed value (forward side → endpoint b)', () => {
    const out = revoluteCommitValue({
      constraint: REV,
      gizmoAngle: { jointId: 'j1', accum: 0.5, sideSign: 1 },
      seedJoint: { current_value: 1.0 },
    })
    expect(out).toEqual({ current_value: 1.5, endpoint_side: 'b' })
  })

  it('applies sideSign so a backward joint subtracts + reports endpoint a', () => {
    const out = revoluteCommitValue({
      constraint: REV,
      gizmoAngle: { jointId: 'j1', accum: 0.5, sideSign: -1 },
      seedJoint: { current_value: 1.0 },
    })
    expect(out).toEqual({ current_value: 0.5, endpoint_side: 'a' })
  })

  it('treats a missing seed current_value as 0', () => {
    const out = revoluteCommitValue({
      constraint: REV,
      gizmoAngle: { jointId: 'j1', accum: 0.25, sideSign: 1 },
      seedJoint: {},
    })
    expect(out.current_value).toBeCloseTo(0.25)
  })

  it('clamps the committed value to the joint limits', () => {
    const out = revoluteCommitValue({
      constraint: REV,
      gizmoAngle: { jointId: 'j1', accum: 99, sideSign: 1 },
      seedJoint: { current_value: 0, min_limit: -1, max_limit: 2 },
    })
    expect(out).toEqual({ current_value: 2, endpoint_side: 'b' })
  })
})
