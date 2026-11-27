/** Renderer work has an explicit lifetime, independent of scene fingerprints.
 * A newer request by the same owner retires its obsolete wait. Separate owners
 * (for example assembly instances) must all finish before tracing can resume. */
export function createGeometryLoads() {
  const pending=new Map()
  let revision=0
  function cancel(owner){if(pending.delete(owner))revision++}
  function begin(owner){
    const token={};pending.set(owner,token);revision++
    return ()=>{if(pending.get(owner)===token)cancel(owner)}
  }
  return {
    begin,cancel,
    getState:()=>({busy:pending.size>0,revision}),
    async track(owner,work){const done=begin(owner);try{return await work()}finally{done()}},
  }
}

export const geometryLoads=createGeometryLoads()
