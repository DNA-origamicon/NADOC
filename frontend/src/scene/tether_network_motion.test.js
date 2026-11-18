import { it, expect, vi } from 'vitest'
import { Object3D, Vector3, Quaternion } from 'three'
import { buildTetherNetwork, createCompliantTetherMotion } from './tether_network_motion.js'

function fixture() {
  const clusters = ['root','arm','link'].map(id => ({ id,helix_ids:[id],pivot:[0,0,0],translation:[0,0,0],rotation:[0,0,0,1] }))
  const x = { root:0,arm:6,link:3 }, counts = {root:8,arm:6,link:2}
  const geometry = clusters.flatMap(c => Array.from({length:counts[c.id]},(_,bp_index) => ({helix_id:c.id,bp_index,
    direction:'FORWARD',helical_site:{axis_point:[x[c.id],0,bp_index*.1]}})))
  const anchor = id => ({strand_id:id,domain_index:0,bp_index:0,direction:'FORWARD'})
  const connections = [['root','link'],['link','arm']].map(([a,b]) => ({cluster_a_id:a,cluster_b_id:b,
    anchor_a:anchor(a),anchor_b:anchor(b),contour_length_nm:3}))
  return { design:{cluster_transforms:clusters,strands:clusters.map(c=>({id:c.id,domains:[{helix_id:c.id}]}))}, geometry,driver:'arm',pending:[],
    network:{connections,gates:Object.fromEntries(clusters.map(c=>[c.id,{gate:true}]))},
    resolve:key=>new Vector3(x[key.split(':')[0]],0,0) }
}
it('pins the largest component body and rejects an unmodelled rigid connection', () => {
  const f=fixture()
  expect(buildTetherNetwork(f).fixed).toBe('root')
  f.network.gates.link.gate=false
  expect(buildTetherNetwork(f)).toBeNull()
})
it('refuses missing anchors rather than dropping their constraints', () => {
  expect(buildTetherNetwork({...fixture(),resolve:()=>null})).toBeNull()
})
it('captures and queues follower transforms through the existing preview transaction', () => {
  const f=fixture(), dummy=new Object3D(), capture=vi.fn(),paint=vi.fn(),record=vi.fn()
  const s={type:'ssdna',clusterId:'arm',dummy,startPos:new Vector3(),startQuat:new Quaternion(),
    incrQuat:new Quaternion(),network:f.network,resolve:f.resolve,constraints:[{}]}
  const motion=createCompliantTetherMotion({store:{getState:()=>({currentDesign:f.design,currentGeometry:f.geometry})},
    read:()=>s,pending:()=>[],capture,paint,record})
  expect(motion.arm()).toBe(true)
  expect(capture).toHaveBeenCalledTimes(1)
  expect(capture.mock.calls[0][0]).toEqual(['link'])
  expect(capture.mock.calls[0][2]).toBe(true)
  dummy.position.y=1
  expect(motion.solve()).toBe(true)
  expect(paint).toHaveBeenCalledTimes(1)
  expect(record.mock.calls[0][0]).toBe('link')
  expect(record.mock.calls[0][1].translation[1]).toBeGreaterThan(0)
  s.type='free'
  expect(motion.arm()).toBe(false)
  expect(motion.solve()).toBe(false)
})
it('does not invoke the live resolver with an unresolvable anchor key', () => {
  const f=fixture(), resolve=vi.fn()
  f.design.strands=[]
  expect(buildTetherNetwork({...f,resolve})).toBeNull()
  expect(resolve).not.toHaveBeenCalled()
})
