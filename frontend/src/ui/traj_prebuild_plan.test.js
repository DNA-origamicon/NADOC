import { describe, it, expect, vi } from 'vitest'
import { initTrajPrebuildPlan, RAM_CACHE_MS } from './traj_prebuild_plan.js'
import { BROWSER_HEAP_CEILING_BYTES } from './oxdna_display.js'

const apiWith = (mb) => ({ getSystemResources: vi.fn(async () => ({ ram_available_mb: mb })) })

describe('freeRamBytes', () => {
  it('converts the backend MemAvailable reading to bytes', async () => {
    const p = initTrajPrebuildPlan({ api: apiWith(2048) })
    expect(await p.freeRamBytes()).toBe(2048 * 1024 * 1024)
  })

  it('caches inside the window and re-reads after it', async () => {
    let t = 0
    const api = apiWith(1024)
    const p = initTrajPrebuildPlan({ api, now: () => t })
    await p.freeRamBytes()
    await p.freeRamBytes()
    expect(api.getSystemResources).toHaveBeenCalledTimes(1)
    t += RAM_CACHE_MS + 1
    await p.freeRamBytes()
    expect(api.getSystemResources).toHaveBeenCalledTimes(2)
  })

  it('answers null when the reading is missing, absent or failing', async () => {
    expect(await initTrajPrebuildPlan({ api: {} }).freeRamBytes()).toBeNull()
    expect(await initTrajPrebuildPlan({ api: apiWith(0) }).freeRamBytes()).toBeNull()
    const boom = { getSystemResources: vi.fn(async () => { throw new Error('down') }) }
    expect(await initTrajPrebuildPlan({ api: boom }).freeRamBytes()).toBeNull()
  })

  it('lastFreeRamBytes is null until the first read, then the cached value', async () => {
    const p = initTrajPrebuildPlan({ api: apiWith(512) })
    expect(p.lastFreeRamBytes()).toBeNull()
    await p.freeRamBytes()
    expect(p.lastFreeRamBytes()).toBe(512 * 1024 * 1024)
  })

  it('gives each instance its own cache — no leak between consumers', async () => {
    const api = apiWith(1024)
    const a = initTrajPrebuildPlan({ api })
    const b = initTrajPrebuildPlan({ api })
    await a.freeRamBytes()
    await b.freeRamBytes()
    expect(api.getSystemResources).toHaveBeenCalledTimes(2)
  })
})

describe('planFor', () => {
  const ctrl = (info) => ({ trajectoryInfo: () => info })

  it('returns null when the controller holds no trajectory', async () => {
    const p = initTrajPrebuildPlan({ api: apiWith(8192) })
    expect(await p.planFor(ctrl(null))).toBeNull()
    expect(await p.planFor(ctrl({ total: 0 }))).toBeNull()
    expect(await p.planFor(undefined)).toBeNull()
  })

  it('prices the prebuild from the exact serial span when it is known', async () => {
    const p = initTrajPrebuildPlan({ api: apiWith(64_000) })
    const plan = await p.planFor(ctrl({ total: 10, atomSerials: 1000, nNucleotides: 50 }))
    expect(plan.frameBytes).toBe(1000 * 3 * 4)
    expect(plan.wantBytes).toBe(10 * 1000 * 3 * 4)
    expect(plan.capped).toBe(false)
  })

  it('falls back to the per-nucleotide estimate before the topology is known', async () => {
    const p = initTrajPrebuildPlan({ api: apiWith(64_000) })
    const plan = await p.planFor(ctrl({ total: 4, atomSerials: 0, nNucleotides: 100 }))
    expect(plan.frameBytes).toBeGreaterThan(0)
  })

  it('lets free RAM bind the budget below the heap ceiling', async () => {
    const tight = await initTrajPrebuildPlan({ api: apiWith(64) })
      .planFor(ctrl({ total: 5000, atomSerials: 400_000 }))
    expect(tight.capped).toBe(true)
    expect(tight.limitedBy).toBe('ram')
    expect(tight.budgetBytes).toBeLessThan(BROWSER_HEAP_CEILING_BYTES)
  })

  it('falls back to the heap ceiling when the machine is unknown', async () => {
    const plan = await initTrajPrebuildPlan({ api: {} })
      .planFor(ctrl({ total: 5000, atomSerials: 400_000 }))
    expect(plan.limitedBy).toBe('heap')
    expect(plan.budgetBytes).toBe(BROWSER_HEAP_CEILING_BYTES)
  })
})
