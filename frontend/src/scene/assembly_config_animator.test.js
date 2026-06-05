import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import * as THREE from 'three'
import { createMockStore } from '../test-helpers/mock_store.js'
import {
  easeInOutQuad,
  buildConfigAnimItems,
  initAssemblyConfigAnimator,
} from './assembly_config_animator.js'

// Row-major translation matrix (the form the backend sends in transform.values).
function translationValues(x, y, z) {
  return [
    1, 0, 0, x,
    0, 1, 0, y,
    0, 0, 1, z,
    0, 0, 0, 1,
  ]
}

describe('easeInOutQuad', () => {
  it('pins the endpoints and midpoint', () => {
    expect(easeInOutQuad(0)).toBe(0)
    expect(easeInOutQuad(1)).toBe(1)
    expect(easeInOutQuad(0.5)).toBeCloseTo(0.5, 12)
  })

  it('is monotonic and stays within [0,1]', () => {
    let prev = -Infinity
    for (let t = 0; t <= 1; t += 0.1) {
      const v = easeInOutQuad(t)
      expect(v).toBeGreaterThanOrEqual(0)
      expect(v).toBeLessThanOrEqual(1)
      expect(v).toBeGreaterThanOrEqual(prev)
      prev = v
    }
  })

  it('eases in slower than linear before the midpoint', () => {
    // quadratic ease-in: value at t=0.25 is below the linear 0.25
    expect(easeInOutQuad(0.25)).toBeLessThan(0.25)
  })
})

describe('buildConfigAnimItems', () => {
  it('returns [] when nothing is animatable', () => {
    expect(buildConfigAnimItems({ instances: [] }, { instance_states: [] }, () => null)).toEqual([])
    expect(buildConfigAnimItems(null, null, () => null)).toEqual([])
  })

  it('skips instances without a stored target transform', () => {
    const assembly = { instances: [{ id: 'a', transform: { values: translationValues(0, 0, 0) } }] }
    const cfg = { instance_states: [{ instance_id: 'a' }] } // no transform.values
    expect(buildConfigAnimItems(assembly, cfg, () => null)).toEqual([])
  })

  it('decomposes start (from live transform) and end (from cfg)', () => {
    const liveStart = new THREE.Matrix4().makeTranslation(1, 2, 3)
    const assembly = { instances: [{ id: 'a', transform: { values: translationValues(0, 0, 0) } }] }
    const cfg = { instance_states: [{ instance_id: 'a', transform: { values: translationValues(7, 8, 9) } }] }

    const items = buildConfigAnimItems(assembly, cfg, (id) => (id === 'a' ? liveStart : null))
    expect(items).toHaveLength(1)
    const it0 = items[0]
    expect(it0.id).toBe('a')
    expect(it0.sp.toArray()).toEqual([1, 2, 3]) // start from live transform
    expect(it0.ep.toArray()).toEqual([7, 8, 9]) // end from cfg
    expect(it0.ss.toArray().map(v => Math.round(v))).toEqual([1, 1, 1])
    expect(it0.es.toArray().map(v => Math.round(v))).toEqual([1, 1, 1])
  })

  it('falls back to the instance transform when no live transform exists', () => {
    const assembly = { instances: [{ id: 'a', transform: { values: translationValues(4, 5, 6) } }] }
    const cfg = { instance_states: [{ instance_id: 'a', transform: { values: translationValues(0, 0, 0) } }] }
    const items = buildConfigAnimItems(assembly, cfg, () => null)
    expect(items[0].sp.toArray()).toEqual([4, 5, 6])
    expect(items[0].ep.toArray()).toEqual([0, 0, 0])
  })

  it('includes only the instances that have a matching cfg state', () => {
    const assembly = {
      instances: [
        { id: 'a', transform: { values: translationValues(0, 0, 0) } },
        { id: 'b', transform: { values: translationValues(0, 0, 0) } },
      ],
    }
    const cfg = { instance_states: [{ instance_id: 'b', transform: { values: translationValues(1, 1, 1) } }] }
    const items = buildConfigAnimItems(assembly, cfg, () => null)
    expect(items.map(i => i.id)).toEqual(['b'])
  })
})

