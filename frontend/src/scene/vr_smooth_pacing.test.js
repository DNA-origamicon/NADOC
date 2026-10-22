import { expect, it } from 'vitest'
import { smoothSampleInterval, presentSmoothTransition } from './vr_smooth_pacing.js'

it('reserves delivery headroom without changing coordinate fractions', async () => {
 let time=0, busyUntil=0
 const shown=[]
 await presentSmoothTransition({
  prepare:async()=>{time+=400}, active:()=>true,
  delivery:()=>({busy:time<busyUntil,milliseconds:80}),
  wait:async ms=>{time+=ms},
  show:fraction=>{shown.push([time,fraction]);busyUntil=time+150},
 })
 expect(shown.map(x=>x[1])).toEqual([1/8,2/8,3/8,4/8,5/8,6/8,7/8])
 expect(shown[0][0]).toBe(500) // Preparation does not consume the presentation interval.
 expect(shown.slice(1).every((x,i)=>x[0]-shown[i][0]>=150)).toBe(true)
 expect(time-shown.at(-1)[0]).toBeGreaterThanOrEqual(150)
})

it('stops while waiting for publication and never draws after cancellation', async()=>{
 let live=true, calls=0
 await presentSmoothTransition({prepare:async()=>true,active:()=>live,
  delivery:()=>({busy:true,milliseconds:0}),wait:async()=>{live=false},
  show:()=>calls++})
 expect(calls).toBe(0)
})

it('keeps a paced final interval and rejects unavailable interpolation',async()=>{
 let time=0
 const shown=[]
 const args={prepare:async()=>true,active:()=>true,delivery:()=>({}),
  wait:async ms=>{time+=ms},show:f=>shown.push([time,f])}
 await presentSmoothTransition(args)
 expect(time).toBe(250)
 expect(shown.at(-1)).toEqual([218.75,7/8])
 shown.length=0
 await presentSmoothTransition({...args,prepare:async()=>false})
 expect(shown).toEqual([])
})

it('bounds invalid delivery observations to the nominal presentation rate',()=>{
 expect(smoothSampleInterval(0)).toBe(31.25)
 expect(smoothSampleInterval(NaN)).toBe(31.25)
 expect(smoothSampleInterval(-1)).toBe(31.25)
 expect(smoothSampleInterval(100)).toBe(125)
})
