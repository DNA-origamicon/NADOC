import { describe, it, expect } from 'vitest'
import * as THREE from 'three'
import {
  matrixFromInstance, sameInstanceTransform, assemblyTransformOnlyChange,
  summarizeConstraint, constraintRelevantChanged,
} from './assembly_diff.js'

const inst = (id, values, extra = {}) => ({ id, transform: { values }, ...extra })
const IDENTITY = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
// Row-major translation by (5,6,7) — matrixFromInstance transposes from row-major.
const TRANSLATE = [1, 0, 0, 5, 0, 1, 0, 6, 0, 0, 1, 7, 0, 0, 0, 1]

describe('matrixFromInstance', () => {
  it('reads a row-major translation correctly', () => {
    const m = matrixFromInstance(inst('a', TRANSLATE))
    const p = new THREE.Vector3(0, 0, 0).applyMatrix4(m)
    expect(p.x).toBeCloseTo(5); expect(p.y).toBeCloseTo(6); expect(p.z).toBeCloseTo(7)
  })
})

describe('sameInstanceTransform', () => {
  it('true for equal value arrays, false for any difference', () => {
    expect(sameInstanceTransform(inst('a', IDENTITY), inst('b', [...IDENTITY]))).toBe(true)
    expect(sameInstanceTransform(inst('a', IDENTITY), inst('b', TRANSLATE))).toBe(false)
  })
  it('false when an array is missing or a different length', () => {
    expect(sameInstanceTransform(inst('a', IDENTITY), { id: 'b' })).toBe(false)
    expect(sameInstanceTransform(inst('a', IDENTITY), inst('b', [1, 2, 3]))).toBe(false)
  })
})

describe('assemblyTransformOnlyChange', () => {
  const base = { instances: [inst('a', IDENTITY, { representation: 'cyl', mode: 'cg' })] }
  it('true when only transform values differ', () => {
    const next = { instances: [inst('a', TRANSLATE, { representation: 'cyl', mode: 'cg' })] }
    expect(assemblyTransformOnlyChange(base, next)).toBe(true)
  })
  it('true for a pure visibility toggle (not geometry-affecting)', () => {
    const a = { instances: [inst('a', IDENTITY, { representation: 'cyl', visible: true })] }
    const b = { instances: [inst('a', IDENTITY, { representation: 'cyl', visible: false })] }
    expect(assemblyTransformOnlyChange(a, b)).toBe(true)
  })
  it('false when representation changes', () => {
    const next = { instances: [inst('a', IDENTITY, { representation: 'full', mode: 'cg' })] }
    expect(assemblyTransformOnlyChange(base, next)).toBe(false)
  })
  it('false when the instance set changes or is empty', () => {
    expect(assemblyTransformOnlyChange(base, { instances: [] })).toBe(false)
    expect(assemblyTransformOnlyChange({ instances: [] }, base)).toBe(false)
  })
  it('false when materialized linker topology changes', () => {
    const a = { instances: [inst('a', IDENTITY)], assembly_helices: [] }
    const b = { instances: [inst('a', IDENTITY)], assembly_helices: [{ id: 'h' }] }
    expect(assemblyTransformOnlyChange(a, b)).toBe(false)
  })
})

describe('summarizeConstraint', () => {
  it('returns null for free / missing', () => {
    expect(summarizeConstraint(null)).toBeNull()
    expect(summarizeConstraint({ dof: 'free' })).toBeNull()
  })
  it('maps each DOF kind to a chip with the right severity', () => {
    expect(summarizeConstraint({ dof: 'anchored', reason: 'fixed' })).toEqual({ text: 'Anchored — fixed', severity: 'locked' })
    expect(summarizeConstraint({ dof: 'over-constrained', reason: 'conflict' })).toEqual({ text: 'conflict', severity: 'warn' })
    expect(summarizeConstraint({ dof: 'revolute', name: 'J1' })).toEqual({ text: '1-DOF rotation about joint "J1"', severity: 'ok' })
    expect(summarizeConstraint({ dof: 'spherical' }).severity).toBe('ok')
  })
})

describe('constraintRelevantChanged', () => {
  const asm = (joints = [], instances = []) => ({ joints, instances })
  it('false when joints + fixed flags are unchanged', () => {
    const a = asm([{ id: 'j', joint_type: 'revolute', instance_a_id: 'A', instance_b_id: 'B' }], [{ id: 'A', fixed: false }])
    const b = asm([{ id: 'j', joint_type: 'revolute', instance_a_id: 'A', instance_b_id: 'B' }], [{ id: 'A', fixed: false }])
    expect(constraintRelevantChanged(a, b)).toBe(false)
  })
  it('true when a joint is added or its limits change', () => {
    expect(constraintRelevantChanged(asm([]), asm([{ id: 'j', joint_type: 'revolute' }]))).toBe(true)
    const a = asm([{ id: 'j', joint_type: 'revolute', max_limit: 1 }])
    const b = asm([{ id: 'j', joint_type: 'revolute', max_limit: 2 }])
    expect(constraintRelevantChanged(a, b)).toBe(true)
  })
  it('true when an instance fixed flag flips', () => {
    expect(constraintRelevantChanged(asm([], [{ id: 'A', fixed: false }]), asm([], [{ id: 'A', fixed: true }]))).toBe(true)
  })
})
