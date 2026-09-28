import { describe, expect, it, vi } from 'vitest'
import { createAssemblySimulationContext, isSimulationApiPath, needsAssemblySimulation } from './simulation_context.js'

describe('assembly simulation context', () => {
  it('recognizes every simulation engine and excludes ordinary design/assembly APIs', () => {
    for (const path of [
      '/simulate/recommendation', '/oxdna/jobs', '/lammps/jobs', '/mrdna/jobs',
      '/cando/jobs', '/snupi/jobs', '/blade/jobs', '/md/jobs', '/shape-metrics/compare',
      '/benchmark/hardware', '/runpod/job-preview',
    ]) expect(isSimulationApiPath(path), path).toBe(true)
    expect(isSimulationApiPath('/assembly/geometry')).toBe(false)
    expect(isSimulationApiPath('/design')).toBe(false)
  })

  it('materializes once per assembly object and rematerializes after replacement', async () => {
    const context = createAssemblySimulationContext()
    const materialize = vi.fn().mockResolvedValue({})
    const first = { id: 'assembly', instances: [] }
    const second = { ...first, instances: [{ id: 'p1' }] }

    await context.ensure({ path: '/oxdna/jobs', method: 'POST', assemblyActive: true, assembly: first, materialize })
    await context.ensure({ path: '/mrdna/jobs', method: 'POST', assemblyActive: true, assembly: first, materialize })
    await context.ensure({ path: '/cando/jobs', method: 'POST', assemblyActive: true, assembly: second, materialize })
    expect(materialize).toHaveBeenCalledTimes(2)
  })

  it('rematerializes when polymerization mutates the same assembly object', async () => {
    const context = createAssemblySimulationContext()
    const materialize = vi.fn().mockResolvedValue({})
    const assembly = { id: 'assembly', instances_v2: [{ id: 'p1' }] }
    await context.ensure({ path: '/cando/jobs', method: 'POST', assemblyActive: true, assembly, materialize })
    assembly.instances_v2.push({ id: 'p2' })
    await context.ensure({ path: '/cando/jobs', method: 'POST', assemblyActive: true, assembly, materialize })
    expect(materialize).toHaveBeenCalledTimes(2)
  })

  it('coalesces concurrent first requests and leaves part mode untouched', async () => {
    const context = createAssemblySimulationContext()
    let release
    const materialize = vi.fn(() => new Promise(resolve => { release = resolve }))
    const assembly = { id: 'assembly' }
    const a = context.ensure({ path: '/oxdna/jobs', method: 'POST', assemblyActive: true, assembly, materialize })
    const b = context.ensure({ path: '/md/jobs', method: 'POST', assemblyActive: true, assembly, materialize })
    await Promise.resolve()
    expect(materialize).toHaveBeenCalledTimes(1)
    release({})
    await Promise.all([a, b])
    await context.ensure({ path: '/oxdna/jobs', method: 'POST', assemblyActive: false, assembly, materialize })
    expect(materialize).toHaveBeenCalledTimes(1)
  })
})


describe('assembly browsing is independent of geometry preparation', () => {
  it('does not prepare for capability, policy, list, progress or stop requests', async () => {
    const context = createAssemblySimulationContext(), materialize = vi.fn()
    for (const path of ['/simulate/recommendation?devices=0', '/simulate/jobs?assembly=true',
      '/md/namd-available', '/md/relax-presets', '/md/queue', '/benchmark/hardware',
      '/md/gpu-status?devices=0', '/md/optimize-advanced/hardware', '/runpod/status',
      ...['oxdna', 'md', 'mrdna', 'cando', 'snupi', 'blade', 'lammps'].flatMap(engine => [
        `/${engine}/available`, `/${engine}/jobs`, `/${engine}/jobs/job`, `/${engine}/jobs/job/progress`,
      ])]) {
      expect(needsAssemblySimulation(path), path).toBe(false)
      await context.ensure({ path, assemblyActive: true, assembly: { id: 'large' }, materialize })
    }
    for (const method of ['POST', 'DELETE']) {
      expect(needsAssemblySimulation('/md/jobs/job/stop', method)).toBe(false)
    }
    expect(materialize).not.toHaveBeenCalled()
  })

  it('prepares explicit design consumers including autorefine and previews', () => {
    for (const path of ['/oxdna/jobs', '/cando/jobs', '/snupi/jobs', '/mrdna/jobs', '/lammps/jobs',
      '/md/jobs', '/md/protocol-plan', '/oxdna/jobs/estimate-disk', '/oxdna/live/start',
      '/design/oxdna/autorefine/start', '/design/cando/autorefine/start']) {
      expect(needsAssemblySimulation(path, 'POST'), path).toBe(true)
    }
    expect(needsAssemblySimulation('/md/optimize-advanced')).toBe(true)
  })

  it('retries failed preparation and invalidates when returning from part mode', async () => {
    const context = createAssemblySimulationContext()
    const materialize = vi.fn().mockRejectedValueOnce(new Error('missing source')).mockResolvedValue({})
    const args = { path: '/oxdna/jobs', method: 'POST', assemblyActive: true, assembly: { id: 'A' }, materialize }
    await expect(context.ensure(args)).rejects.toThrow('missing source')
    await context.ensure(args)
    await context.ensure({ ...args, assemblyActive: false })
    await context.ensure(args)
    expect(materialize).toHaveBeenCalledTimes(3)
  })
})

it('upgrades a compact FEM projection for engines needing browser geometry', async () => {
  const context = createAssemblySimulationContext(), materialize = vi.fn()
  const args = { method: 'POST', assemblyActive: true, assembly: { id: 'A' }, materialize }
  await context.ensure({ ...args, path: '/cando/jobs' })
  await context.ensure({ ...args, path: '/snupi/jobs' })
  await context.ensure({ ...args, path: '/oxdna/jobs' })
  expect(materialize.mock.calls).toEqual([[{ compact: true }], [{ compact: false }]])
  for (const engine of ['cando', 'snupi']) {
    for (const suffix of ['snapshot-geometry', 'display', 'display-bin', 'rmsf', 'deviation', 'cylinders', 'thermal-representative-bin']) {
      expect(needsAssemblySimulation(`/${engine}/jobs/id/${suffix}`)).toBe(false)
    }
  }
})
