import {it,expect,vi} from 'vitest'
import {createTraceSchedule} from './path_trace_schedule.js'
it('uses GPU timing to advance multiple tiles without queuing over an unfinished batch',()=>{
  let complete=false
  const gl={TIMEOUT_EXPIRED:1,WAIT_FAILED:2,QUERY_RESULT_AVAILABLE:3,QUERY_RESULT:4,
    getExtension:()=>({TIME_ELAPSED_EXT:5,GPU_DISJOINT_EXT:6}),getParameter:()=>false,
    createQuery:()=>({}),beginQuery:vi.fn(),endQuery:vi.fn(),deleteQuery:vi.fn(),
    getQueryParameter:(_,p)=>p===3?true:1000000,
    fenceSync:()=>({}),flush:vi.fn(),deleteSync:vi.fn(),clientWaitSync:()=>complete?0:1}
  const s=createTraceSchedule({getContext:()=>gl},{budgetMs:4}),e={samples:0,step(){this.samples+=1/16}}
  expect(s.run(e,4)).toBe(2)
  expect(s.run(e,4)).toBe(0)
  complete=true
  expect(s.ready()).toBe(true);expect(s.ready()).toBe(true)
  expect(s.run(e,4)).toBe(8)
  expect(s.gpuMs).toBe(1)
  s.dispose();expect(gl.deleteSync).toHaveBeenCalledTimes(2)
})
it('caps the fallback and stops exactly at the target',()=>{
  const s=createTraceSchedule({}),e={samples:0,step(){this.samples++}}
  expect(s.run(e,3)).toBe(2);expect(s.run(e,3)).toBe(1);expect(s.run(e,3)).toBe(0)
  s.dispose()
})

function delayedTimers(){
  let available=false,disjoint=false,complete=true
  const gl={TIMEOUT_EXPIRED:1,WAIT_FAILED:2,QUERY_RESULT_AVAILABLE:3,QUERY_RESULT:4,
    getExtension:()=>({TIME_ELAPSED_EXT:5,GPU_DISJOINT_EXT:6}),getParameter:()=>disjoint,
    createQuery:vi.fn(()=>({})),beginQuery:vi.fn(),endQuery:vi.fn(),deleteQuery:vi.fn(),
    getQueryParameter:(_,p)=>p===3?available:1000000,
    fenceSync:()=>({}),flush:vi.fn(),deleteSync:vi.fn(),clientWaitSync:()=>complete?0:1}
  return {gl,setAvailable:v=>available=v,setDisjoint:v=>disjoint=v,setComplete:v=>complete=v}
}
it('continues after GPU completion without waiting for delayed timer results, with bounded timer storage',()=>{
  const d=delayedTimers(),s=createTraceSchedule({getContext:()=>d.gl},{budgetMs:4}),e={samples:0,step(){this.samples+=1/16}}
  for(let i=0;i<10;i++){
    expect(s.run(e,8)).toBe(2)
    expect(s.ready()).toBe(true)
  }
  expect(d.gl.createQuery.mock.calls.length).toBeLessThanOrEqual(4)
  d.setAvailable(true)
  expect(s.run(e,8)).toBe(8)
  d.setComplete(false);expect(s.run(e,8)).toBe(0)
  s.dispose();expect(d.gl.deleteQuery.mock.calls.length).toBe(d.gl.createQuery.mock.calls.length)
})
it('discards disjoint timing estimates and falls back to small batches',()=>{
  const d=delayedTimers(),s=createTraceSchedule({getContext:()=>d.gl}),e={samples:0,step(){this.samples+=1/16}}
  s.run(e,8);d.setAvailable(true);expect(s.run(e,8)).toBeGreaterThan(2)
  d.setDisjoint(true);expect(s.run(e,8)).toBe(2)
  expect(s.gpuMs).toBeNull();s.dispose()
})
it('closes timer queries and releases synchronization objects after a rendering failure',()=>{
  const d=delayedTimers(),s=createTraceSchedule({getContext:()=>d.gl})
  expect(()=>s.run({samples:0,step(){throw new Error('shader failed')}},8)).toThrow('shader failed')
  expect(d.gl.beginQuery).toHaveBeenCalledOnce();expect(d.gl.endQuery).toHaveBeenCalledOnce()
  s.dispose();expect(d.gl.deleteQuery).toHaveBeenCalledOnce();expect(d.gl.deleteSync).toHaveBeenCalledOnce()
})
