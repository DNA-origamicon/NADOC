import { describe, expect, it, vi } from 'vitest'
import { createAssemblySimulationContext, isSimulationApiPath } from './simulation_context.js'

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

    await context.ensure({ path: '/oxdna/jobs', assemblyActive: true, assembly: first, materialize })
    await context.ensure({ path: '/mrdna/jobs', assemblyActive: true, assembly: first, materialize })
    await context.ensure({ path: '/cando/jobs', assemblyActive: true, assembly: second, materialize })
    expect(materialize).toHaveBeenCalledTimes(2)
  })

  it('rematerializes when polymerization mutates the same assembly object', async () => {
    const context = createAssemblySimulationContext()
    const materialize = vi.fn().mockResolvedValue({})
    const assembly = { id: 'assembly', instances_v2: [{ id: 'p1' }] }
    await context.ensure({ path: '/cando/jobs', assemblyActive: true, assembly, materialize })
    assembly.instances_v2.push({ id: 'p2' })
    await context.ensure({ path: '/cando/jobs', assemblyActive: true, assembly, materialize })
    expect(materialize).toHaveBeenCalledTimes(2)
  })

  it('coalesces concurrent first requests and leaves part mode untouched', async () => {
    const context = createAssemblySimulationContext()
    let release
    const materialize = vi.fn(() => new Promise(resolve => { release = resolve }))
    const assembly = { id: 'assembly' }
    const a = context.ensure({ path: '/oxdna/jobs', assemblyActive: true, assembly, materialize })
    const b = context.ensure({ path: '/md/jobs', assemblyActive: true, assembly, materialize })
    await Promise.resolve()
    expect(materialize).toHaveBeenCalledTimes(1)
    release({})
    await Promise.all([a, b])
    await context.ensure({ path: '/oxdna/jobs', assemblyActive: false, assembly, materialize })
    expect(materialize).toHaveBeenCalledTimes(1)
  })
})
