// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest'
import { initEMSimulation, trajectoryEMFrames, collectTrajectoryEMFrames } from './em_simulation.js'
import { settleEMExport } from '../scene/em_export.js'
import { loadEMSettings, saveEMSettings } from './em_settings.js'

const particles = [{ id:'gold', diameter_nm:20, center_nm:[1,2,3] }]
const data = { key:'job:1', keys:[['dna',0],['__gold__',0]], frames:[
  new Float32Array([0,0,0,1,0,0,0,0,1, 1,2,3,1,0,0,0,0,1]),
  new Float32Array([0,0,0,1,0,0,0,0,1, 4,5,6,1,0,0,0,0,1])], frameStart:10, frameStep:2, currentIndex:10 }
let feature, now = 1000
function setup(trajectory = false, capture = () => particles) {
  document.body.innerHTML = '<div><input id="oxdna-jobs-traj-slider"></div><input type="checkbox" id="oxdna-jobs-traj-interpolate" checked><div id="oxdna-jobs-viz-body"></div><div id="md-jobs-viz-body"></div>'
  vi.spyOn(performance,'now').mockImplementation(() => now)
  const display = { isActive:()=>true, mode:()=>trajectory ? 'trajectory':'rmsf', activeJobId:()=> 'j', emTrajectory:()=>trajectory ? data:null }
  const overlay = { show:vi.fn(), showTransition:vi.fn(), clear:vi.fn(), dispose:vi.fn() }, openSettings = vi.fn()
  const api = { _request:vi.fn(async (method,path) => {
    if (method === 'DELETE') return {cancelled:true}
    if (path === '/em-analysis/trajectories') return {id:'batch'}
    if (path.includes('/frames/')) return {peak_intensity:2}
    if (path.includes('/trajectories/')) return {status:'complete', completed:2,total:2,frames:[10,12]}
    return {peak_intensity:2}
  }) }
  const scene = {}
  feature = initEMSimulation({ scene, api, store:{getState:()=>({currentDesign:{id:'d'}})}, displays:{oxdna:()=>display,md:()=>display},
    captureSimulation:capture, openSettings, overlayFactory:()=>overlay })
  const row = document.querySelector('#oxdna-jobs-viz-body')
  return { row, api, overlay, openSettings, display, scene }
}
afterEach(() => { feature?.dispose(); document.body.innerHTML = ''; localStorage.clear(); vi.restoreAllMocks(); now=1000 })

it('extracts loaded moving core frames with original indices without changing input', () => {
  const frames = trajectoryEMFrames(data, particles)
  expect(frames.map(f=>f.frame_index)).toEqual([10,12])
  expect(frames[1].particles[0].center_nm).toEqual([4,5,6])
  expect(particles[0].center_nm).toEqual([1,2,3])
  expect(() => trajectoryEMFrames({...data,keys:[['dna',0]]},particles)).toThrow(/gold-core/)
  expect(trajectoryEMFrames({...data,keys:[]},particles,true)[1].particles[0].center_nm).toEqual([1,2,3])
})
it('toggle analyzes the current visualization and gear opens shared settings', async () => {
  const {row,api,overlay,openSettings} = setup()
  expect(row.querySelector('[data-em-settings]').title).toBe('Setting')
  expect(row.querySelector('[data-em-settings] svg')).not.toBeNull()
  expect(row.querySelector('[data-em-trajectory]').classList.contains('btn')).toBe(true)
  row.querySelector('[data-em-settings]').click(); expect(openSettings).toHaveBeenCalled()
  row.querySelector('[data-em-toggle]').click()
  now+=500; await feature.tick()
  await vi.waitFor(()=>expect(overlay.show).toHaveBeenCalled())
  expect(api._request.mock.calls[0][2].particles).toEqual(particles)
  row.querySelector('[data-em-toggle]').click(); expect(overlay.clear).toHaveBeenCalled()
})
it('trajectory confirmation cancels without computation and Continue submits all loaded frames', async () => {
  const {row,api,overlay} = setup(true)
  await feature.tick(); expect(row.querySelector('[data-em-trajectory]').hidden).toBe(false)
  row.querySelector('[data-em-trajectory]').click()
  expect(document.querySelector('[role=dialog]').textContent).toContain('all 2 selected trajectory frames')
  document.querySelector('.modal__actions button').click(); expect(api._request).not.toHaveBeenCalled()
  row.querySelector('[data-em-trajectory]').click(); document.querySelectorAll('.modal__actions button')[1].click()
  await vi.waitFor(()=>expect(api._request).toHaveBeenCalled())
  const submitted = api._request.mock.calls.find(c=>c[0]==='POST')[2]
  expect(submitted.frames.map(f=>f.frame_index)).toEqual([10,12])
  expect(submitted.frames[1].input.particles[0].center_nm).toEqual([4,5,6])
  now+=500; await feature.tick()
  await vi.waitFor(()=>expect(overlay.show).toHaveBeenCalled())
  expect(document.querySelector('.em-trajectory-progress').getAttribute('aria-valuenow')).toBe('100')
  expect(document.querySelector('#oxdna-jobs-traj-interpolate').checked).toBe(true)
  row.querySelector('[data-em-toggle]').click()
  expect(document.querySelector('#oxdna-jobs-traj-interpolate').checked).toBe(true)
  expect(api._request.mock.calls.some(c=>c[0]==='DELETE')).toBe(true)
})
it('persists validated settings and redraws display changes without recalculation', async () => {
  const {row,api,overlay} = setup()
  row.querySelector('[data-em-toggle]').click(); now+=500; await feature.tick()
  await vi.waitFor(()=>expect(overlay.show).toHaveBeenCalled())
  saveEMSettings({...loadEMSettings(),'dot-size':7})
  expect(loadEMSettings()['dot-size']).toBe(7)
  expect(overlay.show.mock.lastCall[1].dotSize).toBe(7)
  expect(api._request).toHaveBeenCalledTimes(1)
})

