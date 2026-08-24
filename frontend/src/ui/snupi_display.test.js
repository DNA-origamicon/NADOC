import { describe, expect, it, vi } from 'vitest'
import { initSnupiDisplay } from './snupi_display.js'

const display = { ready: true, positions: [{
  helix_id: 'h', bp_index: 0, direction: 'FORWARD', copy: 0,
  backbone_position: [1, 2, 3], nx: 0, ny: 1, nz: 0, tx: 0, ty: 0, tz: 1,
}] }
const snapshot = {
  ready: true, design: { helices: [{ id: 'h' }], strands: [], crossovers: [] },
  nucleotides: [{ helix_id: 'h', bp_index: 0, direction: 'FORWARD', backbone_position: [0, 0, 0] }],
  helix_axes: [],
}

function deps() {
  return {
    designRenderer: {
      applyFemPositions: vi.fn(), clearScalarColors: vi.fn(),
      clearExternalGeometry: vi.fn(), renderExternalGeometry: vi.fn(),
    },
    api: {
      getSnupiDisplay: vi.fn(async () => display),
      getSnupiSnapshotGeometry: vi.fn(async () => snapshot),
    },
  }
}

describe('initSnupiDisplay', () => {
  it('keeps the historical-job snapshot path', async () => {
    const d = deps()
    const c = initSnupiDisplay(d)
    expect(await c.showDeform('old')).toMatchObject({ ok: true, n: 1 })
    expect(d.api.getSnupiSnapshotGeometry).toHaveBeenCalledWith('old', expect.any(AbortSignal))
    expect(d.designRenderer.renderExternalGeometry).toHaveBeenCalled()
  })

  it('reuses exact matching live geometry and reports every subprocess', async () => {
    const d = deps()
    const phases = []
    const c = initSnupiDisplay(d)
    expect(await c.showDeform('current', p => phases.push(p), { reuseLiveGeometry: true }))
      .toMatchObject({ ok: true, n: 1 })
    expect(d.api.getSnupiSnapshotGeometry).not.toHaveBeenCalled()
    expect(d.designRenderer.renderExternalGeometry).not.toHaveBeenCalled()
    expect(d.designRenderer.clearExternalGeometry).toHaveBeenCalled()
    expect(d.designRenderer.applyFemPositions).toHaveBeenCalled()
    expect(phases.map(p => p.phase)).toEqual(expect.arrayContaining([
      'display-data', 'transform', 'reuse-scene', 'apply',
    ]))
  })
})
