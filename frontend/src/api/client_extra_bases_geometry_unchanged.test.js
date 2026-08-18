/**
 * Crossover/forced-ligation extra-bases patches never move real nucleotide
 * geometry (extra_bases lives on the Crossover/ForcedLigation record, never
 * on a strand domain — backend/core/design_geometry.py never reads it). The
 * backend flags this with geometry_unchanged so these wrappers can skip the
 * geometry branch of _syncFromDesignResponse entirely, the same contract
 * overhang_endpoints.test.js already pins for patchOverhang/connectDuplex.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  patchCrossoverExtraBases,
  batchCrossoverExtraBases,
  patchForcedLigationExtraBases,
} from './client.js'
import { store } from '../state/store.js'

function mockGeometryUnchangedFetch(calls) {
  global.fetch = vi.fn(async (url) => {
    calls.push(url)
    return {
      ok: true,
      status: 200,
      headers: { get: () => null },
      json: async () => ({
        design: { id: 'after', helices: [], strands: [], crossovers: [], forced_ligations: [] },
        validation: { loop_strand_ids: [] },
        geometry_unchanged: true,
      }),
    }
  })
}

describe('extra-bases routes keep geometry untouched on the wire', () => {
  beforeEach(() => {
    store.setState({
      currentDesign: { id: 'before', helices: [], strands: [], crossovers: [], forced_ligations: [] },
      currentGeometry: [{ helix_id: 'h1', bp_index: 0 }],
      currentHelixAxes: { h1: { start: [0, 0, 0], end: [0, 0, 1] } },
    })
  })

  it('patchCrossoverExtraBases leaves currentGeometry/currentHelixAxes untouched', async () => {
    const geometry = store.getState().currentGeometry
    const axes = store.getState().currentHelixAxes
    const calls = []
    mockGeometryUnchangedFetch(calls)

    await patchCrossoverExtraBases('xo1', 'TT')

    expect(calls).toEqual(['/api/design/crossovers/xo1/extra-bases'])
    expect(store.getState().currentDesign.id).toBe('after')
    expect(store.getState().currentGeometry).toBe(geometry)
    expect(store.getState().currentHelixAxes).toBe(axes)
  })

  it('batchCrossoverExtraBases leaves currentGeometry/currentHelixAxes untouched', async () => {
    const geometry = store.getState().currentGeometry
    const axes = store.getState().currentHelixAxes
    const calls = []
    mockGeometryUnchangedFetch(calls)

    await batchCrossoverExtraBases([{ crossover_id: 'xo1', sequence: 'AA' }])

    expect(calls).toEqual(['/api/design/crossovers/extra-bases/batch'])
    expect(store.getState().currentGeometry).toBe(geometry)
    expect(store.getState().currentHelixAxes).toBe(axes)
  })

  it('patchForcedLigationExtraBases leaves currentGeometry/currentHelixAxes untouched', async () => {
    const geometry = store.getState().currentGeometry
    const axes = store.getState().currentHelixAxes
    const calls = []
    mockGeometryUnchangedFetch(calls)

    await patchForcedLigationExtraBases('fl1', 'GG')

    expect(calls).toEqual(['/api/design/forced-ligations/fl1/extra-bases'])
    expect(store.getState().currentGeometry).toBe(geometry)
    expect(store.getState().currentHelixAxes).toBe(axes)
  })
})
