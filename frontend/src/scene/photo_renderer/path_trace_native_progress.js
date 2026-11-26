/** One in-flight status read, tied to this frame ID, stopped before disposal. */
export function pollNativeTrace(id,requestId,onStatus,{fetcher=fetch,interval=500}={}) {
  const controller=new AbortController()
  let timer=null,stopped=false
  async function poll(){
    try{
      const response=await fetcher(`/api/render/optix/${id}/progress`,{signal:controller.signal})
      if(!response.ok)throw new Error(`HTTP ${response.status}`)
      const info=await response.json()
      if(!stopped && info.request_id===requestId)onStatus?.(info)
    }catch(error){
      if(!stopped)onStatus?.({stage:'prepare',label:`OptiX rendering · progress temporarily unavailable (${error.message})`,fraction:null})
    }finally{if(!stopped)timer=setTimeout(poll,interval)}
  }
  timer=setTimeout(poll,interval)
  return ()=>{stopped=true;clearTimeout(timer);controller.abort()}
}
