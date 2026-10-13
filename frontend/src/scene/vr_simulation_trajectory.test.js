import { describe, it, expect, vi } from 'vitest'
import { trajectorySelection, createVRSimulationTrajectory } from './vr_simulation_trajectory.js'
function binary(n, first=0) {
  const header = new TextEncoder().encode(JSON.stringify({ keys: [['h',0,'fwd']], frame_start:first, total_n_frames:1000 }))
  const offset = Math.ceil((20 + header.length)/4)*4, buffer = new ArrayBuffer(offset+n*6*4), d = new DataView(buffer)
  ;[0x4E54524A,1,n,1,header.length].forEach((v,i)=>d.setUint32(i*4,v,true));new Uint8Array(buffer,20,header.length).set(header)
  return buffer
}
describe('Full trajectory gate and bounded frame pages', () => {
 it('holds SNUPI frame acknowledgement until its selected representation is ready and rejects a cancelled build', async () => {
  let release
  const display={showTrajectory:async()=>({ok:true}),seekFullTrajectoryFrame:async()=>({ok:true})}
  const t=createVRSimulationTrajectory({api:{getSnupiTrajectoryMeta:async()=>({n_frames:5})},controller:()=>display,
   ensureFull:async()=>{},prepareFrame:()=>new Promise(resolve=>{release=resolve})})
  await t.select('snupi','job')
  const load=t.load();await vi.waitFor(()=>expect(release).toBeTypeOf('function'))
  expect(t.snapshot().phase).toBe('loading');release();await load
  release=null
  const next=t.seek(2);await vi.waitFor(()=>expect(release).toBeTypeOf('function'))
  expect(t.snapshot()).toMatchObject({phase:'buffering',source:1,index:0})
  release();expect(await next).toBe(true)
  expect(t.snapshot()).toMatchObject({phase:'ready',source:3,index:2})
  release=null
  const cancelled=t.seek(3);await vi.waitFor(()=>expect(release).toBeTypeOf('function'))
  t.cancel();release();expect(await cancelled).toBe(false)
  expect(t.snapshot()).toMatchObject({phase:'idle',source:3,index:2})
  t.dispose()
 })
 it('validates exact inclusive source ranges', () => {
  expect(trajectorySelection(50001,100000,500,100000)).toEqual({first:50001,last:100000,interval:500,count:100})
  for(const values of [[0,4,1,4],[4,3,1,4],[1,5,1,4],[1,4,0,4],[1.2,4,1,4]])expect(trajectorySelection(...values)).toBeNull()
 })
 it('does not download until Load; seeks exact source IDs and reuses bounded pages', async () => {
  const calls=[], display={loadFullTrajectoryPage:vi.fn(async()=>({ok:true})),showFullTrajectoryFrame:vi.fn(()=>true)}, ensureFull=vi.fn()
  const t=createVRSimulationTrajectory({api:{getMdTrajectoryMeta:async()=>({total_raw:100000})},controller:()=>display,ensureFull,
   request:async url=>{calls.push(url);const u=new URL(url,'http://local'),lo=+u.searchParams.get('frame_start'),hi=+u.searchParams.get('frame_end'),step=+u.searchParams.get('frame_step');return{ok:true,headers:{get:()=>null},arrayBuffer:async()=>binary(Math.floor((hi-lo)/step)+1)}}})
  await t.select('namd','job');expect(calls).toHaveLength(0)
  expect(await t.seek(1)).toBe(false)
  t.configure({first:50001,last:100000,interval:500});await t.load()
  expect(ensureFull).toHaveBeenCalledTimes(1);expect(calls[0]).toContain('frame_start=50000&frame_end=53500&frame_step=500')
  await t.seek(5);expect(calls).toHaveLength(1);expect(t.snapshot().source).toBe(52501)
  await t.seek(20);expect(calls).toHaveLength(2)
  t.configure({interval:1000});expect(t.snapshot().phase).toBe('idle');expect(await t.seek(1)).toBe(false);t.dispose()
 })
 it('rejects a late page after cancellation',async()=>{
  let release;const display={loadFullTrajectoryPage:vi.fn()},t=createVRSimulationTrajectory({api:{getMdTrajectoryMeta:async()=>({total_raw:8})},controller:()=>display,ensureFull:async()=>{},request:()=>new Promise(r=>{release=r})})
  await t.select('namd','j');const load=t.load();await Promise.resolve();t.cancel();release({ok:true,headers:{get:()=>null},arrayBuffer:async()=>binary(8)});await load
  expect(display.loadFullTrajectoryPage).not.toHaveBeenCalled();expect(t.snapshot().phase).toBe('idle');t.dispose()
 })
 it('holds DNA and ions on the same frame while a companion page buffers', async () => {
  let release
  const drawn = [], overlay = { setEnabled: vi.fn(), setJob: vi.fn(async () => {}),
   prepareAll: vi.fn(() => new Promise(resolve => { release = resolve })), showFrame: i => drawn.push(['ions',i]) }
  const display = { loadFullTrajectoryPage: async () => ({ok:true}), showFullTrajectoryFrame: (_page,i) => { drawn.push(['dna',i]); return true } }
  const t = createVRSimulationTrajectory({api:{getMdTrajectoryMeta:async()=>({total_raw:8})}, controller:()=>display,
   companion:()=>overlay, ensureFull:async()=>{}, request:async()=>({ok:true,headers:{get:()=>null},arrayBuffer:async()=>binary(8)})})
  await t.select('namd','j')
  const loading=t.load()
  await vi.waitFor(()=>expect(release).toBeTypeOf('function'))
  expect(drawn).toEqual([])
  expect(overlay.setJob.mock.calls[0][1].deferDraw).toBe(true)
  expect(t.snapshot().phase).toBe('loading')
  release(true);await loading
  expect(drawn).toEqual([['dna',0],['ions',0]])
  const seeking=t.seek(5)
  await vi.waitFor(()=>expect(overlay.prepareAll).toHaveBeenCalledTimes(2))
  t.cancel();release(true);await seeking
  expect(drawn).toHaveLength(2)
  t.dispose()
 })
 it('reports preparation failure and permits retrying failed metadata',async()=>{
  const api={getMdTrajectoryMeta:vi.fn().mockRejectedValueOnce(new Error('Storage offline')).mockResolvedValue({total_raw:8})}
  const t=createVRSimulationTrajectory({api,controller:()=>({}),ensureFull:async()=>{throw new Error('Full unavailable')}})
  await t.select('namd','j');expect(t.snapshot().phase).toBe('error')
  await t.select('namd','j');expect(t.snapshot().available).toBe(8)
  expect(await t.load()).toBe(false);expect(t.snapshot()).toMatchObject({phase:'error',message:'Full unavailable'});t.dispose()
 })
})

