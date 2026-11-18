import {it,expect,vi} from 'vitest'
import {createClusterAttachment} from './cluster_attachment.js'
it('coalesces selection bridges and rejects a superseded delayed attach',async()=>{
  let state={design:'d',epoch:1,active:true}, release
  const run=createClusterAttachment(()=>state), effects=[]
  const first=vi.fn(async current=>{await new Promise(r=>release=r);if(current())effects.push('a')})
  const a=run('a',first), duplicate=run('a',first)
  expect(duplicate).toBe(a)
  await Promise.resolve()
  await run('b',async current=>{if(current())effects.push('b')})
  release();await a
  expect(first).toHaveBeenCalledTimes(1)
  expect(effects).toEqual(['b'])
})
it('does not revive the tool after cancellation',async()=>{
  let state={design:'d',epoch:1,active:true}, release
  const run=createClusterAttachment(()=>state), attached=vi.fn()
  const pending=run('a',async current=>{await new Promise(r=>release=r);if(current())attached()})
  await Promise.resolve();state={...state,epoch:2,active:false};release();await pending
  expect(attached).not.toHaveBeenCalled()
})
