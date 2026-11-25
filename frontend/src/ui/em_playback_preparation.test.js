import {expect,it,vi} from 'vitest'
import {createEMPlaybackPreparation} from './em_playback_preparation.js'
it('waits for both calculated endpoints and their downloads',async()=>{
 vi.useFakeTimers()
 try {
  let release
  const batch={byIndex:new Map([[0,{}],[1,{}]]),ready:[0],complete:false,
   cache:{ensure:vi.fn(()=>new Promise(r=>{release=r}))}}
  const prepare=createEMPlaybackPreparation({batch,live:()=>true})
  let settled=false;const pending=prepare([0,1]).then(ok=>{settled=true;return ok})
  await vi.advanceTimersByTimeAsync(200);expect(batch.cache.ensure).not.toHaveBeenCalled()
  batch.ready.push(1);await vi.advanceTimersByTimeAsync(100)
  expect(settled).toBe(false);release(true);expect(await pending).toBe(true)
 } finally {vi.useRealTimers()}
})
it('cancels waiting preparation and rejects missing or failed frames',async()=>{
 vi.useFakeTimers()
 try {
  let live=true
  const batch={byIndex:new Map([[0,{}]]),ready:[],complete:false,cache:{ensure:vi.fn()}}
  const prepare=createEMPlaybackPreparation({batch,live:()=>live})
  expect(await prepare([1])).toBe(false)
  const pending=prepare([0]);live=false;await vi.advanceTimersByTimeAsync(100)
  expect(await pending).toBe(false)
  live=true;batch.complete=true;expect(await prepare([0])).toBe(false)
  expect(batch.cache.ensure).not.toHaveBeenCalled()
 } finally {vi.useRealTimers()}
})
