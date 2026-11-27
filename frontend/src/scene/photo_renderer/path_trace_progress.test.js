import {it,expect} from 'vitest'
import {traceSampleProgress,traceVideoProgress} from './path_trace_progress.js'
it('counts completed samples across tiles, including partial sample tiles',()=>{
  expect(traceSampleProgress(1,4,32,64)).toMatchObject({fraction:.375,tile:2,samples:32,target:64})
  expect(traceSampleProgress(3,4,65,64).fraction).toBe(1)
  expect(traceSampleProgress(0,1,.5,64).fraction).toBe(.5/64)
})
it('includes tracing within a video frame without mistaking BVH progress for finished pixels',()=>{
  expect(traceVideoProgress(traceSampleProgress(1,4,32,64),2,10)).toMatchObject({done:2.375,total:10})
  expect(traceVideoProgress({stage:'geometry',fraction:.9,label:'Building geometry'},2,10).done).toBe(2)
  expect(traceVideoProgress({stage:'denoise',fraction:.5,label:'Denoising tile 1/2'},2,10).done).toBe(2.5)
  expect(traceVideoProgress({stage:'composite',fraction:1,label:'Compositing'},2,10).done).toBe(3)
  expect(traceVideoProgress({stage:'complete',fraction:1,label:'Done'},2,10).done).toBe(3)
})