it('publishes a range edit atomically, without an acknowledged old range', async () => {
 const observed = []
 let t
 t = createVRSimulationTrajectory({api:{getMdTrajectoryMeta:async()=>({total_raw:1226})},
  controller:()=>({}), changed:()=>observed.push(t.snapshot())})
 await t.select('namd','job')
 observed.length = 0
 expect(t.configure({first:1,last:515,interval:1})).toBe(true)
 expect(observed).toHaveLength(1)
 expect(observed[0]).toMatchObject({first:1,last:515,interval:1,count:515,phase:'idle'})
 observed.length = 0
 t.cancel()
 expect(observed).toHaveLength(1)
 expect(observed[0].message).toBe('Load cancelled')
 t.dispose()
})

it('reloads an evicted first page at wrap and never interpolates end to start', async () => {
 vi.useFakeTimers()
 const drawn=[], fetched=[], interpolated=[]
 const t=createVRSimulationTrajectory({api:{getMdTrajectoryMeta:async()=>({total_raw:100})},
  controller:()=>({loadFullTrajectoryPage:async()=>({ok:true}),
   showFullTrajectoryFrame:(page,i)=>{drawn.push(page.frame_start+i*page.frame_step);return true},
   ensureInterpolationFrames:async(from,to)=>{interpolated.push([from,to])}}),
  ensureFull:async()=>{},request:async url=>{
   const u=new URL(url,'http://local'),first=+u.searchParams.get('frame_start'),last=+u.searchParams.get('frame_end'),step=+u.searchParams.get('frame_step')
   fetched.push(first)
   return {ok:true,headers:{get:()=>null},arrayBuffer:async()=>binary(Math.floor((last-first)/step)+1)}
  }})
 try {
  await t.select('namd','job');t.configure({first:5,last:37,interval:2});await t.load()
  t.loop();t.smooth();t.toggle()
  await vi.advanceTimersByTimeAsync(1420)
  t.pause()
  expect(drawn.slice(0,18)).toEqual([...Array.from({length:17},(_,i)=>4+2*i),4])
  expect(fetched.filter(i=>i===4)).toHaveLength(2)
  expect(interpolated.every(([from,to])=>to===from+1)).toBe(true)
 } finally { t.dispose();vi.useRealTimers() }
})
