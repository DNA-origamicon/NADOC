import { describe, it, expect, vi } from 'vitest'
import { initTrajectoryStream } from './trajectory_stream.js'
import { loadProgressiveTrajectory } from './progressive_trajectory.js'

describe('exact trajectory pages', () => {
  it('deduplicates seeks, bounds lookahead, and retries failures', async () => {
    const load=vi.fn().mockRejectedValueOnce(new Error('disk')).mockResolvedValue('frame')
    const apply=vi.fn()
    const s=initTrajectoryStream({total:23,pageSize:8,load,apply,live:()=>true})
    const a=s.ensure(17),b=s.ensure(22)
    expect(a).toBe(b)
    await expect(a).rejects.toThrow('disk')
    expect(await s.ensure(17)).toBe(true)
    expect(load).toHaveBeenLastCalledWith(16,22)
    expect(apply).toHaveBeenCalledOnce()
    s.prefetch(22)
    expect(load).toHaveBeenCalledTimes(2)
  })
  it('never installs stale job data', async () => {
    let resolve,live=true
    const apply=vi.fn()
    const s=initTrajectoryStream({total:100,load:()=>new Promise(r=>{resolve=r}),apply,live:()=>live})
    const pending=s.ensure(0)
    await Promise.resolve();await Promise.resolve()
    live=false;resolve('old job')
    expect(await pending).toBe(false)
    expect(apply).not.toHaveBeenCalled()
  })
  it('opens eight frames, then fills and retains the entire selected trajectory', async () => {
    const get=vi.fn(async (_id,spec)=>({ready:true, frames:Array.from({length:spec.frameEnd-spec.frameStart+1},(_,i)=>[spec.frameStart+i]),keys:[]}))
    const heavy=vi.fn(),evict=vi.fn()
    const opened=await loadProgressiveTrajectory({jobId:'p5',spec:{stride:20},
      downloads:{get,consumed:vi.fn()},metadata:async()=>({n_frames:250,stages:[],markers:[]}),
      live:()=>true,heavy,evict})
    expect(get).toHaveBeenCalledOnce()
    expect(opened.resp.frames.length).toBe(250)
    expect(opened.resp.frames[249]).toBeUndefined()
    for(const i of [0,8,24,40]) await opened.ensure(i)
    expect(heavy).toHaveBeenLastCalledWith(40,55)
    expect(opened.resp.frames[0]).toEqual([0])
    await opened.ensure(0)
    expect(opened.resp.frames[0]).toEqual([0])
    await opened.fill()
    expect(opened.status().complete).toBe(true)
    expect(opened.resp.frames[249]).toEqual([249])
    const calls = get.mock.calls.length
    for (const i of [249,0,100,8,200]) await opened.ensure(i)
    expect(get).toHaveBeenCalledTimes(calls)
    expect(evict).not.toHaveBeenCalled()
  })
})

it('foreground scrubbing overtakes background fill and stale jobs stop', async () => {
  let release, live = true
  const order = []
  const s = initTrajectoryStream({total:40, pageSize:8, live:()=>live,
    load:async start => { order.push(start); if (start===0) await new Promise(r=>{release=r}) }, apply:async()=>{}})
  const filling = s.fill()
  await vi.waitFor(()=>expect(release).toBeTypeOf('function'))
  const seek = s.ensure(32)
  release(); await seek
  expect(order.slice(0,2)).toEqual([0,32])
  live=false
  await filling
  expect(order).toEqual([0,32])
})
it('stops full preparation at the memory budget without substituting requested frames', async () => {
  const get=vi.fn(async (_id,s)=>({ready:true,frames:Array.from({length:s.frameEnd-s.frameStart+1},()=>new Float32Array(3))}))
  const evict=vi.fn()
  const opened=await loadProgressiveTrajectory({jobId:'x',spec:{},downloads:{get,consumed:()=>{}},
    metadata:async()=>({n_frames:100}),heavy:async()=>24,evict,live:()=>true,budgetBytes:900})
  await opened.ensure(0);await opened.fill()
  expect(opened.status()).toMatchObject({buffered:24,limited:true,complete:false})
  await opened.ensure(90)
  expect(opened.resp.frames[90]).toBeDefined()
  expect(opened.status().bytes).toBeLessThanOrEqual(900)
  expect(evict).toHaveBeenCalled()
})
