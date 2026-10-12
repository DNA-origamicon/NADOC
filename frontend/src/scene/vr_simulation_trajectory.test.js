import { describe, it, expect, vi } from 'vitest'
import { trajectorySelection, createVRSimulationTrajectory } from './vr_simulation_trajectory.js'
function binary(n, first=0) {
  const header = new TextEncoder().encode(JSON.stringify({ keys: [['h',0,'fwd']], frame_start:first, total_n_frames:1000 }))
  const offset = Math.ceil((20 + header.length)/4)*4, buffer = new ArrayBuffer(offset+n*6*4), d = new DataView(buffer)
  ;[0x4E54524A,1,n,1,header.length].forEach((v,i)=>d.setUint32(i*4,v,true));new Uint8Array(buffer,20,header.length).set(header)
  return buffer
}
describe('Full trajectory gate and bounded frame pages', () => {
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
