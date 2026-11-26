import {it,expect,vi} from 'vitest'
import {createNativeSession} from './path_trace_native_session.js'
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve}}
const response=data=>({json:async()=>data})
it('consumes and releases a startup acknowledgement after caller cancellation',async()=>{
  const reply=deferred(),signal=new AbortController(),events=new EventTarget(),fetcher=vi.fn(async()=>({ok:true}))
  const request=vi.fn(()=>reply.promise)
  const pending=createNativeSession({signal:signal.signal,request,fetcher,events})
  const rejected=expect(pending).rejects.toMatchObject({name:'AbortError'})
  signal.abort();reply.resolve(response({id:'allocated'}));await rejected
  expect(request.mock.calls[0][2]).toBeUndefined()
  expect(fetcher).toHaveBeenCalledExactlyOnceWith('/api/render/optix/allocated',{method:'DELETE',keepalive:true})
})
it('releases a page-owned worker on pagehide and close remains idempotent',async()=>{
  const events=new EventTarget(),fetcher=vi.fn(async()=>({ok:true}))
  const request=vi.fn(async path=>response(path==='/session'?{id:'owned',device:'GPU'}:{upload_limit_bytes:1024}))
  const lease=await createNativeSession({request,fetcher,events})
  expect(lease.capacity.upload_limit_bytes).toBe(1024)
  events.dispatchEvent(new Event('pagehide'));await lease.close();await lease.close()
  expect(fetcher).toHaveBeenCalledOnce()
})
it('closing the page during startup still cleans up the eventual worker',async()=>{
  const reply=deferred(),events=new EventTarget(),fetcher=vi.fn(async()=>({ok:true}))
  const pending=createNativeSession({request:()=>reply.promise,fetcher,events})
  const rejected=expect(pending).rejects.toMatchObject({name:'AbortError'})
  events.dispatchEvent(new Event('pagehide'));reply.resolve(response({id:'late'}));await rejected
  expect(fetcher).toHaveBeenCalledOnce()
})
it('preserves genuine contention without deleting another owner’s renderer',async()=>{
  const fetcher=vi.fn(),error=new Error('OptiX HTTP 409: another owner')
  await expect(createNativeSession({request:async()=>{throw error},fetcher,events:new EventTarget()})).rejects.toBe(error)
  expect(fetcher).not.toHaveBeenCalled()
})
