import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  connectDuplex,
  createConnectionVersion,
  generateOverhangRandomSequence,
  patchOverhang,
} from './overhang_endpoints.js'
import { store } from '../state/store.js'

describe('overhang sequence endpoints', () => {
  beforeEach(() => {
    store.setState({
      currentDesign: { id: 'before', helices: [], strands: [], overhangs: [] },
      currentGeometry: [{ helix_id: 'h1', bp_index: 0 }],
      currentHelixAxes: { h1: { start: [0, 0, 0], end: [0, 0, 1] } },
    })
  })

  it('does not recompute geometry after generating a same-length sequence', async () => {
    const geometry = store.getState().currentGeometry
    const axes = store.getState().currentHelixAxes
    const calls = []
    global.fetch = vi.fn(async (url) => {
      calls.push(url)
      return {
        ok: true,
        status: 200,
        headers: { get: () => null },
        json: async () => ({
          design: { id: 'after', helices: [], strands: [], overhangs: [{ id: 'oh1', sequence: 'ACGT' }] },
          validation: { loop_strand_ids: [] },
        }),
      }
    })

    await generateOverhangRandomSequence('oh1')

    expect(calls).toEqual(['/api/design/overhang/oh1/generate-random'])
    expect(store.getState().currentDesign.id).toBe('after')
    expect(store.getState().currentGeometry).toBe(geometry)
    expect(store.getState().currentHelixAxes).toBe(axes)
  })

  it('keeps Connect intermediate mutations geometry-free', async () => {
    const calls = []
    global.fetch = vi.fn(async (url) => {
      calls.push(url)
      return {
        ok: true,
        status: 200,
        headers: { get: () => null },
        json: async () => ({
          design: { id: 'after', helices: [], strands: [], overhangs: [] },
          validation: { loop_strand_ids: [] },
        }),
      }
    })

    await patchOverhang('oh1', { sequence: 'ACGT', deferReassign: true })
    await createConnectionVersion({ overhang_a_id: 'oh1', overhang_b_id: 'oh2' })
    await connectDuplex({ overhang_a_id: 'oh1', overhang_b_id: 'oh2' }, { skipGeometry: true })

    expect(calls).toEqual([
      '/api/design/overhang/oh1',
      '/api/design/connection-versions',
      '/api/design/duplexes/connect',
    ])
    expect(calls.some(url => url.includes('/design/geometry'))).toBe(false)
  })

  it('does not fetch or replace geometry for a label-only edit', async () => {
    const geometry = store.getState().currentGeometry
    const axes = store.getState().currentHelixAxes
    const calls = []
    global.fetch = vi.fn(async (url) => {
      calls.push(url)
      return {
        ok: true,
        status: 200,
        headers: { get: () => null },
        json: async () => ({
          design: { id: 'after', helices: [], strands: [], overhangs: [{ id: 'oh1', label: 'Handle' }] },
          validation: { loop_strand_ids: [] },
          geometry_unchanged: true,
        }),
      }
    })

    await patchOverhang('oh1', { label: 'Handle' })

    expect(calls).toEqual(['/api/design/overhang/oh1'])
    expect(store.getState().currentGeometry).toBe(geometry)
    expect(store.getState().currentHelixAxes).toBe(axes)
  })
})
