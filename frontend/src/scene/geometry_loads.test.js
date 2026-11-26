import {it,expect} from 'vitest'
import {createGeometryLoads} from './geometry_loads.js'

it('waits for independent geometry owners and ignores obsolete completions',()=>{
  const loads=createGeometryLoads(),a={},b={}
  const old=loads.begin(a),other=loads.begin(b),latest=loads.begin(a)
  old();other();expect(loads.getState().busy).toBe(true)
  latest();expect(loads.getState()).toEqual({busy:false,revision:5})
  latest();expect(loads.getState().revision).toBe(5)
})
it('releases synchronous failures, async failures and explicitly cancelled owners',async()=>{
  const loads=createGeometryLoads(),owner={}
  await expect(loads.track(owner,()=>{throw Error('failed')})).rejects.toThrow('failed')
  await expect(loads.track(owner,async()=>{throw Error('failed')})).rejects.toThrow('failed')
  expect(loads.getState().busy).toBe(false)
  let finish
  const work=loads.track(owner,()=>new Promise(resolve=>{finish=resolve}))
  expect(loads.getState().busy).toBe(true)
  loads.cancel(owner);const revision=loads.getState().revision
  finish(42);expect(await work).toBe(42)
  expect(loads.getState()).toEqual({busy:false,revision})
})
