/**
 * Tests for scene/belt_polymerize.js (extracted from main.js).
 *
 * Two layers:
 *  - buildBeltPolymerizeCopies — the pure copy-transform builder, tested with the
 *    REAL belt_geometry.beltFrameAt against a hand-built square belt loop.
 *  - initBeltPolymerize — the factory wiring, with belt_rider.js (beltRiderCtx /
 *    beltRiderFill) and ui/toast.js mocked so ctx + toast text are assertable.
 *    belt_geometry stays REAL so the success path exercises the real frame math.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import * as THREE from 'three'

vi.mock('./belt_rider.js', () => ({
  beltRiderCtx: vi.fn(),
  beltRiderFill: vi.fn(),
}))
vi.mock('../ui/toast.js', () => ({ showToast: vi.fn() }))

import { beltRiderCtx, beltRiderFill } from './belt_rider.js'
import { showToast } from '../ui/toast.js'
import { createMockStore } from '../test-helpers/mock_store.js'
import { buildBeltPolymerizeCopies, initBeltPolymerize } from './belt_polymerize.js'

const IDENTITY16 = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]

// Unit square loop in the z=0 plane: perimeter length 40, corners at the axes.
function squareLoop() {
  return [
    new THREE.Vector3(0, 0, 0),
    new THREE.Vector3(10, 0, 0),
    new THREE.Vector3(10, 10, 0),
    new THREE.Vector3(0, 10, 0),
  ]
}

function makeCtx({ arcParam = 0 } = {}) {
  return {
    rider: { instance_id: 'inst1', arc_param: arcParam, local_transform: IDENTITY16 },
    points: squareLoop(),
    planeNormal: [0, 0, 1],
  }
}

// row-major translation column (the module sends .transpose().toArray()).
function translationOf(values) {
  return [values[3], values[7], values[11]]
}

describe('buildBeltPolymerizeCopies (pure)', () => {
  it('produces n-1 evenly-spaced copies at the expected arc params', () => {
    const { n, copies } = buildBeltPolymerizeCopies(makeCtx(), 4)
    expect(n).toBe(4)
    expect(copies.map(c => c.arc_param)).toEqual([0.25, 0.5, 0.75])
    expect(copies).toHaveLength(3)
  })

  it('embeds the on-loop world position for each copy', () => {
    const { copies } = buildBeltPolymerizeCopies(makeCtx(), 4)
    // arc 0.25→10 along (10,0,0); 0.5→20 (10,10,0); 0.75→30 (0,10,0)
    expect(translationOf(copies[0].transform.values)).toEqual([10, 0, 0])
    expect(translationOf(copies[1].transform.values)).toEqual([10, 10, 0])
    expect(translationOf(copies[2].transform.values)).toEqual([0, 10, 0])
    for (const c of copies) expect(c.transform.values).toHaveLength(16)
  })

  it('clamps count to a minimum of 2 (count 1 / 0 / falsy → n=2, single copy)', () => {
    expect(buildBeltPolymerizeCopies(makeCtx(), 1).n).toBe(2)
    expect(buildBeltPolymerizeCopies(makeCtx(), 0).n).toBe(2)
    expect(buildBeltPolymerizeCopies(makeCtx(), undefined).n).toBe(2)
    expect(buildBeltPolymerizeCopies(makeCtx(), 1).copies).toHaveLength(1)
  })

  it('floors fractional counts', () => {
    const { n, copies } = buildBeltPolymerizeCopies(makeCtx(), 3.9)
    expect(n).toBe(3)
    expect(copies).toHaveLength(2)
  })

  it('wraps the seed arc_param offset into [0,1)', () => {
    // base 0.5 + 1/2 = 1.0 → wraps to 0
    const { copies } = buildBeltPolymerizeCopies(makeCtx({ arcParam: 0.5 }), 2)
    expect(copies[0].arc_param).toBeCloseTo(0, 12)
  })
})

describe('initBeltPolymerize (factory)', () => {
  let store, api, renderer

  beforeEach(() => {
    vi.clearAllMocks()
    store = createMockStore({ currentAssembly: { id: 'a1' }, lastError: { message: 'boom' } })
    api = { polymerizeBelt: vi.fn().mockResolvedValue({}) }
    renderer = { getInstanceCenters: vi.fn(() => [{ id: 'inst1', size: { x: 5, y: 5, z: 5 } }]) }
  })

  const make = () => initBeltPolymerize({ store, api, getAssemblyRenderer: () => renderer })

  it('beltFillInfo returns null when the rider context is unavailable', () => {
    beltRiderCtx.mockReturnValue(null)
    expect(make().beltFillInfo('rX')).toBeNull()
    expect(beltRiderFill).not.toHaveBeenCalled()
  })

  it('beltFillInfo passes the seed instance bbox size into beltRiderFill', () => {
    const ctx = makeCtx()
    beltRiderCtx.mockReturnValue(ctx)
    beltRiderFill.mockReturnValue({ count: 5, spacingNm: 8, footprintNm: 8 })
    const out = make().beltFillInfo('r1')
    expect(out).toEqual({ count: 5, spacingNm: 8, footprintNm: 8 })
    expect(beltRiderFill).toHaveBeenCalledWith(ctx, { x: 5, y: 5, z: 5 })
  })

  it('polymerizeBelt with no context toasts an error and never calls the api', async () => {
    beltRiderCtx.mockReturnValue(null)
    await make().polymerizeBelt('rX', 4)
    expect(showToast).toHaveBeenCalledWith(
      'Belt geometry unavailable — re-attach the part first.', { severity: 'error' })
    expect(api.polymerizeBelt).not.toHaveBeenCalled()
  })

  it('polymerizeBelt posts the copies and reports success', async () => {
    beltRiderCtx.mockReturnValue(makeCtx())
    await make().polymerizeBelt('r1', 4)
    expect(api.polymerizeBelt).toHaveBeenCalledTimes(1)
    const arg = api.polymerizeBelt.mock.calls[0][0]
    expect(arg.rider_id).toBe('r1')
    expect(arg.copies).toHaveLength(3)
    expect(showToast).toHaveBeenCalledWith('Polymerized 4 copies around the belt.')
  })

  it('polymerizeBelt reports a backend failure (null response) with the last error', async () => {
    beltRiderCtx.mockReturnValue(makeCtx())
    api.polymerizeBelt.mockResolvedValue(null)
    await make().polymerizeBelt('r1', 3)
    expect(showToast).toHaveBeenCalledWith('Polymerize failed: boom', { severity: 'error' })
  })
})
