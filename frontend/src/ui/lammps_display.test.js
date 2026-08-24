import { describe, it, expect, vi } from 'vitest'
import { initLammpsDisplay } from './lammps_display.js'

// A ready /lammps display response (last aligned frame → applyFemPositions updates).
const displayResp = () => ({
  ready: true,
  positions: [
    { helix_id: 'h0', bp_index: 0, direction: 'FORWARD', backbone_position: [1, 2, 3] },
  ],
})

function makeDeps() {
  const designRenderer = {
    applyFemPositions: vi.fn(),
    clearScalarColors: vi.fn(),
    applyScalarColors: vi.fn(),
  }
  const api = {
    getLammpsDisplay: vi.fn(async () => displayResp()),
    getLammpsRmsf: vi.fn(),
    getLammpsDeviation: vi.fn(),
    getLammpsTrajectory: vi.fn(),
  }
  return { designRenderer, api }
}

describe('lammps_display stopAndRestore', () => {
  it('reports final-frame, transform, and apply subprocess progress', async () => {
    const { designRenderer, api } = makeDeps()
    const d = initLammpsDisplay({ designRenderer, api })
    const progress = []

    await d.displayJob('j', true, p => progress.push(`${p.phase}:${p.done}`))

    expect(progress).toEqual([
      'final-frame:0', 'final-frame:1',
      'transform:0', 'transform:1',
      'apply:0', 'apply:1',
    ])
  })

  it('reports RMSF analysis, transform, and apply subprocess progress', async () => {
    const { designRenderer, api } = makeDeps()
    api.getLammpsRmsf.mockResolvedValue({
      ready: true, n_frames: 2, min_rmsf: 0, max_rmsf: 1, mean_rmsf: 0.5,
      positions: [{ helix_id: 'h0', bp_index: 0, direction: 'FORWARD',
        backbone_position: [1, 2, 3], rmsf: 0.5 }],
    })
    const d = initLammpsDisplay({ designRenderer, api })
    const progress = []

    await d.displayRmsf('j', true, p => progress.push(`${p.phase}:${p.done}`))

    expect(progress).toEqual([
      'rmsf-analysis:0', 'rmsf-analysis:1',
      'transform:0', 'transform:1', 'apply:0', 'apply:1',
    ])
  })

  it('reports deviation analysis, transform, and apply subprocess progress', async () => {
    const { designRenderer, api } = makeDeps()
    api.getLammpsDeviation.mockResolvedValue({
      ready: true, n_frames: 2, min_deviation: 0, max_deviation: 1, mean_deviation: 0.5,
      positions: [{ helix_id: 'h0', bp_index: 0, direction: 'FORWARD',
        backbone_position: [1, 2, 3], deviation: 0.5 }],
    })
    const d = initLammpsDisplay({ designRenderer, api })
    const progress = []

    await d.displayDeviation('j', true, p => progress.push(`${p.phase}:${p.done}`))

    expect(progress).toEqual([
      'deviation-analysis:0', 'deviation-analysis:1',
      'transform:0', 'transform:1', 'apply:0', 'apply:1',
    ])
  })

  it('reverts the model when a display IS active', async () => {
    const { designRenderer, api } = makeDeps()
    const d = initLammpsDisplay({ designRenderer, api })
    await d.displayJob('j')
    expect(d.isActive()).toBe(true)
    designRenderer.applyFemPositions.mockClear()

    d.stopAndRestore()
    // _restore() reverts positions (applyFemPositions(null)) + clears colours.
    expect(designRenderer.applyFemPositions).toHaveBeenCalledWith(null)
    expect(d.isActive()).toBe(false)
  })

  it('is a NO-OP when NOTHING is displayed — must not revert bead positions', () => {
    // The bug: a cluster-move commit fires `nadoc:design-changed`, the LAMMPS panel
    // calls _viewsOff() → stopAndRestore() even with no overlay active. An
    // unconditional _restore() → applyFemPositions(null) → revertToGeometry() snapped
    // the just-moved cluster beads/slabs back to the un-posed geometry (while the axis
    // kept the new pose). With no active display, stopAndRestore must touch nothing.
    const { designRenderer, api } = makeDeps()
    const d = initLammpsDisplay({ designRenderer, api })
    expect(d.isActive()).toBe(false)

    d.stopAndRestore()
    expect(designRenderer.applyFemPositions).not.toHaveBeenCalled()
    expect(designRenderer.clearScalarColors).not.toHaveBeenCalled()
  })
})
