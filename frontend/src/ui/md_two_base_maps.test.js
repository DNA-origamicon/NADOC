// @vitest-environment jsdom
import { it, expect, vi, afterEach } from 'vitest'
import { initMdTwoBaseMaps, singleSelectedBase } from './md_two_base_maps.js'
import { twoBasePlots } from './two_base_maps_popup.js'

let dispose
 afterEach(() => { dispose?.(); document.body.replaceChildren() })
function setup() {
  document.body.innerHTML = ['1','2','generate','show','export'].map(id=>`<button id="md-two-base-${id}"></button>`).join('')+'<div id="md-two-base-status"></div><div id="md-two-base-progress" hidden></div><div id="md-two-base-fill"></div><div id="md-two-base-percent"></div>'
  let state = {currentDesign:{id:'d',helices:[],strands:[]},selection:{items:[]}}, listener, job = {job_id:'j'}
  const generate = vi.fn(async()=>({frames:2})), show = vi.fn()
  const c = initMdTwoBaseMaps({getSelectedJob:()=>job,generate,show,stateStore:{getState:()=>state,subscribe:fn=>{listener=fn;return()=>{}}}})
  dispose = c.dispose
  return {c,generate,show,el:id=>document.getElementById(`md-two-base-${id}`),select(key){const old=state;state={...state,selection:{items:key?[{kind:'base',key}]:[]}};listener(state,old)},job(id){job={job_id:id};c.sync()}}
}
it('requires exactly one individual base',()=>{
  expect(singleSelectedBase({selection:{items:[{kind:'strand',id:'s'}]}})).toBeNull()
  expect(singleSelectedBase({selection:{items:[{kind:'base',key:'a'},{kind:'base',key:'b'}]}})).toBeNull()
})
it('captures current or next base, enables Generate, then Show; changing job clears results',async()=>{
  const x=setup()
  x.el('1').click();x.select('h:1:FORWARD')
  expect(x.el('generate').disabled).toBe(true)
  x.select('h:2:FORWARD');x.el('2').click()
  expect(x.el('generate').disabled).toBe(false)
  expect(x.el('show').disabled).toBe(true)
  x.el('generate').click()
  await vi.waitFor(()=>expect(x.el('show').disabled).toBe(false))
  expect(x.generate.mock.calls[0].slice(0,2)).toEqual(['j',['h:1:FORWARD','h:2:FORWARD']])
  x.el('show').click();expect(x.show).toHaveBeenCalledWith({frames:2}, {maps:[0,1,12,13]})
  x.job('other');expect(x.el('show').disabled).toBe(true);expect(x.el('generate').disabled).toBe(true)
})
it('rejects selecting the same base twice and ignores a stale generation',async()=>{
  const x=setup();x.select('h:1:FORWARD');x.el('1').click();x.el('2').click()
  expect(x.el('generate').disabled).toBe(true)
  x.select('h:2:FORWARD');x.el('2').click()
  let resolve;x.generate.mockImplementation(()=>new Promise(r=>{resolve=r}))
  x.el('generate').click();x.job('other');resolve({frames:3})
  await Promise.resolve();expect(x.el('show').disabled).toBe(true)
})
it('plots each of the 15 unique pairs once without dropping samples',()=>{
  const plots=twoBasePlots({labels:['x','y','z','rx','ry','rz'],rows:[[1,2,3,4,5,6],[7,8,9,10,11,12]]})
  expect(plots).toHaveLength(15)
  expect(new Set(plots.map(p=>`${p.x}:${p.y}`)).size).toBe(15)
  expect(plots[0].points).toEqual([[1,2],[7,8]])
  expect(plots.at(-1).points).toEqual([[5,6],[11,12]])
})

it('defaults to two pure position and two pure rotation plots',()=>{
  const plots=twoBasePlots({rows:[]})
  const chosen=[0,1,12,13].map(i=>plots[i])
  expect(chosen.slice(0,2).every(p=>p.x<3&&p.y<3)).toBe(true)
  expect(chosen.slice(2).every(p=>p.x>=3&&p.y>=3)).toBe(true)
})
