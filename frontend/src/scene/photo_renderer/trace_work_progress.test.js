import {it,expect} from 'vitest'
import {createTraceWorkProgress} from './trace_work_progress.js'
it('counts half of a ten-percent subprocess as five percent, without time guesses',()=>{
  const work=createTraceWorkProgress('optix',8)
  work.event({stage:'device',fraction:1})
  work.event({stage:'snapshot',fraction:.5})
  expect(work.get().fraction).toBeCloseTo(.1) // 5% startup + 5% of snapshot
  work.event({stage:'snapshot',fraction:null,label:'Waiting on a native operation'})
  expect(work.get()).toMatchObject({fraction:.1,indeterminate:true})
  work.event({stage:'snapshot',fraction:.2})
  expect(work.get().fraction).toBeCloseTo(.1)
})
it('counts the quick pass separately and requires delivery and display before 100%',()=>{
  const work=createTraceWorkProgress('optix',8)
  work.event({stage:'quick-tracing',fraction:.5})
  const halfway=work.get().fraction
  work.event({stage:'quick-delivery',fraction:1})
  expect(work.get().fraction).toBeGreaterThan(halfway)
  expect(work.get().complete).toBe(false)
  const before=work.get().fraction
  work.event({stage:'acceleration',fraction:null})
  expect(work.get().fraction).toBe(before)
  work.event({stage:'tracing',fraction:1})
  expect(work.get().fraction).toBeLessThan(1)
  work.event({stage:'delivery',fraction:1})
  expect(work.get().fraction).toBe(.9)
  work.event({stage:'display',fraction:1})
  expect(work.get()).toMatchObject({fraction:1,complete:true})
})
it('excludes prewarmed stages from remaining work and ignores stale earlier poll responses',()=>{
  const work=createTraceWorkProgress('optix',1)
  work.event({reused:['device','snapshot','environment','upload','decode','geometry']})
  expect(work.get().fraction).toBe(0)
  expect(work.get().stages[0]).toMatchObject({state:'reused',share:0})
  work.event({stage:'tracing',fraction:.5})
  expect(work.get().fraction).toBeCloseTo((5+12.5)/50)
  work.event({stage:'geometry',fraction:.1})
  expect(work.get().fraction).toBeCloseTo(.35)
})
it('tracks WebGL acceleration, compile and fractional completed tile samples',()=>{
  const work=createTraceWorkProgress('webgl',8)
  work.event({stage:'geometry',fraction:.5})
  expect(work.get().fraction).toBe(.25)
  work.event({stage:'compile',fraction:null})
  expect(work.get()).toMatchObject({fraction:.45,indeterminate:true})
  work.event({stage:'tracing',fraction:.25})
  expect(work.get().fraction).toBeCloseTo(.6125)
})
