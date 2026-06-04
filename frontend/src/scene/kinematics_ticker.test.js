/**
 * Tests for scene/kinematics_ticker.js.
 *
 * Focused on gearDebug() — the console diagnostic moved out of main.js's inline
 * window.nadocGearDebug wiring. It reads currentAssembly from the store and folds
 * in the ticker's internal debugState(), so a mock store is all the setup needed
 * (no tick / renderer machinery). console.log is spied so the tag + payload are
 * assertable. (The integration tick/flush paths are exercised in the app + smoke;
 * this file is the module's first unit coverage, scoped to the extracted helper.)
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createMockStore } from '../test-helpers/mock_store.js'
import { initKinematicsTicker } from './kinematics_ticker.js'

function makeTicker(state = {}) {
  const store = createMockStore(state)
  return initKinematicsTicker({
    store,
    api: {},
    getAssemblyRenderer: () => ({}),
    getAssemblyJointRenderer: () => ({}),
  })
}

describe('kinematics_ticker gearDebug()', () => {
  let logSpy
  beforeEach(() => { logSpy = vi.spyOn(console, 'log').mockImplementation(() => {}) })
  afterEach(() => { logSpy.mockRestore() })

  it('returns an empty-but-shaped dump when there is no assembly', () => {
    const out = makeTicker({ currentAssembly: null }).gearDebug()
    expect(out.assembly_id).toBeUndefined()
    expect(out.joints).toEqual([])
    expect(out.gear_relations).toEqual([])
    // The ticker's own state is always folded in.
    expect(out.ticker).toMatchObject({ hasAssembly: false, gearEdges: [] })
  })

  it('summarizes each joint to the gear-debug field subset', () => {
    const assembly = {
      id: 'asm-1',
      joints: [{
        id: 'j1', name: 'hinge', joint_type: 'revolute',
        current_value: 0.5, angular_velocity_rpm: 12,
        instance_a_id: 'iA', instance_b_id: 'iB',
        // extra fields that must NOT leak into the summary
        min_limit: -1, max_limit: 1, spin_paused: false,
      }],
      gear_relations: [{ driver_joint_id: 'j1', driven_joint_id: 'j2', ratio: 2 }],
    }
    const out = makeTicker({ currentAssembly: assembly }).gearDebug()
    expect(out.assembly_id).toBe('asm-1')
    expect(out.joints).toEqual([{
      id: 'j1', name: 'hinge', type: 'revolute',
      current_value: 0.5, angular_velocity_rpm: 12,
      instance_a_id: 'iA', instance_b_id: 'iB',
    }])
    expect(out.gear_relations).toEqual([{ driver_joint_id: 'j1', driven_joint_id: 'j2', ratio: 2 }])
    expect(out.ticker.hasAssembly).toBe(true)
    expect(out.ticker.gearRelationsOnAssembly).toEqual(assembly.gear_relations)
  })

  it('logs the [nadocGearDebug] tag and returns the same payload it logged', () => {
    const ticker = makeTicker({ currentAssembly: { id: 'asm-x', joints: [] } })
    const out = ticker.gearDebug()
    expect(logSpy).toHaveBeenCalledWith('[nadocGearDebug]', out)
  })
})
