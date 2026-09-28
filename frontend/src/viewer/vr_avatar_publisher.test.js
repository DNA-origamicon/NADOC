import { it, expect, vi } from 'vitest'
import { initVRAvatarPublisher } from './vr_avatar_publisher.js'
const avatar={schema:1,trackingToSource:[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1],head:{position:[0,1.6,0],orientation:[0,0,0,1]},hands:[null,null]}
function setup(options={}) {
  const room={id:'room',revision:'rev'},publish=vi.fn(),request=vi.fn(async()=>({ok:true,json:async()=>({avatar})}))
  const p=initVRAvatarPublisher({getRoom:()=>room,available:()=>true,publish,request,setInterval:()=>1,clearInterval:vi.fn(),...options})
  return {p,publish,request,room}
}
it('publishes bounded poses only to an existing room and sends disable once',async()=>{
  let value=avatar
  const v=setup({request:async()=>({ok:true,json:async()=>({avatar:value})})})
  await v.p.tick();expect(v.publish).toHaveBeenLastCalledWith(v.room,{revision:'rev',avatar})
  value=null;await v.p.tick();await v.p.tick();expect(v.publish).toHaveBeenCalledTimes(2)
  expect(v.publish).toHaveBeenLastCalledWith(v.room,{revision:'rev',avatar:null});v.p.dispose()
  const empty=setup({getRoom:()=>null});await empty.p.tick();expect(empty.request).not.toHaveBeenCalled();empty.p.dispose()
})
it('does not queue poses or publish a completed request into a different room',async()=>{
  let finish,room={id:'one',revision:'rev'}
  const v=setup({getRoom:()=>room,request:()=>new Promise(resolve=>{finish=resolve})})
  const first=v.p.tick();await v.p.tick();room={id:'two',revision:'rev'}
  finish({ok:true,json:async()=>({avatar})});await first;expect(v.publish).not.toHaveBeenCalled();v.p.dispose()
})
it('reports a failed transfer once and ignores work completed after disposal',async()=>{
  const onError=vi.fn(),v=setup({request:async()=>{throw Error('Disconnected')},onError})
  await v.p.tick();await v.p.tick();expect(onError).toHaveBeenCalledOnce();v.p.dispose()
  let finish;const pending=setup({request:()=>new Promise(r=>{finish=r})})
  const work=pending.p.tick();pending.p.dispose();finish({ok:true,json:async()=>({avatar})});await work
  expect(pending.publish).not.toHaveBeenCalled()
})
