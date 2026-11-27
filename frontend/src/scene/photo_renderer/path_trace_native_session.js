import {requestOptix} from './path_trace_errors.js'

const leases=new Set()
// Vite replacement must release workers owned by the old module as well.
import.meta.hot?.dispose(()=>{for(const lease of leases)void lease.close().catch(console.warn)})

/** Retain the startup acknowledgement even after cancellation, so its server
 * worker can always be released. Aborting fetch before reading the returned ID
 * used to leak an allocated renderer until the server's idle timeout. */
export async function createNativeSession({signal,request=requestOptix,fetcher=globalThis.fetch,events=globalThis.window}={}){
  signal?.throwIfAborted()
  let closing=null,closed=false,heartbeat=null
  const startup=request('/session',undefined,undefined).then(response=>response.json())
  const lease={
    close(){
      if(closing)return closing
      closed=true;clearInterval(heartbeat);events?.removeEventListener('pagehide',depart);signal?.removeEventListener('abort',depart);leases.delete(lease)
      closing=(async()=>{
        // Startup errors allocate no acknowledged session. A successful reply
        // must still be consumed and closed, even when the caller has left.
        let session
        try{session=await startup}catch{return}
        const response=await fetcher(`/api/render/optix/${session.id}`,{method:'DELETE',keepalive:true})
        if(!response.ok)throw new Error('Could not close native renderer')
      })()
      return closing
    },
  }
  const depart=()=>{void lease.close().catch(console.warn)}
  leases.add(lease);events?.addEventListener('pagehide',depart);signal?.addEventListener('abort',depart,{once:true})
  try{
    const session=await startup
    if(closed)throw signal?.reason??new DOMException('Native renderer owner closed','AbortError')
    signal?.throwIfAborted()
    const capacity=await(await request(`/${session.id}/capacity`,undefined,signal,{method:'GET'})).json()
    if(closed)throw signal?.reason??new DOMException('Native renderer owner closed','AbortError')
    heartbeat=setInterval(()=>{void request(`/${session.id}/capacity`,undefined,signal,{method:'GET'}).catch(()=>{})},30000)
    return {...session,capacity,close:lease.close}
  }catch(error){await lease.close();throw error}
}
