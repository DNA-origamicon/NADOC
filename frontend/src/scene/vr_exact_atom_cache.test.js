import {it, expect, vi} from 'vitest'
import {createVRExactAtomCache} from './vr_exact_atom_cache.js'
it('prepares exact sparse frames once and keeps their precision across repeats', async () => {
  const fetchFrames=vi.fn(async indices=>Object.fromEntries(indices.map(i=>[i,{dense:new Float64Array([i+1/3,2,3]),serialMap:new Uint32Array([4]),length:15,byteLength:24}])))
  const cache=createVRExactAtomCache({context:()=> 'job:epoch:stride',fetchFrames})
  const payload={frames:Array(200).fill(0),frame_start:2,frame_step:5}
  expect(await cache.prepare(payload)).toBeGreaterThan(200)
  expect(fetchFrames).toHaveBeenCalledTimes(25)
  for(let repeat=0;repeat<2;repeat++)for(let i=0;i<200;i++)expect((await cache.get([2+5*i]))[2+5*i].dense[0]).toBe(2+5*i+1/3)
  expect(fetchFrames).toHaveBeenCalledTimes(25)
})
it('evicts by actual retained bytes, releases shared backing storage, and invalidates job identity', async()=>{
 let key='a'; const backing=new Float64Array(1000)
 const fetchFrames=vi.fn(async indices=>Object.fromEntries(indices.map(i=>[i,backing.subarray(i,i+3)])))
 const cache=createVRExactAtomCache({context:()=>key,fetchFrames,budgetBytes:48})
 expect((await cache.get([0]))[0].buffer.byteLength).toBe(24)
 await cache.get([1]);await cache.get([2]);await cache.get([0]);expect(fetchFrames).toHaveBeenCalledTimes(4)
 key='b';await cache.get([0]);expect(fetchFrames).toHaveBeenCalledTimes(5)
})
it('rejects missing frames and discards cancellation while a request is in flight',async()=>{
 let key='a',release
 const fetchFrames=vi.fn(()=>new Promise(r=>{release=r}))
 const cache=createVRExactAtomCache({context:()=>key,fetchFrames})
 const pending=cache.get([2]);await vi.waitFor(()=>expect(release).toBeTypeOf('function'))
 key='b';release({2:new Float64Array([1,2,3])});expect(await pending).toBeNull()
 fetchFrames.mockResolvedValue({});await expect(cache.get([2])).rejects.toThrow('Missing exact')
})
it('does not continue old-page preparation after cancellation',async()=>{
 let key='a',release
 const fetchFrames=vi.fn(()=>new Promise(r=>{release=r}))
 const cache=createVRExactAtomCache({context:()=>key,fetchFrames})
 const pending=cache.prepare({frames:Array(16).fill(0),frame_start:0,frame_step:1})
 await vi.waitFor(()=>expect(release).toBeTypeOf('function'))
 key='b';release(Object.fromEntries(Array.from({length:8},(_,i)=>[i,new Float64Array([i,2,3])])));
 expect(await pending).toBe(0);expect(fetchFrames).toHaveBeenCalledOnce()
})