it('accepts compact six-value frames without inventing particle motion', () => {
  const compact = {...data, frames:data.frames.map(frame=>frame.filter((_,i)=>i%9<6))}
  expect(trajectoryEMFrames(compact, particles)[1].particles[0].center_nm).toEqual([4,5,6])
})

it('rejects mismatched gold-core indices instead of silently using saved positions', () => {
  expect(() => trajectoryEMFrames({...data,keys:[['dna',0],['__gold__',1]]},particles)).toThrow(/do not match/)
})
it('does not show a snapshot that arrives after the displayed particles moved', async () => {
  let current = particles, finish
  const {row, api, overlay} = setup(false, () => current)
  api._request.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
  row.querySelector('[data-em-toggle]').click()
  now+=500; await feature.tick()
  await vi.waitFor(() => expect(finish).toBeTypeOf('function'))
  current = [{...particles[0],center_nm:[9,8,7]}]
  finish({peak_intensity:2})
  await new Promise(resolve=>setTimeout(resolve,0))
  expect(overlay.show).not.toHaveBeenCalled()
})
it('NAMD toggle uses the same current-state solve and settings', async () => {
  const {api,overlay} = setup()
  document.querySelector('#md-jobs-viz-body [data-em-toggle]').click()
  now+=500; await feature.tick()
  await vi.waitFor(()=>expect(overlay.show).toHaveBeenCalled())
  expect(api._request.mock.calls[0][2].particles).toEqual(particles)
  expect(document.querySelector('#oxdna-jobs-viz-body [data-em-toggle]').checked).toBe(false)
})

it('scrubbing selects the matching analyzed frame and clears an interpolated pose', async () => {
  let current = particles
  const {row,api,overlay} = setup(true,()=>current)
  row.querySelector('[data-em-trajectory]').click()
  document.querySelectorAll('.modal__actions button')[1].click()
  await vi.waitFor(()=>expect(api._request).toHaveBeenCalled())
  now+=500; await feature.tick()
  await vi.waitFor(()=>expect(api._request.mock.calls.some(c=>c[1].endsWith('/frames/1'))).toBe(true))
  await new Promise(resolve=>setTimeout(resolve,0))
  try {
    data.currentIndex=12
    current=[{...particles[0],center_nm:[4,5,6]}]
    const requestsBefore = api._request.mock.calls.length
    now+=16; await feature.tick()
    expect(api._request.mock.calls.length).toBe(requestsBefore)
    expect(api._request.mock.calls.some(c=>c[1].endsWith('/frames/1'))).toBe(true)
    expect(overlay.show).toHaveBeenCalledTimes(2)
    current=[{...particles[0],center_nm:[2,3,4]}]
    now+=500; await feature.tick()
    expect(overlay.clear).toHaveBeenCalled()
    expect(overlay.show).toHaveBeenCalledTimes(2)
    current=[{...particles[0],diameter_nm:25,center_nm:[4,5,6]}]
    now+=500; await feature.tick()
    expect(overlay.show).toHaveBeenCalledTimes(2)
    current=[{...particles[0],center_nm:[4,5,6]}, {...particles[0],id:'new-gold'}]
    now+=500; await feature.tick()
    expect(overlay.show).toHaveBeenCalledTimes(2)
  } finally { data.currentIndex=10 }
})

it('uses the shared modal and closes on Escape without starting analysis',async()=>{
 const {row,api}=setup(true)
 row.querySelector('[data-em-trajectory]').click()
 const modal=document.querySelector('.modal__overlay .modal')
 expect(modal.getAttribute('role')).toBe('dialog')
 expect(modal.querySelectorAll('.modal__body p')).toHaveLength(2)
 expect(modal.querySelector('.modal__actions .btn--primary').textContent).toBe('Continue')
 window.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'}))
 expect(document.querySelector('[role=dialog]')).toBeNull()
 expect(api._request).not.toHaveBeenCalled()
})

