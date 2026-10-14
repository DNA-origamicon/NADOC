import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { recordAssemblyResponse, confirmedAssemblyRepresentations } from './assembly_response_authority.js'
import { _syncFromAssemblyResponse, resetRevisionWatermark } from './client.js'
import { store } from '../state/store.js'

beforeEach(() => { resetRevisionWatermark(); localStorage.clear() })
afterEach(() => { store.setState({ currentAssembly: null }); localStorage.clear() })

describe('accepted assembly response authority', () => {
  it('retains confirmed values without lending authority to local clones or mutable Maps', () => {
    const assembly = { id: 'assembly', instances: [{ id: 'a', representation: 'full' }] }
    recordAssemblyResponse(assembly)
    assembly.instances[0].representation = 'beads'
    const confirmed = confirmedAssemblyRepresentations(assembly)
    expect(confirmed.get('a')).toBe('full')
    confirmed.set('a', 'cylinders')
    expect(confirmedAssemblyRepresentations(assembly).get('a')).toBe('full')
    expect(confirmedAssemblyRepresentations({ ...assembly })).toBeNull()
    expect(confirmedAssemblyRepresentations(null)).toBeNull()
  })

  it('records authority before publishing an accepted v2 response, while rejected revisions remain unmarked', () => {
    const observations = []
    const unsubscribe = store.subscribeSlice('assembly', state => {
      observations.push(confirmedAssemblyRepresentations(state.currentAssembly))
    })
    try {
      const response = { revision: 10, assembly: { id: 'assembly', format_version: 2,
        sources: { 'f:/part.nadoc:1:': { type: 'file', path: 'part.nadoc' } },
        instances_v2: [{ id: 'a', src_key: 'f:/part.nadoc:1:', representation: 'full',
          t12: [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0] }],
      } }
      _syncFromAssemblyResponse(response)
      expect(observations).toHaveLength(1)
      expect(observations[0].get('a')).toBe('full')
      expect(confirmedAssemblyRepresentations(response).get('a')).toBe('full')
      const accepted = store.getState().currentAssembly
      expect(accepted.instances[0].geometrySourceKey).toBe('f:/part.nadoc:1:')
      const stale = { id: 'assembly', instances: [{ id: 'a', representation: 'cylinders' }] }
      _syncFromAssemblyResponse({ revision: 9, assembly: stale })
      expect(store.getState().currentAssembly).toBe(accepted)
      expect(observations).toHaveLength(1)
      expect(confirmedAssemblyRepresentations(stale)).toBeNull()
    } finally { unsubscribe() }
  })
})
