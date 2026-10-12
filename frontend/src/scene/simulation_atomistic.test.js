import { it, expect, vi } from 'vitest'
import { createSimulationAtomistic } from './simulation_atomistic.js'
it('serializes reconstructions, discards superseded frames and ignores a late result after native restoration', async () => {
  const releases=[], requests=[]
  const renderer={update:vi.fn(),applyScalarColors:vi.fn()}
  const model={atoms:[{x:9,y:8,z:7}],bonds:[]}
  const view=createSimulationAtomistic({renderer,getDesign:()=>({id:'job-snapshot'}),setCGVisible:vi.fn(),
    request:(_url,init)=>{requests.push(JSON.parse(init.body));return new Promise(resolve=>releases.push(()=>resolve({ok:true,json:async()=>model})))}})
  const a=view.apply([{backbone_position:[1,2,3]}],null)
  await Promise.resolve()
  const b=view.apply([{backbone_position:[4,5,6]}],null)
  const c=view.apply([{backbone_position:[7,8,9]}],null)
  expect(b).toBe(a);expect(c).toBe(a)
  expect(requests).toHaveLength(1)
  releases.shift()();await vi.waitFor(() => expect(requests).toHaveLength(2))
  expect(requests).toHaveLength(2)
  expect(requests[1].positions[0].backbone_position).toEqual([7,8,9])
  expect(renderer.update).not.toHaveBeenCalled()
  view.cancel();releases.shift()();await c
  expect(renderer.update).not.toHaveBeenCalled()
})
it('coalesces duplicate requests during reconstruction and applies the newest colours', async () => {
  let release
  const request=vi.fn(() => new Promise(resolve => {release=()=>resolve({ok:true,json:async()=>({atoms:[{}]})})}))
  const renderer={update:vi.fn(),applyScalarColors:vi.fn()}
  const view=createSimulationAtomistic({renderer,getDesign:()=>({id:'job'}),setCGVisible:vi.fn(),request})
  const positions=[{backbone_position:[1,2,3]}]
  const first=view.apply(positions,{h:1});await Promise.resolve()
  const second=view.apply(positions,{h:2});release();await second;await first
  expect(request).toHaveBeenCalledTimes(1)
  expect(renderer.update).toHaveBeenCalledTimes(1)
  expect(renderer.applyScalarColors).toHaveBeenLastCalledWith({h:2})
})
it('shares one model across atomic styles while retaining scalar colours', async () => {
  const renderer={update:vi.fn(),applyScalarColors:vi.fn()},request=vi.fn(async()=>({ok:true,json:async()=>({atoms:[{}]})}))
  const view=createSimulationAtomistic({renderer,getDesign:()=>({id:'snapshot'}),setCGVisible:vi.fn(),request})
  await view.apply([{backbone_position:[1,2,3]}],{h:0xff0000})
  await view.apply([{backbone_position:[1,2,3]}],{h:0x00ff00})
  expect(request).toHaveBeenCalledTimes(1)
  expect(renderer.applyScalarColors).toHaveBeenLastCalledWith({h:0x00ff00})
})
