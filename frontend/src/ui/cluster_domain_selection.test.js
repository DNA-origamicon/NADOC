// @vitest-environment jsdom
import { describe, it, expect, vi } from 'vitest'
import { clusterDomainIdsFromSelection, initClusterPanel } from './cluster_panel.js'
import { createMockStore } from '../test-helpers/mock_store.js'

const design = {
  strands: [{ id: 's', domains: [{ helix_id: 'h0' }, { helix_id: 'h1' }] }],
  extensions: [{ strand_id: 's', end: 'three_prime' }, { strand_id: 's', end: 'five_prime' }],
  cluster_transforms: [],
}
const domain = i => ({ kind: 'domain', strandId: 's', domainIndex: i })

describe('cluster creation from domain selection', () => {
  it('resolves extension geometry indices to their terminal domains and deduplicates', () => {
    expect(clusterDomainIdsFromSelection([domain(0), domain(-1), domain(2), domain(1)], design))
      .toEqual([{ strand_id: 's', domain_index: 0 }, { strand_id: 's', domain_index: 1 }])
  })
  it('preserves exact domains and includes strands in mixed selections', () => {
    expect(clusterDomainIdsFromSelection([domain(1)], design)).toEqual([{ strand_id: 's', domain_index: 1 }])
    expect(clusterDomainIdsFromSelection([domain(1), { kind: 'strand', id: 's' }], design)).toHaveLength(2)
  })
  it('rejects stale references instead of silently creating a partial cluster', () => {
    expect(() => clusterDomainIdsFromSelection([domain(3)], design)).toThrow('no longer exists')
    expect(() => clusterDomainIdsFromSelection([domain(2)], { ...design, extensions: [] })).toThrow('no longer exists')
  })
  it('the sidebar sends only real domain refs when selection includes a 3-prime tail', async () => {
    document.body.innerHTML = '<div id="cluster-list"></div><button id="cluster-new-btn"></button><div id="cluster-panel-heading"></div><div id="cluster-panel-body"></div>'
    const store = createMockStore({ currentDesign: design, selection: { items: [domain(0), domain(2)] } })
    const api = { createCluster: vi.fn().mockResolvedValue({}) }
    const panel = initClusterPanel(store, { api })
    document.getElementById('cluster-new-btn').click()
    expect(api.createCluster).toHaveBeenCalledWith({ name: 'Cluster 1', helix_ids: ['h0', 'h1'],
      domain_ids: [{ strand_id: 's', domain_index: 0 }, { strand_id: 's', domain_index: 1 }] })
    panel?.destroy?.()
    document.body.innerHTML = ''
  })
})
