import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  projectTrajectoryFrame,
  showTTCpdTrajectoryHelp,
  trajectoryDurationPs,
} from './tt_cpd_trajectory_help.js'

afterEach(() => {
  document.body.innerHTML = ''
  vi.restoreAllMocks()
})

const product = (id, stereo, available = false) => ({
  id,
  product: 'TT-CPD',
  stereochemistry: stereo,
  label: `${stereo} TT-CPD`,
  next_gate: available ? null : 'qm_reference_data',
  help_trajectory: {
    available,
    reason: available ? null : 'real NAMD smoke validation has not passed',
  },
})

describe('TT-CPD help trajectories', () => {
  it('computes trajectory time and centered projections', () => {
    const trajectory = { frames: [[], [], []], stride_steps: 10, timestep_fs: 2 }
    expect(trajectoryDurationPs(trajectory)).toBeCloseTo(0.04)
    const points = projectTrajectoryFrame([[0, 0, 0], [2, 0, 0]], 100, 80)
    expect(points).toHaveLength(2)
    expect((points[0][0] + points[1][0]) / 2).toBeCloseTo(50)
  })

  it('shows all eight ordered DNA forms and explains why unavailable trajectories are gated', async () => {
    const forms = ['cis-syn', 'cis-syn-II', 'trans-syn-I', 'trans-syn-II', 'cis-anti-I', 'cis-anti-II', 'trans-anti-I', 'trans-anti-II']
    const api = { getPhotoproductCatalog: vi.fn().mockResolvedValue({ products: forms.map((x, i) => product(`p-${i}`, x)) }) }
    await showTTCpdTrajectoryHelp({ api })
    expect(document.querySelectorAll('[data-product-id]')).toHaveLength(8)
    expect(document.querySelector('[data-cpd-trajectory-message]').textContent).toMatch(/NAMD smoke validation has not passed/)
    expect(document.body.textContent).toMatch(/not KIMMDY reactant propensity/)
  })

  it('loads only a capability-approved, backend-verified trajectory', async () => {
    const context = {
      clearRect: vi.fn(), fillRect: vi.fn(), beginPath: vi.fn(), moveTo: vi.fn(),
      lineTo: vi.fn(), stroke: vi.fn(), arc: vi.fn(), fill: vi.fn(),
    }
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(context)
    const trajectory = {
      schema: 'nadoc.photoproduct-help-trajectory.v1',
      frames: [[[0, 0, 0], [1, 0, 0]], [[0, 0, 0], [1.1, 0, 0]]],
      elements: ['C', 'C'], bonds: [[0, 1]], timestep_fs: 2, stride_steps: 10,
      provenance: { engine: 'NAMD 3' },
    }
    const api = {
      getPhotoproductCatalog: vi.fn().mockResolvedValue({ products: [product('tt-cpd-cis-syn', 'cis-syn', true)] }),
      getPhotoproductModelTrajectory: vi.fn().mockResolvedValue(trajectory),
    }
    await showTTCpdTrajectoryHelp({ api })
    await vi.waitFor(() => expect(api.getPhotoproductModelTrajectory).toHaveBeenCalledWith('tt-cpd-cis-syn'))
    await vi.waitFor(() => expect(document.querySelector('[data-cpd-trajectory-message]').textContent).toMatch(/2 frames.*NAMD 3/))
    expect(context.arc).toHaveBeenCalled()
  })
})
