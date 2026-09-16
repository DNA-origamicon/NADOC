import { it, expect, vi } from 'vitest'
import { initMdTrajectoryPrefetch } from './md_trajectory_prefetch.js'
it('starts independent reads together and consumes each only for the same job and stride',async()=>{
  const api={getMdAtomisticModel:vi.fn(async()=>({atoms:[]})),getMdFramesAtomistic:vi.fn(async()=>({0:[1]}))}
  const p=initMdTrajectoryPrefetch(api)
  p.start('p5',20)
  expect(api.getMdAtomisticModel).toHaveBeenCalledOnce()
  expect(api.getMdFramesAtomistic).toHaveBeenCalledOnce()
  await p.model('p5');await p.frames('p5',[0,1],20)
  expect(api.getMdAtomisticModel).toHaveBeenCalledOnce()
  expect(api.getMdFramesAtomistic).toHaveBeenCalledOnce()
  await p.frames('p5',[0],40)
  expect(api.getMdFramesAtomistic).toHaveBeenCalledTimes(2)
  p.start('next',20)
  await p.model('p5')
  expect(api.getMdAtomisticModel).toHaveBeenCalledTimes(3)
})
