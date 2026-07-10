import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('../api/client.js', () => ({ simulateRecommendation: vi.fn() }))
vi.mock('./job_activity.js', () => ({
  confirmSimEngineLaunch: vi.fn(),
  confirmGpuLaunch: vi.fn(),
}))

import { simulateRecommendation } from '../api/client.js'
import { confirmSimEngineLaunch, confirmGpuLaunch } from './job_activity.js'
import { initSimulateLaunch } from './simulate_launch.js'

const REC_FREE = {
  gpu: { available: true, busy: false }, free_cores: 16, has_proteins: false,
  n_nucleotides: 1328, gpu_eta_seconds: null,
  recommendation: { engine: 'oxdna', backend: 'CUDA', cpu_slowdown_factor: 13 },
}
const REC_BUSY = {
  gpu: { available: true, busy: true, holder_name: 'namd3' }, free_cores: 12,
  has_proteins: false, n_nucleotides: 14172, gpu_eta_seconds: 420,
  recommendation: { engine: 'lammps', backend: 'CPU', cpu_slowdown_factor: 47 },
}
const REC_BUSY_PROTEIN = { ...REC_BUSY, has_proteins: true,
  recommendation: { engine: 'oxdna', backend: 'CUDA', cpu_slowdown_factor: 47 } }

function make(overrides = {}) {
  const engineSelector = { select: vi.fn() }
  const launchLammps = vi.fn().mockResolvedValue({ job_id: 'l1' })
  const statusMount = document.createElement('div')
  const sim = initSimulateLaunch({
    engineSelector, statusMount, getDevices: () => '0',
    oxdnaForm: () => ({ mdRelaxSteps: 5000, salt: 0.4 }),
    getForces: () => ({ field: null, anchors: [], wall: null }),
    launchLammps, ...overrides,
  })
  return { sim, engineSelector, launchLammps, statusMount }
}

beforeEach(() => vi.clearAllMocks())

describe('refresh', () => {
  it('renders the status line from the recommendation', async () => {
    simulateRecommendation.mockResolvedValue(REC_FREE)
    const { sim, statusMount } = make()
    await sim.refresh()
    expect(statusMount.textContent).toMatch(/GPU: free/)
    expect(statusMount.textContent).toMatch(/oxDNA \(GPU\)/)
  })
  it('degrades to a neutral line when the endpoint fails', async () => {
    simulateRecommendation.mockResolvedValue(null)
    const { sim, statusMount } = make()
    await sim.refresh()
    expect(statusMount.textContent).toMatch(/unknown/)
  })
})

describe('guardOxdnaLaunch', () => {
  it('GPU free → gpu, no dialog', async () => {
    simulateRecommendation.mockResolvedValue(REC_FREE)
    const { sim, launchLammps } = make()
    expect(await sim.guardOxdnaLaunch()).toBe('gpu')
    expect(confirmSimEngineLaunch).not.toHaveBeenCalled()
    expect(launchLammps).not.toHaveBeenCalled()
  })

  it('GPU busy + CPU chosen → switches to LAMMPS, launches it, returns cpu', async () => {
    simulateRecommendation.mockResolvedValue(REC_BUSY)
    confirmSimEngineLaunch.mockResolvedValue('cpu')
    const { sim, engineSelector, launchLammps } = make()
    expect(await sim.guardOxdnaLaunch()).toBe('cpu')
    expect(engineSelector.select).toHaveBeenCalledWith('lammps')
    expect(launchLammps).toHaveBeenCalledTimes(1)
    const params = launchLammps.mock.calls[0][0]
    expect(params).toMatchObject({ steps: 5000, salt: 0.4, cores: 12, ranks: 12 })
  })

  it('GPU busy + GPU chosen → gpu, no LAMMPS launch', async () => {
    simulateRecommendation.mockResolvedValue(REC_BUSY)
    confirmSimEngineLaunch.mockResolvedValue('gpu')
    const { sim, launchLammps } = make()
    expect(await sim.guardOxdnaLaunch()).toBe('gpu')
    expect(launchLammps).not.toHaveBeenCalled()
  })

  it('GPU busy + proteins → two-way GPU confirm (no CPU fallback)', async () => {
    simulateRecommendation.mockResolvedValue(REC_BUSY_PROTEIN)
    confirmGpuLaunch.mockResolvedValue('gpu')
    const { sim, launchLammps } = make()
    expect(await sim.guardOxdnaLaunch()).toBe('gpu')
    expect(confirmGpuLaunch).toHaveBeenCalledWith(
      expect.objectContaining({ hasCpuAlternative: false }))
    expect(confirmSimEngineLaunch).not.toHaveBeenCalled()
    expect(launchLammps).not.toHaveBeenCalled()
  })
})
