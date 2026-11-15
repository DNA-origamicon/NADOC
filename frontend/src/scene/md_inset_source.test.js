import { it, expect, vi } from 'vitest'
import { insetAtomSubset, initMdInsetSource } from './md_inset_source.js'
import { createMdInsetAtomHub } from './md_inset_atoms.js'
const model = { atoms: [
  { serial: 7, helix_id: 'h', bp_index: 1, direction: 'FORWARD', name: 'P', element:'P' },
  { serial: 9, helix_id: 'h', bp_index: 1, direction: 'FORWARD', name: 'O1P', element:'O' },
  { serial: 10, helix_id: 'h', bp_index: 2, direction: 'FORWARD', name:'P', element:'P' },
], bonds:[[7,9],[9,10]] }
const frame = x => ({serialMap:[7,9,10],dense:[x,2,3,x+.16,2.01,3.02,9,9,9]})
const keys = ['h:1:FORWARD']
it('selects original serials, exact deformed atom positions and only surviving PSF bonds', () => {
  const r = insetAtomSubset(model, frame(5), keys)
  expect(r.atoms.map(a=>[a.serial,a.x,a.y,a.z])).toEqual([[7,5,2,3],[9,5.16,2.01,3.02]])
  expect(r.bonds).toEqual([[7,9]])
})
it('publishes exact preliminary and final means without any main atom renderer', async () => {
  const hub=createMdInsetAtomHub(); hub.setResidues('inset',keys)
  const api={getOxdnaRmsfAtomistic:vi.fn(async()=>({model,atomistic:frame(8)}))}
  const source=initMdInsetSource({api,hub})
  await source.flex('job',{preliminary:true},{atomistic_model:model,atomistic_average:{atomistic:frame(5)}},null)
  expect(hub.atoms().get('h:1:FORWARD:OP1')).toEqual([5.16,2.01,3.02])
  await source.flex('job',{},null,{start:10,end:20,interval:1})
  expect(api.getOxdnaRmsfAtomistic).toHaveBeenCalledWith('job',expect.objectContaining({frameRange:{start:10,end:20,interval:1}}))
  expect(hub.atoms().get('h:1:FORWARD:P')).toEqual([8,2,3])
  source.clear(); expect(hub.exact()).toBe(false)
})
it('interpolates actual atom endpoints in Full playback', async () => {
  const hub=createMdInsetAtomHub(); hub.setResidues('inset',keys)
  const api={getOxdnaAtomisticModel:async()=>model,getOxdnaFramesAtomistic:vi.fn(async(job,ids)=>Object.fromEntries(ids.map(i=>[i,frame(i)])))}
  const source=initMdInsetSource({api,hub})
  await source.frame('job',0,20); await source.prepare('job',[0,1],20)
  source.interpolate('job',0,1,.25,null,null,20)
  expect(hub.atoms().get('h:1:FORWARD:P')).toEqual([.25,2,3])
  expect(hub.atoms().get('h:1:FORWARD:OP1')[0]).toBeCloseTo(.41)
  expect(api.getOxdnaFramesAtomistic).toHaveBeenCalledWith('job',[1],true,'job',20)
})
it('discards a late frame after stop', async()=>{
  const hub=createMdInsetAtomHub(); hub.setResidues('inset',keys)
  let release
  const api={getOxdnaAtomisticModel:async()=>model,getOxdnaFramesAtomistic:()=>new Promise(r=>{release=r})}
  const source=initMdInsetSource({api,hub}), pending=source.frame('job',0,1)
  await Promise.resolve()
  expect(hub.exact()).toBe(true); expect(hub.atoms()).toBeNull()
  source.clear(); release({0:frame(10)}); await pending
  expect(hub.atoms()).toBeNull(); expect(hub.exact()).toBe(false)
})
it('aborts an old flex mean when replacing its selected range',async()=>{
 const hub=createMdInsetAtomHub();hub.setResidues('inset',keys)
 let signal
 const api={getOxdnaRmsfAtomistic:(_,opts)=>new Promise((resolve,reject)=>{
  signal=opts.signal;signal.addEventListener('abort',()=>reject(new DOMException('Aborted','AbortError')))
 })}
 const source=initMdInsetSource({api,hub})
 const pending=source.flex('job',{},null,{start:1,end:10,interval:1})
 const next=source.flex('job',{preliminary:true},{atomistic_model:model,atomistic_average:{atomistic:frame(5)}},{start:20,end:30,interval:1})
 expect(signal.aborted).toBe(true)
 await pending;await next;await Promise.resolve()
 expect(hub.atoms().get('h:1:FORWARD:P')).toEqual([5,2,3])
 source.clear()
})