it('collects every sparse trajectory frame with stable source indices and owned core positions', async()=>{
 const frames = new Array(4); frames[0] = data.frames[0]
 const readFrame = vi.fn(async i => {delete frames[i-1]; return data.frames[1]})
 const result = await collectTrajectoryEMFrames({...data,frames,readFrame},particles,false)
 expect(result.map(f=>f.frame_index)).toEqual([10,12,14,16])
 expect(readFrame.mock.calls.map(c=>c[0])).toEqual([1,2,3])
 expect(result[0].particles[0].center_nm).toEqual([1,2,3])
 expect(result[3].particles[0].center_nm).toEqual([4,5,6])
})
it('does not submit an incomplete trajectory if a missing frame cannot be loaded', async()=>{
 const frames = new Array(2); frames[0] = data.frames[0]
 await expect(collectTrajectoryEMFrames({...data,frames},particles,false)).rejects.toThrow('frame 2')
 await expect(collectTrajectoryEMFrames(data,particles,false,()=>false)).rejects.toThrow('cancelled')
})

it('confirms the complete selected count before sparse pages have arrived',async()=>{
 const {row,display,api} = setup(true)
 const frames = new Array(5); frames[0] = data.frames[0]
 display.emTrajectory = () => ({...data,frames,readFrame:async()=>data.frames[1]})
 row.querySelector('[data-em-trajectory]').click()
 expect(document.querySelector('[role=dialog]').textContent).toContain('all 5 selected trajectory frames')
 document.querySelectorAll('.modal__actions button')[1].click()
 await vi.waitFor(()=>expect(api._request.mock.calls.find(c=>c[0]==='POST')?.[2].frames).toHaveLength(5))
})

it('uses the molecular interpolation fraction and restores exact fields on pause',async()=>{
 let current=particles
 const {row,api,overlay,display}=setup(true,()=>current)
 display.setEMPlaybackPreparation=vi.fn()
 row.querySelector('[data-em-trajectory]').click()
 document.querySelectorAll('.modal__actions button')[1].click()
 await vi.waitFor(()=>expect(display.setEMPlaybackPreparation).toHaveBeenCalled())
 now+=500;await feature.tick()
 await vi.waitFor(()=>expect(api._request.mock.calls.some(c=>c[1].endsWith('/frames/1'))).toBe(true))
 await new Promise(r=>setTimeout(r,0))
 const pose=data.frames[0].slice();pose.set([2.5,3.5,4.5],9)
 try {
  data.transition={from:10,to:12,t:.5,frame:pose}
  current=[{...particles[0],center_nm:[2.5,3.5,4.5]}]
  now+=16;await feature.tick()
  expect(overlay.showTransition).toHaveBeenLastCalledWith(expect.anything(),expect.anything(),.5,expect.anything())
  expect(row.querySelector('[data-em-frame-status]').textContent).toContain('visual interpolation')
  delete data.transition;current=particles;now+=16;await feature.tick()
  expect(row.querySelector('[data-em-frame-status]').textContent).toBe('')
  row.querySelector('[data-em-toggle]').click()
  expect(display.setEMPlaybackPreparation).toHaveBeenLastCalledWith(null)
 } finally {delete data.transition}
})

it('offline capture waits for the requested field without a render-loop tick',async()=>{
 let current=particles
 const {row,api,overlay,display,scene}=setup(true,()=>current)
 row.querySelector('[data-em-trajectory]').click();document.querySelectorAll('.modal__actions button')[1].click()
 await vi.waitFor(()=>expect(api._request.mock.calls.some(c=>c[0]==='POST')).toBe(true))
 await settleEMExport(scene)
 expect(overlay.show).toHaveBeenCalled()
 let finish
 api._request.mockImplementation(async(method,path)=>path.endsWith('/frames/1') ? new Promise(r=>{finish=r}) : {status:'complete',completed:2,total:2,frames:[10,12]})
 const next={...data,currentIndex:12};display.emTrajectory=()=>next
 current=[{...particles[0],center_nm:[4,5,6]}]
 overlay.show.mockClear()
 const exported=settleEMExport(scene)
 await vi.waitFor(()=>expect(finish).toBeTypeOf('function'))
 expect(overlay.show).not.toHaveBeenCalled()
 finish({peak_intensity:12});await exported
 expect(overlay.show.mock.lastCall[0].peak_intensity).toBe(12)
 next.key='another trajectory'
 await expect(settleEMExport(scene)).rejects.toThrow('differs')
 row.querySelector('[data-em-toggle]').click()
 await expect(settleEMExport(scene)).resolves.toBeUndefined()
})
it('refuses a missing analyzed frame instead of exporting an empty or stale field',async()=>{
 const {row,api,scene}=setup(true)
 row.querySelector('[data-em-trajectory]').click();document.querySelectorAll('.modal__actions button')[1].click()
 await vi.waitFor(()=>expect(api._request.mock.calls.some(c=>c[0]==='POST')).toBe(true))
 api._request.mockResolvedValue({status:'running',frames:[]})
 await expect(settleEMExport(scene)).rejects.toThrow('not ready')
})
