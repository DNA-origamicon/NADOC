import {expect,it,vi} from 'vitest'
import {createEMFrameCache} from './em_frame_cache.js'
it('prefetches ahead once and revisits frames without requests',async()=>{
 const load=vi.fn(async index=>({intensity:[index]})), prepare=vi.fn()
 const cache=createEMFrameCache({load,prepare})
 await cache.prefetch([10,12,14],12)
 expect(load.mock.calls.map(c=>c[0])).toEqual([12,14,10])
 expect(Array.from(cache.get(10).intensity)).toEqual([10])
 await cache.prefetch([10,12,14],14)
 expect(load).toHaveBeenCalledTimes(3); expect(prepare).toHaveBeenCalledTimes(3)
 cache.dispose(); expect(cache.get(10)).toBeNull()
})
it('bounds look-ahead memory and cancels in-flight downloads on disposal',async()=>{
 const load=vi.fn(async index=>({intensity:[index]}))
 const cache=createEMFrameCache({load,budget:8300})
 await cache.prefetch([1,2,3],1)
 expect(cache.get(1)).not.toBeNull(); expect(cache.get(2)).not.toBeNull(); expect(cache.get(3)).toBeNull()
 const count=load.mock.calls.length
 await cache.prefetch([1,2,3],1)
 expect(load).toHaveBeenCalledTimes(count)
 cache.dispose(); expect(cache.get(1)).toBeNull()
})
it('never installs a late result after disposal',async()=>{
 let resolve
 const cache=createEMFrameCache({load:()=>new Promise(r=>{resolve=r})})
 const pending=cache.prefetch([1],1)
 cache.dispose(); resolve({intensity:[1]}); await pending
 expect(cache.get(1)).toBeNull()
})
it('serves a scrubbed frame while an obsolete look-ahead request is stalled', async()=>{
 let release
 const load=vi.fn(async index=> index===1 ? new Promise(r=>{release=r}) : {intensity:[index]})
 const cache=createEMFrameCache({load})
 const warm=cache.prefetch([0,1,2,3,4],0)
 await vi.waitFor(()=>expect(release).toBeTypeOf('function'))
 cache.demand([0,1,2,3,4],4)
 await vi.waitFor(()=>expect(cache.get(4) && Array.from(cache.get(4).intensity)).toEqual([4]))
 release({intensity:[1]}); await warm
 expect(load.mock.calls.map(c=>c[0])).toEqual([0,1,4])
 cache.dispose()
})
it('coalesces demand and prefetch and protects the current frame from eviction',async()=>{
 let release
 const load=vi.fn(index=>index===0 ? new Promise(r=>{release=()=>r({intensity:[index]})}) : Promise.resolve({intensity:[index]}))
 const cache=createEMFrameCache({load,budget:4130})
 cache.demand([0,1],0)
 const warm=cache.prefetch([0,1],0)
 expect(load).toHaveBeenCalledTimes(1)
 release(); await warm
 expect(cache.get(0)).not.toBeNull()
 cache.dispose()
})
it('a seek bypasses even the in-flight demand shared with prefetch',async()=>{
 let release
 const load=vi.fn(async index=>index===0 ? new Promise(r=>{release=r}) : {intensity:[index]})
 const cache=createEMFrameCache({load})
 cache.demand([0,1],0)
 const warm=cache.prefetch([0,1],0)
 cache.demand([0,1],1)
 await vi.waitFor(()=>expect(cache.get(1) && Array.from(cache.get(1).intensity)).toEqual([1]))
 expect(load.mock.calls[0][2].aborted).toBe(true)
 release({intensity:[0]}); await warm
 expect(cache.get(0)).toBeNull()
 cache.dispose()
})
it('finishes downloads during playback faster than network latency', async()=>{
 vi.useFakeTimers()
 try {
  const load=vi.fn((index,ordinal,signal)=>new Promise(resolve=>setTimeout(()=>resolve({intensity:[index]}),150)))
  const cache=createEMFrameCache({load})
  const ready=[0,1,2,3,4,5,6,7]
  cache.demand(ready,0,{playing:true})
  const warm=cache.prefetch(ready,0)
  for(let i=1;i<6;i++) {
   await vi.advanceTimersByTimeAsync(100)
   cache.demand(ready,i,{playing:true})
  }
  await vi.advanceTimersByTimeAsync(1500); await warm
  expect(load.mock.calls.every(call=>!call[2].aborted)).toBe(true)
  for(const i of ready) expect(cache.get(i) && Array.from(cache.get(i).intensity)).toEqual([i])
  cache.dispose()
 } finally {vi.useRealTimers()}
})
it('keeps both transition fields while preparing the following endpoint under memory pressure',async()=>{
 const cache=createEMFrameCache({budget:4130,load:async i=>({intensity:[i]})})
 cache.protect([0,1])
 expect(await cache.ensure([0,1,2],[0,1])).toBe(true)
 expect(await cache.ensure([0,1,2],[1,2])).toBe(true)
 for(const i of [0,1,2])expect(cache.get(i)).not.toBeNull()
 cache.protect([2]);await cache.ensure([0,1,2,3],[3])
 expect(cache.get(0)).toBeNull();expect(cache.get(2)).not.toBeNull()
 cache.dispose()
})
it('promotes a pending background read to a required endpoint despite its original allowance',async()=>{
 let release
 const cache=createEMFrameCache({budget:4130,load:async i=>i===1?new Promise(r=>{release=r}):{intensity:[i]}})
 const warm=cache.prefetch([0,1],0)
 await vi.waitFor(()=>expect(release).toBeTypeOf('function'))
 const required=cache.ensure([0,1],[1])
 release({intensity:[1]})
 expect(await required).toBe(true);await warm
 expect(cache.get(1)).not.toBeNull();cache.dispose()
})
