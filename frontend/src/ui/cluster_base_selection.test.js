// @vitest-environment jsdom
import { it, expect, vi } from 'vitest'
import { clusterSelectionInput, assignClusterSelection } from './cluster_base_selection.js'
import { clusterMemberFilter, clusterIdForNucleotide, clusterNucKeys, clusterAlphaForNuc, clusterAlphaKeys } from '../scene/cluster_entries.js'
import { buildClusterColorLookup, buildClusterLookup } from '../scene/helix_renderer/palette.js'
import { createMockStore } from '../test-helpers/mock_store.js'
import { initClusterPanel } from './cluster_panel.js'
const geometry = [0, 1, 2, 3].flatMap(bp_index => ['FORWARD', 'REVERSE'].map(direction => ({
  helix_id: 'h', bp_index, direction, strand_id: direction === 'FORWARD' ? 'scaffold' : 'S72', domain_index: 0,
})))
const design = { id: 'd', helices: [{ id: 'h' }], strands: [], cluster_transforms: [] }
const refs = [{ kind: 'strand', id: 'S72' }, { kind: 'base', key: 'h:1:FORWARD' }]
it('preserves mixed strand and base selection without sweeping the rest of the scaffold', () => {
  const input = clusterSelectionInput(refs, design, geometry)
  expect(input.base_ids).toHaveLength(5)
  expect(input.base_ids.filter(n => n.direction === 'FORWARD').map(n => n.bp_index)).toEqual([1])
  expect(input.helix_ids).toEqual(['h'])
  expect(() => clusterSelectionInput([{ kind: 'base', key: 'h:9:FORWARD' }], design, geometry)).toThrow('unavailable')
})
it('base clusters select, color and fade only exact bases and outrank imported umbrellas', () => {
  const c = { id: 'new', color: '#ff0000', opacity: 0.3, ...clusterSelectionInput([{kind:'base',key:'h:1:FORWARD'}], design, geometry) }
  const d = { ...design, cluster_transforms: [{ id: 'old', helix_ids:['h'], auto_created:true }, c] }
  const selected = geometry.find(n => n.bp_index===1 && n.direction==='FORWARD'), other = geometry[0]
  expect(clusterMemberFilter(c,d)(selected)).toBe(true)
  expect(clusterMemberFilter(c,d)(other)).toBe(false)
  expect(clusterIdForNucleotide(selected,d)).toBe('new')
  expect(clusterIdForNucleotide(other,d)).toBe('old')
  expect(buildClusterLookup(d)(selected)).toBe(1)
  expect(buildClusterLookup(d)(other)).toBe(0)
  expect(buildClusterColorLookup(d)(selected)).toBe(0xff0000)
  expect(clusterNucKeys(c,d)).toEqual(new Set(['b:h:1:FORWARD']))
  expect(clusterAlphaForNuc(clusterAlphaKeys(d),selected)).toBe(0.3)
  expect(clusterAlphaForNuc(clusterAlphaKeys(d),other)).toBe(1)
})
it('sidebar enables and submits base-only selection', () => {
  document.body.innerHTML = '<div id="cluster-list"></div><button id="cluster-new-btn"></button><div id="cluster-panel-heading"></div><div id="cluster-panel-body"></div>'
  const store = createMockStore({ currentDesign: design, currentGeometry:geometry, selection:{items:[{kind:'base',key:'h:1:FORWARD'}]} })
  const api = { createCluster:vi.fn().mockResolvedValue({design}) }
  const panel=initClusterPanel(store,{api})
  const button=document.getElementById('cluster-new-btn')
  expect(button.disabled).toBe(false);button.click()
  expect(api.createCluster).toHaveBeenCalledWith(expect.objectContaining({base_ids:[{helix_id:'h',bp_index:1,direction:'FORWARD',copy_k:0}]}))
  panel.destroy();document.body.innerHTML=''
})
it('assignment failures surface and existing members survive', async () => {
  const d={...design,cluster_transforms:[{id:'c',helix_ids:['h'],base_ids:[{helix_id:'h',bp_index:0,direction:'FORWARD',copy_k:0}]}]}
  const store=createMockStore({currentDesign:d,currentGeometry:geometry,lastError:{message:'refused'}})
  const api={patchCluster:vi.fn().mockResolvedValue(null)}
  await expect(assignClusterSelection({store,api,refs:[{kind:'base',key:'h:1:FORWARD'}],clusterId:'c'})).rejects.toThrow('refused')
  expect(api.patchCluster.mock.calls[0][1].base_ids).toHaveLength(2)
})

it('transferred bases leave the original cluster selection and movement scope', async () => {
  const { clusterTransformSelection } = await import('../scene/cluster_entries.js')
  const old={id:'old',helix_ids:['h']}, next={id:'new',...clusterSelectionInput([{kind:'base',key:'h:1:FORWARD'}],design,geometry)}
  const d={...design,cluster_transforms:[old,next]}
  const selected=geometry.find(n=>n.bp_index===1&&n.direction==='FORWARD')
  expect(clusterMemberFilter(old,d)(selected)).toBe(false)
  expect(clusterTransformSelection(old,d,geometry)).toHaveLength(7)
  expect(clusterTransformSelection(next,d,geometry)).toHaveLength(1)
})