describe('initAssemblyConfigAnimator', () => {
  let deps, store, api, assemblyRenderer, assemblyJointRenderer

  function makeDeps(state = {}) {
    store = createMockStore(state)
    api = { restoreAssemblyConfiguration: vi.fn().mockResolvedValue(undefined) }
    assemblyRenderer = {
      getLiveTransform: vi.fn(() => null),
      setLiveTransform: vi.fn(),
    }
    assemblyJointRenderer = { setLiveJointTransform: vi.fn() }
    deps = {
      store, api, assemblyRenderer, assemblyJointRenderer,
      hasAssemblyPending: vi.fn(() => false),
      commitAssemblyPending: vi.fn().mockResolvedValue(undefined),
    }
    return deps
  }

  it('no-ops with no assembly and never hits the backend', async () => {
    const { animate } = initAssemblyConfigAnimator(makeDeps({ currentAssembly: null }))
    await animate({ id: 'cfg1' })
    expect(api.restoreAssemblyConfiguration).not.toHaveBeenCalled()
  })

  it('no-ops with no cfg', async () => {
    const { animate } = initAssemblyConfigAnimator(makeDeps({ currentAssembly: { instances: [] } }))
    await animate(null)
    expect(api.restoreAssemblyConfiguration).not.toHaveBeenCalled()
  })

  it('with nothing to tween, restores directly without touching renderers', async () => {
    const assembly = { instances: [{ id: 'a', transform: { values: translationValues(0, 0, 0) } }] }
    const { animate } = initAssemblyConfigAnimator(makeDeps({ currentAssembly: assembly }))
    await animate({ id: 'cfg1', instance_states: [] })
    expect(assemblyRenderer.setLiveTransform).not.toHaveBeenCalled()
    expect(api.restoreAssemblyConfiguration).toHaveBeenCalledWith('cfg1')
  })

  it('commits a pending transform before animating', async () => {
    const assembly = { instances: [{ id: 'a', transform: { values: translationValues(0, 0, 0) } }] }
    const d = makeDeps({ currentAssembly: assembly })
    d.hasAssemblyPending = vi.fn(() => true)
    d.commitAssemblyPending = vi.fn().mockResolvedValue(undefined)
    const { animate } = initAssemblyConfigAnimator(d)
    await animate({ id: 'cfg1', instance_states: [] })
    expect(d.commitAssemblyPending).toHaveBeenCalledTimes(1)
  })

  describe('with a fake animation clock', () => {
    // Advance the clock by 400 ms each rAF tick so the tween hits t>=1 (the
    // 650 ms duration) on the second frame and resolves — no infinite loop.
    beforeEach(() => {
      let clock = 0
      vi.stubGlobal('performance', { now: () => clock })
      vi.stubGlobal('requestAnimationFrame', (cb) => {
        clock += 400
        queueMicrotask(() => cb(clock))
        return 1
      })
    })
    afterEach(() => { vi.unstubAllGlobals() })

    it('drives both renderers each frame and restores at the end', async () => {
      const assembly = { instances: [{ id: 'a', transform: { values: translationValues(0, 0, 0) } }] }
      const cfg = { id: 'cfg1', instance_states: [{ instance_id: 'a', transform: { values: translationValues(10, 0, 0) } }] }
      const { animate } = initAssemblyConfigAnimator(makeDeps({ currentAssembly: assembly }))

      await animate(cfg)

      expect(assemblyRenderer.setLiveTransform).toHaveBeenCalled()
      expect(assemblyJointRenderer.setLiveJointTransform).toHaveBeenCalled()
      // last write lands at the target position (10,0,0)
      const lastMat = assemblyRenderer.setLiveTransform.mock.calls.at(-1)[1]
      const pos = new THREE.Vector3().setFromMatrixPosition(lastMat)
      expect(pos.x).toBeCloseTo(10, 6)
      expect(api.restoreAssemblyConfiguration).toHaveBeenCalledWith('cfg1')
    })
  })
})
