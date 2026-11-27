import {it,expect} from 'vitest'
import {createTraceMotion} from './trace_motion.js'

it('paces completed views at 15 Hz without queueing over unfinished GPU work',()=>{
  const motion=createTraceMotion();motion.begin(0)
  expect(motion.due(0)).toBe(true)
  expect(motion.submit(0,1280,720)).toEqual({width:832,height:468})
  expect(motion.due(100)).toBe(false)
  motion.complete(40);expect(motion.due(50)).toBe(false);expect(motion.due(67)).toBe(true)
  motion.submit(67,1280,720);motion.complete(107)
  expect(motion.due(134)).toBe(true)
})
it('reduces resolution under load and recovers it when the device has capacity',()=>{
  const motion=createTraceMotion();motion.begin(0);motion.submit(0,1280,720);motion.complete(120)
  expect(motion.state.nextResolutionScale).toBeLessThan(.65)
  for(let i=1;i<20;i++){motion.submit(i*200,1280,720);motion.complete(i*200+10)}
  expect(motion.state.nextResolutionScale).toBe(1)
  expect(motion.submit(5000,1280,720)).toEqual({width:1280,height:720})
})
